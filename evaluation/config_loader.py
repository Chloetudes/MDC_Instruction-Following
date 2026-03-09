# -*- coding: utf-8 -*-
"""
项目配置加载：支持项目级 config.json 覆盖全局配置。
- 项目目录：output_base_dir / project_id /
- 若存在 config.json，则与全局 CONFIG 深度合并，项目配置优先
- stages 支持预设代号，减少配置劳动量
"""
import os
import json

# 阶段预设代号：可用 "stages": "full" 或 "stages": ["criteria", "eval_only"]
STAGE_PRESETS = {
    "full": [
        "generate_instructions", "extract_instructions", "evaluate_instructions",
        "expand_multiturn", "promote_to_questions", "generate_criteria",
        "generate_references", "generate_replies", "evaluate_replies",
        "analyze_results", "generate_report",
    ],
    "criteria_ref": ["generate_criteria", "generate_references"],
    "criteria_ref_reply": ["generate_criteria", "generate_references", "generate_replies"],
    "eval_only": ["evaluate_replies", "analyze_results", "generate_report"],
    "reply_eval": ["generate_replies", "evaluate_replies", "analyze_results", "generate_report"],
    "criteria": ["generate_criteria"],
    "references": ["generate_references"],
    "reply": ["generate_replies"],
    "eval": ["evaluate_replies"],
    "analyze": ["analyze_results", "generate_report"],
    # 仅跑专家数据审核统计：只执行 analyze_results（需配合 analysis.stats_only: true），输出一张「专家数据质量与一致性」
    "expert_stats": ["analyze_results"],
    # 专家新题快速检验：若有新题则自动 生成标准→参考→回复→评测→统计
    "expert_quick_check": ["expert_quick_check"],
}


def expand_stages(raw) -> list:
    """
    将 stages 解析为阶段列表。支持：
    - 字符串：预设代号，如 "full"、"criteria_ref"、"eval_only"
    - 列表：可混合预设代号与单阶段名，如 ["criteria", "eval_only"] 或 ["generate_criteria"]
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    result = []
    for item in raw:
        s = (item or "").strip()
        if not s:
            continue
        if s in STAGE_PRESETS:
            result.extend(STAGE_PRESETS[s])
        else:
            result.append(s)
    return result


def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并：override 的值覆盖 base，嵌套 dict 递归合并。"""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_project_config(project_dir: str) -> dict:
    """
    从项目目录加载 config.json 或 config.yaml。不存在则返回空 dict。
    project_dir: 项目根目录（绝对路径）
    """
    for name in ('config.json', 'config.yaml'):
        path = os.path.join(project_dir, name)
        if os.path.isfile(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                if name.endswith('.json'):
                    return json.loads(content) if content.strip() else {}
                try:
                    import yaml
                    return yaml.safe_load(content) or {}
                except ImportError:
                    pass
            except Exception as e:
                print(f"⚠️  加载项目配置失败 {path}: {e}")
    return {}


def resolve_config(
    global_config: dict,
    project_root: str,
    output_base_dir: str = "outputs",
) -> dict:
    """
    解析最终配置：合并全局配置与项目 config.json，并解析项目相关路径。
    - project_id 有值时，项目目录 = project_root/output_base_dir/project_id
    - sysprompt_excel 未显式设置时，默认项目目录/sysprompts.xlsx
    - 返回合并后的 config（会修改 global_config 的副本）
    """
    config = dict(global_config)
    project_id = (config.get('project_id') or '').strip()
    # 阶段预设展开（有无项目均执行）
    raw_stages = config.get('stages')
    if raw_stages is not None:
        expanded = expand_stages(raw_stages)
        if expanded:
            config['stages'] = expanded

    if not project_id:
        return config

    project_dir = os.path.join(project_root, output_base_dir, project_id)
    if not os.path.isdir(project_dir):
        os.makedirs(project_dir, exist_ok=True)
        print(f"  📁 已创建项目目录: {project_dir}")

    project_cfg = load_project_config(project_dir)
    if project_cfg:
        config = _deep_merge(config, {k: v for k, v in project_cfg.items()
                                      if not (isinstance(k, str) and k.startswith('_'))})
        cfg_name = 'config.json' if os.path.isfile(os.path.join(project_dir, 'config.json')) else 'config.yaml'
        print(f"  📖 已加载项目配置: {os.path.basename(project_dir)}/{cfg_name}")

    # 项目级 sysprompt：若未在项目配置中显式设置，且项目目录下有 sysprompts.xlsx，则优先使用
    if 'sysprompt_excel' not in project_cfg:
        default_sysprompt = os.path.join(project_dir, 'sysprompts.xlsx')
        if os.path.isfile(default_sysprompt):
            config['sysprompt_excel'] = os.path.abspath(default_sysprompt)
            print(f"  📖 使用项目提示词: {default_sysprompt}")
    elif config.get('sysprompt_excel') and not os.path.isabs(config['sysprompt_excel']):
        # 项目配置中的相对路径，相对于项目目录解析
        config['sysprompt_excel'] = os.path.abspath(
            os.path.join(project_dir, config['sysprompt_excel'])
        )

    # 合并后再次展开 stages（项目 config 可能覆盖了 stages）
    raw_stages = config.get('stages')
    if raw_stages is not None:
        expanded = expand_stages(raw_stages)
        if expanded:
            config['stages'] = expanded

    # ========= 配置归一化：减少重复参数 =========
    # data_batch：文件后缀批次（questions_{batch}.xlsx / replies_{batch}.xlsx），与 eval_batch_id 不同概念
    # eval_batch_id / batch_id / analysis.eval_batch_id / report.eval_batch_id：本质都是“使用哪一列 eval_{id}”
    # 统一为一个来源：优先 root.eval_batch_id，其次 root.batch_id，其次 analysis/report 中已有值
    def _pick_first(*vals):
        for v in vals:
            if v is None:
                continue
            s = str(v).strip()
            if s:
                return s
        return ''

    analysis_cfg = config.get('analysis') if isinstance(config.get('analysis'), dict) else {}
    report_cfg = config.get('report') if isinstance(config.get('report'), dict) else {}

    resolved_eval_batch_id = _pick_first(
        config.get('eval_batch_id'),
        config.get('batch_id'),
        analysis_cfg.get('eval_batch_id'),
        report_cfg.get('eval_batch_id'),
    )
    if resolved_eval_batch_id:
        # 统计/报告默认使用同一批次；若用户需要刻意分开，仍可显式覆盖（这里不强制覆盖非空值）
        config['eval_batch_id'] = resolved_eval_batch_id
        if isinstance(config.get('analysis'), dict):
            config['analysis'].setdefault('eval_batch_id', resolved_eval_batch_id)
        else:
            config['analysis'] = {'eval_batch_id': resolved_eval_batch_id}
        if isinstance(config.get('report'), dict):
            config['report'].setdefault('eval_batch_id', resolved_eval_batch_id)
        else:
            config['report'] = {'eval_batch_id': resolved_eval_batch_id}
        # evaluate_replies 默认 batch_id 与 eval_batch_id 对齐，避免“评估写一列、统计读另一列”
        if not (config.get('batch_id') and str(config.get('batch_id')).strip()):
            config['batch_id'] = resolved_eval_batch_id

    return config

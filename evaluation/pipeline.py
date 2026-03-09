# -*- coding: utf-8 -*-
import sys
import os
import json
from datetime import datetime, timedelta

_pipeline_file = os.path.abspath(__file__)
_evaluation_pkg_dir = os.path.dirname(_pipeline_file)
_project_root = os.path.dirname(_evaluation_pkg_dir)

if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from typing import Dict, List, Optional

import pandas as pd

from .managers.directory import DirectoryManager
from .managers.sysprompt import SyspromptManager
from .managers.constraint_library import ConstraintLibraryManager
from .testing.model_tester import (
    ModelAvailabilityTester,
    select_best_judge_model,
    expand_reply_model_configs,
)
from .models_from_excel import (
    load_models_from_excel,
    update_availability_in_excel,
    try_use_cached_availability,
    mark_failed_models_from_replies,
)
from .core.blacklist import MODEL_BLACKLIST
from .core.utils import safe_save_excel
from config import get_provider_for_model, MODEL_PROVIDER_MAPPING, JUDGE_CANDIDATE_MODELS
from .stages import (
    generate_instructions,
    extract_structured_instructions,
    expand_to_multiturn,
    batch_evaluate_instruction_quality,
    batch_generate_criteria,
    batch_generate_references,
    batch_generate_replies,
    batch_summarize_expert_assessments,
    batch_evaluate_responses_with_cache,
    generate_evaluation_report,
)
from .analysis import generate_analysis_report, generate_all_series_reports, generate_multiturn_analysis


class PipelineManager:
    STAGE_DEFINITIONS = {
        'generate_instructions': {
            'name': '指令生成',
            'input_files': [],
            'output_files': ['stage0_generation/generated_responses.xlsx']
        },
        'extract_instructions': {
            'name': '指令提取',
            'input_files': ['stage0_generation/generated_responses.xlsx'],
            'output_files': ['stage0.5_extraction/extracted_instructions.xlsx']
        },
        'evaluate_instructions': {
            'name': '指令质量评估（可选）',
            'input_files': ['stage0.5_extraction/extracted_instructions.xlsx'],
            'output_files': ['stage1_quality/evaluated_instructions.xlsx']
        },
        'expand_multiturn': {
            'name': '多轮对话扩展（可选）',
            'input_files': ['stage0.5_extraction/extracted_instructions.xlsx'],
            'output_files': ['stage0.7_multiturn/multiturn_instructions.xlsx']
        },
        'promote_to_questions': {
            'name': '数据提升为评测题目',
            'input_files': [],
            'output_files': ['questions/questions.xlsx']
        },
        'generate_criteria': {
            'name': '评估标准生成',
            'input_files': ['questions/questions.xlsx'],
            'output_files': ['questions/questions_with_criteria.xlsx']
        },
        'generate_references': {
            'name': '参考答案生成',
            'input_files': ['questions/questions_with_criteria.xlsx'],
            'output_files': ['questions/questions_complete.xlsx']
        },
        'generate_replies': {
            'name': '回复生成',
            'input_files': ['questions/questions_complete.xlsx'],
            'output_files': ['replies/replies.xlsx']
        },
        'summarize_expert_assessments': {
            'name': '专家评估归纳',
            'input_files': ['questions/questions_complete.xlsx', 'replies/replies.xlsx'],
            'output_files': ['questions/questions_complete.xlsx']
        },
        'evaluate_replies': {
            'name': '回复评估',
            'input_files': ['questions/questions_complete.xlsx', 'replies/replies.xlsx'],
            'output_files': ['evaluations/evaluation_results.xlsx']
        },
        'analyze_multiturn': {
            'name': '多轮分析',
            'input_files': ['replies/replies.xlsx'],
            'output_files': ['reports/multiturn_analysis.xlsx']
        },
        'test_models': {
            'name': '模型可用性测试',
            'input_files': [],
            'output_files': ['library/model_availability_test.xlsx']
        },
        'test_judge_models': {
            'name': '裁判模型可用性测试（Claude/Gemini/GPT5.2）',
            'input_files': [],
            'output_files': []
        },
        'analyze_results': {
            'name': '评测结果综合分析',
            'input_files': ['questions/questions_complete.xlsx', 'replies/replies.xlsx'],
            'output_files': ['reports/analysis_report.xlsx']
        },
        'generate_report': {
            'name': '可视化报告生成（综合报告）',
            'input_files': ['questions/questions_complete.xlsx', 'replies/replies.xlsx'],
            'output_files': ['reports/evaluation_report_*.html', 'reports/evaluation_report_*.md']
        },
        'generate_series_reports': {
            'name': '厂商专项报告',
            'input_files': ['questions/questions_complete.xlsx', 'replies/replies.xlsx'],
            'output_files': ['reports/series_report_*.xlsx', 'reports/series_report_*.md']
        },
        'expert_quick_check': {
            'name': '专家新题快速检验（有新题则生成标准→参考→回复→评测→统计）',
            'input_files': ['questions/questions_prof.xlsx'],
            'output_files': [],
        },
    }

    def __init__(self, config: dict):
        self.config = config
        base = config.get('output_base_dir', 'outputs')
        project_id = config.get('project_id') or ""
        self.dir_manager = DirectoryManager(
            base_dir=base, project_id=project_id, project_root=_project_root
        )
        sysprompt_path = config.get('sysprompt_excel', 'data/sysprompts.xlsx')
        if sysprompt_path and not os.path.isabs(sysprompt_path):
            sysprompt_path = os.path.join(_project_root, sysprompt_path)
        self.sysprompt_manager = SyspromptManager(sysprompt_path)
        self.constraint_library = ConstraintLibraryManager(
            self._resolve_path(self.dir_manager.get_path("library", "constraint_library.xlsx"))
        )

    def _get_sorted_stages(self, stages: List[str]) -> List[str]:
        all_stages = list(self.STAGE_DEFINITIONS.keys())
        for stage in stages:
            if stage not in all_stages:
                raise ValueError(f"未知的阶段: {stage}，可用阶段: {all_stages}")
        return [s for s in all_stages if s in stages]

    def _resolve_path(self, path_str: str) -> str:
        """解析路径：绝对路径原样返回，相对路径相对于项目根目录。"""
        if not path_str or os.path.isabs(path_str):
            return path_str or ""
        return os.path.join(_project_root, path_str)

    def _batch_suffix(self) -> str:
        """数据批次后缀：data_batch 有值时返回 '_self'、'_expert' 等，否则空字符串。"""
        batch = (self.config.get('data_batch') or '').strip()
        return f"_{batch}" if batch else ""

    def _resolve_questions_excel_for_evaluate(self) -> str:
        """评估/分析/报告用的题目表：优先 questions_excel；否则用 questions_complete{_batch}.xlsx（唯一题目表，含专家等全部字段）。"""
        custom = self.config.get('questions_excel')
        if custom and str(custom).strip():
            path = str(custom).strip()
            if os.path.isabs(path):
                return path
            return self._resolve_path(path)
        suffix = self._batch_suffix()
        return self._resolve_path(self.dir_manager.get_path("questions", f"questions_complete{suffix}.xlsx"))

    def _resolve_replies_excel(self) -> str:
        """
        回复表路径。支持：
        - 单个路径（str）：相对路径相对于项目根 _project_root 解析。
        - 多个路径（list）：合并为一张表，相对路径相对于项目根解析。
        - 为空时：使用 replies/replies{_batch}.xlsx（data_batch 有值时带批次后缀）
        """
        raw = self.config.get('replies_excel')
        if not raw:
            suffix = self._batch_suffix()
            fname = f"replies{suffix}.xlsx"
            return self._resolve_path(self.dir_manager.get_path("replies", fname))
        if isinstance(raw, list):
            paths = []
            for p in raw:
                if not p or not str(p).strip():
                    continue
                p = str(p).strip()
                paths.append(p if os.path.isabs(p) else self._resolve_path(p))
            if not paths:
                suffix = self._batch_suffix()
                return self._resolve_path(self.dir_manager.get_path("replies", f"replies{suffix}.xlsx"))
            if len(paths) == 1:
                return paths[0]
            # 多表合并：读每个文件的首个数据 sheet，按行拼接后写入 merged_replies.xlsx
            dfs = []
            for p in paths:
                if not os.path.exists(p):
                    print(f"  ⚠️  回复表不存在，跳过: {p}")
                    continue
                try:
                    xls = pd.ExcelFile(p)
                    sheet = next((s for s in ('Sheet1', 'replies') if s in xls.sheet_names), xls.sheet_names[0])
                    df = pd.read_excel(p, sheet_name=sheet)
                    if 'qid' in df.columns and 'model' in df.columns and 'reply' in df.columns:
                        dfs.append(df)
                    else:
                        print(f"  ⚠️  跳过（缺 qid/model/reply）: {p}")
                except Exception as e:
                    print(f"  ⚠️  读取失败，跳过: {p}  {e}")
            if not dfs:
                raise FileNotFoundError("未成功读取任何回复表，请检查 replies_excel 路径及表结构（需含 qid, model, reply）")
            merged = pd.concat(dfs, ignore_index=True)
            out_path = self._resolve_path(self.dir_manager.get_path("replies", "merged_replies.xlsx"))
            if safe_save_excel(merged, out_path):
                print(f"  📂 已合并 {len(paths)} 个回复表 → {out_path}  共 {len(merged)} 行\n")
            return out_path
        path = str(raw).strip()
        return path if os.path.isabs(path) else self._resolve_path(path)

    def _resolve_promote_source(self) -> tuple:
        """
        按优先级选择 promote_to_questions 的数据源。
        优先级：用户显式指定 > stage1_quality > stage0.7_multiturn > stage0.5_extraction
        返回 (source_path, source_label)
        """
        import os
        dm = self.dir_manager
        cfg = self.config

        explicit_source = cfg.get('promote_source_excel')
        if explicit_source and os.path.exists(explicit_source):
            return explicit_source, f'用户指定（{explicit_source}）'

        quality_path = self._resolve_path(dm.get_path("stage1_quality", "evaluated_instructions.xlsx"))
        multiturn_path = self._resolve_path(dm.get_path("stage0.7_multiturn", "multiturn_instructions.xlsx"))
        extracted_path = self._resolve_path(dm.get_path("stage0.5_extraction", "extracted_instructions.xlsx"))

        if os.path.exists(quality_path):
            return quality_path, 'stage1_quality（已过滤）'
        if os.path.exists(multiturn_path):
            return multiturn_path, 'stage0.7_multiturn（多轮）'
        if os.path.exists(extracted_path):
            return extracted_path, 'stage0.5_extraction（单轮）'

        return None, None

    def test_models(self, model_configs: List[Dict[str, str]],
                    output_excel: Optional[str] = None) -> pd.DataFrame:
        tester = ModelAvailabilityTester(
            timeout=self.config.get('test_timeout', 30),
            test_prompt=self.config.get('test_prompt'),
        )
        results = tester.test_all_models(model_configs, max_workers=3)
        if output_excel and safe_save_excel(results, output_excel):
            print(f"✅ 测试结果已保存: {output_excel}")
        return results

    def auto_select_judge_model(self, test_results: pd.DataFrame) -> bool:
        judge_config = select_best_judge_model(test_results)
        if judge_config:
            self.config['provider'] = judge_config['provider']
            self.config['model'] = judge_config['model']
            print(f"✅ 已自动配置裁判模型")
            return True
        print(f"❌ 无法自动选择裁判模型")
        return False

    def _get_judge_candidate_configs(self) -> List[Dict]:
        """裁判模型候选：仅 Claude/Gemini/GPT-5.2，从 JUDGE_CANDIDATE_MODELS 或配置的 judge_model_configs 构建。"""
        cfg = self.config
        custom = cfg.get('judge_model_configs')
        if custom:
            return expand_reply_model_configs(custom)
        configs = []
        for model_name in JUDGE_CANDIDATE_MODELS:
            if model_name not in MODEL_PROVIDER_MAPPING:
                continue
            try:
                pc = get_provider_for_model(model_name)
                configs.append({"provider": pc.name, "model": model_name})
            except ValueError:
                pass
        return configs

    def _judge_cache_path(self) -> str:
        """裁判可用性缓存文件路径。"""
        return self._resolve_path(
            self.dir_manager.get_path("library", "judge_availability_cache.json")
        )

    def _try_use_judge_cache(self, provider: str, model: str, max_age_days: int) -> Optional[bool]:
        """
        若已配置的裁判 (provider, model) 在缓存中且距上次测试不足 max_age_days 天，返回可用状态；
        否则返回 None 表示需重新测试。
        """
        if not provider or not model:
            return None
        path = self._judge_cache_path()
        if not os.path.exists(path):
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                cache = json.load(f)
        except Exception:
            return None
        key = f"{provider}:{model}"
        entry = cache.get(key)
        if not entry or not isinstance(entry, dict):
            return None
        last_str = entry.get('last_tested')
        if not last_str:
            return None
        try:
            last_dt = datetime.fromisoformat(last_str.replace('Z', '+00:00'))
            if getattr(last_dt, 'tzinfo', None):
                last_dt = last_dt.replace(tzinfo=None)
        except (ValueError, TypeError, OSError):
            return None
        if datetime.now() - last_dt > timedelta(days=max_age_days):
            return None
        return bool(entry.get('available', False))

    def _save_judge_cache(self, provider: str, model: str, available: bool) -> None:
        """将裁判可用性写回缓存。"""
        path = self._judge_cache_path()
        cache = {}
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
            except Exception:
                pass
        key = f"{provider}:{model}"
        cache[key] = {'last_tested': datetime.now().isoformat(), 'available': available}
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def check_and_select_judge_model(self) -> Optional[Dict[str, str]]:
        """
        裁判模型选择：若已配置且缓存有效（距上次测试不足 max_age_days 天）则跳过 API 检测；
        否则测 Claude/Gemini/GPT-5.2 候选可用性，再交互选择其一。
        选中的写回 config['provider'], config['model']。
        """
        cfg = self.config
        max_age_days = cfg.get('availability_test_max_age_days', 14)
        judge_provider, judge_model = self._resolve_judge_provider_model()
        if judge_provider and judge_model:
            cached_available = self._try_use_judge_cache(judge_provider, judge_model, max_age_days)
            if cached_available is True:
                print(f"  📋 使用裁判缓存（{judge_provider}/{judge_model}，最后检测距今 < {max_age_days} 天），跳过 API 检测\n")
                self._judge_checked_this_run = True
                return {"provider": judge_provider, "model": judge_model}
            if cached_available is False:
                print(f"  ⚠️  缓存显示裁判不可用，将重新测试...\n")

        configs = self._get_judge_candidate_configs()
        if not configs:
            print("⚠️  裁判模型候选为空。请配置 judge_model_configs 或确保 config.JUDGE_CANDIDATE_MODELS 有有效模型。")
            return None

        tester = ModelAvailabilityTester(
            timeout=self.config.get('test_timeout', 30),
            test_prompt=self.config.get('test_prompt'),
        )
        test_results = tester.test_all_models(configs, max_workers=3)
        available = test_results[test_results['available']].sort_values('response_time').reset_index(drop=True)

        if len(available) == 0:
            print("❌ 裁判模型候选均不可用，请检查配置或网络后重试。")
            return None

        print(f"\n{'=' * 60}")
        print(f"📋 可用裁判模型（共 {len(available)} 项，Claude/Gemini/GPT-5.2 系列）")
        print(f"{'=' * 60}")
        for i, row in available.iterrows():
            rt = row.get('response_time')
            rt_str = f" {rt:.2f}s" if rt is not None and not pd.isna(rt) else ""
            print(f"  {i + 1:3d}. {row['provider']:20s} / {row['model']:35s}{rt_str}")
        print(f"{'=' * 60}")
        print("  请输入要作为裁判的编号（如 1），直接回车=选第 1 个：", end="")
        try:
            choice = input().strip()
        except EOFError:
            choice = ""
        idx = 0
        if choice and choice.isdigit():
            idx = int(choice) - 1
        if idx < 0 or idx >= len(available):
            idx = 0
        selected = available.iloc[idx]
        self.config["provider"] = selected["provider"]
        self.config["model"] = selected["model"]
        self._judge_checked_this_run = True
        self._save_judge_cache(selected["provider"], selected["model"], True)
        print(f"\n✅ 已选择裁判模型: {selected['provider']} / {selected['model']}")
        return {"provider": selected["provider"], "model": selected["model"]}

    def _resolve_judge_provider_model(self) -> tuple:
        """
        解析裁判模型的 provider 和 model。
        若 model 在 MODEL_PROVIDER_MAPPING 中，则用对应 provider（避免 idealab 上 Claude 报「模型不存在」）；
        否则用顶层配置的 provider。
        """
        cfg = self.config
        model = cfg.get('model')
        if model:
            try:
                pc = get_provider_for_model(model)
                return (pc.name, model)
            except ValueError:
                pass
        return (cfg.get('provider'), model)

    def _resolve_models_excel_path(self) -> Optional[str]:
        """解析模型清单 Excel 的绝对路径。若未配置或文件不存在则返回 None。"""
        path = self.config.get('models_excel') or 'data/idealab_models.xlsx'
        if not path:
            return None
        if not os.path.isabs(path):
            path = os.path.join(_project_root, path)
        return path if os.path.exists(path) else None

    def check_and_select_reply_models(self) -> List[Dict]:
        """
        批量回复前：检测模型可用性，输出可用清单，交互式选择参与批量回复的模型。
        若启用 use_models_from_excel，则从 idealab_models.xlsx 加载待测模型，测试后写回「可用状态」。
        裁判模型不受影响。选中的列表写回 config['reply_model_configs']，并返回。
        """
        model_configs = self.config.get('reply_model_configs') or []
        models_excel_path = None
        if self.config.get('use_models_from_excel'):
            models_excel_path = self._resolve_models_excel_path()
            if models_excel_path:
                try:
                    provider = self.config.get('models_excel_provider')
                    model_configs = load_models_from_excel(models_excel_path, provider=provider)
                    print(f"  📂 已从表格加载待测模型: {models_excel_path}  共 {len(model_configs)} 个")
                except Exception as e:
                    print(f"  ⚠️ 从表格加载失败: {e}，改用 reply_model_configs")
                    model_configs = self.config.get('reply_model_configs') or []
            else:
                print("  ⚠️  use_models_from_excel 已开启但 models_excel 未找到，改用 reply_model_configs")

        if not model_configs:
            print("⚠️  待测模型为空。请配置 reply_model_configs，或启用 use_models_from_excel 并确保 data/idealab_models.xlsx 存在。")
            return []

        max_age_days = self.config.get('availability_test_max_age_days', 14)
        test_results = None
        used_cache = False
        if models_excel_path:
            can_skip, cached_df = try_use_cached_availability(
                models_excel_path, model_configs,
                max_age_days=max_age_days,
                provider=self.config.get('models_excel_provider'),
            )
            if can_skip and cached_df is not None:
                test_results = cached_df
                used_cache = True
                print(f"  📋 使用表格缓存的可用状态（最后检测距今 < {max_age_days} 天），跳过 API 检测\n")

        if test_results is None:
            tester = ModelAvailabilityTester(
                timeout=self.config.get('test_timeout', 30),
                test_prompt=self.config.get('test_prompt'),
            )
            test_results = tester.test_all_models(model_configs, max_workers=3)
        if models_excel_path and not test_results.empty and not used_cache:
            try:
                update_availability_in_excel(
                    models_excel_path, test_results,
                    provider=self.config.get('models_excel_provider'),
                )
                print(f"  ✅ 已更新表格可用状态: {models_excel_path}")
            except Exception as e:
                print(f"  ⚠️ 写回表格失败: {e}")

        available = test_results[test_results['available'] == True].sort_values('response_time').reset_index(drop=True)

        if len(available) == 0:
            print("❌ 当前无可用模型，请检查配置或网络后重试。")
            return []

        print(f"\n{'=' * 60}")
        print(f"📋 可用模型清单（共 {len(available)} 项，按响应时间排序）")
        print(f"{'=' * 60}")
        for i, row in available.iterrows():
            rt = row.get('response_time')
            rt_str = f" {rt:.2f}s" if rt is not None and not pd.isna(rt) else ""
            label = row.get('展示名称') or row['model']
            print(f"  {i + 1:3d}. {label:40s} ({row['model']}){rt_str}")
        print(f"{'=' * 60}")
        print("  输入要参与批量回复的编号，逗号分隔（如 1,3,5），或 all 全选，直接回车=全选：", end="")
        try:
            choice = input().strip()
        except EOFError:
            choice = ""
        if not choice:
            choice = "all"

        selected = []
        if choice.strip().lower() == "all":
            selected = available.to_dict("records")
        else:
            for part in choice.split(","):
                part = part.strip()
                if not part.isdigit():
                    continue
                idx = int(part) - 1
                if 0 <= idx < len(available):
                    selected.append(available.iloc[idx].to_dict())

        # 转为 reply_model_configs 格式：每项含 provider, model, enable_thinking
        reply_configs = []
        for row in selected:
            reply_configs.append({
                "provider": row["provider"],
                "model": row["model"],
                "enable_thinking": row.get("enable_thinking", False),
            })
        self.config["reply_model_configs"] = reply_configs
        print(f"\n✅ 已选择 {len(reply_configs)} 个模型参与本次批量回复。")
        return reply_configs

    def _normalize_qid(self, val) -> str:
        s = str(val).strip()
        try:
            f = float(s)
            if not (f != f) and f == int(f):
                return str(int(f))
        except (ValueError, TypeError):
            pass
        return s

    def _execute_expert_quick_check(self):
        """检验专家题目表是否有新题；若有则依次执行：生成评估标准 → 参考答案 → 回复 → 评测 → 统计。"""
        cfg = self.config
        dm = self.dir_manager
        batch_sfx = self._batch_suffix()
        questions_input = cfg.get('questions_input_excel') or f"questions{batch_sfx}.xlsx"
        if os.path.isabs(questions_input):
            input_path = questions_input
        elif '/' in questions_input or os.path.sep in questions_input:
            input_path = self._resolve_path(questions_input)
        else:
            input_path = self._resolve_path(dm.get_path("questions", questions_input))
        if not os.path.exists(input_path):
            print("  ⚠️ 专家题目表不存在，跳过检验。路径: {}".format(input_path))
            return
        df_input = pd.read_excel(input_path)
        if 'qid' not in df_input.columns:
            print("  ⚠️ 题目表无 qid 列，跳过检验。")
            return
        input_qids = set(df_input['qid'].astype(str).str.strip().map(self._normalize_qid).tolist())
        complete_path = self._resolve_path(dm.get_path("questions", f"questions_complete{batch_sfx}.xlsx"))
        if os.path.exists(complete_path):
            df_complete = pd.read_excel(complete_path)
            complete_qids = set(df_complete['qid'].astype(str).str.strip().map(self._normalize_qid).tolist()) if 'qid' in df_complete.columns else set()
        else:
            complete_qids = set()
        new_qids = sorted(input_qids - complete_qids, key=lambda x: (len(x), x))
        if not new_qids:
            print("  ✅ 无新题，无需补充。当前题目表与 questions_complete 一致。")
            return
        print("  📌 检测到 {} 道新题，将依次执行：生成评估标准 → 参考答案 → 回复 → 评测 → 统计".format(len(new_qids)))
        if len(new_qids) <= 10:
            print("     新题 qid: {}".format(new_qids))
        else:
            print("     新题 qid 示例: {} ...".format(new_qids[:10]))
        for stage in ['generate_criteria', 'generate_references', 'generate_replies', 'evaluate_replies', 'analyze_results']:
            self.execute_stage(stage)

    def _execute_promote_to_questions(self):
        source_path, source_label = self._resolve_promote_source()

        if not source_path:
            raise RuntimeError(
                "promote_to_questions: 找不到可用的输入文件。\n"
                "请先运行 extract_instructions，或在 CONFIG 中设置 'promote_source_excel' 指定自定义路径。"
            )

        print(f"  📖 数据来源: {source_label}")
        df = pd.read_excel(source_path)

        if 'status' in df.columns:
            before_count = len(df)
            df = df[df['status'] == 'ok']
            print(f"  📌 按 status=ok 过滤: {before_count} → {len(df)} 条")

        batch_sfx = self._batch_suffix()
        questions_fname = f"questions{batch_sfx}.xlsx"
        output_path = self._resolve_path(self.dir_manager.get_path("questions", questions_fname))
        if safe_save_excel(df, output_path):
            print(f"  ✅ 题目已写入: {output_path}  共 {len(df)} 条")

        # 多轮数据同时写入 questions_multiturn{batch}.xlsx，作为多轮题库的命名副本
        is_multiturn = '多轮' in source_label or 'multiturn' in source_label.lower()
        if is_multiturn and 'history_context' in df.columns:
            multiturn_fname = f"questions_multiturn{batch_sfx}.xlsx"
            multiturn_path = self._resolve_path(self.dir_manager.get_path("questions", multiturn_fname))
            if safe_save_excel(df, multiturn_path):
                print(f"  ✅ 多轮题库副本: {multiturn_path}  共 {len(df)} 条")

    def execute_stage(self, stage: str):
        stage_def = self.STAGE_DEFINITIONS[stage]
        print(f"\n{'=' * 60}")
        print(f"🚀 执行阶段: {stage_def['name']}")
        print(f"{'=' * 60}\n")

        cfg = self.config
        dm = self.dir_manager
        sp = self.sysprompt_manager
        judge_using_stages = ('generate_instructions', 'evaluate_instructions', 'expand_multiturn',
                              'generate_criteria', 'generate_references', 'summarize_expert_assessments',
                              'evaluate_replies', 'generate_report')
        # 裁判验证改为可选：skip_judge_validation=True 时直接使用已配置的 provider/model，不测可用性、不交互选择
        if (stage in judge_using_stages
                and not cfg.get('skip_judge_validation', False)
                and cfg.get('check_judge_before_use', False)
                and not getattr(self, '_judge_checked_this_run', False)):
            if not self.check_and_select_judge_model():
                raise RuntimeError("裁判模型选择取消或无可选模型，无法继续。")
            self._judge_checked_this_run = True
        judge_provider, judge_model = self._resolve_judge_provider_model()
        if stage in judge_using_stages:
            if not judge_provider or not judge_model:
                raise RuntimeError("未配置裁判模型（config.provider / config.model）。请配置固定裁判，或设置 check_judge_before_use=True / 在 stages 中加入 test_judge_models 进行选型。")
            print(f"  裁判模型: {judge_provider}/{judge_model}\n")

        if stage == 'generate_instructions':
            generation_cfg = cfg.get('generation', {})
            generate_instructions(
                output_excel=self._resolve_path(dm.get_path("stage0_generation", "generated_responses.xlsx")),
                provider=judge_provider, model=judge_model,
                sysprompt_manager=sp,
                num_batches=generation_cfg.get('num_batches', cfg.get('num_instruction_batches', 15)),
                items_per_batch=generation_cfg.get('items_per_batch', 3),
                temperature=cfg.get('instruction_temperature', 0.8),
                timeout=cfg['timeout'],
                schema_excel=generation_cfg.get('schema_excel'),
                see_excel=generation_cfg.get('see_excel'),
            )

        elif stage == 'extract_instructions':
            extract_structured_instructions(
                input_excel=self._resolve_path(dm.get_path("stage0_generation", "generated_responses.xlsx")),
                output_excel=self._resolve_path(dm.get_path("stage0.5_extraction", "extracted_instructions.xlsx"))
            )

        elif stage == 'evaluate_instructions':
            batch_evaluate_instruction_quality(
                input_excel=self._resolve_path(dm.get_path("stage0.5_extraction", "extracted_instructions.xlsx")),
                output_excel=self._resolve_path(dm.get_path("stage1_quality", "evaluated_instructions.xlsx")),
                provider=judge_provider, model=judge_model,
                sysprompt_manager=sp,
                constraint_library=self.constraint_library,
                temperature=cfg.get('evaluation_temperature', 0.3),
                max_workers=cfg.get('max_workers', 4),
                checkpoint_interval=cfg.get('checkpoint_interval', 10),
                timeout=cfg['timeout']
            )

        elif stage == 'expand_multiturn':
            multiturn_cfg = cfg.get('multiturn', {})
            expand_to_multiturn(
                input_excel=self._resolve_path(dm.get_path("stage0.5_extraction", "extracted_instructions.xlsx")),
                output_excel=self._resolve_path(dm.get_path("stage0.7_multiturn", "multiturn_instructions.xlsx")),
                provider=judge_provider, model=judge_model,
                sysprompt_manager=sp,
                min_turns=multiturn_cfg.get('min_turns', 3),
                max_turns=multiturn_cfg.get('max_turns', 8),
                temperature=multiturn_cfg.get('temperature', 0.8),
                max_workers=multiturn_cfg.get('max_workers', cfg.get('max_workers', 3)),
                checkpoint_interval=cfg.get('checkpoint_interval', 10),
                timeout=cfg['timeout'],
            )

        elif stage == 'promote_to_questions':
            self._execute_promote_to_questions()

        elif stage == 'expert_quick_check':
            self._execute_expert_quick_check()

        elif stage == 'generate_criteria':
            batch_sfx = self._batch_suffix()
            complete_path = self._resolve_path(dm.get_path("questions", f"questions_complete{batch_sfx}.xlsx"))
            seed_path = self._resolve_path(dm.get_path("questions", f"questions{batch_sfx}.xlsx"))
            # 唯一题目表：有 complete 则在其上补充 criteria；无则用 questions_prof 等作为种子，写出到 complete
            input_path = complete_path if os.path.exists(complete_path) else seed_path
            batch_generate_criteria(
                input_excel=input_path,
                output_excel=complete_path,
                provider=judge_provider, model=judge_model,
                sysprompt_manager=sp,
                temperature=cfg.get('criteria_temperature', 0.3),
                max_workers=1,
                checkpoint_interval=cfg.get('checkpoint_interval', 10),
                timeout=cfg['timeout']
            )

        elif stage == 'generate_references':
            batch_sfx = self._batch_suffix()
            complete_path = self._resolve_path(dm.get_path("questions", f"questions_complete{batch_sfx}.xlsx"))
            batch_generate_references(
                input_excel=complete_path,
                output_excel=complete_path,
                provider=judge_provider, model=judge_model,
                sysprompt_manager=sp,
                temperature=cfg.get('reference_temperature', 0.7),
                max_workers=1,
                checkpoint_interval=cfg.get('checkpoint_interval', 10),
                timeout=cfg['timeout']
            )

        elif stage == 'generate_replies':
            if cfg.get('check_models_before_reply', True):
                selected = self.check_and_select_reply_models()
                if not selected:
                    print("⚠️  未选择任何模型，跳过批量回复。")
                    return
            else:
                # 未跑交互测试时，若从表格加载且当前无模型列表，则只加载「可用状态」为是的模型，确保回复只用可用模型
                reply_configs = cfg.get('reply_model_configs') or []
                if not reply_configs and cfg.get('use_models_from_excel'):
                    models_excel_path = self._resolve_models_excel_path()
                    if models_excel_path:
                        try:
                            reply_configs = load_models_from_excel(
                                models_excel_path,
                                provider=cfg.get('models_excel_provider'),
                                only_available=True,
                            )
                            if reply_configs:
                                cfg['reply_model_configs'] = reply_configs
                                print(f"  📂 已从表格加载可用模型（仅 可用状态=是）: {len(reply_configs)} 个\n")
                            else:
                                print("  ⚠️  表格中无 可用状态=是 的模型，请先运行可用性测试或勾选参与模型。\n")
                        except Exception as e:
                            print(f"  ⚠️  从表格加载可用模型失败: {e}\n")
            if not (cfg.get('reply_model_configs')):
                print("⚠️  无待测模型，跳过批量回复。请配置 reply_model_configs 或启用 use_models_from_excel 并先运行可用性测试。")
                return
            batch_sfx = self._batch_suffix()
            questions_for_reply = self._resolve_path(dm.get_path("questions", f"questions_complete{batch_sfx}.xlsx"))
            if not os.path.exists(questions_for_reply):
                raise FileNotFoundError(
                    f"题目表不存在，无法生成回复。请先运行 generate_criteria（或 generate_references）。\n"
                    f"  查找路径: {questions_for_reply}"
                )
            print(f"  📂 使用题目表: {os.path.basename(questions_for_reply)}\n")
            models_excel_path = self._resolve_models_excel_path()
            df_replies, failed_from_run = batch_generate_replies(
                questions_excel=questions_for_reply,
                model_configs=cfg['reply_model_configs'],
                output_excel=self._resolve_replies_excel(),
                temperature=cfg.get('reply_temperature', 0.6),
                max_workers=cfg.get('max_workers', 5),
                checkpoint_interval=cfg.get('checkpoint_interval', 10),
                timeout=cfg['timeout'],
                models_excel_path=models_excel_path,
            )
            # 将批量生成时失败的模型（黑名单跳过 + status=error 未写入的）标记为不可用（首次失败时已在 batch 内即时写入，此处做汇总）
            blacklisted = MODEL_BLACKLIST.get_all()
            all_failed = blacklisted + (failed_from_run or [])
            if models_excel_path and all_failed:
                n = mark_failed_models_from_replies(
                    models_excel_path,
                    replies_df=None,
                    provider=None,
                    blacklisted_models=all_failed,
                )
                if n > 0:
                    print(f"  ✅ 已将 {n} 个调用失败的模型标记为不可用: {models_excel_path}\n")
                elif n == 0 and all_failed:
                    print(f"  ⚠️  有 {len(all_failed)} 个失败模型，但表格中未匹配到对应行（请检查来源/ api_model_id 是否一致）\n")
            elif all_failed and not models_excel_path:
                print(f"  ⚠️  有 {len(all_failed)} 个失败模型，但未找到模型表格路径（models_excel），无法更新可用状态\n")

        elif stage == 'summarize_expert_assessments':
            questions_file = self._resolve_questions_excel_for_evaluate()
            replies_file = self._resolve_replies_excel()
            if not os.path.exists(questions_file) or not os.path.exists(replies_file):
                raise FileNotFoundError(f"题目表或回复表不存在: {questions_file}, {replies_file}")
            batch_summarize_expert_assessments(
                replies_excel=replies_file,
                questions_excel=questions_file,
                output_questions_excel=questions_file,
                provider=judge_provider,
                model=judge_model,
                temperature=cfg.get('evaluation_temperature', 0.3),
                timeout=cfg.get('timeout', 120),
            )

        elif stage == 'evaluate_replies':
            questions_file = self._resolve_questions_excel_for_evaluate()
            replies_file = self._resolve_replies_excel()
            if not questions_file or not os.path.exists(questions_file):
                parent = os.path.dirname(questions_file)
                hint = (
                    f"请将题目表放到: {questions_file}\n"
                    f"或把 main.py 中 questions_excel 改为您文件所在的绝对路径（例如: 'questions_excel': '/完整路径/questions_complete.xlsx'）"
                )
                raise FileNotFoundError(
                    f"题目表不存在，无法评估回复:\n  {questions_file}\n{hint}"
                )
            if not replies_file or not os.path.exists(replies_file):
                raise FileNotFoundError(
                    f"回复表不存在，无法评估: {replies_file}。"
                    "请先运行 generate_replies 生成回复，或配置 replies_excel 指向已有回复表"
                )
            batch_evaluate_responses_with_cache(
                questions_excel=questions_file,
                replies_excel=replies_file,
                output_excel=replies_file,
                provider=judge_provider, model=judge_model,
                sysprompt_manager=sp,
                batch_id=cfg.get('batch_id'),
                data_filters=cfg.get('data_filters'),
                temperature=cfg.get('evaluation_temperature', 0.3),
                max_workers=cfg.get('max_workers', 5),
                checkpoint_interval=cfg.get('checkpoint_interval', 10),
                timeout=cfg['timeout'],
                overwrite_mode=cfg.get('overwrite_mode', 'skip'),
            )

        elif stage == 'analyze_multiturn':
            replies_file = self._resolve_replies_excel()
            analysis_cfg = cfg.get('analysis', {})
            batch_sfx = self._batch_suffix()
            generate_multiturn_analysis(
                replies_excel=replies_file,
                output_excel=self._resolve_path(dm.get_path("reports", f"multiturn_analysis{batch_sfx}.xlsx")),
                eval_batch_id=analysis_cfg.get('eval_batch_id', cfg.get('batch_id')),
                score_pass_threshold=cfg.get('multiturn_pass_threshold', 60.0),
            )

        elif stage == 'analyze_results':
            analysis_cfg = cfg.get('analysis', {})
            stats_only = analysis_cfg.get('stats_only', False)
            eval_batch_id = analysis_cfg.get('eval_batch_id', cfg.get('batch_id'))
            questions_file = self._resolve_questions_excel_for_evaluate()
            replies_file = analysis_cfg.get('replies_excel') or self._resolve_replies_excel()
            human_excel = analysis_cfg.get('human_excel')
            batch_sfx = self._batch_suffix()
            report_name = f"analysis_report{batch_sfx}.xlsx"
            backfill_questions = analysis_cfg.get('backfill_questions', False)
            backfill_path = None
            if backfill_questions:
                backfill_path = analysis_cfg.get('backfill_questions_excel') or questions_file
            print(f"  📊 统计以评估批次为准: eval_batch_id={eval_batch_id}（分数列 eval_{eval_batch_id}）")
            generate_analysis_report(
                questions_excel=questions_file,
                replies_excel=replies_file,
                output_excel=self._resolve_path(dm.get_path("reports", report_name)),
                human_excel=human_excel,
                eval_batch_id=eval_batch_id,
                stats_only=stats_only,
                backfill_questions_excel=self._resolve_path(backfill_path) if backfill_path else None,
                quality_thresholds=analysis_cfg.get('quality_thresholds'),
            )

            if stats_only:
                # 专家验证仅统计模式：不生成厂商专项报告与后续完整报告
                return

            import pandas as pd
            from evaluation.analysis.data_loader import _load_replies, _resolve_eval_column, _preprocess_replies
            from evaluation.analysis.series_report import select_series_interactive
            questions_df = pd.read_excel(questions_file)
            replies_df = _load_replies(replies_file)
            eval_col = _resolve_eval_column(replies_df, eval_batch_id)
            _preprocess_replies(replies_df, eval_col)

            model_series_config = analysis_cfg.get('model_series')
            if model_series_config is None or (isinstance(model_series_config, dict) and not model_series_config):
                model_series_config = select_series_interactive(replies_df)
            if model_series_config:
                # 厂商专项报告按 batch 分目录，避免专家/普通模式互相覆盖；传入 provider/model 时对重点模型做错题做与主体报告同框架的案例分析
                batch_sfx = self._batch_suffix()
                series_output_dir = self._resolve_path(
                    dm.get_path("reports", f"series{batch_sfx}" if batch_sfx else "")
                )
                if batch_sfx:
                    os.makedirs(series_output_dir, exist_ok=True)
                judge_provider, judge_model = self._resolve_judge_provider_model()
                generate_all_series_reports(
                    replies_df=replies_df,
                    questions_df=questions_df,
                    model_series_config=model_series_config,
                    output_dir=series_output_dir,
                    eval_column=eval_col,
                    provider=judge_provider,
                    model=judge_model,
                    sysprompt_manager=self.sysprompt_manager,
                    focus_model=analysis_cfg.get('series_focus_model'),
                )

        elif stage == 'test_judge_models':
            print(f"\n{'=' * 60}")
            print(f"⚖️  裁判模型可用性测试（Claude / Gemini / GPT5.2）")
            print(f"{'=' * 60}\n")
            if not self.check_and_select_judge_model():
                raise RuntimeError("裁判模型选择取消或无可选模型。")
            return

        elif stage == 'generate_report':
            report_cfg = cfg.get('report', {})
            analysis_cfg = cfg.get('analysis', {})
            if analysis_cfg.get('stats_only'):
                print("\n  ⏭ 专家验证仅统计模式（analysis.stats_only=True），跳过 HTML/MD 案例分析报告")
                return
            questions_file = self._resolve_questions_excel_for_evaluate()
            replies_file = report_cfg.get('replies_excel') or self._resolve_replies_excel()
            batch_sfx = self._batch_suffix()
            report_prefix = f"evaluation_report{batch_sfx}" if batch_sfx else 'evaluation_report'
            generate_evaluation_report(
                questions_excel=questions_file,
                replies_excel=replies_file,
                output_dir=self._resolve_path(dm.get_path("reports", "")),
                report_filename_prefix=report_prefix,
                provider=judge_provider,
                model=judge_model,
                sysprompt_manager=sp,
                human_excel=report_cfg.get('human_excel'),
                eval_batch_id=report_cfg.get('eval_batch_id', cfg.get('batch_id')),
                top_n_cases=report_cfg.get('top_n_cases', 20),
                max_workers=report_cfg.get('max_workers', cfg.get('max_workers', 3)),
                timeout=report_cfg.get('timeout', cfg.get('timeout', 120)),
                temperature=report_cfg.get('temperature', 0.3),
                report_title=report_cfg.get('report_title', '多模型能力评测报告'),
                model_list=report_cfg.get('model_list'),
                vendor_series=report_cfg.get('vendor_series'),
                thinking_models=report_cfg.get('thinking_models'),
                use_report_cache=report_cfg.get('use_report_cache', True),
                force_refresh=report_cfg.get('force_refresh', False),
                generate_html=report_cfg.get('generate_html', False),
                report_config=report_cfg,
            )

    def _print_path_summary(self, sorted_stages: List[str]) -> None:
        """根据待执行阶段打印输入/输出路径，便于检查配置是否正确。"""
        batch_sfx = self._batch_suffix()
        dm = self.dir_manager
        lines = []
        if 'expert_quick_check' in sorted_stages:
            qi = self.config.get('questions_input_excel') or f"questions{batch_sfx}.xlsx"
            if not (os.path.isabs(qi) or '/' in qi or os.path.sep in qi):
                inp = self._resolve_path(dm.get_path("questions", qi))
            else:
                inp = self._resolve_path(qi)
            lines.append(("expert_quick_check", inp, "有新题→标准/参考/回复/评测/统计"))
        if 'generate_criteria' in sorted_stages:
            complete_path = self._resolve_path(dm.get_path("questions", f"questions_complete{batch_sfx}.xlsx"))
            seed_path = self._resolve_path(dm.get_path("questions", f"questions{batch_sfx}.xlsx"))
            inp = complete_path if os.path.exists(complete_path) else seed_path
            lines.append(("generate_criteria", inp, complete_path))
        if 'generate_references' in sorted_stages:
            complete_path = self._resolve_path(dm.get_path("questions", f"questions_complete{batch_sfx}.xlsx"))
            lines.append(("generate_references", complete_path, complete_path))
        if 'generate_replies' in sorted_stages:
            qc = self._resolve_path(dm.get_path("questions", f"questions_complete{batch_sfx}.xlsx"))
            lines.append(("generate_replies", qc, self._resolve_replies_excel()))
        if any(s in sorted_stages for s in ('evaluate_replies', 'analyze_results', 'summarize_expert_assessments')):
            inp_q = self._resolve_questions_excel_for_evaluate()
            inp_r = self._resolve_replies_excel()
            lines.append(("evaluate/analyze 输入", inp_q + " + " + inp_r, "—"))
        if 'evaluate_replies' in sorted_stages:
            out = self._resolve_replies_excel()
            lines.append(("evaluate_replies 输出", "(写入回复表)", out))
        if 'analyze_results' in sorted_stages:
            out = self._resolve_path(dm.get_path("reports", f"analysis_report{batch_sfx}.xlsx"))
            lines.append(("analyze_results 输出", "—", out))
        if 'generate_report' in sorted_stages:
            out_dir = self._resolve_path(dm.get_path("reports", ""))
            lines.append(("generate_report 输出", "—", os.path.join(out_dir, f"evaluation_report{batch_sfx}_*.md")))

        if lines:
            print(f"📂 输入/输出路径摘要")
            print(f"{'=' * 60}")
            for stage_or_label, inp, out in lines:
                print(f"  【{stage_or_label}】")
                print(f"    输入: {inp}")
                print(f"    输出: {out}")
            print(f"{'=' * 60}\n")

    def run(self, stages: List[str], preserve_judge_selection: bool = False):
        sorted_stages = self._get_sorted_stages(stages)
        proj_id = self.config.get('project_id') or ""
        batch = self.config.get('data_batch') or ""
        out_hint = f"  输出: {self.dir_manager._root}" + (f"  数据批次: {batch}" if batch else "")

        print(f"\n{'=' * 60}")
        print(f"🎯 执行流程  阶段数量: {len(sorted_stages)}{out_hint}")
        print(f"{'=' * 60}")
        for i, stage in enumerate(sorted_stages, 1):
            print(f"  {i}. {self.STAGE_DEFINITIONS[stage]['name']} ({stage})")
        print(f"{'=' * 60}\n")

        self._print_path_summary(sorted_stages)

        try:
            if not preserve_judge_selection:
                self._judge_checked_this_run = False
            for stage in sorted_stages:
                self.execute_stage(stage)
            print(f"\n{'=' * 60}")
            print(f"✅ 流程执行完毕！")
            print(f"{'=' * 60}\n")
        except RuntimeError as e:
            print(f"\n❌ 流程终止: {e}")
        except Exception as e:
            print(f"\n❌ 执行失败: {e}")
            import traceback
            traceback.print_exc()

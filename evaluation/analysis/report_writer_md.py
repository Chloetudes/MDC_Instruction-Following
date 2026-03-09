# -*- coding: utf-8 -*-
import os
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .report_writer import _safe_float, _safe_str, _sanitize_excel_text, _task_count, _source_counts, _source_counts_3
from .chart_selection import profile_data, select_charts_for_report, render_charts_to_markdown


def _md_table(df: pd.DataFrame, max_rows: int = 50) -> str:
    if df.empty:
        return '_（无数据）_\n'
    display_df = df.head(max_rows)
    cols = list(display_df.columns)
    lines = ['| ' + ' | '.join(str(c) for c in cols) + ' |']
    lines.append('| ' + ' | '.join(['---'] * len(cols)) + ' |')
    for _, row in display_df.iterrows():
        cells = []
        for col in cols:
            val = row[col]
            if isinstance(val, float) and not np.isnan(val):
                cells.append(f'{val:.3f}' if abs(val) < 10 else f'{val:.2f}')
            else:
                cells.append(str(val) if pd.notna(val) else '')
        lines.append('| ' + ' | '.join(cells) + ' |')
    return '\n'.join(lines) + '\n'


def _section(title: str, level: int = 2) -> str:
    return '#' * level + ' ' + title + '\n\n'


def _group_models_into_tiers(model_scores: dict, max_tiers: int = 3) -> list:
    """按分数排序后，依模型间分差在分差最大处切分为第一/第二/第三梯队，不设固定分数。返回 [(梯队名, [(model, score), ...]), ...]。"""
    if not model_scores:
        return []
    items = [(m, _safe_float(s)) for m, s in model_scores.items()]
    items.sort(key=lambda x: x[1], reverse=True)
    scores = [x[1] for x in items]
    n = len(scores)
    if n <= max_tiers:
        return [('各模型', items)]
    # 按分差切档：在相邻分数差最大的位置划分梯队
    gaps = [scores[i] - scores[i + 1] for i in range(n - 1)]
    num_splits = min(max_tiers - 1, n - 1)
    gap_rank = sorted(range(n - 1), key=lambda i: gaps[i], reverse=True)
    split_after = sorted(gap_rank[:num_splits])
    boundaries = [-1] + split_after + [n - 1]
    tiers = []
    tier_names = ('第一梯队', '第二梯队', '第三梯队') if max_tiers == 3 else tuple(f'第{i+1}档' for i in range(max_tiers))
    for i in range(min(max_tiers, len(boundaries) - 1)):
        start, end = boundaries[i] + 1, boundaries[i + 1]
        chunk = items[start : end + 1]
        if not chunk:
            continue
        tier_name = tier_names[i] if i < len(tier_names) else f'第{i+1}档'
        tiers.append((tier_name, chunk))
    return tiers


def _build_overview_and_dimension_paragraphs(data_cache: dict) -> tuple:
    """生成总体模型表现（≤50字）及 D1–D5 分维度总体表现（每段≤150字），供报告总述使用。"""
    overall = data_cache.get('overall_ranking', pd.DataFrame())
    full_pass = data_cache.get('full_pass_summary') or {}
    dim_ila_df = data_cache.get('dimension_ila_df', pd.DataFrame())
    source_gap = data_cache.get('source_gap_summary') or {}
    overview_50 = ''
    if not overall.empty and '平均分' in overall.columns:
        n_models = len(overall)
        avg_score = overall['平均分'].mean()
        ov_rate = full_pass.get('overall_rate')
        gap = source_gap.get('公开vs纯人工自建_均分差')
        parts = [f'共 {n_models} 个模型，整体均分 {avg_score:.1f}']
        if ov_rate is not None:
            parts.append(f'ILA {ov_rate}%')
        if gap is not None and not (isinstance(gap, float) and np.isnan(gap)):
            parts.append(f'自建较公开低 {gap} 分')
        overview_50 = '；'.join(parts)[:50]
    dim_labels = {'D1': 'D1 业务理解', 'D2': 'D2 流程步骤', 'D3': 'D3 边界范围', 'D4': 'D4 格式形式', 'D5': 'D5 内容质量'}
    dim_paragraphs = []
    if not dim_ila_df.empty:
        for col in ['D1_ILA率(%)', 'D2_ILA率(%)', 'D3_ILA率(%)', 'D4_ILA率(%)', 'D5_ILA率(%)']:
            if col not in dim_ila_df.columns:
                continue
            dim_name = col.replace('_ILA率(%)', '')
            label = dim_labels.get(dim_name, dim_name)
            vals = pd.to_numeric(dim_ila_df[col], errors='coerce').dropna()
            if vals.empty:
                continue
            mean_ila = vals.mean()
            low = vals.min()
            high = vals.max()
            text = f'各模型 {label} ILA 均约 {mean_ila:.1f}%，区间 {low:.1f}%–{high:.1f}%。'
            if mean_ila < 60:
                text += '该维度整体较难，易暴露模型短板。'
            elif mean_ila > 85:
                text += '该维度通过率较高，区分度有限。'
            dim_paragraphs.append((label, text[:150]))
    return overview_50, dim_paragraphs


def generate_markdown_report(
    output_md: str,
    data: dict,
    data_cache: dict,
    case_analyses: List[dict],
    report_title: str = '多模型能力评测报告',
) -> str:
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    overall_ranking = data_cache.get('overall_ranking', pd.DataFrame())
    top20_df = data_cache.get('top20_questions', pd.DataFrame())
    item_analysis_df = data_cache.get('item_analysis_df', pd.DataFrame())
    rater_vs_others = data_cache.get('rater_vs_others', pd.DataFrame())
    model_expert_overall = data_cache.get('model_expert_overall', pd.DataFrame())
    model_ranking_summary = data_cache.get('model_ranking_summary', pd.DataFrame())
    corrected_ranking = data_cache.get('corrected_ranking', pd.DataFrame())

    replies = data.get('replies', pd.DataFrame())
    questions = data.get('questions', pd.DataFrame())
    model_count = replies['model'].nunique() if not replies.empty else 0
    task_count = _task_count(questions)
    eval_count = replies.shape[0] if not replies.empty else 0
    public_cnt, self_cnt = _source_counts(questions)
    pub_cnt_3, human_cnt_3, m_cnt_3 = _source_counts_3(questions)

    lines = []
    lines.append(f'# {report_title}\n')
    meta = f'> 生成时间: {timestamp}  \n> 评测模型: **{model_count}** 个 | 评测题目: **{task_count}** 道 | 总评测次数: **{eval_count}**'
    if public_cnt or self_cnt:
        meta += f' | 公开: {public_cnt} 题 | 自建: {self_cnt} 题'
        if human_cnt_3 or m_cnt_3:
            meta += f'（纯人工: {human_cnt_3} | M合成: {m_cnt_3}）'
    lines.append(meta + '\n')
    lines.append('\n---\n')

    lines.append(_section('目录'))
    lines.append('1. [一、执行摘要](#一执行摘要)\n')
    lines.append('2. [二、评测方法论](#二评测方法论)\n')
    lines.append('3. [三、模型能力概览](#三模型能力概览)\n')
    lines.append('4. [四、分维度与分意图能力洞察](#四分维度与分意图能力洞察)\n')
    lines.append('5. [五、专家视角与可靠性](#五专家视角与可靠性)\n')
    lines.append('6. [六、典型案例与价值题目](#六典型案例与价值题目)\n')
    lines.append('7. [七、结论与建议](#七结论与建议)\n')
    lines.append('\n---\n')

    source_stats = data_cache.get('source_stats', pd.DataFrame())
    source_gap = data_cache.get('source_gap_summary') or {}
    # 一、执行摘要（EVAL_REPORT_FRAMEWORK_v2）
    lines.append(_section('一、执行摘要'))
    lines.append('**1.1 评测目的与背景**\n\n')
    lines.append('本次评测旨在系统性评估大模型在真实复杂指令场景下的能力，通过多维度约束评测框架，打破传统基准的「分数天花板」，识别模型在语言理解、任务执行、边界遵守、格式规范等维度的差异与短板。\n\n')
    lines.append('**1.2 评测对象与数据**\n\n')
    lines.append(f'- 评测模型：{model_count} 个 | 评测题目：{task_count} 道 | 总评测次数：{eval_count}\n')
    if public_cnt or self_cnt:
        lines.append(f'- 公开数据题：{public_cnt} 题 | 自建数据题：{self_cnt} 题')
        if human_cnt_3 or m_cnt_3:
            lines.append(f'（纯人工: {human_cnt_3} | M合成: {m_cnt_3}）')
        lines.append('\n')
    if source_gap:
        gap = source_gap.get('公开vs纯人工自建_均分差')
        if gap is not None and not (isinstance(gap, float) and np.isnan(gap)):
            lines.append(f'- **公开 vs 纯人工自建均分差**：**{gap} 分**（核心指标）\n')
    lines.append('\n**1.3 核心结论**\n\n')
    conclusions = []
    if source_gap:
        gap = source_gap.get('公开vs纯人工自建_均分差')
        if gap is not None and not (isinstance(gap, float) and np.isnan(gap)):
            conclusions.append(f'- 自建题目上模型均分较公开低 {gap} 分，纯人工自建更能反映真实业务难度。')
    if not corrected_ranking.empty and '模型' in corrected_ranking.columns:
        top3 = corrected_ranking.head(3)['模型'].tolist()
        conclusions.append(f'- 专家纠偏后 TOP3：{", ".join(str(m) for m in top3)}。')
    if not model_expert_overall.empty and '斯皮尔曼_ρ' in model_expert_overall.columns:
        rho = model_expert_overall.iloc[0].get('斯皮尔曼_ρ')
        if rho is not None and not (isinstance(rho, float) and np.isnan(rho)):
            conclusions.append(f'- 整体人机排名一致性斯皮尔曼 ρ={float(rho):.2f}。')
    for c in conclusions:
        lines.append(c + '\n')
    lines.append('\n**1.4 主要建议**\n\n')
    lines.append('- **选型方**：优先考虑专家纠偏排名与 L1 能力匹配，按场景选模型。\n')
    lines.append('- **训练方**：强化 D2/D3/D5 等薄弱维度的训练与评测。\n')
    lines.append('- **数据方**：增加高区分度自建题（H/R/HM），控制 M 合成题比例。\n\n')

    # 二、评测方法论
    lines.append(_section('二、评测方法论'))
    lines.append('本评测采用三级分类体系：L1 指令结构、L2 约束功能、L3 约束类型。评分采用 AdvancedIF Rubrics 五维度（D1 业务理解、D2 流程步骤、D3 边界范围、D4 格式形式、D5 内容质量），按 D5=50%、D2=22%、D3=20%、D4=8% 加权聚合为主分数。数据来源包括公开基准与自建复杂指令集。专家纠偏：有专家打分的题目上以专家分替换模型自动分后重算均分。\n\n')

    # 三、模型能力概览
    lines.append(_section('三、模型能力概览'))
    lines.append('**3.1 综合排名**\n\n')
    rankings_scope = _safe_str(data_cache.get('rankings_source_scope') or '')
    if rankings_scope:
        lines.append(f'_注：{rankings_scope}_\n\n')
    if '原均分(CLA)' in (overall_ranking.columns if not overall_ranking.empty else []):
        lines.append('_平均分=维度加权通过率（主分数），原均分(CLA)=约束通过率。_\n')
    if not overall_ranking.empty:
        display_cols = [c for c in ['排名', '模型', '评测数量', '平均分', '原均分(CLA)', '标准差', '最高分', '最低分', '中位数'] if c in overall_ranking.columns]
        lines.append(_md_table(overall_ranking[display_cols], max_rows=15))
    else:
        lines.append('_（无排名数据）_\n')
    lines.append('\n')

    # 3.1.1 数据可视化（根据维度与数据特性自动选图，输出 PNG 嵌入 Markdown；每张图下附 LLM 约100字解读）
    try:
        profile = profile_data(data, data_cache)
        chart_configs = select_charts_for_report(data, data_cache, profile)
        if chart_configs:
            chart_insights = data_cache.get('chart_insights') or {}
            chart_md = render_charts_to_markdown(
                data, data_cache, chart_configs, output_md, chart_insights=chart_insights
            )
            if chart_md:
                lines.append('**3.1.1 数据可视化**\n\n')
                lines.append(chart_md)
                lines.append('\n')
    except Exception as e:
        lines.append(f'_（图表生成跳过: {e}）_\n\n')

    # 综合得分与完全通过率（主分数=维度加权，辅助指标独立报告）
    full_pass_summary = data_cache.get('full_pass_summary') or {}
    if full_pass_summary.get('per_model_df') is not None and not full_pass_summary['per_model_df'].empty:
        lines.append(_section('3.2 主分数与完全通过率', 3))
        lines.append('**主分数**：维度加权通过率（D5=50%, D2=22%, D3=20%, D4=8%），连续无断点。')
        lines.append('**辅助指标**：① CLA 约束通过率（passed/total）；② ILA 完全通过率（所有检查点 PASS 的题目占比）；③ 各维度 D2/D3/D4/D5 通过率。\n')
        lines.append('**各模型完全通过率**（下表仅展示前 15，完整见 Excel）：\n')
        fp_df = full_pass_summary['per_model_df']
        lines.append(_md_table(fp_df, max_rows=15))
        ov = full_pass_summary.get('overall_rate')
        if ov is not None:
            lines.append(f'\n_全体完全通过率：{full_pass_summary.get("overall_pass", 0)}/{full_pass_summary.get("overall_total", 0)} = {ov}%_\n')
        lines.append('\n')

    dimension_ila_df = data_cache.get('dimension_ila_df', pd.DataFrame())
    if not dimension_ila_df.empty:
        lines.append(_section('3.3 维度能力摘要（D1–D5 ILA）', 3))
        lines.append('各维度 ILA = 该维度下全部检查点 PASS 的题目占比；上图雷达图更直观，下表供查阅（前 15）。\n')
        lines.append(_md_table(dimension_ila_df, max_rows=15))
        lines.append('\n')

    # 基于 eval_*_raw 的扣分点汇总：按 D1–D5 统计 FAIL 比率（总体 + 按模型）
    dim_fail = (data_cache.get('dimension_fail_tables') or {})
    overall_fail_df = dim_fail.get('overall_df', pd.DataFrame()) if isinstance(dim_fail, dict) else pd.DataFrame()
    per_model_fail_df = dim_fail.get('per_model_df', pd.DataFrame()) if isinstance(dim_fail, dict) else pd.DataFrame()
    if overall_fail_df is not None and not overall_fail_df.empty:
        lines.append(_section('3.3.1 维度失分比率（基于 eval_raw 扣分点）', 3))
        lines.append('失分率=FAIL/(PASS+FAIL)。维度含义：D1=业务理解（深度理解），D2=流程步骤（遗漏/未做），D3=边界范围（越界/不遵循边界），D4=格式形式（格式不合规），D5=内容质量（内容错误/质量不佳/逻辑一致性）。其中 D2–D3 可视为“听话/遵循约束能力”，D4 为基础格式听话能力，D5 为“听话同时把事做对做好”，D1 为复杂场景下的业务理解。\n\n')
        lines.append('**总体维度失分率**\n\n')
        lines.append(_md_table(overall_fail_df, max_rows=10))
        lines.append('\n')
        if per_model_fail_df is not None and not per_model_fail_df.empty:
            lines.append('**按模型维度失分率（前 20）**\n\n')
            show = per_model_fail_df.sort_values(['失分率(%)'], ascending=False)
            lines.append(_md_table(show, max_rows=20))
            lines.append('\n')

    d5_by_l1 = data_cache.get('d5_fail_by_l1', pd.DataFrame())
    if d5_by_l1 is not None and not d5_by_l1.empty:
        lines.append(_section('3.3.2 D5（内容质量）按 L1 的失分分布', 3))
        lines.append('D5 对应“在遵循约束的同时把事情做对做好”，按 L1 聚合可定位具体业务能力薄弱类型（如写作质量、角色扮演剧情/对话理解、逻辑一致性等）。\n\n')
        lines.append(_md_table(d5_by_l1, max_rows=15))
        lines.append('\n')

    # 总体模型表现（50 字内）+ 分维度总体表现（每维度 150 字内），模板生成
    overview_50, dim_paragraphs = _build_overview_and_dimension_paragraphs(data_cache)
    if overview_50:
        lines.append(_section('3.4 总体模型表现', 3))
        lines.append(f'{overview_50}\n\n')
    if dim_paragraphs:
        lines.append('**分维度总体表现**\n\n')
        for dim_name, text in dim_paragraphs:
            lines.append(f'**{dim_name}**：{text}\n\n')

    # 四、分维度与分意图能力洞察
    lines.append(_section('四、分维度与分意图能力洞察'))

    # 4.1 L1 失分特征总结：基于 AI 评估的 Dx_Y 检查点及失分评语汇总，区分内容质量(D5)/边界限制(D3)等维度
    l1_loss_df = data_cache.get('l1_loss_profiles', pd.DataFrame())
    if not l1_loss_df.empty:
        lines.append('**4.1 L1 失分特征总结**\n')
        lines.append('本总结基于 **AI 评估的 Dx_Y 检查点及失分评语** 汇总：按 L1 任务意图聚合维度通过率与主要失分点，并列出高频失分检查点及典型失分原因（来自评语）。可明确看出各 L1 在 **内容质量(D5)**、**边界限制(D3)**、流程步骤(D2)、格式形式(D4) 等维度的失分情况，便于把握各任务类型上的能力差异。\n')
        lines.append(_md_table(l1_loss_df, max_rows=25))
        lines.append('\n')
        if '失分特征简述' in l1_loss_df.columns:
            for _, row in l1_loss_df.head(20).iterrows():
                l1_name = _safe_str(row.get('L1', ''))
                desc = _safe_str(row.get('失分特征简述', ''))
                if l1_name and desc:
                    lines.append(f'- **{l1_name}**：{desc}\n')
            lines.append('\n')

    # 4.1.1 模型×L1 失分画像：具体模型在哪些 L1、哪些维度失分及评语原因，便于定位与改进
    model_l1_df = data_cache.get('model_l1_loss_profiles', pd.DataFrame())
    model_weakness_summary = data_cache.get('model_weakness_summary') or {}
    if not model_l1_df.empty or model_weakness_summary:
        lines.append('**4.1.1 模型×L1 失分画像**\n')
        if not model_l1_df.empty:
            lines.append('按 **模型 × L1** 汇总维度通过率与 AI 评语失分原因，可直接看出「具体模型在哪些意图、哪些方面（内容质量/边界限制/流程/格式）失去分数」，便于针对性改进与数据合成。\n')
        else:
            lines.append('基于 **统计汇总** 各模型薄弱 L1 及主要失分维度（未解析评语，计算量小）。若要查看具体模型评语与 LLM 总结，请在 report 配置中设置 `l1_loss_scope: focus` 与 `focus_models_for_loss: [模型名]`。\n')
        if model_weakness_summary:
            lines.append('各模型薄弱 L1 及主要失分维度（按该模型下通过率最低的 3 个 L1）：\n')
            for model, summary in list(model_weakness_summary.items())[:30]:
                lines.append(f'- **{_safe_str(model)}**：{_safe_str(summary)}\n')
            lines.append('\n')
        if not model_l1_df.empty:
            lines.append('模型×L1 明细（前 40 行，完整可查 Excel）：\n')
            lines.append(_md_table(model_l1_df, max_rows=40))
            lines.append('\n')
        focus_llm = data_cache.get('focus_model_loss_summary') or {}
        if focus_llm:
            lines.append('**聚焦模型 vs 第一名 · LLM 失分总结**\n')
            for fm, text in focus_llm.items():
                lines.append(f'- **{_safe_str(fm)}**（相对第一名）：{_safe_str(text)}\n\n')

    l1_high_df = data_cache.get('l1_high_distinction_stats', pd.DataFrame())
    l1_summaries = data_cache.get('l1_capability_summaries') or {}
    if not l1_high_df.empty or l1_summaries:
        lines.append('**4.2 L1 高区分度题目统计与能力总结**\n')
        lines.append('按 L1 统计典型高区分度题目（区分度≥0.3），并借助统计与 LLM 分析各 L1 上的模型表现。\n')
        if not l1_high_df.empty:
            lines.append(_md_table(l1_high_df, max_rows=8))
            lines.append('\n')
        if l1_summaries:
            for l1, text in list(l1_summaries.items())[:15]:
                lines.append(f'**{_safe_str(l1)}**：{_safe_str(text) or "—"}\n\n')

    intent_level = data_cache.get('intent_level_analysis', pd.DataFrame())
    if not intent_level.empty:
        lines.append('**4.3 意图级别分析（方差 TOP10）**\n\n')
        lines.append('方差越大区分度越高。\n')
        lines.append(_md_table(intent_level, max_rows=10))
        lines.append('\n')

    constraint_insights = data_cache.get('constraint_insights') or []
    if constraint_insights:
        lines.append('**4.4 约束挑战洞察**\n\n')
        for line in constraint_insights[:15]:
            lines.append(line + '\n')
        lines.append('\n')

    # 五、专家视角与可靠性
    lines.append(_section('五、专家视角与可靠性'))
    lines.append('**5.1 专家纠偏排名**（前 15，完整见 Excel）\n\n')
    if not corrected_ranking.empty:
        lines.append(_md_table(corrected_ranking, max_rows=15))
    else:
        lines.append('_（无专家评分数据，跳过）_\n')
    lines.append('\n')

    expert_only_ranking = (data_cache.get('rankings') or {}).get('expert_only', pd.DataFrame())
    if expert_only_ranking is not None and not expert_only_ranking.empty:
        lines.append('**5.2 专家评测题目榜单**\n\n')
        lines.append('仅统计**有专家打分**的题目×模型，按专家均分排名（前 10）。\n')
        lines.append(_md_table(expert_only_ranking, max_rows=10))
        lines.append('\n')

    lines.append('**5.3 人机一致性**\n\n')
    if not model_expert_overall.empty:
        row = model_expert_overall.iloc[0]
        metrics_order = [
            ('皮尔逊_r', '线性相关，0~1 越高越一致，看趋势吻合度'),
            ('准确率(%)', '完全一致：模型分==专家分的比例'),
            ('容差准确率_±0.5分(%)', '偏差≤0.5分的比例，业务最易理解'),
            ('误差≤5分比例(%)', '偏差在5分以内'),
            ('误差≤10分比例(%)', '偏差在10分以内'),
            ('斯皮尔曼_ρ', '排名相关，-1~1 越高越一致'),
            ('ICC(2,1)', '绝对一致性'),
            ('加权Kappa', '分档一致性'),
            ('MAE', '平均绝对误差，越小越好'),
            ('RMSE', '均方根误差'),
            ('归一化MAE', '相对误差 0~1 越小越好'),
        ]
        for col, hint in metrics_order:
            if col in row.index:
                val = row[col]
                disp = val if isinstance(val, str) else f'{float(val):.3f}' if isinstance(val, (int, float)) and not (isinstance(val, float) and np.isnan(val)) else str(val)
                lines.append(f'- **{col}**：{disp} _（{hint}）_\n')
        lines.append(f'- **样本量**：{row.get("样本量", "N/A")} | **题目数**：{row.get("题目数", "N/A")} | **模型数**：{row.get("模型数", "N/A")}\n')
        lines.append('\n')
    model_expert_detail = data_cache.get('model_expert_detail', pd.DataFrame())
    if not model_expert_detail.empty:
        lines.append('按模型统计其打分与专家打分的一致性（皮尔逊、准确率、容差准确率、ICC、MAE等），排名靠前表示与专家越一致。\n')
        lines.append(_md_table(model_expert_detail, max_rows=50))
        lines.append('\n')
    if not rater_vs_others.empty:
        lines.append(_md_table(rater_vs_others))
    if not model_ranking_summary.empty:
        lines.append(_md_table(model_ranking_summary))
    if rater_vs_others.empty and model_ranking_summary.empty and model_expert_overall.empty:
        lines.append('_（无人工/专家标注数据，跳过）_\n')
    lines.append('\n')

    lines.append(_section('六、典型案例与价值题目'))
    lines.append('**6.1 价值题目 TOP20**\n\n')
    model_tiers_pre = data_cache.get('model_tiers') or []
    if model_tiers_pre:
        tier_groups = {}
        for t in model_tiers_pre:
            k = t.get('梯队', '')
            if k not in tier_groups:
                tier_groups[k] = []
            tier_groups[k].append(f"{t.get('模型', '')}（{t.get('均分', 0):.1f} 分）")
        for tier in ['第一梯队', '第二梯队', '第三梯队', '第四梯队']:
            if tier in tier_groups:
                s = ', '.join(tier_groups[tier])
                lines.append(f'- **{tier}**：{s}\n')
        lines.append('\n')
    else:
        lines.append('_（无梯队数据时由排名表可自行划分高/中/低三档）_\n\n')

    if not top20_df.empty:
        display_cols = [c for c in ['排名', 'qid', 'L1', 'L2', '数据来源', '预设难度', '模型均分', '区分度_D值', '综合价值分', '最佳模型', '最差模型'] if c in top20_df.columns]
        lines.append(_md_table(top20_df[display_cols], max_rows=8))
        if len(top20_df) > 8:
            lines.append('_（完整价值题目 TOP20 见 Excel 分析报告）_\n')
    else:
        lines.append('_（无价值题目数据）_\n')
    lines.append('\n')

    lines.append('**6.2 典型案例**\n\n')
    if case_analyses:
        for idx, case in enumerate(case_analyses, 1):
            qid = _safe_str(case.get('qid', ''))
            query = _safe_str(case.get('query', ''))
            l1 = _safe_str(case.get('L1', ''))
            l3 = _safe_str(case.get('L3', ''))
            difficulty_level = _safe_str(case.get('difficulty_level', ''))
            difficulty_score = _safe_str(case.get('difficulty_score', ''))
            difficulty = f'{difficulty_level}' + (f' / {difficulty_score}分' if difficulty_score and str(difficulty_score) not in ('', 'nan', 'None') else '')
            model_scores: dict = case.get('model_scores', {})
            model_gaps: dict = case.get('model_gaps', {})
            best_model = case.get('best_model', '')
            best_score = _safe_float(case.get('best_score', 0))
            expert_opinion = _safe_str(case.get('expert_opinion', ''))
            ai_summary = _safe_str(case.get('ai_summary', ''))
            ai_analysis = _safe_str(case.get('ai_analysis', ''))
            score_range = _safe_float(case.get('score_range', 0))
            dimension_info = _safe_str(case.get('dimension_info', ''))

            lines.append(_section(f'案例 {idx}: Q{qid}', 3))
            lines.append(f'- **L1**: {l1} | **L3**: {l3} | **难度**: {difficulty} | **分数范围**: {score_range:.1f}\n')

            if query:
                q = _sanitize_excel_text(query)
                lines.append(_section('题目内容', 4))
                lines.append(f'> {q[:300]}{"..." if len(q) > 300 else ""}\n\n')

            if model_scores:
                lines.append(_section('模型分档表现', 4))
                if best_model and best_score is not None:
                    lines.append(f'- **本题最佳**：{best_model}（{best_score:.1f} 分）\n')
                tiers = _group_models_into_tiers(model_scores, max_tiers=3)
                for tier_name, chunk in tiers:
                    names = [m for m, _ in chunk]
                    sep = '、'
                suffix = '…' if len(names) > 8 else ''
                lines.append(f'- **{tier_name}**：{sep.join(names[:8])}{suffix}\n')
                lines.append('\n')

            if dimension_info:
                lines.append(_section('本题目各模型维度表现（D2/D3/D4/D5 通过情况）', 4))
                lines.append(f'```\n{dimension_info}\n```\n\n')

            # 不罗列专家评估意见，仅保留 AI 综合评估与失分点分析
            if ai_summary:
                lines.append(_section('AI综合评估', 4))
                lines.append(f'{_sanitize_excel_text(ai_summary)}\n\n')

            if ai_analysis:
                lines.append(_section('失分点分析', 4))
                lines.append(f'{_sanitize_excel_text(ai_analysis)}\n\n')

            lines.append('---\n\n')
    else:
        lines.append('_（无典型案例分析）_\n')

    lines.append(_section('七、结论与建议'))
    lines.append('**7.1 假设验证**\n\n')
    lines.append('- 自建题目更能区分模型：公开 vs 纯人工自建均分差（见执行摘要）。\n')
    lines.append('- 模型重格式轻逻辑：D2/D3/D5 通过率普遍低于 D4，见第三章。\n')
    lines.append('- 专家纠偏影响排名：纠偏前后变化见第五章。\n\n')
    lines.append('**7.2 分角色建议**\n\n')
    lines.append('- **选型方**：结合 L1 能力总结与专家纠偏排名，按场景选模型。\n')
    lines.append('- **训练方**：加强 D2/D3/D5 相关约束的训练与评测。\n')
    lines.append('- **数据方**：增加高区分度自建题（H/R/HM），控制 M 合成题比例。\n\n')

    data_synthesis_suggestions = data_cache.get('data_synthesis_suggestions') or []
    if data_synthesis_suggestions:
        lines.append('**7.3 数据合成建议**（基于 L1 与模型×L1 失分维度与评语生成）\n\n')
        for s in data_synthesis_suggestions:
            lines.append(f'- {s}\n')
        lines.append('\n')

    model_tiers = data_cache.get('model_tiers') or []
    if model_tiers:
        lines.append('**7.4 模型能力分档**\n\n')
        tier_groups = {}
        for t in model_tiers:
            k = t.get('梯队', '')
            if k not in tier_groups:
                tier_groups[k] = []
            tier_groups[k].append(f"{t.get('模型', '')}（{t.get('均分', 0):.1f} 分）")
        for tier in ['第一梯队', '第二梯队', '第三梯队', '第四梯队']:
            if tier in tier_groups:
                lines.append(f'- **{tier}**：{", ".join(tier_groups[tier])}\n')
        lines.append('\n')

    intent_insights = data_cache.get('intent_insights') or []
    scenario_guide = data_cache.get('scenario_guide', pd.DataFrame())
    improvement_paths = data_cache.get('improvement_paths') or []

    if intent_insights:
        lines.append('**意图级别洞察**\n\n')
        for line in intent_insights[:15]:
            lines.append(line + '\n')
        lines.append('\n')

    if not scenario_guide.empty:
        lines.append('**场景化选型指南**\n\n')
        lines.append(_md_table(scenario_guide))
        lines.append('\n')

    if improvement_paths:
        lines.append('**模型能力提升路径**\n\n')
        for line in improvement_paths:
            lines.append(line + '\n')

    lines.append(_section('附录'))
    lines.append('_以下为精简统计，完整表格与多维透视见 Excel 分析报告。_\n\n')
    source_stats = data_cache.get('source_stats', pd.DataFrame())
    if not source_stats.empty:
        lines.append('**按 Source 分组得分**（前 5 行）\n\n')
        lines.append(_md_table(source_stats, max_rows=5))
        lines.append('\n')
    score_distribution = data_cache.get('score_distribution', pd.DataFrame())
    if not score_distribution.empty:
        lines.append('**分数分布**（前 10）\n\n')
        lines.append(_md_table(score_distribution, max_rows=10))
        lines.append('\n')
    constraint_eff = data_cache.get('constraint_efficacy') or {}
    if constraint_eff.get('efficacy_df') is not None and not constraint_eff['efficacy_df'].empty:
        lines.append('**约束级别分析**（前 5）\n\n')
        lines.append(_md_table(constraint_eff['efficacy_df'], max_rows=5))
        lines.append('\n')
    version_progression = data_cache.get('version_progression') or []
    if version_progression:
        vp_rows = []
        for row in version_progression:
            vp_rows.append({
                '厂商': row.get('厂商', ''), '版本顺序': row.get('版本顺序', ''), '模型': row.get('模型', ''),
                '平均分': row.get('平均分', ''), '较上版提升': row.get('较上版提升'), '较上版提升率(%)': row.get('较上版提升率(%)'),
            })
        lines.append('**厂商系列版本递进**\n\n')
        lines.append(_md_table(pd.DataFrame(vp_rows)))
        lines.append('\n')
    tc = data_cache.get('thinking_comparison')
    if tc and (tc.get('thinking_avg') is not None or tc.get('non_thinking_avg') is not None):
        lines.append('**思考模型 vs 非思考模型**\n\n')
        if tc.get('thinking_avg') is not None:
            lines.append(f'- 思考模型均分 (n={tc.get("thinking_count", 0)}): {tc["thinking_avg"]:.2f}\n')
        if tc.get('non_thinking_avg') is not None:
            lines.append(f'- 非思考模型均分 (n={tc.get("non_thinking_count", 0)}): {tc["non_thinking_avg"]:.2f}\n')
        if tc.get('delta') is not None:
            lines.append(f'- 差值: {tc["delta"]:+.2f}\n')
        lines.append('\n')
    dimension_stats = data_cache.get('dimension_stats') or {}
    if dimension_stats.get('has_data'):
        pivot = dimension_stats.get('dimension_pivot_df', pd.DataFrame())
        if not pivot.empty:
            lines.append('**维度得失分统计**\n\n')
            lines.append(_md_table(pivot))
            lines.append('\n')
    lines.append('**题目质量分析**（前 10，完整见 Excel）\n\n')
    if not item_analysis_df.empty:
        display_cols = [c for c in ['排名', 'qid', 'L1', 'L3', '难度等级', '平均质量分', '分数范围', '区分度指数_D', '综合质量分', '题目质量等级'] if c in item_analysis_df.columns]
        lines.append(_md_table(item_analysis_df[display_cols], max_rows=10))
    else:
        lines.append('_（无题目质量数据）_\n')
    lines.append('\n')

    content = '\n'.join(lines)
    os.makedirs(os.path.dirname(os.path.abspath(output_md)), exist_ok=True)
    with open(output_md, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f'  ✓ Markdown报告已生成: {output_md}')
    return output_md

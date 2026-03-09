# -*- coding: utf-8 -*-
"""
报告扩展分析模块 — 分数分布、意图级别、约束级别、总结建议
与 REPORT_EXPANSION_PLAN 对应，支撑综合报告全量扩展。
"""
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from collections import defaultdict


# D 维度 → 约束类型/中文标签（与 rubric_dimension_analysis 一致）
D_TO_CONSTRAINT_TYPE = {
    'D1': '业务理解',
    'D2': '流程步骤',
    'D3': '边界范围',
    'D4': '格式形式',
    'D5': '内容质量',
}


def compute_score_distribution(replies_df: pd.DataFrame, bins: List[Tuple[float, float]] = None) -> pd.DataFrame:
    """
    计算各模型分数分布（0-20, 20-40, 40-60, 60-80, 80-100 分段）。
    返回每模型各分数段的题目数及占比。
    """
    if replies_df.empty or 'model' not in replies_df.columns or 'eval_score' not in replies_df.columns:
        return pd.DataFrame()
    bins = bins or [(0, 20), (20, 40), (40, 60), (60, 80), (80, 101)]
    rows = []
    for model in replies_df['model'].unique():
        scores = replies_df[replies_df['model'] == model]['eval_score'].dropna()
        total = len(scores)
        if total == 0:
            continue
        row = {'模型': model, '总题目数': total}
        for lo, hi in bins:
            label = f'{int(lo)}-{int(hi) if hi <= 100 else 100}分'
            cnt = int(((scores >= lo) & (scores < hi)).sum())
            pct = round(cnt / total * 100, 1) if total > 0 else 0
            row[label] = f'{cnt}题 ({pct}%)'
        rows.append(row)
    return pd.DataFrame(rows)


def analyze_intent_level(
    replies_with_q: pd.DataFrame,
    dim_col: str = 'L1',
    top_n: int = 50,
) -> pd.DataFrame:
    """
    意图级别分析：按 L1 维度汇总各意图的题目数、平均分数方差、最佳/最差模型、各模型均分。
    意图较多时仅按 L1 分析，不深入到 L2/L3。
    """
    if replies_with_q.empty or dim_col not in replies_with_q.columns:
        return pd.DataFrame()
    dim_vals = replies_with_q[dim_col].dropna().unique()
    dim_vals = sorted([str(v).strip() for v in dim_vals if v])
    if top_n:
        counts = replies_with_q[dim_col].value_counts()
        dim_vals = [v for v in dim_vals if v in counts.index][:top_n]
    rows = []
    for dim_val in dim_vals:
        sub = replies_with_q[replies_with_q[dim_col] == dim_val]
        if sub.empty:
            continue
        q_count = sub['qid'].nunique()
        scores = sub['eval_score'].dropna()
        if len(scores) < 2:
            continue
        var_s = float(scores.var())
        model_avg = sub.groupby('model')['eval_score'].mean()
        if model_avg.empty:
            continue
        best_model = str(model_avg.idxmax())
        worst_model = str(model_avg.idxmin())
        model_scores = model_avg.sort_values(ascending=False)
        scores_str = ', '.join([f'{m}: {s:.2f}' for m, s in model_scores.items()])
        rows.append({
            '意图': dim_val,
            '题目数': int(q_count),
            '平均分数方差': round(var_s, 2),
            '最佳模型': best_model,
            '最差模型': worst_model,
            '各模型平均分': scores_str,
        })
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df = df.sort_values('平均分数方差', ascending=False).reset_index(drop=True)
    df.insert(0, '排名', df.index + 1)
    return df


def analyze_constraint_efficacy(
    replies_df: pd.DataFrame,
    dimension_stats: dict,
    eval_column: str = '',
) -> Dict:
    """
    约束级别分析：基于 rubrics_check 解析，按 D 维度（或检查点）统计失分率，
    划分 A/B/C/D 效能等级，输出最具挑战性约束 Top10。
    A: 50%+ 模型失分；B: 30-50%；C: <30%；D: 全满分
    若无细粒度检查点，则按 D 维度整体统计。
    """
    result = {
        'efficacy_df': pd.DataFrame(),
        'type_summary_df': pd.DataFrame(),
        'top10_challenging': [],
        'total_constraints': 0,
    }
    row_level_df = dimension_stats.get('row_level_df', pd.DataFrame())
    if row_level_df.empty:
        return result

    # 从 row_level_df 按 (qid, 维度) 聚合：每个 (qid, model) 有 D2_pass/D2_total 等
    # 我们需要的是：按「检查点」或「维度」跨题目聚合，看多少模型失分
    # 简化：按维度聚合。每个题目×模型×维度 可视为一个「约束实例」
    # 失分率 = (total - pass) / total 的模型比例
    try:
        from .rubric_dimension_analysis import parse_rubrics_check_from_eval_raw, get_dimension_from_checkpoint
    except ImportError:
        return result

    raw_col = ''
    if eval_column:
        raw_col = f"{eval_column}_raw" if not eval_column.endswith('_raw') else eval_column
    if raw_col not in replies_df.columns:
        raw_col = next((c for c in replies_df.columns if isinstance(c, str) and c.startswith('eval_') and c.endswith('_raw')), '')

    if not raw_col:
        # 退化为按 dimension row_level 汇总
        checkpoint_stats = []
        for dim in ['D2', 'D3', 'D4', 'D5']:
            pass_col = f'{dim}_pass'
            total_col = f'{dim}_total'
            if pass_col not in row_level_df.columns:
                continue
            total_sum = row_level_df[total_col].sum()
            pass_sum = row_level_df[pass_col].sum()
            if total_sum > 0:
                fail_rate_pct = (1 - pass_sum / total_sum) * 100
                checkpoint_stats.append({
                    'checkpoint': dim,
                    'type': D_TO_CONSTRAINT_TYPE.get(dim, dim),
                    'avg_score_pct': round(pass_sum / total_sum * 100, 1),
                    'fail_rate_pct': round(fail_rate_pct, 1),
                    'model_count': int(row_level_df['model'].nunique()),
                    'qid_count': int(row_level_df['qid'].nunique()),
                })
        if not checkpoint_stats:
            return result
        eff_df = pd.DataFrame(checkpoint_stats)
        by_cp = eff_df.copy()
        by_cp = by_cp.rename(columns={'checkpoint': '约束/维度', 'avg_score_pct': '平均得分率', 'fail_rate_pct': '平均失分率', 'qid_count': '题目数'})
        by_cp = by_cp[['约束/维度', '平均得分率', '平均失分率', '题目数']]
        by_cp['平均失分率'] = by_cp['平均失分率'].round(1)
        by_cp['平均得分率'] = by_cp['平均得分率'].round(1)

        def _grade(fail_rate):
            if fail_rate >= 50:
                return 'A'
            if fail_rate >= 30:
                return 'B'
            if fail_rate > 0:
                return 'C'
            return 'D'

        by_cp['效能等级'] = by_cp['平均失分率'].apply(_grade)
        result['efficacy_df'] = by_cp
        result['type_summary_df'] = by_cp
        result['total_constraints'] = len(by_cp)
        result['top10_challenging'] = by_cp.nlargest(10, '平均失分率').to_dict('records')
        return result
    # 若有 raw，可解析逐检查点
    return result


def compute_model_tiers(
    overall_ranking: pd.DataFrame,
    thresholds: List[float] = None,
) -> List[dict]:
    """
    模型能力梯队划分。默认阈值：90+ 第一梯队，80-90 第二梯队，70-80 第三梯队，<70 第四梯队。
    """
    if overall_ranking.empty or '平均分' not in overall_ranking.columns:
        return []
    thresholds = thresholds or [90, 80, 70]
    model_col = '模型' if '模型' in overall_ranking.columns else 'model'
    score_col = '平均分' if '平均分' in overall_ranking.columns else 'eval_score'
    if model_col not in overall_ranking.columns or score_col not in overall_ranking.columns:
        return []
    tiers = []
    for _, row in overall_ranking.iterrows():
        model = row[model_col]
        score = float(row[score_col])
        if score >= thresholds[0]:
            tier = '第一梯队'
            desc = '顶尖'
        elif score >= thresholds[1]:
            tier = '第二梯队'
            desc = '优秀'
        elif score >= thresholds[2]:
            tier = '第三梯队'
            desc = '良好'
        else:
            tier = '第四梯队'
            desc = '待提升'
        tiers.append({'模型': model, '梯队': tier, '均分': score, '描述': desc})
    return tiers


def build_intent_insights(intent_analysis_df: pd.DataFrame) -> List[str]:
    """
    意图级别深度剖析：每意图的最佳模型及简要洞察。
    """
    if intent_analysis_df.empty:
        return []
    lines = []
    for _, row in intent_analysis_df.head(20).iterrows():
        intent = row.get('意图', '')
        best = row.get('最佳模型', '')
        worst = row.get('最差模型', '')
        var_s = row.get('平均分数方差', 0)
        if intent and best:
            lines.append(f"- **{intent}**：最佳 {best}，最差 {worst}，分数方差 {var_s}（方差越大区分度越高）")
    return lines


def build_constraint_challenge_insights(constraint_result: dict) -> List[str]:
    """约束挑战深度解析：A 级约束说明与改进方向。"""
    top10 = constraint_result.get('top10_challenging', [])
    if not top10:
        return []
    lines = ['**最具挑战性的约束/维度（失分率 Top10）**：']
    for i, c in enumerate(top10[:10], 1):
        cp = c.get('约束/维度', c.get('checkpoint', ''))
        typ = c.get('type', D_TO_CONSTRAINT_TYPE.get(cp, ''))
        fail = c.get('平均失分率', c.get('fail_rate_pct', ''))
        lines.append(f'{i}. {cp}（{typ}）— 平均失分率 {fail}%')
    lines.append('\n**改进方向**：D2 流程步骤失分高建议加强多步推理数据；D4 格式形式失分高建议强化输出格式约束训练。')
    return lines


def build_scenario_guide(intent_analysis_df: pd.DataFrame, overall_ranking: pd.DataFrame) -> pd.DataFrame:
    """
    场景化模型选择指南：按意图推荐首选/次选模型。
    """
    if intent_analysis_df.empty or overall_ranking.empty:
        return pd.DataFrame()
    model_col = '模型' if '模型' in overall_ranking.columns else 'model'
    rank_order = overall_ranking[model_col].tolist()
    rows = []
    for _, row in intent_analysis_df.head(15).iterrows():
        intent = row.get('意图', '')
        best = row.get('最佳模型', '')
        worst = row.get('最差模型', '')
        all_scores = row.get('各模型平均分', '')
        second = None
        if all_scores and ',' in all_scores:
            parts = [p.strip() for p in all_scores.split(',')]
            for p in parts[1:2]:
                if ':' in p:
                    m = p.split(':')[0].strip()
                    if m != best:
                        second = m
                        break
        rows.append({
            '应用场景': intent,
            '首选模型': best,
            '次选模型': second or '—',
            '避免使用': worst,
        })
    return pd.DataFrame(rows)


def build_improvement_path(tiers: List[dict], dimension_stats: dict) -> List[str]:
    """
    模型能力提升路径：针对各梯队的改进建议。
    """
    lines = []
    dim_pivot = (dimension_stats or {}).get('dimension_pivot_df', pd.DataFrame())
    for t in tiers:
        model = t.get('模型', '')
        tier = t.get('梯队', '')
        score = t.get('均分', 0)
        if tier == '第一梯队':
            lines.append(f"- **{model}**：保持领先，可针对性补足 D2/D3 等短板维度")
        elif tier == '第二梯队':
            lines.append(f"- **{model}**：冲击第一梯队，建议强化高方差意图上的表现")
        elif tier == '第三梯队':
            lines.append(f"- **{model}**：夯实基础，重点加强流程步骤（D2）与格式形式（D4）")
        else:
            lines.append(f"- **{model}**：均分 {score:.1f}，需系统性提升，建议从 D2 操作执行逻辑入手")
    return lines

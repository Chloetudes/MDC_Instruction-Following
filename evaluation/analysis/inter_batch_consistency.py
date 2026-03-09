# -*- coding: utf-8 -*-
"""
多批次评估一致性：同一批专家数据被裁判模型多次评估（不同 batch_id）时，
计算各批次间一致性，并给出「哪个批次更可靠」的参考。
"""
import numpy as np
import pandas as pd
from scipy.stats import spearmanr, pearsonr

from .data_loader import _parse_eval_score
from .metrics import ScientificMetrics

MIN_SAMPLE = 5


def _get_eval_columns(replies_df: pd.DataFrame):
    """获取所有评估分数列（eval_ 开头且不以 _raw 结尾）。"""
    if replies_df is None or replies_df.empty:
        return []
    cols = [
        c for c in replies_df.columns
        if isinstance(c, str) and c.startswith('eval_') and not c.endswith('_raw')
    ]
    return sorted(cols)


def _scores_for_column(replies_df: pd.DataFrame, col: str) -> pd.DataFrame:
    """解析某一评估列为 (qid, model, score) 的 DataFrame。"""
    df = replies_df[['qid', 'model', col]].copy()
    df['qid'] = df['qid'].astype(str).str.strip()
    df['model'] = df['model'].astype(str).str.strip()
    df['_score'] = df[col].apply(lambda x: _parse_eval_score(x, col))
    df = df.dropna(subset=['_score'])
    return df[['qid', 'model', '_score']].rename(columns={'_score': col})


def compute_inter_batch_consistency(replies_df: pd.DataFrame):
    """
    当回复表中存在多列评估（如 eval_batch_1, eval_batch_2, eval_batch_3）时，
    计算批次间两两一致性及每批次「与其它批次平均一致性」，用于判断哪次评估更可靠。

    Returns:
        pairwise_df: 两两批次一致性（批次A, 批次B, 斯皮尔曼, Pearson, ICC, MAE, 有效样本数）
        per_batch_df: 每批次汇总（批次, 与其它批次平均斯皮尔曼, 与其它批次平均MAE, 有效样本数, 可靠性排名）
    """
    eval_cols = _get_eval_columns(replies_df)
    if len(eval_cols) < 2:
        return pd.DataFrame(), pd.DataFrame()

    # 解析各列为数值
    score_dfs = {}
    for col in eval_cols:
        score_dfs[col] = _scores_for_column(replies_df, col)

    # 两两一致性
    rows = []
    for i, col_a in enumerate(eval_cols):
        for j, col_b in enumerate(eval_cols):
            if i >= j:
                continue
            df_a = score_dfs[col_a]
            df_b = score_dfs[col_b]
            merged = df_a.merge(df_b, on=['qid', 'model'], how='inner')
            merged = merged.dropna()
            n = len(merged)
            if n < MIN_SAMPLE:
                rows.append({
                    '批次A': col_a.replace('eval_', ''),
                    '批次B': col_b.replace('eval_', ''),
                    '斯皮尔曼': np.nan,
                    'Pearson': np.nan,
                    'ICC(2,1)': np.nan,
                    'MAE': np.nan,
                    '有效样本数': n,
                })
                continue
            sa = merged[col_a].astype(float).values
            sb = merged[col_b].astype(float).values
            sp, _ = spearmanr(sa, sb)
            pe, _ = pearsonr(sa, sb)
            icc = ScientificMetrics.icc_2_1(sa, sb)
            mae = float(np.abs(sa - sb).mean())
            rows.append({
                '批次A': col_a.replace('eval_', ''),
                '批次B': col_b.replace('eval_', ''),
                '斯皮尔曼': round(float(sp), 3) if not np.isnan(sp) else np.nan,
                'Pearson': round(float(pe), 3) if not np.isnan(pe) else np.nan,
                'ICC(2,1)': round(float(icc), 3) if not np.isnan(icc) else np.nan,
                'MAE': round(mae, 2),
                '有效样本数': n,
            })

    pairwise_df = pd.DataFrame(rows)

    # 每批次：与其它批次的平均斯皮尔曼、平均 MAE
    batch_id_to_col = {c.replace('eval_', ''): c for c in eval_cols}
    per_batch = []
    for bid, col in batch_id_to_col.items():
        others = [c for c in eval_cols if c != col]
        if not others:
            per_batch.append({
                '批次': bid,
                '与其它批次平均斯皮尔曼': np.nan,
                '与其它批次平均MAE': np.nan,
                '有效样本数': len(score_dfs[col]),
            })
            continue
        sp_list, mae_list = [], []
        for oc in others:
            r = pairwise_df[
                ((pairwise_df['批次A'] == bid) & (pairwise_df['批次B'] == oc.replace('eval_', ''))) |
                ((pairwise_df['批次B'] == bid) & (pairwise_df['批次A'] == oc.replace('eval_', '')))
            ]
            if not r.empty:
                sp_val = r['斯皮尔曼'].values[0]
                mae_val = r['MAE'].values[0]
                if not np.isnan(sp_val):
                    sp_list.append(sp_val)
                if not np.isnan(mae_val):
                    mae_list.append(mae_val)
        mean_sp = round(float(np.mean(sp_list)), 3) if sp_list else np.nan
        mean_mae = round(float(np.mean(mae_list)), 2) if mae_list else np.nan
        per_batch.append({
            '批次': bid,
            '与其它批次平均斯皮尔曼': mean_sp,
            '与其它批次平均MAE': mean_mae,
            '有效样本数': len(score_dfs[col]),
        })

    per_batch_df = pd.DataFrame(per_batch)
    if not per_batch_df.empty and per_batch_df['与其它批次平均斯皮尔曼'].notna().any():
        per_batch_df = per_batch_df.sort_values(
            '与其它批次平均斯皮尔曼', ascending=False, na_position='last'
        ).reset_index(drop=True)
        per_batch_df.insert(0, '可靠性排名', per_batch_df.index + 1)

    return pairwise_df, per_batch_df


def _expert_aggregate(expert_scores_df: pd.DataFrame) -> pd.DataFrame:
    """(qid, model) -> expert_score，多专家时取均分。"""
    if expert_scores_df is None or expert_scores_df.empty or 'score' not in expert_scores_df.columns:
        return pd.DataFrame()
    agg = expert_scores_df.groupby(['qid', 'model'])['score'].mean().reset_index()
    agg.columns = ['qid', 'model', 'expert_score']
    agg['qid'] = agg['qid'].astype(str).str.strip()
    agg['model'] = agg['model'].astype(str).str.strip()
    return agg


def compute_expert_model_consistency_per_batch(
    replies_df: pd.DataFrame,
    expert_scores_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    按评估批次统计「专家打分 vs 裁判模型打分」的人机一致性。
    用于观察 human_rubrics 优化前后、或多次更新后各批次一致性的变化，引导专家调整 rubrics 或评估标准与模型对齐。

    Returns:
        DataFrame: 每行一个批次，列含 批次, 样本量, 题目数, 斯皮尔曼, 皮尔逊, ICC(2,1), MAE, 与上一批次斯皮尔曼变化
    """
    eval_cols = _get_eval_columns(replies_df)
    if not eval_cols:
        return pd.DataFrame()

    expert_agg = _expert_aggregate(expert_scores_df)
    if expert_agg.empty:
        return pd.DataFrame()

    # 按批次名排序，使 batch_1, batch_2, batch_10 按数字顺序
    def _batch_sort_key(c):
        s = c.replace('eval_', '').strip()
        parts = s.split('_')
        last = parts[-1] if parts else s
        try:
            return (0, int(last)) if str(last).isdigit() else (1, s)
        except Exception:
            return (1, s)

    eval_cols_sorted = sorted(eval_cols, key=_batch_sort_key)

    rows = []
    prev_sp = None
    for col in eval_cols_sorted:
        model_df = _scores_for_column(replies_df, col)
        if model_df.empty:
            continue
        model_df = model_df.rename(columns={col: 'model_score'})
        merged = model_df.merge(expert_agg, on=['qid', 'model'], how='inner').dropna()
        n = len(merged)
        if n < MIN_SAMPLE:
            rows.append({
                '批次': col.replace('eval_', ''),
                '样本量': n,
                '题目数': merged['qid'].nunique() if n > 0 else 0,
                '斯皮尔曼': np.nan,
                '皮尔逊': np.nan,
                'ICC(2,1)': np.nan,
                'MAE': np.nan,
                '与上一批次斯皮尔曼变化': np.nan,
            })
            continue
        x = merged['model_score'].astype(float).values
        y = merged['expert_score'].astype(float).values
        sp, _ = spearmanr(x, y)
        pe, _ = pearsonr(x, y)
        icc = ScientificMetrics.icc_2_1(x, y)
        mae = float(np.abs(x - y).mean())
        delta = (float(sp) - prev_sp) if prev_sp is not None and not np.isnan(sp) else np.nan
        if not np.isnan(sp):
            prev_sp = float(sp)
        rows.append({
            '批次': col.replace('eval_', ''),
            '样本量': n,
            '题目数': merged['qid'].nunique(),
            '斯皮尔曼': round(float(sp), 3) if not np.isnan(sp) else np.nan,
            '皮尔逊': round(float(pe), 3) if not np.isnan(pe) else np.nan,
            'ICC(2,1)': round(float(icc), 3) if not np.isnan(icc) else np.nan,
            'MAE': round(mae, 2),
            '与上一批次斯皮尔曼变化': round(delta, 3) if not np.isnan(delta) else np.nan,
        })

    df = pd.DataFrame(rows)
    return df


def compute_ranking_per_batch(replies_df: pd.DataFrame) -> pd.DataFrame:
    """
    按评估批次分别计算模型综合表现（均分、评测数量、排名），便于对比各批次间模型表现变化。
    Returns:
        DataFrame: 列含 批次, 模型, 平均分, 评测数量, 排名[, 标准差]
    """
    eval_cols = _get_eval_columns(replies_df)
    if not eval_cols:
        return pd.DataFrame()

    def _batch_sort_key(c):
        s = c.replace('eval_', '').strip()
        parts = s.split('_')
        last = parts[-1] if parts else s
        try:
            return (0, int(last)) if str(last).isdigit() else (1, s)
        except Exception:
            return (1, s)

    eval_cols_sorted = sorted(eval_cols, key=_batch_sort_key)
    all_rows = []
    for col in eval_cols_sorted:
        score_df = _scores_for_column(replies_df, col)
        if score_df.empty:
            continue
        score_df = score_df.rename(columns={col: 'score'})
        agg = score_df.groupby('model').agg(
            平均分=('score', lambda x: round(float(x.mean()), 2)),
            评测数量=('score', 'count'),
            标准差=('score', lambda x: round(float(x.std()), 2) if len(x) > 1 else 0.0),
        ).reset_index()
        agg = agg.rename(columns={'model': '模型'})
        agg = agg.sort_values('平均分', ascending=False).reset_index(drop=True)
        agg.insert(0, '排名', agg.index + 1)
        agg.insert(0, '批次', col.replace('eval_', ''))
        all_rows.append(agg)
    if not all_rows:
        return pd.DataFrame()
    return pd.concat(all_rows, ignore_index=True)


def compute_expert_model_consistency_per_batch_per_expert(
    replies_df: pd.DataFrame,
    expert_scores_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    按专家、按评估批次统计每位专家在每个批次上的人机一致性（专家打分 vs 该批次裁判模型打分）。
    用于在专家数据统计上看到每个人在各批次的表现，便于对比与迭代。
    Returns:
        DataFrame: 列含 专家, 批次, 样本量, 题目数, 斯皮尔曼, 皮尔逊, ICC(2,1), MAE
    """
    eval_cols = _get_eval_columns(replies_df)
    if not eval_cols:
        return pd.DataFrame()
    if expert_scores_df is None or expert_scores_df.empty or 'score' not in expert_scores_df.columns:
        return pd.DataFrame()
    if 'rater' not in expert_scores_df.columns:
        return pd.DataFrame()

    def _batch_sort_key(c):
        s = c.replace('eval_', '').strip()
        parts = s.split('_')
        last = parts[-1] if parts else s
        try:
            return (0, int(last)) if str(last).isdigit() else (1, s)
        except Exception:
            return (1, s)

    eval_cols_sorted = sorted(eval_cols, key=_batch_sort_key)
    expert_scores_df = expert_scores_df.copy()
    expert_scores_df['qid'] = expert_scores_df['qid'].astype(str).str.strip()
    expert_scores_df['model'] = expert_scores_df['model'].astype(str).str.strip()

    rows = []
    for expert in expert_scores_df['rater'].unique():
        exp_sub = expert_scores_df[expert_scores_df['rater'] == expert][['qid', 'model', 'score']]
        for col in eval_cols_sorted:
            model_df = _scores_for_column(replies_df, col)
            if model_df.empty:
                continue
            model_df = model_df.rename(columns={col: 'model_score'})
            merged = model_df.merge(exp_sub, on=['qid', 'model'], how='inner').dropna()
            n = len(merged)
            if n < MIN_SAMPLE:
                rows.append({
                    '专家': str(expert),
                    '批次': col.replace('eval_', ''),
                    '样本量': n,
                    '题目数': merged['qid'].nunique() if n > 0 else 0,
                    '斯皮尔曼': np.nan,
                    '皮尔逊': np.nan,
                    'ICC(2,1)': np.nan,
                    'MAE': np.nan,
                })
                continue
            x = merged['model_score'].astype(float).values
            y = merged['score'].astype(float).values
            sp, _ = spearmanr(x, y)
            pe, _ = pearsonr(x, y)
            icc = ScientificMetrics.icc_2_1(x, y)
            mae = float(np.abs(x - y).mean())
            rows.append({
                '专家': str(expert),
                '批次': col.replace('eval_', ''),
                '样本量': n,
                '题目数': merged['qid'].nunique(),
                '斯皮尔曼': round(float(sp), 3) if not np.isnan(sp) else np.nan,
                '皮尔逊': round(float(pe), 3) if not np.isnan(pe) else np.nan,
                'ICC(2,1)': round(float(icc), 3) if not np.isnan(icc) else np.nan,
                'MAE': round(mae, 2),
            })
    return pd.DataFrame(rows)

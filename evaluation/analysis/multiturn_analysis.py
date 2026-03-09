# -*- coding: utf-8 -*-
"""
多轮评测分析：按 session + model 汇总每轮得分，定位首败轮次、会话是否通过。
复用逐轮打分结果（replies 表含 session_id, turn_id, eval_*），不做新打分。
"""
import os
from typing import Optional

import numpy as np
import pandas as pd

from .data_loader import _load_replies, _resolve_eval_column


def generate_multiturn_analysis(
    replies_excel: str,
    output_excel: str,
    eval_batch_id: Optional[str] = None,
    score_pass_threshold: float = 60.0,
) -> pd.DataFrame:
    """
    基于回复表（含 session_id, turn_id 与评估列）做多轮分析。
    输出：每个 (session_id, model) 的轮次得分、首败轮次、会话是否通过、均分等。
    """
    print(f"\n{'=' * 60}")
    print(f"📊 多轮评测分析")
    print(f"{'=' * 60}\n")

    if not os.path.exists(replies_excel):
        raise FileNotFoundError(f"回复表不存在: {replies_excel}")

    replies_df = _load_replies(replies_excel)
    eval_column = _resolve_eval_column(replies_df, eval_batch_id)

    for col in ['session_id', 'turn_id']:
        if col not in replies_df.columns:
            print(f"⚠️  回复表缺少列 {col}，跳过多轮分析（仅多轮数据含该列）")
            return pd.DataFrame()

    replies_df['qid'] = replies_df['qid'].astype(str).str.strip()
    replies_df['model'] = replies_df['model'].astype(str).str.strip()

    try:
        replies_df['turn_id'] = pd.to_numeric(replies_df['turn_id'], errors='coerce')
    except Exception:
        pass

    valid = replies_df[eval_column].apply(
        lambda x: x is not None and not (isinstance(x, float) and np.isnan(x)) and str(x).strip() != ''
    )
    try:
        scores = pd.to_numeric(replies_df.loc[valid, eval_column], errors='coerce')
        replies_df.loc[valid, '_score'] = scores
    except Exception:
        replies_df['_score'] = np.nan
    replies_df.loc[~valid, '_score'] = np.nan

    session_id_col = 'session_id'
    turn_id_col = 'turn_id'

    rows = []
    for (session_id, model), grp in replies_df.groupby([session_id_col, 'model']):
        grp = grp.sort_values(turn_id_col).drop_duplicates(subset=[turn_id_col], keep='first')
        turn_ids = grp[turn_id_col].astype(int).tolist()
        score_list = grp['_score'].tolist()
        turn_scores = [(t, s) for t, s in zip(turn_ids, score_list) if not (s is None or (isinstance(s, float) and np.isnan(s)))]

        if not turn_scores:
            turn_ids_str = ','.join(map(str, turn_ids)) if turn_ids else ''
            turn_scores_str = ''
            first_fail_turn = None
            session_passed = False
            avg_score = np.nan
            min_turn_score = np.nan
        else:
            turn_ids_str = ','.join(str(t) for t, _ in turn_scores)
            turn_scores_str = ','.join(f"{t}:{float(s):.0f}" for t, s in turn_scores)
            scores_only = [float(s) for _, s in turn_scores]
            avg_score = float(np.nanmean(scores_only))
            min_turn_score = float(np.nanmin(scores_only))
            first_fail_turn = None
            for t, s in turn_scores:
                if s is not None and not (isinstance(s, float) and np.isnan(s)):
                    if float(s) < score_pass_threshold:
                        first_fail_turn = int(t)
                        break
            session_passed = first_fail_turn is None

        rows.append({
            'session_id': session_id,
            'model': model,
            'num_turns': len(turn_scores),
            'turn_ids': turn_ids_str,
            'turn_scores': turn_scores_str if turn_scores else '',
            'avg_score': avg_score,
            'min_turn_score': min_turn_score,
            'first_fail_turn': first_fail_turn,
            'session_passed': session_passed,
        })

    df_out = pd.DataFrame(rows)

    if df_out.empty:
        print("  无多轮会话数据可分析")
        return df_out

    os.makedirs(os.path.dirname(output_excel) or '.', exist_ok=True)
    df_out.to_excel(output_excel, index=False)
    print(f"  ✅ 多轮分析已保存: {output_excel}")
    print(f"  会话数: {df_out['session_id'].nunique()}  模型数: {df_out['model'].nunique()}")
    print(f"  通过会话数: {df_out['session_passed'].sum()}  首败轮次已标注")
    print(f"{'=' * 60}\n")
    return df_out

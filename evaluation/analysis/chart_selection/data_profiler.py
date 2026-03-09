# -*- coding: utf-8 -*-
"""
数据画像：根据 data_cache 和 data 生成统计摘要，供图表选型使用。
"""
from typing import Dict, Any

import numpy as np
import pandas as pd


def profile_data(data: dict, data_cache: dict) -> dict:
    """
    从 data 和 data_cache 提取数据画像。
    返回: {
        model_count: int,
        has_L1: bool, has_L2: bool, has_L3: bool,
        has_difficulty: bool, has_source: bool,
        has_dimension_pivot: bool,
        dimension_cols: list,
        score_col: str,
    }
    """
    profile = {
        'model_count': 0,
        'has_L1': False, 'has_L2': False, 'has_L3': False,
        'has_difficulty': False, 'has_source': False,
        'has_dimension_pivot': False,
        'has_dimension_ila': False,
        'dimension_cols': [],
        'score_col': 'eval_score',
    }

    replies = data.get('replies', pd.DataFrame())
    replies_with_q = data.get('replies_with_question', pd.DataFrame())
    df = replies_with_q if not replies_with_q.empty else replies
    overall = data_cache.get('overall_ranking', pd.DataFrame())
    dim_stats = data_cache.get('dimension_stats') or {}
    pivot = dim_stats.get('dimension_pivot_df', pd.DataFrame())

    if not overall.empty and '模型' in overall.columns:
        profile['model_count'] = len(overall)
    elif not df.empty and 'model' in df.columns:
        profile['model_count'] = df['model'].nunique()

    if not df.empty:
        profile['has_L1'] = 'L1' in df.columns and df['L1'].notna().any()
        profile['has_L2'] = 'L2' in df.columns and df['L2'].notna().any()
        profile['has_L3'] = 'L3' in df.columns and df['L3'].notna().any()
        profile['has_difficulty'] = (
            ('difficulty_level' in df.columns and df['difficulty_level'].notna().any()) or
            ('difficulty_code' in df.columns and df['difficulty_code'].notna().any())
        )
        has_src = 'source' in df.columns and df['source'].notna().any()
        has_sg = 'source_group' in df.columns and df['source_group'].notna().any()
        profile['has_source'] = has_src or has_sg

    dim_cols = ['D2通过率', 'D3通过率', 'D4通过率', 'D5通过率']
    if not pivot.empty:
        profile['has_dimension_pivot'] = any(c in pivot.columns for c in dim_cols)
        profile['dimension_cols'] = [c for c in dim_cols if c in pivot.columns]
    dim_ila = data_cache.get('dimension_ila_df', pd.DataFrame())
    profile['has_dimension_ila'] = not dim_ila.empty and any(c in dim_ila.columns for c in ['D1_ILA率(%)', 'D2_ILA率(%)', 'D3_ILA率(%)'])

    return profile

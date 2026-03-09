# -*- coding: utf-8 -*-
"""
图表选型：根据分析意图和数据画像选择图表类型与配置。
"""
from dataclasses import dataclass
from typing import List, Optional

import pandas as pd


@dataclass
class ChartConfig:
    """图表配置"""
    chart_id: str
    chart_type: str  # bar, heatmap, radar, box, scatter, histogram
    title: str
    x_dim: Optional[str] = None
    y_dim: Optional[str] = None
    color_dim: Optional[str] = None
    row_dim: Optional[str] = None      # 热力图行
    col_dim: Optional[str] = None      # 热力图列
    value_dim: Optional[str] = None
    top_n: Optional[int] = None
    condition: Optional[dict] = None   # 额外条件，如 model_count <= 10


# 选型规则：分析场景 -> 图表配置
CHART_RULES = [
    {
        'id': 'model_bar',
        'chart_type': 'bar',
        'title': '模型综合均分对比（TOP20）',
        'dims': ['model'],
        'metric': 'eval_score',
        'agg': 'mean',
        'x_dim': 'model',
        'y_dim': 'mean_score',
        'top_n': 20,
    },
    {
        'id': 'dim_heatmap',
        'chart_type': 'heatmap',
        'title': 'D2-D5 维度通过率×模型热力图',
        'requires': ['has_dimension_pivot'],
        'row_dim': 'model',
        'col_dim': 'dimension',
        'value_dim': 'pass_rate',
    },
    {
        'id': 'dim_radar',
        'chart_type': 'radar',
        'title': 'TOP5 模型 D2-D5 约束维度雷达图',
        'requires': ['has_dimension_pivot'],
        'top_n': 5,
    },
    {
        'id': 'l1_radar',
        'chart_type': 'radar',
        'title': 'TOP5 模型 L1 意图类型均分雷达图',
        'requires': ['has_L1'],
        'top_n': 5,
    },
    {
        'id': 'd1d5_radar',
        'chart_type': 'radar',
        'title': 'TOP5 模型 D1-D5 维度 ILA 通过率雷达图',
        'requires': ['has_dimension_ila'],
        'top_n': 5,
    },
    {
        'id': 'l1_heatmap',
        'chart_type': 'heatmap',
        'title': 'L1意图类型×模型得分热力图',
        'requires': ['has_L1'],
        'row_dim': 'model',
        'col_dim': 'L1',
        'value_dim': 'eval_score',
    },
    {
        'id': 'difficulty_heatmap',
        'chart_type': 'heatmap',
        'title': '难度等级×模型得分热力图',
        'requires': ['has_difficulty'],
        'row_dim': 'difficulty_level',
        'col_dim': 'model',
        'value_dim': 'eval_score',
    },
    {
        'id': 'source_heatmap',
        'chart_type': 'heatmap',
        'title': '数据来源×模型得分热力图',
        'requires': ['has_source'],
        'row_dim': 'source_group',
        'col_dim': 'model',
        'value_dim': 'eval_score',
    },
    {
        'id': 'score_box',
        'chart_type': 'box',
        'title': '各模型得分分布（箱线图）',
        'x_dim': 'model',
        'y_dim': 'eval_score',
        'top_n': 20,
    },
    {
        'id': 'score_histogram',
        'chart_type': 'histogram',
        'title': '整体分数分布',
        'x_dim': 'eval_score',
    },
]


def select_charts_for_report(data: dict, data_cache: dict, profile: dict) -> List[ChartConfig]:
    """
    根据数据画像选择本报告应生成的图表列表。
    """
    configs = []
    overall = data_cache.get('overall_ranking', pd.DataFrame())
    model_count = profile.get('model_count', 0)

    for rule in CHART_RULES:
        requires = rule.get('requires', [])
        if requires and not all(profile.get(r, False) for r in requires):
            continue
        cond = rule.get('condition', {})
        if cond:
            max_m = cond.get('model_count_max')
            if max_m is not None and model_count > max_m:
                continue
        cfg = ChartConfig(
            chart_id=rule['id'],
            chart_type=rule['chart_type'],
            title=rule['title'],
            x_dim=rule.get('x_dim'),
            y_dim=rule.get('y_dim'),
            row_dim=rule.get('row_dim'),
            col_dim=rule.get('col_dim'),
            value_dim=rule.get('value_dim'),
            top_n=rule.get('top_n'),
        )
        configs.append(cfg)
    return configs

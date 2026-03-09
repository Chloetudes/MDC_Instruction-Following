# -*- coding: utf-8 -*-
"""图表选型模块：根据分析维度和数据特性自动选择并生成图表。"""
from .data_profiler import profile_data
from .chart_selector import select_charts_for_report, ChartConfig
from .chart_renderer import render_charts_to_markdown

__all__ = ['profile_data', 'select_charts_for_report', 'ChartConfig', 'render_charts_to_markdown']

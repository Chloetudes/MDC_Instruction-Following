# -*- coding: utf-8 -*-
"""
图表渲染：将 ChartConfig + 数据 渲染为 PNG，并生成 Markdown 引用。
中文显示：优先使用系统支持的 CJK 字体，保证标题/轴标签正确显示汉字。
"""
import os
from typing import List, Optional, Dict

import numpy as np
import pandas as pd

from .chart_selector import ChartConfig

# 中文字体优先级：macOS 常用 PingFang SC / Heiti SC，Windows 用 Microsoft YaHei / SimHei，最后兜底
_CHINESE_FONT_SET = False


def _setup_chinese_font():
    """设置 matplotlib 使用支持中文的字体，仅执行一次。"""
    global _CHINESE_FONT_SET
    if _CHINESE_FONT_SET:
        return
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.font_manager as fm
        # 优先选用已安装的 CJK 字体，避免方框
        candidates = [
            'PingFang SC', 'Heiti SC', 'STHeiti', 'Microsoft YaHei', 'SimHei',
            'WenQuanYi Micro Hei', 'Noto Sans CJK SC', 'Arial Unicode MS', 'sans-serif'
        ]
        available = [f.name for f in fm.fontManager.ttflist]
        chosen = []
        for c in candidates:
            if c in available or any(c in f for f in available):
                chosen.append(c)
                break
        if not chosen:
            chosen = ['SimHei', 'DejaVu Sans', 'sans-serif']
        plt.rcParams['font.sans-serif'] = chosen + ['DejaVu Sans', 'sans-serif']
        plt.rcParams['axes.unicode_minus'] = False
        _CHINESE_FONT_SET = True
    except Exception:
        _CHINESE_FONT_SET = True


def _chart_dpi():
    """图表保存 DPI，略高以提升中文可读性。"""
    return 150


def _safe_float(x):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return 0.0
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _safe_str(x):
    return str(x).strip() if x is not None and not (isinstance(x, float) and np.isnan(x)) else ''


def _ensure_figures_dir(output_md: str) -> str:
    """确保 figures 目录存在，返回 figures 目录绝对路径。"""
    base = os.path.dirname(output_md)
    fig_dir = os.path.join(base, 'figures')
    os.makedirs(fig_dir, exist_ok=True)
    return fig_dir


def _render_bar(data_cache: dict, config: ChartConfig, fig_path: str) -> bool:
    """柱状图：模型均分 TOP N，带误差条。"""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        _setup_chinese_font()
    except ImportError:
        return False

    overall = data_cache.get('overall_ranking', pd.DataFrame())
    if overall.empty or '模型' not in overall.columns or '平均分' not in overall.columns:
        return False
    n = config.top_n or 20
    df = overall.head(n)
    models = [str(m) for m in df['模型'].tolist()]
    scores = [_safe_float(s) for s in df['平均分'].tolist()]
    stds = df['标准差'].tolist() if '标准差' in df.columns else [0] * len(models)
    stds = [_safe_float(s) for s in stds]
    if len(stds) < len(models):
        stds = stds + [0] * (len(models) - len(stds))

    fig, ax = plt.subplots(figsize=(12, 6))
    x = range(len(models))
    # 高区分度配色：tab10 循环，保证相邻模型颜色差异大
    cmap = plt.cm.tab10
    colors = [cmap(i % 10) for i in range(len(models))]
    bars = ax.bar(x, scores, yerr=stds, capsize=2, color=colors, edgecolor='#333', linewidth=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels([m[:16] + '…' if len(m) > 16 else m for m in models], rotation=45, ha='right', fontsize=9)
    ax.set_ylabel('平均分', fontsize=11)
    ax.set_xlabel('模型', fontsize=11)
    ax.set_title(config.title, fontsize=13)
    ax.set_ylim(0, min(105, max(scores) + 15) if scores else 100)
    ax.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    plt.savefig(fig_path, dpi=_chart_dpi(), bbox_inches='tight')
    plt.close()
    return True


def _render_heatmap(data: dict, data_cache: dict, config: ChartConfig, fig_path: str) -> bool:
    """热力图：row_dim × col_dim，值为 value_dim。"""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        _setup_chinese_font()
    except ImportError:
        return False

    replies = data.get('replies_with_question', data.get('replies', pd.DataFrame()))
    dim_stats = data_cache.get('dimension_stats') or {}
    pivot = dim_stats.get('dimension_pivot_df', pd.DataFrame())
    overall = data_cache.get('overall_ranking', pd.DataFrame())

    if config.chart_id == 'dim_heatmap' and not pivot.empty:
        dim_cols = [c for c in ['D2通过率', 'D3通过率', 'D4通过率', 'D5通过率'] if c in pivot.columns]
        if not dim_cols or '模型' not in pivot.columns:
            return False
        labels = {'D2通过率': 'D2流程', 'D3通过率': 'D3边界', 'D4通过率': 'D4格式', 'D5通过率': 'D5内容'}
        z = pivot[dim_cols].apply(lambda c: pd.to_numeric(c, errors='coerce').fillna(0)).values
        row_labels = pivot['模型'].astype(str).tolist()
        col_labels = [labels.get(c, c) for c in dim_cols]
    elif config.chart_id == 'l1_heatmap' and not replies.empty and 'L1' in replies.columns:
        model_list = overall['模型'].astype(str).tolist() if not overall.empty else replies['model'].unique().tolist()
        l1_cats = sorted([str(c) for c in replies['L1'].dropna().unique()])
        z = []
        for m in model_list:
            row = []
            for cat in l1_cats:
                sub = replies[(replies['model'] == m) & (replies['L1'] == cat)]
                row.append(sub['eval_score'].mean() if not sub.empty else np.nan)
            z.append(row)
        z = np.array(z)
        row_labels = [str(m)[:20] for m in model_list]
        col_labels = l1_cats
    elif config.chart_id == 'difficulty_heatmap' and not replies.empty:
        dim_col = 'difficulty_level' if 'difficulty_level' in replies.columns else 'difficulty_code'
        if dim_col not in replies.columns:
            return False
        model_list = overall['模型'].astype(str).tolist() if not overall.empty else replies['model'].unique().tolist()
        cats = sorted([str(c) for c in replies[dim_col].dropna().unique()])
        z = []
        for c in cats:
            row = []
            for m in model_list:
                sub = replies[(replies['model'] == m) & (replies[dim_col].astype(str) == c)]
                row.append(sub['eval_score'].mean() if not sub.empty else np.nan)
            z.append(row)
        z = np.array(z)
        row_labels = cats
        col_labels = [str(m)[:16] for m in model_list]
    elif config.chart_id == 'source_heatmap' and not replies.empty and 'source_group' in replies.columns:
        model_list = overall['模型'].astype(str).tolist() if not overall.empty else replies['model'].unique().tolist()
        cats = sorted([str(c) for c in replies['source_group'].dropna().unique()])
        z = []
        for c in cats:
            row = []
            for m in model_list:
                sub = replies[(replies['model'] == m) & (replies['source_group'].astype(str) == c)]
                row.append(sub['eval_score'].mean() if not sub.empty else np.nan)
            z.append(row)
        z = np.array(z)
        row_labels = cats
        col_labels = [str(m)[:16] for m in model_list]
    else:
        return False

    fig, ax = plt.subplots(figsize=(max(8, len(col_labels) * 0.5), max(5, len(row_labels) * 0.35)))
    # 高对比度热力配色：深蓝→青→绿→黄，便于区分低分与高分
    from matplotlib.colors import LinearSegmentedColormap
    _heat_colors = ['#0d47a1', '#1565c0', '#1976d2', '#42a5f5', '#90caf9', '#b3e5fc', '#c8e6c9', '#81c784', '#ffb74d', '#ff9800', '#f57c00']
    heat_cmap = LinearSegmentedColormap.from_list('report_heat', _heat_colors, N=256)
    im = ax.imshow(np.nan_to_num(z, nan=0), cmap=heat_cmap, aspect='auto', vmin=0, vmax=100)
    ax.set_xticks(range(len(col_labels)))
    ax.set_yticks(range(len(row_labels)))
    ax.set_xticklabels(col_labels, rotation=45, ha='right', fontsize=9)
    ax.set_yticklabels(row_labels, fontsize=9)
    for i in range(len(row_labels)):
        for j in range(len(col_labels)):
            v = z[i, j]
            ax.text(j, i, f'{v:.0f}' if not np.isnan(v) else '-', ha='center', va='center', fontsize=8, color='#333')
    cbar = plt.colorbar(im, ax=ax)
    cbar.set_label('得分', fontsize=10)
    # 按图表类型设置清晰的轴标签
    if config.chart_id == 'dim_heatmap':
        ax.set_xlabel('维度（D2流程/D3边界/D4格式/D5内容）', fontsize=10)
        ax.set_ylabel('模型', fontsize=10)
    elif config.chart_id == 'l1_heatmap':
        ax.set_xlabel('L1 意图类型', fontsize=10)
        ax.set_ylabel('模型', fontsize=10)
    elif config.chart_id == 'difficulty_heatmap':
        ax.set_xlabel('模型', fontsize=10)
        ax.set_ylabel('难度等级', fontsize=10)
    elif config.chart_id == 'source_heatmap':
        ax.set_xlabel('模型', fontsize=10)
        ax.set_ylabel('数据来源', fontsize=10)
    else:
        ax.set_xlabel('列维度', fontsize=10)
        ax.set_ylabel('行维度', fontsize=10)
    ax.set_title(config.title, fontsize=13)
    plt.tight_layout()
    plt.savefig(fig_path, dpi=_chart_dpi(), bbox_inches='tight')
    plt.close()
    return True


def _render_radar_l1(data: dict, data_cache: dict, config: ChartConfig, fig_path: str) -> bool:
    """L1 雷达图：TOP N 模型在各 L1 意图类型上的均分。"""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import math
        _setup_chinese_font()
    except ImportError:
        return False
    replies = data.get('replies_with_question', data.get('replies', pd.DataFrame()))
    overall = data_cache.get('overall_ranking', pd.DataFrame())
    if replies.empty or 'L1' not in replies.columns or overall.empty:
        return False
    l1_cats = sorted([str(c) for c in replies['L1'].dropna().unique()])
    if not l1_cats:
        return False
    top_n = config.top_n or 5
    models = overall.head(top_n)['模型'].astype(str).tolist()
    n = len(l1_cats)
    angles = [2 * math.pi * i / n for i in range(n)] + [0]
    fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(projection='polar'))
    colors = plt.cm.tab10(np.linspace(0, 1, max(len(models), 1)))
    for idx, model in enumerate(models):
        vals = []
        for cat in l1_cats:
            sub = replies[(replies['model'] == model) & (replies['L1'] == cat)]
            vals.append(float(sub['eval_score'].mean()) if not sub.empty else 0)
        vals = vals + [vals[0]]
        ax.plot(angles, vals, 'o-', linewidth=2, label=(model[:18] + '…' if len(model) > 18 else model), color=colors[idx % 10])
        ax.fill(angles, vals, alpha=0.25, color=colors[idx % 10])
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(l1_cats, fontsize=9)
    ax.set_ylim(0, 105)
    ax.set_ylabel('均分', fontsize=10)
    ax.legend(loc='upper right', bbox_to_anchor=(1.28, 1.0), fontsize=8)
    ax.set_title(config.title, fontsize=13)
    plt.tight_layout()
    plt.savefig(fig_path, dpi=_chart_dpi(), bbox_inches='tight')
    plt.close()
    return True


def _render_radar_d1d5(data_cache: dict, config: ChartConfig, fig_path: str) -> bool:
    """D1–D5 维度雷达图：TOP N 模型在各维度 ILA 通过率。"""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import math
        _setup_chinese_font()
    except ImportError:
        return False
    dim_ila = data_cache.get('dimension_ila_df', pd.DataFrame())
    overall = data_cache.get('overall_ranking', pd.DataFrame())
    if dim_ila.empty or overall.empty or '模型' not in dim_ila.columns:
        return False
    dim_cols = [c for c in ['D1_ILA率(%)', 'D2_ILA率(%)', 'D3_ILA率(%)', 'D4_ILA率(%)', 'D5_ILA率(%)'] if c in dim_ila.columns]
    if not dim_cols:
        return False
    theta = ['D1业务理解', 'D2流程步骤', 'D3边界范围', 'D4格式形式', 'D5内容质量'][:len(dim_cols)]
    top_n = config.top_n or 5
    models = overall.head(top_n)['模型'].astype(str).tolist()
    n = len(theta)
    angles = [2 * math.pi * i / n for i in range(n)] + [0]
    fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(projection='polar'))
    colors = plt.cm.tab10(np.linspace(0, 1, max(len(models), 1)))
    for idx, model in enumerate(models):
        row = dim_ila[dim_ila['模型'].astype(str) == model]
        if row.empty:
            continue
        vals = [float(pd.to_numeric(row.iloc[0].get(c), errors='coerce') or 0) for c in dim_cols]
        vals = vals + [vals[0]]
        ax.plot(angles, vals, 'o-', linewidth=2, label=(model[:18] + '…' if len(model) > 18 else model), color=colors[idx % 10])
        ax.fill(angles, vals, alpha=0.25, color=colors[idx % 10])
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(theta, fontsize=9)
    ax.set_ylim(0, 105)
    ax.set_ylabel('ILA通过率(%)', fontsize=10)
    ax.legend(loc='upper right', bbox_to_anchor=(1.28, 1.0), fontsize=8)
    ax.set_title(config.title, fontsize=13)
    plt.tight_layout()
    plt.savefig(fig_path, dpi=_chart_dpi(), bbox_inches='tight')
    plt.close()
    return True


def _render_radar(data_cache: dict, config: ChartConfig, fig_path: str) -> bool:
    """雷达图：TOP N 模型在 D2–D5 的通过率（约束维度）。"""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import math
        _setup_chinese_font()
    except ImportError:
        return False

    dim_stats = data_cache.get('dimension_stats') or {}
    pivot = dim_stats.get('dimension_pivot_df', pd.DataFrame())
    overall = data_cache.get('overall_ranking', pd.DataFrame())
    if pivot.empty or overall.empty:
        return False
    dim_cols = [c for c in ['D2通过率', 'D3通过率', 'D4通过率', 'D5通过率'] if c in pivot.columns]
    if not dim_cols:
        return False
    theta = ['D2流程', 'D3边界', 'D4格式', 'D5内容']
    top5 = overall.head(config.top_n or 5)['模型'].astype(str).tolist()
    n = len(theta)
    angles = [2 * math.pi * i / n for i in range(n)] + [0]

    fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(projection='polar'))
    colors = plt.cm.tab10(np.linspace(0, 1, max(len(top5), 1)))
    for idx, model in enumerate(top5):
        row = pivot[pivot['模型'].astype(str) == model]
        if row.empty:
            continue
        vals = [float(pd.to_numeric(row.iloc[0].get(c), errors='coerce') or 0) for c in dim_cols]
        vals = vals + [vals[0]]
        ax.plot(angles, vals, 'o-', linewidth=2, label=(model[:18] + '…' if len(model) > 18 else model), color=colors[idx % 10])
        ax.fill(angles, vals, alpha=0.25, color=colors[idx % 10])
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(theta, fontsize=9)
    ax.set_ylim(0, 105)
    ax.set_ylabel('通过率(%)', fontsize=10)
    ax.legend(loc='upper right', bbox_to_anchor=(1.28, 1.0), fontsize=8)
    ax.set_title(config.title, fontsize=13)
    plt.tight_layout()
    plt.savefig(fig_path, dpi=_chart_dpi(), bbox_inches='tight')
    plt.close()
    return True


def _render_box(data: dict, data_cache: dict, config: ChartConfig, fig_path: str) -> bool:
    """箱线图：各模型得分分布。"""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        _setup_chinese_font()
    except ImportError:
        return False

    replies = data.get('replies_with_question', data.get('replies', pd.DataFrame()))
    overall = data_cache.get('overall_ranking', pd.DataFrame())
    if replies.empty or 'model' not in replies.columns or 'eval_score' not in replies.columns:
        return False
    models = overall.head(config.top_n or 20)['模型'].astype(str).tolist() if not overall.empty else list(replies['model'].unique())[:20]
    data_list = [replies[replies['model'] == m]['eval_score'].dropna().tolist() for m in models]
    data_list = [[float(x) for x in vs if x is not None] for vs in data_list]
    labels = [m[:16] + '…' if len(m) > 16 else m for m in models]

    fig, ax = plt.subplots(figsize=(12, 6))
    bp = ax.boxplot(data_list, labels=labels, patch_artist=True)
    for patch in bp['boxes']:
        patch.set_facecolor('lightblue')
        patch.set_alpha(0.7)
    ax.set_xticklabels(labels, rotation=45, ha='right')
    ax.set_ylabel('得分')
    ax.set_ylim(0, 105)
    ax.set_title(config.title)
    ax.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    plt.savefig(fig_path, dpi=_chart_dpi(), bbox_inches='tight')
    plt.close()
    return True


def _render_histogram(data: dict, config: ChartConfig, fig_path: str) -> bool:
    """直方图：整体分数分布。"""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        _setup_chinese_font()
    except ImportError:
        return False

    replies = data.get('replies_with_question', data.get('replies', pd.DataFrame()))
    if replies.empty or 'eval_score' not in replies.columns:
        return False
    scores = replies['eval_score'].dropna().astype(float)
    scores = scores[(scores >= 0) & (scores <= 100)]

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(scores, bins=20, range=(0, 100), color='steelblue', edgecolor='white', alpha=0.8)
    ax.set_xlabel('得分')
    ax.set_ylabel('频数')
    ax.set_title(config.title)
    ax.set_xlim(0, 100)
    ax.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    plt.savefig(fig_path, dpi=_chart_dpi(), bbox_inches='tight')
    plt.close()
    return True


def render_charts_to_markdown(
    data: dict,
    data_cache: dict,
    configs: List[ChartConfig],
    output_md: str,
    chart_insights: Optional[Dict[str, str]] = None,
) -> str:
    """
    将选中的图表渲染为 PNG 并生成 Markdown 片段（含图片引用）。
    output_md: 报告 Markdown 路径，用于确定 figures 输出目录。
    chart_insights: 可选，chart_id -> 约100字图表解读，每张图下会追加「图表解读」段落。
    返回: Markdown 字符串，可直接插入报告。
    """
    fig_dir = _ensure_figures_dir(output_md)
    rel_fig_dir = 'figures'
    insights = chart_insights or {}
    lines = []

    for config in configs:
        fname = f"{config.chart_id}.png"
        fig_path = os.path.join(fig_dir, fname)
        ok = False
        if config.chart_type == 'bar':
            ok = _render_bar(data_cache, config, fig_path)
        elif config.chart_type == 'heatmap':
            ok = _render_heatmap(data, data_cache, config, fig_path)
        elif config.chart_type == 'radar':
            if config.chart_id == 'l1_radar':
                ok = _render_radar_l1(data, data_cache, config, fig_path)
            elif config.chart_id == 'd1d5_radar':
                ok = _render_radar_d1d5(data_cache, config, fig_path)
            else:
                ok = _render_radar(data_cache, config, fig_path)
        elif config.chart_type == 'box':
            ok = _render_box(data, data_cache, config, fig_path)
        elif config.chart_type == 'histogram':
            ok = _render_histogram(data, config, fig_path)
        if ok:
            rel = os.path.join(rel_fig_dir, fname)
            lines.append(f"\n![{config.title}]({rel})\n")
            insight = insights.get(config.chart_id, '').strip()
            if insight:
                lines.append(f"\n**图表解读**：{insight}\n\n")
    return '\n'.join(lines) if lines else ''

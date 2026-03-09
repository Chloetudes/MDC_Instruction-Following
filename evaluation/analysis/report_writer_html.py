# -*- coding: utf-8 -*-
"""
评测报告 HTML 生成器。图表采用统一学术风格配色（色盲友好），便于直接用于报告/论文。
"""
import json
import os
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

# 统一图表样式（学术/出版用）
_CHART_LAYOUT = {
    'paper_bgcolor': '#ffffff',
    'plot_bgcolor': '#fafafa',
    'font_family': '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif',
    'title_font': {'size': 15, 'color': '#2c3e50'},
    'margin': {'t': 50, 'b': 60, 'l': 60, 'r': 40},
    'height': 420,
}
_COLORS = {
    'accent': ['#2E86AB', '#A23B72', '#F18F01', '#C73E1D', '#3B1F2B'],  # 色盲友好
    'categorical': ['#4477AA', '#EE6677', '#228833', '#CCBB44', '#66CCEE', '#AA3377', '#BBBBBB'],
}

from .report_writer import (
    _get_model_icon, _escape_html, _nl2br, _sanitize_excel_text, _safe_float, _safe_str,
    _task_count, _source_counts, _source_counts_3,
)
from .report_content import (
    EXEC_SUMMARY_BACKGROUND,
    EXEC_SUMMARY_BULLETS,
    CH1_TEST_OBJECTIVES,
    CH2_METHODOLOGY,
)


def _html_head(title: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_escape_html(title)}</title>
<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/highlight.js@11.9.0/styles/github.min.css">
<script src="https://cdn.jsdelivr.net/npm/highlight.js@11.9.0/highlight.min.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;background:linear-gradient(135deg,#5e35b1 0%,#7e57c2 50%,#ffeb3b 100%);padding:20px;line-height:1.6}}
.container{{max-width:1400px;margin:0 auto;background:#fff;border-radius:20px;box-shadow:0 20px 60px rgba(0,0,0,.3);overflow:hidden}}
.header{{background:linear-gradient(135deg,#5e35b1 0%,#7e57c2 50%,#ffeb3b 100%);color:#fff;padding:60px 40px;text-align:center}}
.header h1{{font-size:38px;margin-bottom:16px;font-weight:700}}
.header .meta{{font-size:15px;opacity:.9}}
.section{{padding:40px;border-bottom:1px solid #e0e0e0}}
.section:last-child{{border-bottom:none}}
.section-title{{font-size:28px;color:#2c3e50;margin-bottom:28px;padding-bottom:12px;border-bottom:3px solid #7e57c2;display:flex;align-items:center;gap:12px}}
.subsection-title{{font-size:20px;color:#34495e;margin:28px 0 16px;padding-left:14px;border-left:4px solid #3498db}}
.stats-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:18px;margin:24px 0}}
.stat-card{{background:linear-gradient(135deg,#5e35b1 0%,#7e57c2 100%);color:#fff;padding:28px;border-radius:14px;text-align:center;box-shadow:0 4px 15px rgba(126,87,194,.4);transition:transform .3s}}
.stat-card:hover{{transform:translateY(-4px)}}
.stat-value{{font-size:42px;font-weight:700;margin-bottom:8px}}
.stat-label{{font-size:14px;opacity:.9}}
.ranking-table{{width:100%;border-collapse:collapse;border-radius:12px;overflow:hidden;box-shadow:0 2px 10px rgba(0,0,0,.08)}}
.ranking-table th{{background:linear-gradient(135deg,#5e35b1 0%,#7e57c2 100%);color:#fff;padding:16px;text-align:left;font-weight:600}}
.ranking-table td{{padding:16px;border-bottom:1px solid #e0e0e0}}
.ranking-table tr:hover td{{background:#f8f9fa}}
.rank-badge{{display:inline-flex;align-items:center;justify-content:center;width:36px;height:36px;border-radius:50%;font-weight:700;color:#fff;font-size:16px}}
.rank-1{{background:linear-gradient(135deg,#f093fb 0%,#f5576c 100%)}}
.rank-2{{background:linear-gradient(135deg,#4facfe 0%,#00f2fe 100%)}}
.rank-3{{background:linear-gradient(135deg,#43e97b 0%,#38f9d7 100%)}}
.rank-other{{background:linear-gradient(135deg,#a8edea 0%,#fed6e3 100%)}}
.model-info{{display:flex;align-items:center;gap:10px}}
.model-icon{{width:36px;height:36px;border-radius:7px;object-fit:contain;background:#fff;padding:3px;box-shadow:0 2px 6px rgba(0,0,0,.1)}}
.model-name{{font-weight:600;color:#2c3e50}}
.chart-container{{background:#f8f9fa;padding:28px;border-radius:14px;margin:18px 0;box-shadow:0 2px 8px rgba(0,0,0,.05)}}
.chart-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:24px;margin:18px 0}}
@media(max-width:900px){{.chart-grid{{grid-template-columns:1fr}}}}
.case-card{{background:#fff;border-radius:14px;margin:24px 0;overflow:hidden;box-shadow:0 4px 18px rgba(0,0,0,.1);transition:box-shadow .3s}}
.case-card:hover{{box-shadow:0 8px 28px rgba(0,0,0,.15)}}
.case-header{{background:linear-gradient(135deg,#5e35b1 0%,#7e57c2 100%);color:#fff;padding:22px 28px;cursor:pointer;display:flex;justify-content:space-between;align-items:center}}
.case-header h3{{font-size:20px;font-weight:600}}
.case-header .toggle-icon{{font-size:22px;transition:transform .3s}}
.case-header.active .toggle-icon{{transform:rotate(180deg)}}
.case-content{{max-height:0;overflow:hidden;transition:max-height .5s ease-out}}
.case-content.active{{max-height:30000px;transition:max-height 2s ease-in}}
.case-body{{padding:28px}}
.info-box{{padding:18px;border-radius:10px;margin:16px 0}}
.info-box.query{{background:linear-gradient(135deg,#e3f2fd,#bbdefb);border-left:4px solid #2196f3}}
.info-box.reference{{background:linear-gradient(135deg,#f3e5f5,#e1bee7);border-left:4px solid #9c27b0}}
.info-box.summary{{background:linear-gradient(135deg,#fff3e0,#ffe0b2);border-left:4px solid #ff9800}}
.info-box.expert{{background:linear-gradient(135deg,#e8f5e9,#c8e6c9);border-left:4px solid #4caf50}}
.info-box h4{{font-size:16px;margin-bottom:12px;color:#2c3e50;display:flex;align-items:center;gap:8px}}
.score-badge{{display:inline-block;padding:3px 10px;border-radius:12px;font-size:13px;font-weight:700;color:#fff}}
.score-high{{background:#27ae60}}
.score-mid{{background:#f39c12}}
.score-low{{background:#e74c3c}}
.reply-tabs{{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}}
.reply-tab{{padding:10px 20px;background:#ecf0f1;border:none;border-radius:8px;cursor:pointer;font-size:14px;font-weight:500;transition:all .3s;display:flex;align-items:center;gap:6px}}
.reply-tab img{{width:22px;height:22px;border-radius:4px}}
.reply-tab:hover{{background:#bdc3c7;transform:translateY(-2px)}}
.reply-tab.active{{background:linear-gradient(135deg,#5e35b1 0%,#7e57c2 100%);color:#fff}}
.reply-content{{display:none;background:#f8f9fa;padding:22px;border-radius:10px;border-left:4px solid #3498db}}
.reply-content.active{{display:block;animation:fadeIn .3s}}
@keyframes fadeIn{{from{{opacity:0}}to{{opacity:1}}}}
.reply-text,.evaluation-text{{background:#fff;padding:18px;border-radius:8px;margin:8px 0;max-height:500px;overflow-y:auto;line-height:1.8;white-space:pre-wrap;word-break:break-word}}
.evaluation-text{{background:#fff9e6}}
.markdown-content{{line-height:1.8;color:#333;word-break:break-word}}
.markdown-content h1,.markdown-content h2,.markdown-content h3{{margin:16px 0 8px;color:#2c3e50}}
.markdown-content p{{margin:10px 0}}
.markdown-content ul,.markdown-content ol{{margin:10px 0;padding-left:22px}}
.markdown-content li{{margin:6px 0}}
.markdown-content code{{background:#f5f5f5;padding:2px 5px;border-radius:4px;font-family:monospace;color:#e74c3c}}
.markdown-content pre{{background:#f8f9fa;padding:14px;border-radius:8px;overflow-x:auto;margin:14px 0;border-left:4px solid #7e57c2}}
.markdown-content table{{width:100%;border-collapse:collapse;margin:14px 0}}
.markdown-content table th{{background:#f8f9fa;padding:10px;border:1px solid #e0e0e0;font-weight:600}}
.markdown-content table td{{padding:10px;border:1px solid #e0e0e0}}
.failure-table{{width:100%;border-collapse:collapse;border-radius:10px;overflow:hidden;box-shadow:0 2px 6px rgba(0,0,0,.07);margin:14px 0}}
.failure-table th{{background:linear-gradient(135deg,#5e35b1 0%,#7e57c2 100%);color:#fff;padding:12px;text-align:left;font-size:13px}}
.failure-table td{{padding:11px;border-bottom:1px solid #e0e0e0;font-size:13px;vertical-align:top}}
.failure-table tr:hover td{{background:#f8f9fa}}
.deduction{{color:#e74c3c;font-weight:700}}
.analysis-block{{background:#fff;border:1px solid #e0e0e0;border-radius:10px;padding:20px;margin:14px 0}}
@media(max-width:768px){{.header h1{{font-size:26px}}.section{{padding:20px}}.stats-grid{{grid-template-columns:1fr}}}}
</style>
</head>"""


def _html_scripts() -> str:
    return """<script>
marked.setOptions({breaks:true,gfm:true});
document.addEventListener('DOMContentLoaded',function(){
  document.querySelectorAll('[data-md]').forEach(function(el){
    var text=el.getAttribute('data-raw')||el.textContent;
    el.innerHTML=marked.parse(text);
    el.querySelectorAll('pre code').forEach(function(b){hljs.highlightElement(b)});
  });
});
function toggleCase(id){
  var c=document.getElementById(id);
  var h=c.previousElementSibling;
  c.classList.toggle('active');
  h.classList.toggle('active');
}
function switchTab(caseId,model){
  var parts=caseId.split('-');var caseNum=parts[1];
  document.querySelectorAll('#tabs-'+caseId+' .reply-tab').forEach(function(t){t.classList.remove('active')});
  event.target.closest('.reply-tab').classList.add('active');
  document.querySelectorAll('[id^="reply-'+caseId+'-"]').forEach(function(c){c.classList.remove('active')});
  document.getElementById('reply-'+caseId+'-'+model).classList.add('active');
}
</script>"""


def _count_vendors(models: list) -> int:
    """按模型图标归属粗略估算厂商数（同图标=同厂商）。"""
    seen = set()
    for m in models:
        icon = _get_model_icon(_safe_str(m))
        seen.add(icon)
    return len(seen)


# 模型名 -> 厂商：使用 vendor_config 统一配置
from .vendor_config import get_model_vendor as _get_model_vendor


def _score_badge(score: float) -> str:
    css = 'score-high' if score >= 80 else ('score-mid' if score >= 60 else 'score-low')
    return f'<span class="score-badge {css}">{score:.1f}</span>'


def _build_report_meta_section(data: dict) -> str:
    """报告元信息（保留供兼容，精简版用 _build_ch1）"""
    return ''


def _build_ch1_test_intro(data: dict, data_cache: dict) -> str:
    """第一章：评测目标与基本信息"""
    replies = data.get('replies', pd.DataFrame())
    questions = data.get('questions', pd.DataFrame())
    overall = data_cache.get('overall_ranking', pd.DataFrame())
    model_count = replies['model'].nunique() if not replies.empty else 0
    task_count = _task_count(questions)
    eval_count = replies.shape[0] if not replies.empty else 0
    models_list = overall['模型'].tolist() if not overall.empty else []
    vendor_count = _count_vendors(models_list) if models_list else 0

    html = f"""<div class="section">
<h2 class="section-title">一、评测目标与基本信息</h2>
<p style="margin-bottom:20px;line-height:1.8;color:#444">{CH1_TEST_OBJECTIVES}</p>
<div class="stats-grid">
  <div class="stat-card"><div class="stat-value">{vendor_count}</div><div class="stat-label">参与厂商</div></div>
  <div class="stat-card"><div class="stat-value">{model_count}</div><div class="stat-label">评测模型</div></div>
  <div class="stat-card"><div class="stat-value">{task_count}</div><div class="stat-label">评测题目</div></div>
  <div class="stat-card"><div class="stat-value">{eval_count}</div><div class="stat-label">总评测次数</div></div>
</div>
</div>"""
    return html


def _build_ch2_methodology_section() -> str:
    """第 2 章 评测方法论（EVAL_REPORT_FRAMEWORK_v2）"""
    html = f"""<div class="section">
<h2 class="section-title">二、评测方法论</h2>
<p style="line-height:1.8;color:#444">{CH2_METHODOLOGY}</p>
<p style="margin-top:16px;color:#555;font-size:14px"><strong>专家纠偏机制</strong>：有专家打分的题目上，用专家分替换模型自动分后重算均分；专家覆盖率、纠偏前后排名变化见第五章。</p>
</div>"""
    return html


def _insight_callout(emoji: str, title: str, text: str) -> str:
    """洞察卡片：标题 + 解读，用于图表前/后的叙事串联"""
    return f'''<div class="info-box" style="background:linear-gradient(135deg,#e8f5e9,#c8e6c9);border-left:4px solid #4caf50;margin:16px 0">
  <strong>{emoji} {_escape_html(title)}</strong>
  <p style="margin:8px 0 0;line-height:1.7;color:#333">{_escape_html(text)}</p>
</div>'''


def _build_data_viz_charts(overall_ranking: pd.DataFrame, data: dict, data_cache: dict, focused: bool = True) -> str:
    """
    数据可视化：洞察驱动布局。focused=True 时仅保留核心图表（柱状、雷达、公私域、维度、厂商），
    每组图表配洞察解读，减少信息分散。
    """
    if overall_ranking.empty:
        return ''

    scripts = []
    chart_ids = []

    # 1. 柱状图：模型综合均分（TOP20），带标准差误差条
    models = [_safe_str(r) for r in overall_ranking.head(20)['模型'].tolist()]
    scores = [_safe_float(s) for s in overall_ranking.head(20)['平均分'].tolist()]
    stds = overall_ranking.head(20).get('标准差', pd.Series([0] * len(models)))
    stds = [_safe_float(s) for s in stds.tolist()]
    colors = [_COLORS['accent'][0] if i == 0 else _COLORS['accent'][1] if i == 1 else _COLORS['accent'][2] if i == 2 else _COLORS['categorical'][i % len(_COLORS['categorical'])] for i in range(len(models))]
    bar_script = f"""
var barData = [{{
  x: {json.dumps(models, ensure_ascii=False)},
  y: {json.dumps(scores)},
  error_y: {{type: 'data', array: {json.dumps(stds)}, visible: true, thickness: 1.5}},
  marker: {{color: {json.dumps(colors)}, line: {{color: '#5e35b1', width: 0.5}}}},
  text: {json.dumps([f'{s:.1f}' for s in scores])},
  textposition: 'outside',
  textfont: {{size: 11}}
}}];
Plotly.newPlot('chart-model-bar', [barData], {{
  title: {{text: '模型综合均分对比（TOP20）', font: {{size: 16, color: '#2c3e50'}}}},
  xaxis: {{title: '模型', tickangle: -45, tickfont: {{size: 10}}}},
  yaxis: {{title: '平均分', range: [0, Math.min(105, Math.max.apply(null, {json.dumps(scores)}) + 15)]}},
  paper_bgcolor: '{_CHART_LAYOUT["paper_bgcolor"]}', plot_bgcolor: '{_CHART_LAYOUT["plot_bgcolor"]}',
  margin: {{b: 120}},
  height: {_CHART_LAYOUT["height"]}
}}, {{responsive: true}});
"""
    scripts.append(bar_script)
    chart_ids.append('chart-model-bar')

    # 2. 雷达图：TOP5 模型在 D2-D5 的通过率（按综合排名取前5）
    dim_stats = data_cache.get('dimension_stats') or {}
    pivot = dim_stats.get('dimension_pivot_df', pd.DataFrame())
    dim_cols = ['D2通过率', 'D3通过率', 'D4通过率', 'D5通过率']
    if not pivot.empty and all(c in pivot.columns for c in dim_cols):
        top5_models = overall_ranking.head(5)['模型'].astype(str).tolist()
        pivot_model_col = pivot['模型'].astype(str)
        theta = ['D2流程步骤', 'D3边界范围', 'D4格式形式', 'D5内容质量']
        radar_colors = _COLORS['accent'] + _COLORS['categorical']
        radar_traces = []
        for i, model_name in enumerate(top5_models):
            match = pivot[pivot_model_col == model_name]
            if match.empty:
                continue
            row = match.iloc[0]
            r_vals = [float(pd.to_numeric(row[col], errors='coerce') or 0) for col in dim_cols]
            disp_name = (model_name[:24] + '…') if len(model_name) > 24 else model_name
            radar_traces.append(f"""{{ type: 'scatterpolar', r: {json.dumps(r_vals)}, theta: {json.dumps(theta, ensure_ascii=False)}, fill: 'toself', name: {json.dumps(disp_name, ensure_ascii=False)}, line: {{color: '{radar_colors[i % len(radar_colors)]}'}} }}""")
        radar_script = f"""
Plotly.newPlot('chart-radar-dim', [{', '.join(radar_traces)}], {{
  polar: {{ radialaxis: {{ visible: true, range: [0, 100], tickfont: {{size: 10}} }} }},
  title: {{text: 'TOP5 模型 D2-D5 维度通过率雷达图', font: {{size: 16, color: '#2c3e50'}}}},
  paper_bgcolor: '{_CHART_LAYOUT["paper_bgcolor"]}', plot_bgcolor: '{_CHART_LAYOUT["plot_bgcolor"]}',
  height: 450,
  showlegend: true,
  legend: {{ orientation: 'h', y: 1.15 }}
}}, {{responsive: true}});
"""
        scripts.append(radar_script)
        chart_ids.append('chart-radar-dim')

    # 3. 热力图：L1×模型（focused 模式下跳过，减少信息过载）
    if not focused:
        _heat_colors = ['#1a237e', '#283593', '#3949ab', '#5c6bc0', '#7986cb', '#9fa8da', '#c5cae9', '#e8eaf6', '#fff8e1', '#ffecb3', '#ffe082', '#ffd54f', '#ffca28', '#ffc107', '#ffb300', '#ff8f00', '#ff6f00', '#e65100', '#bf360c', '#ffeb3b']
        _heat_scale = json.dumps([[i / 19, _heat_colors[i]] for i in range(20)])
    replies_with_q = data.get('replies_with_question', pd.DataFrame())
    if not focused and not replies_with_q.empty and 'L1' in replies_with_q.columns:
        l1_cats = sorted([str(c) for c in replies_with_q['L1'].dropna().unique()])
        model_list = [_safe_str(r) for r in overall_ranking['模型'].tolist()]
        z_by_model = []
        for model in model_list:
            row_scores = []
            for cat in l1_cats:
                subset = replies_with_q[(replies_with_q['model'] == model) & (replies_with_q['L1'] == cat)]
                row_scores.append(round(_safe_float(subset['eval_score'].mean()), 2) if not subset.empty else None)
            z_by_model.append(row_scores)
        flat = [v for row in z_by_model for v in row if v is not None]
        zmin_h = max(0, (min(flat) if flat else 0) - 2)
        zmax_h = min(100, (max(flat) if flat else 100) + 2)
        heat_l1_script = f"""
Plotly.newPlot('chart-l1-heatmap', [{{
  z: {json.dumps(z_by_model)},
  x: {json.dumps(l1_cats, ensure_ascii=False)},
  y: {json.dumps(model_list, ensure_ascii=False)},
  type: 'heatmap',
  colorscale: {_heat_scale},
  zmin: {zmin_h}, zmax: {zmax_h},
  showscale: true,
  hoverongaps: false
}}], {{title: {{text: 'L1意图类型×模型得分热力图', font: {{size: 16, color: '#2c3e50'}}}}, xaxis: {{title: 'L1意图类型'}}, yaxis: {{title: '模型'}}, paper_bgcolor: '#f8f9fa', plot_bgcolor: '#f8f9fa', height: 500}}, {{responsive: true}});
"""
        scripts.append(heat_l1_script)
        chart_ids.append('chart-l1-heatmap')

    # 4. 热力图：D2/D3/D4/D5×模型（focused 模式跳过，用 D4vsD2+维度箱线替代）
    if not focused and not pivot.empty:
        dim_cols_pivot = [c for c in ['D2通过率', 'D3通过率', 'D4通过率', 'D5通过率'] if c in pivot.columns]
        if dim_cols_pivot:
            dim_labels = {'D2通过率': 'D2流程步骤', 'D3通过率': 'D3边界范围', 'D4通过率': 'D4格式形式', 'D5通过率': 'D5内容质量'}
            z_dim = []
            for _, row in pivot.iterrows():
                z_dim.append([float(pd.to_numeric(row.get(c), errors='coerce') or 0) for c in dim_cols_pivot])
            dim_axis = [dim_labels.get(c, c) for c in dim_cols_pivot]
            mod_axis = pivot['模型'].astype(str).tolist()
            heat_dim_script = f"""
Plotly.newPlot('chart-dim-heatmap', [{{
  z: {json.dumps(z_dim)},
  x: {json.dumps(dim_axis, ensure_ascii=False)},
  y: {json.dumps(mod_axis, ensure_ascii=False)},
  type: 'heatmap',
  colorscale: {_heat_scale},
  zmin: 0, zmax: 100,
  showscale: true
}}], {{title: {{text: 'D2-D5 维度通过率×模型热力图', font: {{size: 16, color: '#2c3e50'}}}}, xaxis: {{title: '维度'}}, yaxis: {{title: '模型'}}, paper_bgcolor: '#f8f9fa', plot_bgcolor: '#f8f9fa', height: 480}}, {{responsive: true}});
"""
            scripts.append(heat_dim_script)
            chart_ids.append('chart-dim-heatmap')

    # 5. 箱线图：各模型得分分布（focused 模式跳过）
    if not focused and not replies_with_q.empty and 'eval_score' in replies_with_q.columns and 'model' in replies_with_q.columns:
        model_list_top20 = overall_ranking.head(20)['模型'].astype(str).tolist()
        box_traces = []
        box_colors = _COLORS['accent'] + _COLORS['categorical']
        for i, m in enumerate(model_list_top20):
            vals = replies_with_q[replies_with_q['model'] == m]['eval_score'].dropna().tolist()
            vals = [float(x) for x in vals if x is not None]
            if vals:
                box_traces.append(f"""{{ y: {json.dumps(vals)}, name: {json.dumps(m[:20] + ('…' if len(m) > 20 else ''), ensure_ascii=False)}, marker: {{color: '{box_colors[i % len(box_colors)]}'}}, boxpoints: 'outliers' }}""")
        if box_traces:
            box_script = f"""
Plotly.newPlot('chart-model-box', [{', '.join(box_traces)}], {{
  title: {{text: '各模型得分分布（箱线图）', font: {{size: 16, color: '#2c3e50'}}}},
  yaxis: {{title: '得分', range: [0, 105]}},
  paper_bgcolor: '{_CHART_LAYOUT["paper_bgcolor"]}', plot_bgcolor: '{_CHART_LAYOUT["plot_bgcolor"]}',
  height: {_CHART_LAYOUT["height"]},
  margin: {{b: 120}},
  xaxis: {{tickangle: -45, tickfont: {{size: 10}}}}
}}, {{responsive: true}});
"""
            scripts.append(box_script)
            chart_ids.append('chart-model-box')

    # 6. 热力图：难度等级×模型（focused 模式跳过）
    if not focused and not replies_with_q.empty and 'difficulty_level' in replies_with_q.columns:
        priority = {'S': 6, 'A': 5, 'B': 4, 'C': 3, 'D': 2, 'E': 1}
        diff_levels = sorted(replies_with_q['difficulty_level'].dropna().unique(),
                             key=lambda x: priority.get(str(x), 0), reverse=True)
        diff_levels = [str(l) for l in diff_levels]
        model_list = overall_ranking.head(20)['模型'].astype(str).tolist()
        z_diff = []
        for level in diff_levels:
            row_scores = []
            for m in model_list:
                subset = replies_with_q[(replies_with_q['model'] == m) & (replies_with_q['difficulty_level'].astype(str) == level)]
                row_scores.append(round(_safe_float(subset['eval_score'].mean()), 2) if not subset.empty else None)
            z_diff.append(row_scores)
        flat_diff = [v for row in z_diff for v in row if v is not None]
        zmin_d = max(0, (min(flat_diff) if flat_diff else 0) - 2)
        zmax_d = min(100, (max(flat_diff) if flat_diff else 100) + 2)
        heat_diff_script = f"""
Plotly.newPlot('chart-difficulty-heatmap', [{{
  z: {json.dumps(z_diff)},
  x: {json.dumps(model_list, ensure_ascii=False)},
  y: {json.dumps(diff_levels, ensure_ascii=False)},
  type: 'heatmap',
  colorscale: {_heat_scale},
  zmin: {zmin_d}, zmax: {zmax_d},
  showscale: true
}}], {{title: {{text: '难度等级×模型得分热力图', font: {{size: 16, color: '#2c3e50'}}}}, xaxis: {{title: '模型'}}, yaxis: {{title: '难度等级'}}, paper_bgcolor: '#f8f9fa', plot_bgcolor: '#f8f9fa', height: 420, margin: {{b: 120}}}}, {{responsive: true}});
"""
        scripts.append(heat_diff_script)
        chart_ids.append('chart-difficulty-heatmap')

    # 7. 热力图：数据来源×模型（focused 模式跳过）
    if not focused and not replies_with_q.empty and 'source_group' in replies_with_q.columns:
        src_groups = sorted([str(g) for g in replies_with_q['source_group'].dropna().unique()])
        model_list = overall_ranking.head(20)['模型'].astype(str).tolist()
        z_src = []
        for grp in src_groups:
            row_scores = []
            for m in model_list:
                subset = replies_with_q[(replies_with_q['model'] == m) & (replies_with_q['source_group'].astype(str) == grp)]
                row_scores.append(round(_safe_float(subset['eval_score'].mean()), 2) if not subset.empty else None)
            z_src.append(row_scores)
        flat_src = [v for row in z_src for v in row if v is not None]
        zmin_s = max(0, (min(flat_src) if flat_src else 0) - 2)
        zmax_s = min(100, (max(flat_src) if flat_src else 100) + 2)
        heat_src_script = f"""
Plotly.newPlot('chart-source-heatmap', [{{
  z: {json.dumps(z_src)},
  x: {json.dumps(model_list, ensure_ascii=False)},
  y: {json.dumps(src_groups, ensure_ascii=False)},
  type: 'heatmap',
  colorscale: {_heat_scale},
  zmin: {zmin_s}, zmax: {zmax_s},
  showscale: true
}}], {{title: {{text: '数据来源×模型得分热力图', font: {{size: 16, color: '#2c3e50'}}}}, xaxis: {{title: '模型'}}, yaxis: {{title: '数据来源'}}, paper_bgcolor: '#f8f9fa', plot_bgcolor: '#f8f9fa', height: 420, margin: {{b: 120}}}}, {{responsive: true}});
"""
        scripts.append(heat_src_script)
        chart_ids.append('chart-source-heatmap')

    # 8. 公私域散点图（公开均分 vs 自建均分）
    panorama_df = data_cache.get('panorama_df', pd.DataFrame())
    if not panorama_df.empty and 'Public_Score' in panorama_df.columns and 'Private_Score' in panorama_df.columns:
        pub = panorama_df['Public_Score'].astype(float)
        priv = panorama_df['Private_Score'].astype(float)
        valid = ~(pub.isna() | priv.isna())
        if valid.any():
            x_vals = pub[valid].tolist()
            y_vals = priv[valid].tolist()
            names = panorama_df.loc[valid, 'Model_Name'].astype(str).tolist()
            dom_colors = ['#2E86AB' if d == '国内' else '#A23B72' for d in panorama_df.loc[valid, 'Domestic'].tolist()]
            scatter_pubpriv_script = f"""
Plotly.newPlot('chart-public-private-scatter', [{{
  x: {json.dumps(x_vals)},
  y: {json.dumps(y_vals)},
  mode: 'markers+text',
  marker: {{size: 12, color: {json.dumps(dom_colors)}, line: {{color: '#333', width: 1}}, symbol: 'circle'}},
  text: {json.dumps(names, ensure_ascii=False)},
  textposition: 'top center',
  textfont: {{size: 9}},
  customdata: {json.dumps(names, ensure_ascii=False)},
  hovertemplate: '模型: %{{customdata}}<br>公开均分: %{{x:.1f}}<br>自建均分: %{{y:.1f}}<extra></extra>'
}}], {{
  title: {{text: '公开均分 vs 自建均分', font: {json.dumps(_CHART_LAYOUT['title_font'])}}},
  xaxis: {{title: '公开来源均分', zeroline: true}},
  yaxis: {{title: '自建来源均分', zeroline: true}},
  shapes: [{{type: 'line', x0: 0, y0: 0, x1: 100, y1: 100, line: {{dash: 'dot', color: '#999'}}}}],
  paper_bgcolor: '{_CHART_LAYOUT["paper_bgcolor"]}', plot_bgcolor: '{_CHART_LAYOUT["plot_bgcolor"]}',
  height: {_CHART_LAYOUT["height"]}
}}, {{responsive: true}});
"""
            scripts.append(scatter_pubpriv_script)
            chart_ids.append('chart-public-private-scatter')

    # 9. 公私域落差条形图（Score_Gap）
    if not panorama_df.empty and 'Score_Gap' in panorama_df.columns:
        gap_valid = panorama_df['Score_Gap'].notna()
        if gap_valid.any():
            gap_df = panorama_df[gap_valid].sort_values('Score_Gap', ascending=True)
            gap_models = gap_df['Model_Name'].astype(str).tolist()
            gap_vals = gap_df['Score_Gap'].astype(float).tolist()
            gap_colors = ['#C73E1D' if g > 0 else '#228833' for g in gap_vals]
            bar_gap_script = f"""
Plotly.newPlot('chart-score-gap', [{{
  x: {json.dumps(gap_vals)},
  y: {json.dumps(gap_models, ensure_ascii=False)},
  type: 'bar',
  orientation: 'h',
  marker: {{color: {json.dumps(gap_colors)}, line: {{color: '#333', width: 0.5}}}},
  text: {json.dumps([f'{g:+.1f}' for g in gap_vals])},
  textposition: 'outside',
  textfont: {{size: 10}}
}}], {{
  title: {{text: '公私域落差（自建均分 - 公开均分）', font: {json.dumps(_CHART_LAYOUT['title_font'])}}},
  xaxis: {{title: 'Score_Gap', zeroline: true}},
  yaxis: {{title: '', automargin: true}},
  paper_bgcolor: '{_CHART_LAYOUT["paper_bgcolor"]}', plot_bgcolor: '{_CHART_LAYOUT["plot_bgcolor"]}',
  height: {_CHART_LAYOUT["height"]},
  margin: {{l: 140}}
}}, {{responsive: true}});
"""
            scripts.append(bar_gap_script)
            chart_ids.append('chart-score-gap')

    # 10. 国内/国外 分组条形图（Main_Score 均值）
    if not panorama_df.empty and 'Domestic' in panorama_df.columns and 'Main_Score' in panorama_df.columns:
        dom_agg = panorama_df.groupby('Domestic')['Main_Score'].agg(['mean', 'count']).reset_index()
        dom_labels = dom_agg['Domestic'].astype(str).tolist()
        dom_means = dom_agg['mean'].round(2).tolist()
        bar_dom_script = f"""
Plotly.newPlot('chart-domestic-bar', [{{
  x: {json.dumps(dom_labels, ensure_ascii=False)},
  y: {json.dumps(dom_means)},
  type: 'bar',
  marker: {{color: {json.dumps(_COLORS['categorical'][:len(dom_labels)])}, line: {{color: '#333', width: 0.5}}}},
  text: {json.dumps([f'{m:.1f}' for m in dom_means])},
  textposition: 'outside'
}}], {{
  title: {{text: '国内/国外 模型均分对比', font: {json.dumps(_CHART_LAYOUT['title_font'])}}},
  xaxis: {{title: ''}},
  yaxis: {{title: 'Main_Score 均值'}},
  paper_bgcolor: '{_CHART_LAYOUT["paper_bgcolor"]}', plot_bgcolor: '{_CHART_LAYOUT["plot_bgcolor"]}',
  height: 380
}}, {{responsive: true}});
"""
        scripts.append(bar_dom_script)
        chart_ids.append('chart-domestic-bar')

    # 11. 深度思考 vs 非深度思考 分组条形图
    if not panorama_df.empty and 'Thinking' in panorama_df.columns and 'Main_Score' in panorama_df.columns:
        think_agg = panorama_df.groupby('Thinking')['Main_Score'].agg(['mean', 'count']).reset_index()
        think_labels = think_agg['Thinking'].astype(str).tolist()
        think_means = think_agg['mean'].round(2).tolist()
        bar_think_script = f"""
Plotly.newPlot('chart-thinking-bar', [{{
  x: {json.dumps(think_labels, ensure_ascii=False)},
  y: {json.dumps(think_means)},
  type: 'bar',
  marker: {{color: {json.dumps(_COLORS['categorical'][2:2+len(think_labels)])}, line: {{color: '#333', width: 0.5}}}},
  text: {json.dumps([f'{m:.1f}' for m in think_means])},
  textposition: 'outside'
}}], {{
  title: {{text: '深度思考 vs 非深度思考 均分对比', font: {json.dumps(_CHART_LAYOUT['title_font'])}}},
  xaxis: {{title: ''}},
  yaxis: {{title: 'Main_Score 均值'}},
  paper_bgcolor: '{_CHART_LAYOUT["paper_bgcolor"]}', plot_bgcolor: '{_CHART_LAYOUT["plot_bgcolor"]}',
  height: 380
}}, {{responsive: true}});
"""
        scripts.append(bar_think_script)
        chart_ids.append('chart-thinking-bar')

    # 12. D4 vs D2 散点图（格式 vs 逻辑）
    if not pivot.empty:
        d2_col = 'D2通过率' if 'D2通过率' in pivot.columns else None
        d4_col = 'D4通过率' if 'D4通过率' in pivot.columns else None
        if d2_col and d4_col:
            d2_vals = pivot[d2_col].astype(float).tolist()
            d4_vals = pivot[d4_col].astype(float).tolist()
            mod_names = pivot['模型'].astype(str).tolist()
            scatter_d4d2_script = f"""
Plotly.newPlot('chart-d4-d2-scatter', [{{
  x: {json.dumps(d2_vals)},
  y: {json.dumps(d4_vals)},
  mode: 'markers+text',
  marker: {{size: 10, color: '{_COLORS["accent"][0]}', line: {{color: '#333', width: 1}}}},
  text: {json.dumps(mod_names, ensure_ascii=False)},
  textposition: 'top center',
  textfont: {{size: 9}},
  hovertemplate: '模型: %{{text}}<br>D2: %{{x:.1f}}%<br>D4: %{{y:.1f}}%<extra></extra>'
}}], {{
  title: {{text: 'D2流程步骤 vs D4格式形式 通过率', font: {json.dumps(_CHART_LAYOUT['title_font'])}}},
  xaxis: {{title: 'D2通过率 (%)'}},
  yaxis: {{title: 'D4通过率 (%)'}},
  paper_bgcolor: '{_CHART_LAYOUT["paper_bgcolor"]}', plot_bgcolor: '{_CHART_LAYOUT["plot_bgcolor"]}',
  height: {_CHART_LAYOUT["height"]}
}}, {{responsive: true}});
"""
            scripts.append(scatter_d4d2_script)
            chart_ids.append('chart-d4-d2-scatter')

    # 13. D2/D3/D4/D5 维度通过率箱线图
    if not pivot.empty:
        dim_cols_box = [c for c in ['D2通过率', 'D3通过率', 'D4通过率', 'D5通过率'] if c in pivot.columns]
        if dim_cols_box:
            box_traces_js = []
            dim_labels_box = {'D2通过率': 'D2流程', 'D3通过率': 'D3边界', 'D4通过率': 'D4格式', 'D5通过率': 'D5内容'}
            for i, col in enumerate(dim_cols_box):
                vals = pivot[col].astype(float).dropna().tolist()
                if vals:
                    box_traces_js.append(f"""{{ y: {json.dumps(vals)}, name: {json.dumps(dim_labels_box.get(col, col), ensure_ascii=False)}, marker: {{color: '{_COLORS["accent"][i % len(_COLORS["accent"])]}'}}, boxpoints: 'outliers' }}""")
            if box_traces_js:
                box_dim_script = f"""
Plotly.newPlot('chart-dimension-box', [{', '.join(box_traces_js)}], {{
  title: {{text: 'D2-D5 维度通过率分布', font: {json.dumps(_CHART_LAYOUT['title_font'])}}},
  yaxis: {{title: '通过率 (%)', range: [0, 105]}},
  paper_bgcolor: '{_CHART_LAYOUT["paper_bgcolor"]}', plot_bgcolor: '{_CHART_LAYOUT["plot_bgcolor"]}',
  height: 400,
  showlegend: true,
  legend: {{orientation: 'h'}}
}}, {{responsive: true}});
"""
                scripts.append(box_dim_script)
                chart_ids.append('chart-dimension-box')

    if not scripts:
        return ''

    # 洞察驱动布局：每组图表配解读，形成「发现→图表→洞察」串联
    html = ''
    if focused:
        # 发现1：综合排名与维度能力
        html += '<h3 class="subsection-title">3.1 综合排名与 TOP5 维度能力</h3>'
        html += _insight_callout('📊', '核心指标', '左图展示各模型综合均分（维度加权），右图雷达图呈现 TOP5 在 D2 流程步骤、D3 边界范围、D4 格式形式、D5 内容质量四个维度的通过率对比，便于识别头部模型的强项与短板。')
        html += '<div class="chart-grid">'
        html += '<div class="chart-container"><div id="chart-model-bar"></div></div>'
        if 'chart-radar-dim' in chart_ids:
            html += '<div class="chart-container"><div id="chart-radar-dim"></div></div>'
        html += '</div>'

        # 发现2：公私域落差
        if 'chart-public-private-scatter' in chart_ids or 'chart-score-gap' in chart_ids:
            gap_val = ''
            if data_cache.get('source_gap_summary'):
                g = data_cache['source_gap_summary'].get('公开vs纯人工自建_均分差')
                if g is not None and not (isinstance(g, float) and np.isnan(g)):
                    gap_val = f'（本次约 {g:.0f} 分）'
            html += '<h3 class="subsection-title">3.2 公私域落差</h3>'
            html += _insight_callout('🔍', '自建 vs 公开', f'自建题目更能反映真实业务难度。左图：公开均分 vs 自建均分散点，对角线下方表示自建得分低于公开；右图：Score_Gap = 自建 - 公开，正数表示自建上表现更好。{gap_val}')
            html += '<div class="chart-grid">'
            if 'chart-public-private-scatter' in chart_ids:
                html += '<div class="chart-container"><div id="chart-public-private-scatter"></div></div>'
            if 'chart-score-gap' in chart_ids:
                html += '<div class="chart-container"><div id="chart-score-gap"></div></div>'
            html += '</div>'

        # 发现3：重格式轻逻辑
        if 'chart-d4-d2-scatter' in chart_ids or 'chart-dimension-box' in chart_ids:
            html += '<h3 class="subsection-title">3.3 重格式、轻逻辑</h3>'
            html += _insight_callout('⚖️', 'D2 vs D4', 'D2 对应流程步骤（逻辑执行），D4 对应格式要求。左图：各模型 D2 vs D4 散点，多数落在对角线下方说明 D4 高于 D2；右图：D2-D5 维度通过率分布，印证模型在逻辑执行上普遍弱于格式规范。')
            html += '<div class="chart-grid">'
            if 'chart-d4-d2-scatter' in chart_ids:
                html += '<div class="chart-container"><div id="chart-d4-d2-scatter"></div></div>'
            if 'chart-dimension-box' in chart_ids:
                html += '<div class="chart-container"><div id="chart-dimension-box"></div></div>'
            html += '</div>'

        # 发现4：国内/国外与深度思考
        if 'chart-domestic-bar' in chart_ids or 'chart-thinking-bar' in chart_ids:
            html += '<h3 class="subsection-title">3.4 分组对比</h3>'
            html += _insight_callout('🏷️', '国内/国外与深度思考', '按厂商性质划分国内/国外，按模型名是否含 thinking/reasoning 划分深度思考。可观察不同分组下 Main_Score 均值差异。')
            html += '<div class="chart-grid">'
            if 'chart-domestic-bar' in chart_ids:
                html += '<div class="chart-container"><div id="chart-domestic-bar"></div></div>'
            if 'chart-thinking-bar' in chart_ids:
                html += '<div class="chart-container"><div id="chart-thinking-bar"></div></div>'
            html += '</div>'

    else:
        # 非 focused：传统布局
        html += '<h3 class="subsection-title">3.1 数据可视化</h3>'
        html += '<div class="chart-grid"><div class="chart-container"><div id="chart-model-bar"></div></div>'
        if 'chart-radar-dim' in chart_ids:
            html += '<div class="chart-container"><div id="chart-radar-dim"></div></div>'
        html += '</div>'
        for cid in ['chart-model-box', 'chart-l1-heatmap', 'chart-dim-heatmap', 'chart-difficulty-heatmap', 'chart-source-heatmap']:
            if cid in chart_ids:
                html += f'<div class="chart-container"><div id="{cid}"></div></div>'
        if 'chart-public-private-scatter' in chart_ids:
            html += '<div class="chart-grid"><div class="chart-container"><div id="chart-public-private-scatter"></div></div>'
            html += '<div class="chart-container"><div id="chart-score-gap"></div></div></div>'
        if 'chart-domestic-bar' in chart_ids or 'chart-thinking-bar' in chart_ids:
            html += '<div class="chart-grid">'
            if 'chart-domestic-bar' in chart_ids:
                html += '<div class="chart-container"><div id="chart-domestic-bar"></div></div>'
            if 'chart-thinking-bar' in chart_ids:
                html += '<div class="chart-container"><div id="chart-thinking-bar"></div></div>'
            html += '</div>'
        if 'chart-d4-d2-scatter' in chart_ids or 'chart-dimension-box' in chart_ids:
            html += '<div class="chart-grid">'
            if 'chart-d4-d2-scatter' in chart_ids:
                html += '<div class="chart-container"><div id="chart-d4-d2-scatter"></div></div>'
            if 'chart-dimension-box' in chart_ids:
                html += '<div class="chart-container"><div id="chart-dimension-box"></div></div>'
            html += '</div>'

    html += f'<script>{"".join(scripts)}</script>'
    return html


def _build_vendor_rankings_charts(overall_ranking: pd.DataFrame, data_cache: dict) -> str:
    """
    厂商维度排行：厂商最强模型柱状图 + 模型迭代榜单柱状图（参考评测论文）
    """
    if overall_ranking.empty:
        return ''

    scripts = []
    vendor_best_rows = []

    # 计算厂商最强模型：按 _get_model_vendor 分组，取每组最高均分的模型
    model_to_avg = dict(zip(overall_ranking['模型'].astype(str), overall_ranking['平均分'].astype(float)))
    vendor_best: Dict[str, tuple] = {}
    for model, avg in model_to_avg.items():
        v = _get_model_vendor(model)
        if v not in vendor_best or vendor_best[v][1] < avg:
            vendor_best[v] = (model, float(avg))

    # 按均分降序排序
    sorted_vendors = sorted(vendor_best.items(), key=lambda x: x[1][1], reverse=True)
    if not sorted_vendors:
        return ''

    vendors = [v[0] for v in sorted_vendors]
    best_scores = [v[1][1] for v in sorted_vendors]
    best_models = [v[1][0] for v in sorted_vendors]
    colors_vb = [_COLORS['accent'][0] if i == 0 else _COLORS['accent'][1] if i == 1 else _COLORS['accent'][2] if i == 2 else _COLORS['categorical'][i % len(_COLORS['categorical'])] for i in range(len(vendors))]

    bar_vendor_script = f"""
Plotly.newPlot('chart-vendor-best', [{{
  x: {json.dumps(vendors, ensure_ascii=False)},
  y: {json.dumps(best_scores)},
  marker: {{color: {json.dumps(colors_vb)}, line: {{color: '#5e35b1', width: 0.5}}}},
  text: {json.dumps([f'{s:.1f}' for s in best_scores])},
  textposition: 'outside',
  textfont: {{size: 11}},
  customdata: {json.dumps(best_models, ensure_ascii=False)},
  hovertemplate: '厂商: %{{x}}<br>最强模型: %{{customdata}}<br>均分: %{{y:.1f}}<extra></extra>'
}}], {{
  title: {{text: '厂商最强模型排行（每厂商取最高均分模型）', font: {{size: 16, color: '#2c3e50'}}}},
  xaxis: {{title: '厂商', tickangle: -45, tickfont: {{size: 11}}}},
  yaxis: {{title: '均分', range: [0, Math.min(105, Math.max.apply(null, {json.dumps(best_scores)}) + 10)]}},
  paper_bgcolor: '{_CHART_LAYOUT["paper_bgcolor"]}', plot_bgcolor: '{_CHART_LAYOUT["plot_bgcolor"]}',
  margin: {{b: 100}},
  height: {_CHART_LAYOUT["height"]}
}}, {{responsive: true}});
"""
    scripts.append(bar_vendor_script)
    for rank, (v, (m, s)) in enumerate(sorted_vendors, 1):
        rank_cls = f'rank-{rank}' if rank <= 3 else 'rank-other'
        vendor_best_rows.append(f'<tr><td><span class="rank-badge {rank_cls}">{rank}</span></td><td>{_escape_html(v)}</td><td>{_escape_html(m[:40] + ("…" if len(m) > 40 else ""))}</td><td><strong>{s:.1f}</strong></td></tr>')

    # 模型迭代榜单柱状图（version_progression 存在时）
    version_progression = data_cache.get('version_progression') or []
    iter_script = ''
    if version_progression:
        # 按厂商分组，每组内按版本顺序
        by_vendor: Dict[str, List[dict]] = {}
        for row in version_progression:
            v = str(row.get('厂商', ''))
            if v not in by_vendor:
                by_vendor[v] = []
            by_vendor[v].append(row)
        vendors_iter = list(by_vendor.keys())
        max_versions = max(len(rows) for rows in by_vendor.values()) if by_vendor else 0
        traces_js = []
        colors_iter = ['#5e35b1', '#7e57c2', '#9c27b0', '#e91e63', '#f44336', '#7986cb']
        for ver_idx in range(max_versions):
            y_vals = []
            for v in vendors_iter:
                rows = by_vendor.get(v, [])
                if ver_idx < len(rows):
                    y_vals.append(float(rows[ver_idx].get('平均分', 0)))
                else:
                    y_vals.append(None)
            text_vals = [f'{y:.1f}' if y is not None else '' for y in y_vals]
            traces_js.append(f"""{{ x: {json.dumps(vendors_iter, ensure_ascii=False)}, y: {json.dumps(y_vals)}, name: '版本{ver_idx + 1}', type: 'bar', marker: {{color: '{colors_iter[ver_idx % len(colors_iter)]}'}}, text: {json.dumps(text_vals)}, textposition: 'outside' }}""")
        if traces_js:
            iter_script = f"""
Plotly.newPlot('chart-version-progression', [{', '.join(traces_js)}], {{
  title: {{text: '厂商系列版本递进（同厂商内按版本顺序）', font: {{size: 16, color: '#2c3e50'}}}},
  xaxis: {{title: '厂商', tickangle: -30}},
  yaxis: {{title: '平均分', range: [0, 105]}},
  barmode: 'group',
  paper_bgcolor: '{_CHART_LAYOUT["paper_bgcolor"]}', plot_bgcolor: '{_CHART_LAYOUT["plot_bgcolor"]}',
  height: {_CHART_LAYOUT["height"]},
  margin: {{b: 100}},
  legend: {{orientation: 'h', y: 1.08}}
}}, {{responsive: true}});
"""
            scripts.append(iter_script)

    html = '<h3 class="subsection-title">3.6 厂商维度</h3>'
    html += '<p style="margin-bottom:12px;color:#555;font-size:14px">每厂商取均分最高的模型代表该厂商，便于横向对比厂商实力。下表为补充参考，可结合上图快速定位头部厂商。</p>'
    html += '<div class="chart-container"><div id="chart-vendor-best"></div></div>'
    html += '<details style="margin-top:12px"><summary style="cursor:pointer;color:#7e57c2;font-weight:600">展开厂商明细表</summary>'
    html += '<table class="ranking-table" style="max-width:700px;margin-top:8px"><thead><tr><th>排名</th><th>厂商</th><th>最强模型</th><th>均分</th></tr></thead><tbody>'
    html += ''.join(vendor_best_rows)
    html += '</tbody></table></details>'

    if iter_script:
        html += '<h4 style="margin:28px 0 12px;color:#37474f;font-size:15px">模型迭代榜单</h4>'
        html += '<p style="margin-bottom:12px;color:#555;font-size:13px">按配置的 vendor_series 展示同厂商内版本顺序与均分变化，便于观察迭代效果。</p>'
        html += '<div class="chart-container"><div id="chart-version-progression"></div></div>'

    html += f'<script>{"".join(scripts)}</script>'
    return html


def _build_ch3_capability_overview(overall_ranking: pd.DataFrame, data: dict, data_cache: dict) -> str:
    """第三章：模型能力概览 - 洞察驱动，图表+解读串联，精简排名表 TOP15"""
    if overall_ranking.empty:
        return ''

    charts_html = _build_data_viz_charts(overall_ranking, data, data_cache, focused=True)
    vendor_charts = _build_vendor_rankings_charts(overall_ranking, data_cache)

    # 精简排名表：TOP15，突出头部
    rank_rows = ''
    for _, row in overall_ranking.head(15).iterrows():
        rank = int(row.get('排名', 0))
        model = _escape_html(_safe_str(row.get('模型', '')))
        avg = _safe_float(row.get('平均分', 0))
        rank_cls = f'rank-{rank}' if rank <= 3 else 'rank-other'
        rank_rows += f'<tr><td><span class="rank-badge {rank_cls}">{rank}</span></td><td>{model}</td><td><strong>{avg:.1f}</strong></td></tr>'

    html = f"""<div class="section">
<h2 class="section-title">三、模型能力概览</h2>
<p style="margin-bottom:20px;color:#555;font-size:14px;line-height:1.6">
  本节围绕四大核心发现组织：综合排名与维度能力、公私域落差、重格式轻逻辑、分组对比。每组图表配有洞察解读，便于快速理解数据含义。
</p>
{charts_html}
{vendor_charts}
<h3 class="subsection-title">3.5 综合排名（TOP15）</h3>
<table class="ranking-table" style="max-width:560px">
<thead><tr><th>排名</th><th>模型</th><th>均分</th></tr></thead>
<tbody>{rank_rows}</tbody>
</table>
</div>"""
    return html


def _build_l1_capability_summaries_section(data_cache: dict) -> str:
    """
    L1 能力概览：以 LLM 总结为主，高区分度统计折叠，减少表格堆砌。
    """
    high_df = data_cache.get('l1_high_distinction_stats', pd.DataFrame())
    summaries = data_cache.get('l1_capability_summaries') or {}
    intent_df = data_cache.get('intent_level_analysis', pd.DataFrame())

    if not summaries and high_df.empty and (intent_df is None or intent_df.empty):
        return ''

    html = '<div class="section"><h2 class="section-title">四、分意图能力洞察</h2>'
    html += '<p style="margin-bottom:16px;color:#555;font-size:14px">按 L1 意图类型，结合统计与 LLM 分析各意图上模型表现。重点阅读各 L1 能力总结，表格供查阅。</p>'

    if summaries:
        html += '<h3 class="subsection-title">4.1 各 L1 能力总结</h3>'
        for l1, text in list(summaries.items())[:10]:
            html += f'<div class="info-box" style="margin-bottom:12px"><strong>{_escape_html(l1)}</strong><p style="margin:8px 0 0;line-height:1.6">{_escape_html(text) or "—"}</p></div>'

    # 高区分度题目、意图分析表折叠
    if not high_df.empty:
        html += '<details style="margin-top:16px"><summary style="cursor:pointer;color:#7e57c2;font-weight:600">展开 L1 高区分度题目统计（区分度≥0.3）</summary>'
        html += '<table class="ranking-table" style="max-width:700px;margin-top:8px"><thead><tr>'
        for c in high_df.columns:
            html += f'<th>{_escape_html(str(c))}</th>'
        html += '</tr></thead><tbody>'
        for _, row in high_df.iterrows():
            html += '<tr>' + ''.join(f'<td>{_escape_html(str(row.get(c, "")))}</td>' for c in high_df.columns) + '</tr>'
        html += '</tbody></table></details>'

    if intent_df is not None and not intent_df.empty:
        html += '<details style="margin-top:12px"><summary style="cursor:pointer;color:#7e57c2;font-weight:600">展开 意图级别分析（方差 TOP10）</summary>'
        html += '<div style="overflow-x:auto;margin-top:8px"><table class="ranking-table"><thead><tr>'
        for c in intent_df.columns:
            html += f'<th>{_escape_html(str(c))}</th>'
        html += '</tr></thead><tbody>'
        for _, row in intent_df.head(10).iterrows():
            html += '<tr>' + ''.join(f'<td>{_escape_html(_safe_str(row.get(c, "")))}</td>' for c in intent_df.columns) + '</tr>'
        html += '</tbody></table></div></details>'

    html += '</div>'
    return html


def _build_ch5_expert_section(data_cache: dict) -> str:
    """第 5 章 专家视角与可靠性（EVAL_REPORT_FRAMEWORK_v2）"""
    corrected = data_cache.get('corrected_ranking', pd.DataFrame())
    expert_only = (data_cache.get('rankings') or {}).get('expert_only', pd.DataFrame())
    model_expert_overall = data_cache.get('model_expert_overall', pd.DataFrame())
    model_expert_detail = data_cache.get('model_expert_detail', pd.DataFrame())

    html = '<div class="section"><h2 class="section-title">五、专家视角与可靠性</h2>'

    if not corrected.empty:
        html += '<h3 class="subsection-title">5.1 专家纠偏排名</h3><p style="margin-bottom:12px;color:#555">有专家打分的题目上以专家分替代自动分后重算均分，纠偏后排名更贴近人工判断。</p>'
        html += '<div style="overflow-x:auto"><table class="ranking-table"><thead><tr>'
        for c in corrected.columns:
            html += f'<th>{_escape_html(str(c))}</th>'
        html += '</tr></thead><tbody>'
        for _, row in corrected.head(15).iterrows():
            html += '<tr>'
            for c in corrected.columns:
                v = row.get(c, '')
                if isinstance(v, (int, float)) and not (isinstance(v, float) and np.isnan(v)):
                    html += f'<td>{v:.2f}</td>'
                else:
                    html += f'<td>{_escape_html(_safe_str(v))}</td>'
            html += '</tr>'
        html += '</tbody></table></div>'

    if expert_only is not None and not expert_only.empty:
        html += '<h3 class="subsection-title">5.2 专家评测题目榜单</h3><p style="margin-bottom:12px;color:#555">仅统计有专家打分的题目×模型，按专家均分排名。</p>'
        html += '<div style="overflow-x:auto"><table class="ranking-table"><thead><tr>'
        for c in expert_only.columns:
            html += f'<th>{_escape_html(str(c))}</th>'
        html += '</tr></thead><tbody>'
        for _, row in expert_only.head(15).iterrows():
            html += '<tr>' + ''.join(f'<td>{_escape_html(_safe_str(v))}</td>' for v in row) + '</tr>'
        html += '</tbody></table></div>'

    if not model_expert_overall.empty:
        row = model_expert_overall.iloc[0]
        html += '<h3 class="subsection-title">5.3 人机一致性</h3>'
        spearman = row.get('斯皮尔曼_ρ')
        icc = row.get('ICC(2,1)')
        mae = row.get('MAE')
        parts = []
        if spearman is not None and not (isinstance(spearman, float) and np.isnan(spearman)):
            parts.append(f'斯皮尔曼 ρ={float(spearman):.2f}')
        if icc is not None and not (isinstance(icc, float) and np.isnan(icc)):
            parts.append(f'ICC(2,1)={float(icc):.2f}')
        if mae is not None and not (isinstance(mae, float) and np.isnan(mae)):
            parts.append(f'MAE={float(mae):.2f}')
        if parts:
            html += f'<p style="margin-bottom:12px;color:#555">整体一致性：{", ".join(parts)}。自动打分与专家趋势吻合，可辅助参考。</p>'
    if model_expert_detail is not None and not model_expert_detail.empty:
        html += '<details style="margin-top:12px"><summary style="cursor:pointer;color:#7e57c2;font-weight:600">展开 各模型与专家一致性</summary>'
        html += '<div style="overflow-x:auto;margin-top:8px"><table class="ranking-table"><thead><tr>'
        for c in model_expert_detail.columns:
            html += f'<th>{_escape_html(str(c))}</th>'
        html += '</tr></thead><tbody>'
        for _, row in model_expert_detail.head(5).iterrows():
            html += '<tr>' + ''.join(f'<td>{_escape_html(_safe_str(v))}</td>' for v in row) + '</tr>'
        html += '<tr><td colspan="' + str(len(model_expert_detail.columns)) + '" style="text-align:center;color:#999">…</td></tr>'
        for _, row in model_expert_detail.tail(5).iterrows():
            html += '<tr>' + ''.join(f'<td>{_escape_html(_safe_str(v))}</td>' for v in row) + '</tr>'
        html += '</tbody></table></div></details>'

    html += '</div>'
    return html


def _build_ch6_section(
    case_analyses: List[dict],
    data_cache: dict,
    top20_df: pd.DataFrame,
) -> str:
    """第 6 章 典型案例与价值题目（EVAL_REPORT_FRAMEWORK_v2）"""
    html = '<div class="section"><h2 class="section-title">六、典型案例与价值题目</h2>'

    if not top20_df.empty:
        html += '<h3 class="subsection-title">6.1 价值题目 TOP20</h3>'
        html += '<details open><summary style="cursor:pointer;color:#7e57c2;font-weight:600">价值题目列表（区分度高，便于选型参考）</summary>'
        html += '<div style="overflow-x:auto;margin-top:8px"><table class="ranking-table"><thead><tr>'
        cols = ['排名', 'qid', 'L1', 'L2', '数据来源', '模型均分', '区分度_D值', '最佳模型', '最差模型']
        for c in [x for x in cols if x in top20_df.columns]:
            html += f'<th>{_escape_html(c)}</th>'
        html += '</tr></thead><tbody>'
        for _, row in top20_df.head(20).iterrows():
            html += '<tr>'
            for c in [x for x in cols if x in top20_df.columns]:
                html += f'<td>{_escape_html(_safe_str(row.get(c, "")))}</td>'
            html += '</tr>'
        html += '</tbody></table></div></details>'

    if case_analyses:
        html += '<h3 class="subsection-title">6.2 典型案例（按 L1 选取代表）</h3>'
        html += '<p style="margin-bottom:16px;color:#555;font-size:14px">从各 L1 维度选取代表案例，含模型分档总结与好/中/差回复示范。</p>'
        seen_l1 = set()
        idx = 0
        for case in case_analyses[:20]:
            l1 = _safe_str(case.get('L1', ''))
            if l1 in seen_l1 or idx >= 12:
                continue
            seen_l1.add(l1)
            idx += 1
            html += _build_case_card(idx, case)

    html += '</div>'
    return html


def _build_ch7_conclusions_section(data_cache: dict) -> str:
    """第 7 章 结论与建议（EVAL_REPORT_FRAMEWORK_v2），含补充指标（ILA、维度）"""
    tiers = data_cache.get('model_tiers') or []
    intent_insights = data_cache.get('intent_insights') or []
    scenario_guide = data_cache.get('scenario_guide', pd.DataFrame())
    improvement_paths = data_cache.get('improvement_paths') or []
    source_gap = data_cache.get('source_gap_summary') or {}
    fp = data_cache.get('full_pass_summary') or {}
    dim_stats = data_cache.get('dimension_stats') or {}

    html = '<div class="section"><h2 class="section-title">七、结论与建议</h2>'

    # 补充指标（原 full_pass、dimension_ila 精简为一行摘要）
    supp_lines = []
    if fp:
        ov_pass, ov_total = fp.get('overall_pass', 0), fp.get('overall_total', 0)
        ov_rate = fp.get('overall_rate')
        if ov_total and ov_rate is not None:
            supp_lines.append(f'完全通过率（ILA）：{ov_pass}/{ov_total} = {ov_rate}%')
    if dim_stats.get('has_data'):
        pivot = dim_stats.get('dimension_pivot_df', pd.DataFrame())
        if not pivot.empty and 'D2通过率' in pivot.columns and 'D4通过率' in pivot.columns:
            d2_m = pd.to_numeric(pivot['D2通过率'], errors='coerce').mean()
            d4_m = pd.to_numeric(pivot['D4通过率'], errors='coerce').mean()
            if not (pd.isna(d2_m) or pd.isna(d4_m)):
                supp_lines.append(f'维度均值：D2 {d2_m:.1f}% · D4 {d4_m:.1f}%（D4&gt;D2 印证重格式轻逻辑）')
    if supp_lines:
        html += f'<div class="info-box" style="background:#f5f5f5;border-left:4px solid #9e9e9e;margin-bottom:20px"><strong>📋 补充指标</strong><p style="margin:6px 0 0">{" | ".join(supp_lines)}</p></div>'

    html += '<h3 class="subsection-title">7.1 假设验证</h3><ul style="padding-left:24px;line-height:1.8">'
    gap = source_gap.get('公开vs纯人工自建_均分差')
    if gap is not None and not (isinstance(gap, float) and np.isnan(gap)):
        html += f'<li>自建题目更能区分模型：公开 vs 纯人工自建均分差 {gap} 分，自建难度更高。</li>'
    html += '<li>模型重格式轻逻辑：D2/D3/D5 通过率普遍低于 D4，见第三章维度摘要。</li>'
    html += '<li>专家纠偏影响排名：纠偏前后排名变化见第五章。</li></ul>'

    html += '<h3 class="subsection-title">7.2 分角色建议</h3><ul style="padding-left:24px;line-height:1.8">'
    html += '<li><strong>选型方</strong>：结合 L1 能力总结与专家纠偏排名，按场景选模型。</li>'
    html += '<li><strong>训练方</strong>：加强 D2/D3/D5 相关约束的训练与评测。</li>'
    html += '<li><strong>数据方</strong>：增加高区分度自建题（H/R/HM），控制 M 合成题比例。</li></ul>'

    if tiers:
        html += '<h3 class="subsection-title">7.3 模型能力分档</h3><ul style="padding-left:24px;line-height:1.8">'
        tier_groups = {}
        for t in tiers:
            k = t.get('梯队', '')
            if k not in tier_groups:
                tier_groups[k] = []
            tier_groups[k].append(f"{t.get('模型', '')}（{t.get('均分', 0):.1f} 分）")
        for tier in ['第一梯队', '第二梯队', '第三梯队', '第四梯队']:
            if tier in tier_groups:
                html += f'<li><strong>{_escape_html(tier)}</strong>：{", ".join(_escape_html(m) for m in tier_groups[tier][:12])}{" …" if len(tier_groups[tier]) > 12 else ""}</li>'
        html += '</ul>'

    if intent_insights:
        html += '<h3 class="subsection-title">意图级别洞察</h3><ul style="padding-left:24px;line-height:1.8">'
        for line in intent_insights[:10]:
            html += f'<li>{_escape_html(line)}</li>'
        html += '</ul>'

    if scenario_guide is not None and not scenario_guide.empty:
        html += '<details style="margin-top:12px"><summary style="cursor:pointer;color:#7e57c2;font-weight:600">展开 场景化选型指南</summary>'
        html += '<div style="overflow-x:auto;margin-top:8px"><table class="ranking-table">'
        html += '<thead><tr>' + ''.join(f'<th>{_escape_html(str(c))}</th>' for c in scenario_guide.columns) + '</tr></thead><tbody>'
        for _, row in scenario_guide.iterrows():
            html += '<tr>' + ''.join(f'<td>{_escape_html(_safe_str(row.get(c, "")))}</td>' for c in scenario_guide.columns) + '</tr>'
        html += '</tbody></table></div></details>'

    if improvement_paths:
        html += '<h3 class="subsection-title">模型能力提升路径</h3><ul style="padding-left:24px;line-height:1.8">'
        for line in improvement_paths:
            html += f'<li>{_escape_html(line)}</li>'
        html += '</ul>'

    html += '</div>'
    return html




def _build_ch1_executive_summary(data: dict, data_cache: dict) -> str:
    """第 1 章 执行摘要：背景 + 数据驱动核心结论 + 关键数据 + 主要建议（EVAL_REPORT_FRAMEWORK_v2）"""
    replies = data.get('replies', pd.DataFrame())
    questions = data.get('questions', pd.DataFrame())
    overall = data_cache.get('overall_ranking', pd.DataFrame())
    corrected = data_cache.get('corrected_ranking', pd.DataFrame())
    source_gap = data_cache.get('source_gap_summary') or {}
    model_expert = data_cache.get('model_expert_overall', pd.DataFrame())
    dim_stats = data_cache.get('dimension_stats', {})

    model_count = replies['model'].nunique() if not replies.empty else 0
    task_count = _task_count(questions)
    public_cnt, self_cnt = _source_counts(questions)

    # 1.3 数据驱动核心结论
    conclusions = []
    gap = source_gap.get('公开vs纯人工自建_均分差')
    if gap is not None and not (isinstance(gap, float) and np.isnan(gap)):
        conclusions.append(f'自建题目上模型均分较公开低 <strong>{gap} 分</strong>，纯人工自建更能反映真实业务难度，区分度更佳。')
    if dim_stats.get('has_data'):
        pivot = dim_stats.get('dimension_pivot_df', pd.DataFrame())
        if not pivot.empty and 'D2通过率' in pivot.columns and 'D4通过率' in pivot.columns:
            d2_mean = pd.to_numeric(pivot['D2通过率'], errors='coerce').mean()
            d4_mean = pd.to_numeric(pivot['D4通过率'], errors='coerce').mean()
            if not (pd.isna(d2_mean) or pd.isna(d4_mean)):
                conclusions.append(f'D2（流程步骤）平均通过率 {d2_mean:.1f}%，D4（格式要求）{d4_mean:.1f}%，D4 显著高于 D2，印证「重格式、轻逻辑」。')
    if not corrected.empty and '模型' in corrected.columns:
        top3 = corrected.head(3)['模型'].tolist()
        conclusions.append(f'专家纠偏后 TOP3：{", ".join(_escape_html(m) for m in top3)}。')
    if not model_expert.empty and '斯皮尔曼_ρ' in model_expert.columns:
        rho = model_expert.iloc[0].get('斯皮尔曼_ρ')
        if rho is not None and not (isinstance(rho, float) and np.isnan(rho)):
            conclusions.append(f'整体人机排名一致性斯皮尔曼 ρ={float(rho):.2f}。')
    if not conclusions:
        for b in EXEC_SUMMARY_BULLETS[:3]:
            conclusions.append(b)

    html = f"""<div class="section">
<h2 class="section-title">一、执行摘要</h2>
<h3 class="subsection-title">1.1 评测目的与背景</h3>
<div class="info-box summary">
<p>{EXEC_SUMMARY_BACKGROUND}</p>
</div>
<h3 class="subsection-title">1.2 评测对象与数据</h3>
<table class="ranking-table" style="max-width:600px">
<thead><tr><th>指标</th><th>数值</th></tr></thead>
<tbody>
<tr><td>评测模型数</td><td><strong>{model_count}</strong></td></tr>
<tr><td>评测题目数</td><td><strong>{task_count}</strong></td></tr>
<tr><td>公开数据题</td><td><strong>{public_cnt}</strong></td></tr>
<tr><td>自建数据题</td><td><strong>{self_cnt}</strong></td></tr>
"""
    if gap is not None and not (isinstance(gap, float) and np.isnan(gap)):
        html += f'<tr><td><strong>公开 vs 纯人工自建均分差</strong></td><td><strong style="color:#e74c3c">{gap} 分</strong></td></tr>'
    html += """</tbody></table>
<h3 class="subsection-title">1.3 核心结论</h3>
<ul style="margin:16px 0;padding-left:24px;line-height:1.8">
"""
    for c in conclusions:
        html += f'  <li>{c}</li>\n'
    html += """</ul>
<h3 class="subsection-title">1.4 主要建议</h3>
<ul style="margin:16px 0;padding-left:24px;line-height:1.8">
  <li><strong>选型方</strong>：优先考虑专家纠偏排名与 L1 能力匹配，按场景选模型。</li>
  <li><strong>训练方</strong>：强化 D2/D3/D5 等薄弱维度的训练与评测。</li>
  <li><strong>数据方</strong>：增加高区分度自建题（H/R/HM），控制 M 合成题比例。</li>
</ul>
</div>"""
    return html


def _build_source_stats_section(data_cache: dict) -> str:
    """按 source 分组得分表 + 公开vs自建对比摘要（突出纯人工自建 vs M合成）"""
    source_stats = data_cache.get('source_stats', pd.DataFrame())
    source_gap = data_cache.get('source_gap_summary') or {}
    if source_stats.empty and not source_gap:
        return ''
    html = '<div class="section"><h2 class="section-title">📊 按 Source 分组得分</h2>'

    if not source_stats.empty:
        html += """
<p style="margin-bottom:16px;color:#555">题目表 source：公开=to_b/nlp_* 等；自建=H(人工)/R(真实来源)/HM(人机协作)/M(模型合成)</p>
<div style="overflow-x:auto"><table class="ranking-table"><thead><tr>
<th>source</th><th>分组</th><th>题目数</th><th>模型均分</th><th>标准差</th>
</tr></thead><tbody>
"""
        for _, row in source_stats.iterrows():
            src = _escape_html(str(row.get('source', '')))
            group = _escape_html(str(row.get('分组', '')))
            qcnt = row.get('题目数', 'N/A')
            meanv = row.get('模型均分', 'N/A')
            stdv = row.get('标准差', 'N/A')
            html += f'<tr><td>{src}</td><td>{group}</td><td>{qcnt}</td><td>{meanv}</td><td>{stdv}</td></tr>\n'
        html += '</tbody></table></div>'

    if source_gap:
        gap = source_gap.get('公开vs纯人工自建_均分差')
        gap_str = f'<strong style="color:#e74c3c;font-size:18px">{gap} 分</strong>' if gap is not None and not (isinstance(gap, float) and np.isnan(gap)) else 'N/A'
        html += """<h3 class="subsection-title">公开 vs 自建 对比摘要</h3>
<div class="info-box" style="background:linear-gradient(135deg,#fff3e0,#ffe0b2);border-left:4px solid #ff9800;margin-top:12px">
<p style="margin-bottom:12px"><strong>核心指标</strong>：<span style="color:#e74c3c">公开 vs 纯人工自建 均分差</span> = """
        html += gap_str
        html += """（公开更高，差值越大越体现自建题目真实难度）</p>
<ul style="margin:8px 0;padding-left:20px;line-height:1.8">
<li><strong>公开数据</strong>："""
        html += f"{source_gap.get('公开数据_均分', 'N/A')} 分（{source_gap.get('公开数据_题数', 0)} 题）</li>"
        html += '<li><strong>纯人工自建</strong>（H/R/HM）：'
        html += f"{source_gap.get('纯人工自建_均分', 'N/A')} 分（{source_gap.get('纯人工自建_题数', 0)} 题）— 更能反映真实业务难度</li>"
        html += '<li><strong>M 合成</strong>：'
        html += f"{source_gap.get('M合成_均分', 'N/A')} 分（{source_gap.get('M合成_题数', 0)} 题）— 模型生成题目，<span style='color:#c0392b'>评估打分可能偏高</span></li>"
        vr = source_gap.get('纯人工自建vs公开_方差比')
        if vr is not None and not (isinstance(vr, float) and np.isnan(vr)):
            html += f"<li>纯人工自建 vs 公开 方差比：{vr}（&gt;1 表示自建离散度更大）</li>"
        html += '</ul>'
        html += f"<p style='margin-top:12px;color:#555;font-size:13px'><em>{_escape_html(source_gap.get('M合成打分说明', ''))}</em></p>"
        html += '</div>'
    html += '</div>'
    return html


def _build_overview_section(overall_ranking: pd.DataFrame, data: dict) -> str:
    replies = data.get('replies', pd.DataFrame())
    questions = data.get('questions', pd.DataFrame())
    model_count = replies['model'].nunique() if not replies.empty else 0
    task_count = _task_count(questions)
    eval_count = replies.shape[0] if not replies.empty else 0
    models_list = overall_ranking['模型'].tolist() if not overall_ranking.empty else []
    vendor_count = _count_vendors(models_list) if models_list else 0

    html = f"""<div class="section">
<h2 class="section-title">📊 整体概况</h2>
<div class="stats-grid">
  <div class="stat-card"><div class="stat-value">{model_count}</div><div class="stat-label">评测模型数</div></div>
  <div class="stat-card"><div class="stat-value">{vendor_count}</div><div class="stat-label">厂商数（估算）</div></div>
  <div class="stat-card"><div class="stat-value">{task_count}</div><div class="stat-label">评测题目数</div></div>
  <div class="stat-card"><div class="stat-value">{eval_count}</div><div class="stat-label">总评测次数</div></div>
</div>"""

    if not overall_ranking.empty:
        has_cla = '原均分(CLA)' in overall_ranking.columns
        html += '<h3 class="subsection-title">模型综合排名</h3>'
        if has_cla:
            html += '<p style="margin-bottom:8px;color:#555;font-size:13px"><em>平均分=维度加权通过率，原均分(CLA)=约束通过率</em></p>'
        html += '<table class="ranking-table"><thead><tr><th>排名</th><th>模型</th><th>平均分</th>'
        if has_cla:
            html += '<th>原均分(CLA)</th>'
        html += '<th>标准差</th><th>最高分</th><th>最低分</th><th>题目数</th></tr></thead><tbody>'
        for _, row in overall_ranking.iterrows():
            rank = int(row.get('排名', 0))
            rank_cls = f'rank-{rank}' if rank <= 3 else 'rank-other'
            model = _safe_str(row.get('模型', ''))
            icon = _get_model_icon(model)
            html += f'<tr><td><span class="rank-badge {rank_cls}">#{rank}</span></td>'
            html += f'<td><div class="model-info"><img src="{icon}" class="model-icon" onerror="this.src=\'https://via.placeholder.com/36/667eea/fff?text=AI\'" alt="{_escape_html(model)}"><span class="model-name">{_escape_html(model)}</span></div></td>'
            html += f'<td><strong>{_safe_float(row.get("平均分")):.2f}</strong></td>'
            if has_cla:
                html += f'<td>{_safe_float(row.get("原均分(CLA)")):.2f}</td>'
            html += f'<td>{_safe_float(row.get("标准差")):.2f}</td>'
            html += f'<td>{_safe_float(row.get("最高分")):.2f}</td>'
            html += f'<td>{_safe_float(row.get("最低分")):.2f}</td>'
            html += f'<td>{int(row.get("评测数量", 0))}</td></tr>'
        html += '</tbody></table>'

    html += '</div>'
    return html


def _build_charts_section(overall_ranking: pd.DataFrame, data: dict) -> str:
    if overall_ranking.empty:
        return ''

    # 每5分一个色阶的热力色标（0,5,10,...,100 共21档）
    _heat_colors = ['#1a237e','#283593','#3949ab','#5c6bc0','#7986cb','#9fa8da','#c5cae9','#e8eaf6','#fff8e1','#ffecb3','#ffe082','#ffd54f','#ffca28','#ffc107','#ffb300','#ffa000','#ff8f00','#ff6f00','#e65100','#bf360c','#ffeb3b']
    _heat_scale = json.dumps([[i/20, _heat_colors[i]] for i in range(21)])

    models = [_safe_str(r) for r in overall_ranking['模型'].tolist()]
    scores = [_safe_float(s) for s in overall_ranking['平均分'].tolist()]
    stds = [_safe_float(s) for s in overall_ranking.get('标准差', pd.Series([0]*len(models))).tolist()]

    models_json = json.dumps(models, ensure_ascii=False)
    scores_json = json.dumps(scores)
    stds_json = json.dumps(stds)

    replies_with_q = data.get('replies_with_question', pd.DataFrame())
    heatmap_script = ''
    if not replies_with_q.empty and 'L1' in replies_with_q.columns:
        l1_cats = sorted([str(c) for c in replies_with_q['L1'].dropna().unique()])
        model_list = [_safe_str(m) for m in overall_ranking['模型'].tolist()]
        # 原始: z[model_idx][l1_idx]。目标: 模型=横轴(x)，L1=纵轴(y)，故 z[l1_idx][model_idx]
        z_by_model = []
        for model in model_list:
            row_scores = []
            for cat in l1_cats:
                subset = replies_with_q[(replies_with_q['model'] == model) & (replies_with_q['L1'] == cat)]
                row_scores.append(round(_safe_float(subset['eval_score'].mean()), 2) if not subset.empty else None)
            z_by_model.append(row_scores)
        z_data = [list(col) for col in zip(*z_by_model)]  # 转置: 行=L1, 列=模型
        flat = [v for row in z_data for v in row if v is not None]
        zmin_h = max(0, (min(flat) if flat else 0) - 2)
        zmax_h = min(100, (max(flat) if flat else 100) + 2)
        heatmap_script = f"""
Plotly.newPlot('chart-l1-heatmap',[{{
  z:{json.dumps(z_data)},
  x:{json.dumps(model_list, ensure_ascii=False)},
  y:{json.dumps(l1_cats, ensure_ascii=False)},
  type:'heatmap',
  colorscale:{_heat_scale},
  zmin:{zmin_h},zmax:{zmax_h},
  showscale:true
}}],{{title:{{text:'L1意图类型×模型得分热力图',font:{{size:18,color:'#2c3e50'}}}},xaxis:{{title:'模型'}},yaxis:{{title:'L1意图类型'}},paper_bgcolor:'#f8f9fa',plot_bgcolor:'#f8f9fa'}},{{responsive:true}});"""

    difficulty_script = ''
    if not replies_with_q.empty and 'difficulty_level' in replies_with_q.columns:
        priority = {'S': 6, 'A': 5, 'B': 4, 'C': 3, 'D': 2, 'E': 1}
        diff_levels = sorted(replies_with_q['difficulty_level'].dropna().unique(),
                             key=lambda x: priority.get(str(x), 0), reverse=True)
        model_list = [_safe_str(m) for m in overall_ranking['模型'].tolist()]
        z_by_model_diff = []
        for model in model_list:
            row_scores = []
            for level in diff_levels:
                subset = replies_with_q[(replies_with_q['model'] == model) & (replies_with_q['difficulty_level'] == level)]
                row_scores.append(round(_safe_float(subset['eval_score'].mean()), 2) if not subset.empty else None)
            z_by_model_diff.append(row_scores)
        z_data_diff = [list(col) for col in zip(*z_by_model_diff)]  # 转置: 行=难度, 列=模型
        flat_diff = [v for row in z_data_diff for v in row if v is not None]
        zmin_d = max(0, (min(flat_diff) if flat_diff else 0) - 2)
        zmax_d = min(100, (max(flat_diff) if flat_diff else 100) + 2)
        difficulty_script = f"""
Plotly.newPlot('chart-difficulty-heatmap',[{{
  z:{json.dumps(z_data_diff)},
  x:{json.dumps(model_list, ensure_ascii=False)},
  y:{json.dumps([str(l) for l in diff_levels])},
  type:'heatmap',
  colorscale:{_heat_scale},
  zmin:{zmin_d},zmax:{zmax_d},
  showscale:true
}}],{{title:{{text:'难度等级×模型得分热力图（题目表 difficulty_level）',font:{{size:18,color:'#2c3e50'}}}},xaxis:{{title:'模型'}},yaxis:{{title:'难度等级'}},paper_bgcolor:'#f8f9fa',plot_bgcolor:'#f8f9fa'}},{{responsive:true}});"""

    source_script = ''
    if not replies_with_q.empty and 'source_group' in replies_with_q.columns:
        src_groups = sorted([str(g) for g in replies_with_q['source_group'].dropna().unique()])
        model_list = [_safe_str(m) for m in overall_ranking['模型'].tolist()]
        z_by_model_src = []
        for model in model_list:
            row_scores = []
            for grp in src_groups:
                subset = replies_with_q[(replies_with_q['model'] == model) & (replies_with_q['source_group'] == grp)]
                row_scores.append(round(_safe_float(subset['eval_score'].mean()), 2) if not subset.empty else None)
            z_by_model_src.append(row_scores)
        z_data_src = [list(col) for col in zip(*z_by_model_src)]  # 行=source_group, 列=模型
        flat_src = [v for row in z_data_src for v in row if v is not None]
        zmin_s = max(0, (min(flat_src) if flat_src else 0) - 2)
        zmax_s = min(100, (max(flat_src) if flat_src else 100) + 2)
        source_script = f"""
Plotly.newPlot('chart-source-heatmap',[{{
  z:{json.dumps(z_data_src)},
  x:{json.dumps(model_list, ensure_ascii=False)},
  y:{json.dumps(src_groups, ensure_ascii=False)},
  type:'heatmap',
  colorscale:{_heat_scale},
  zmin:{zmin_s},zmax:{zmax_s},
  showscale:true
}}],{{title:{{text:'自建/公开数据×模型得分热力图',font:{{size:18,color:'#2c3e50'}}}},xaxis:{{title:'模型'}},yaxis:{{title:'数据来源'}},paper_bgcolor:'#f8f9fa',plot_bgcolor:'#f8f9fa'}},{{responsive:true}});"""

    html = f"""<div class="section">
<h2 class="section-title">📈 数据可视化</h2>
<div class="chart-container"><div id="chart-model-bar"></div></div>
<div class="chart-container"><div id="chart-model-box"></div></div>
{'<div class="chart-container"><div id="chart-l1-heatmap"></div></div>' if heatmap_script else ''}
{'<div class="chart-container"><div id="chart-source-heatmap"></div></div>' if source_script else ''}
{'<div class="chart-container"><div id="chart-difficulty-heatmap"></div></div>' if difficulty_script else ''}
</div>
<script>
Plotly.newPlot('chart-model-bar',[{{
  x:{models_json},y:{scores_json},type:'bar',
  error_y:{{type:'data',array:{stds_json},visible:true}},
  marker:{{color:['#5e35b1','#7e57c2','#9c27b0','#ba68c8','#ce93d8','#ffeb3b','#ffee58','#fff59d','#e1bee7','#b39ddb']}},
  text:{json.dumps([f'{s:.1f}' for s in scores])},textposition:'outside'
}}],{{title:{{text:'模型平均分对比',font:{{size:18,color:'#2c3e50'}}}},xaxis:{{title:'模型'}},yaxis:{{title:'平均分',range:[0,105]}},paper_bgcolor:'#f8f9fa',plot_bgcolor:'#f8f9fa'}},{{responsive:true}});
{heatmap_script}
{source_script}
{difficulty_script}
</script>"""
    return html


def _build_valuable_questions_section(
    top20_df: pd.DataFrame,
    item_analysis_df: pd.DataFrame,
    case_analyses: List[dict],
) -> str:
    if top20_df.empty and not case_analyses:
        return ''

    html = '<div class="section"><h2 class="section-title">🎯 价值题目深度分析</h2>'

    if not top20_df.empty:
        html += '<h3 class="subsection-title">价值题目TOP20概览</h3>'
        html += '<div style="overflow-x:auto"><table class="ranking-table"><thead><tr>'
        display_cols = ['排名', 'qid', 'L1', 'L2', '数据来源', '预设难度', '模型均分', '区分度_D值', '综合价值分', '最佳模型', '最差模型']
        actual_cols = [c for c in display_cols if c in top20_df.columns]
        for col in actual_cols:
            html += f'<th>{_escape_html(col)}</th>'
        html += '</tr></thead><tbody>'
        for _, row in top20_df.iterrows():
            html += '<tr>'
            for col in actual_cols:
                html += f'<td>{_escape_html(_safe_str(row.get(col, "")))}</td>'
            html += '</tr>'
        html += '</tbody></table></div>'

    if case_analyses:
        html += '<h3 class="subsection-title">典型题目详细分析</h3>'
        for idx, case in enumerate(case_analyses, 1):
            html += _build_case_card(idx, case)

    html += '</div>'
    return html


def _build_case_card(case_num: int, case: dict) -> str:
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
    model_replies: dict = case.get('model_replies', {})
    model_evaluations: dict = case.get('model_evaluations', {})
    expert_opinion: str = _safe_str(case.get('expert_opinion', ''))
    ai_summary: str = _safe_str(case.get('ai_summary', ''))
    ai_analysis: str = _safe_str(case.get('ai_analysis', ''))
    score_range = _safe_float(case.get('score_range', 0))

    sorted_scores = sorted(model_scores.items(), key=lambda x: x[1], reverse=True)
    # 各模型得分 + 与本题最佳差距（便于厂商看与强模型差距）
    parts = []
    for m, s in sorted_scores:
        gap = model_gaps.get(m)
        if gap is not None and gap == 0 and best_model:
            parts.append(f'<strong>{_escape_html(m)}</strong>: {_score_badge(s)} <span style="color:#27ae60;font-size:12px">（本题最佳）</span>')
        elif gap is not None and gap > 0:
            parts.append(f'<strong>{_escape_html(m)}</strong>: {_score_badge(s)} <span style="color:#7f8c8d;font-size:12px">（与最佳差 {gap:.1f} 分）</span>')
        else:
            parts.append(f'<strong>{_escape_html(m)}</strong>: {_score_badge(s)}')
    scores_text = ' | '.join(parts)

    case_id = f'case-{case_num}'
    html = f"""<div class="case-card">
<div class="case-header" onclick="toggleCase('{case_id}')">
  <div>
    <h3>案例 {case_num}: Q{_escape_html(qid)}</h3>
    <p style="margin-top:6px;opacity:.9;font-size:14px">L1: {_escape_html(l1)} | L3: {_escape_html(l3)} | 难度: {_escape_html(difficulty)} | 分数范围: {score_range:.1f}</p>
  </div>
  <span class="toggle-icon">▼</span>
</div>
<div class="case-content" id="{case_id}">
<div class="case-body">
  <div class="info-box query">
    <h4>📝 题目内容</h4>
    <div class="markdown-content" data-md data-raw="{_escape_html(_sanitize_excel_text(query))}"></div>
  </div>
  <div class="info-box summary">
    <h4>📊 各模型得分（与本题最佳对比）</h4>
    <p>{scores_text}</p>
  </div>"""

    dimension_info = _safe_str(case.get('dimension_info', ''))
    if dimension_info:
        html += f"""<div class="info-box summary">
    <h4>📐 本题目各模型维度表现（D2/D3/D4/D5 通过情况）</h4>
    <pre style="margin:0;white-space:pre-wrap;font-size:13px">{_escape_html(dimension_info)}</pre>
  </div>"""

    if ai_summary:
        html += f"""<div class="info-box summary">
    <h4>💡 AI综合评估</h4>
    <div class="markdown-content" data-md data-raw="{_escape_html(_sanitize_excel_text(ai_summary))}"></div>
  </div>"""

    if ai_analysis:
        html += f"""<div class="analysis-block">
    <h4 style="margin-bottom:12px;color:#2c3e50">📋 模型分档与失分点分析</h4>
    <div class="markdown-content" data-md data-raw="{_escape_html(_sanitize_excel_text(ai_analysis))}"></div>
  </div>"""

    # 回复示范：仅展示好、中、差三个典型案例
    tier_models = case.get('tier_models') or []
    if model_scores and sorted_scores:
        demo_models = []
        if tier_models:
            # 从优秀档取第一个、中间档取第一个、待改进档取第一个
            if len(tier_models) >= 1 and tier_models[0][1]:
                demo_models.append((tier_models[0][1][0], '优秀示范'))
            mid = len(tier_models) // 2
            if len(tier_models) >= 2 and mid > 0 and tier_models[mid][1]:
                demo_models.append((tier_models[mid][1][0], '中等示范'))
            if len(tier_models) >= 2 and tier_models[-1][1]:
                demo_models.append((tier_models[-1][1][0], '待改进示范'))
        if len(demo_models) < 3:
            # 兜底：取最好、中间、最差
            n = len(sorted_scores)
            indices = [0, n // 2, n - 1] if n >= 3 else list(range(n))
            labels = ['优秀示范', '中等示范', '待改进示范']
            demo_models = [(sorted_scores[i][0], labels[i]) for i in indices[:3]]
        # 去重，保持顺序
        seen = set()
        unique_demos = []
        for m, lb in demo_models:
            if m not in seen:
                seen.add(m)
                unique_demos.append((m, lb))
        if len(unique_demos) == 1:
            unique_demos[0] = (unique_demos[0][0], '示范案例')
        html += f'<h4 style="margin:24px 0 12px;color:#2c3e50">回复示范（好/中/差）</h4>'
        html += f'<p style="margin-bottom:12px;color:#555;font-size:13px">选取各档位代表模型回复作为示范，便于对比表现差异。</p>'
        for idx, (model, label) in enumerate(unique_demos):
            score = model_scores.get(model, 0)
            reply = _sanitize_excel_text(_safe_str(model_replies.get(model, '')))
            evaluation = _sanitize_excel_text(_safe_str(model_evaluations.get(model, '')))
            badge_cls = 'score-high' if label == '优秀示范' else ('score-mid' if label == '中等示范' else 'score-low')
            html += f'<div class="info-box" style="margin-bottom:16px;border-left:4px solid ' + ('#27ae60' if label == '优秀示范' else ('#f39c12' if label == '中等示范' else '#e74c3c')) + '">'
            html += f'<h5 style="margin-bottom:8px">{label}：{_escape_html(model)} <span class="score-badge {badge_cls}">{score:.1f}</span></h5>'
            html += f'<div class="reply-text" style="max-height:300px;overflow-y:auto">{_nl2br(reply)}</div>'
            if evaluation:
                html += f'<details style="margin-top:10px"><summary style="cursor:pointer;font-size:13px;color:#7e57c2">展开评估详情</summary>'
                html += f'<div class="evaluation-text" style="margin-top:8px;font-size:13px">{_nl2br(evaluation)}</div></details>'
            html += '</div>'

    html += '</div></div></div>'
    return html


def _build_expert_only_ranking_section(data_cache: dict) -> str:
    """专家评测过的题目榜单：仅统计有专家打分的题目×模型，按专家均分排名。"""
    expert_only = (data_cache.get('rankings') or {}).get('expert_only', pd.DataFrame())
    if expert_only is None or expert_only.empty:
        return ''
    html = '<div class="section"><h2 class="section-title">📋 专家评测过的题目榜单</h2>'
    html += '<p style="margin-bottom:16px;color:#555">仅统计<strong>有专家打分</strong>的题目×模型，按专家均分排名，可与自动打分区分看待。同一子集上的「模型均分(专家题上)」供对比。</p>'
    html += '<div style="overflow-x:auto"><table class="ranking-table"><thead><tr>'
    for c in expert_only.columns:
        html += f'<th>{_escape_html(str(c))}</th>'
    html += '</tr></thead><tbody>'
    for _, row in expert_only.iterrows():
        html += '<tr>'
        for c in expert_only.columns:
            v = row.get(c, '')
            if isinstance(v, float) and not np.isnan(v):
                html += f'<td>{v:.2f}</td>'
            else:
                html += f'<td>{_escape_html(_safe_str(v))}</td>'
        html += '</tr>'
    html += '</tbody></table></div></div>'
    return html


def _build_consistency_section(data_cache: dict) -> str:
    rater_vs_others = data_cache.get('rater_vs_others', pd.DataFrame())
    model_expert_overall = data_cache.get('model_expert_overall', pd.DataFrame())
    model_ranking_summary = data_cache.get('model_ranking_summary', pd.DataFrame())

    if rater_vs_others.empty and model_ranking_summary.empty and model_expert_overall.empty:
        return ''

    html = '<div class="section"><h2 class="section-title">📐 一致性分析摘要</h2>'

    # 专家-模型打分一致性指标（多维度）
    if not model_expert_overall.empty:
        row = model_expert_overall.iloc[0]
        metrics_info = [
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
        html += '<div class="info-box" style="margin-bottom:16px"><h4>👨‍🔬 专家-模型打分一致性指标</h4><table style="margin-top:8px;font-size:14px"><tbody>'
        for col, hint in metrics_info:
            if col in row.index:
                val = row[col]
                disp = val if isinstance(val, str) else (f'{float(val):.3f}' if isinstance(val, (int, float)) and not (isinstance(val, float) and np.isnan(val)) else str(val))
                html += f'<tr><td style="padding:4px 12px 4px 0"><strong>{_escape_html(col)}</strong></td><td style="padding:4px">{_escape_html(str(disp))}</td><td style="padding:4px;color:#666;font-size:12px">{_escape_html(hint)}</td></tr>'
        html += f'<tr><td colspan="3" style="padding:8px 0 0 0;color:#666">样本量 {row.get("样本量", "N/A")} | 题目数 {row.get("题目数", "N/A")} | 模型数 {row.get("模型数", "N/A")}</td></tr>'
        html += '</tbody></table></div>'
    model_expert_detail = data_cache.get('model_expert_detail', pd.DataFrame())
    if model_expert_detail is not None and not model_expert_detail.empty:
        html += '<h3 class="subsection-title">各模型与专家打分一致性</h3>'
        html += '<p style="margin-bottom:12px;color:#555">按模型统计其打分与专家打分的一致性，排名靠前表示与专家越一致。</p>'
        html += '<div style="overflow-x:auto"><table class="ranking-table"><thead><tr>'
        for c in model_expert_detail.columns:
            html += f'<th>{_escape_html(str(c))}</th>'
        html += '</tr></thead><tbody>'
        for _, row in model_expert_detail.iterrows():
            html += '<tr>' + ''.join(f'<td>{_escape_html(_safe_str(v))}</td>' for v in row) + '</tr>'
        html += '</tbody></table></div>'

    if not rater_vs_others.empty:
        html += '<h3 class="subsection-title">标注员组内一致性</h3>'
        html += '<div style="overflow-x:auto"><table class="ranking-table"><thead><tr>'
        for col in rater_vs_others.columns:
            html += f'<th>{_escape_html(str(col))}</th>'
        html += '</tr></thead><tbody>'
        for _, row in rater_vs_others.iterrows():
            html += '<tr>' + ''.join(f'<td>{_escape_html(_safe_str(v))}</td>' for v in row) + '</tr>'
        html += '</tbody></table></div>'

    if not model_ranking_summary.empty:
        html += '<h3 class="subsection-title">模型排名一致性（与专家对比）</h3>'
        html += '<div style="overflow-x:auto"><table class="ranking-table"><thead><tr>'
        for col in model_ranking_summary.columns:
            html += f'<th>{_escape_html(str(col))}</th>'
        html += '</tr></thead><tbody>'
        for _, row in model_ranking_summary.iterrows():
            html += '<tr>' + ''.join(f'<td>{_escape_html(_safe_str(v))}</td>' for v in row) + '</tr>'
        html += '</tbody></table></div>'

    html += '</div>'
    return html


def _build_full_pass_section(data_cache: dict) -> str:
    """3.3 主分数与完全通过率（EVAL_REPORT_FRAMEWORK_v2 第3章）"""
    fp = data_cache.get('full_pass_summary') or {}
    fp_df = fp.get('per_model_df')
    if fp_df is None or fp_df.empty:
        return ''
    html = '<div class="section"><h3 class="subsection-title">3.3 主分数与完全通过率</h3>'
    html += """<p style="margin-bottom:12px;color:#555">主分数=维度加权通过率（D5=50%, D2=22%, D3=20%, D4=8%）；ILA=所有检查点PASS的题目占比。</p>"""
    html += '<div style="overflow-x:auto"><table class="ranking-table"><thead><tr>'
    for c in fp_df.columns:
        html += f'<th>{_escape_html(str(c))}</th>'
    html += '</tr></thead><tbody>'
    for _, row in fp_df.iterrows():
        html += '<tr>'
        for c in fp_df.columns:
            html += f'<td>{_escape_html(_safe_str(row.get(c, "")))}</td>'
        html += '</tr>'
    html += '</tbody></table></div>'
    ov = fp.get('overall_rate')
    if ov is not None:
        html += f'<p style="margin-top:12px;color:#555"><em>全体完全通过率：{fp.get("overall_pass", 0)}/{fp.get("overall_total", 0)} = {ov}%</em></p>'
    html += '</div>'
    return html


def _build_dimension_ila_section(data_cache: dict) -> str:
    """3.4 维度能力摘要 D2/D3/D4/D5（EVAL_REPORT_FRAMEWORK_v2 第3章）"""
    dim_df = data_cache.get('dimension_ila_df', pd.DataFrame())
    if dim_df is None or dim_df.empty:
        return ''
    html = '<div class="section"><h3 class="subsection-title">3.4 维度能力摘要（D2/D3/D4/D5 ILA 通过率）</h3>'
    html += '<p style="margin-bottom:16px;color:#555">各维度 ILA = 该维度下全部检查点 PASS 的题目占比，便于分析模型在哪些维度易出问题。</p>'
    html += '<div style="overflow-x:auto"><table class="ranking-table"><thead><tr>'
    for c in dim_df.columns:
        html += f'<th>{_escape_html(str(c))}</th>'
    html += '</tr></thead><tbody>'
    for _, row in dim_df.iterrows():
        html += '<tr>'
        for c in dim_df.columns:
            html += f'<td>{_escape_html(_safe_str(row.get(c, "")))}</td>'
        html += '</tr>'
    html += '</tbody></table></div></div>'
    return html


def _build_score_distribution_section(data_cache: dict) -> str:
    score_dist = data_cache.get('score_distribution', pd.DataFrame())
    if score_dist is None or score_dist.empty:
        return ''
    html = '<div class="section"><h2 class="section-title">📈 分数分布</h2>'
    html += '<p style="margin-bottom:16px;color:#555">各模型在 0-20、20-40、40-60、60-80、80-100 分数段的题目数与占比</p>'
    html += '<div style="overflow-x:auto"><table class="ranking-table"><thead><tr>'
    for c in score_dist.columns:
        html += f'<th>{_escape_html(str(c))}</th>'
    html += '</tr></thead><tbody>'
    for _, row in score_dist.iterrows():
        html += '<tr>'
        for c in score_dist.columns:
            html += f'<td>{_escape_html(_safe_str(row.get(c, "")))}</td>'
        html += '</tr>'
    html += '</tbody></table></div></div>'
    return html


def _build_intent_level_section(data_cache: dict) -> str:
    intent_df = data_cache.get('intent_level_analysis', pd.DataFrame())
    if intent_df is None or intent_df.empty:
        return ''
    html = '<div class="section"><h2 class="section-title">📋 意图级别分析</h2>'
    html += '<p style="margin-bottom:16px;color:#555">按 L1 意图类型的题目数、平均分数方差、最佳/最差模型、各模型均分。方差越大区分度越高。</p>'
    html += '<div style="overflow-x:auto"><table class="ranking-table"><thead><tr>'
    for c in intent_df.columns:
        html += f'<th>{_escape_html(str(c))}</th>'
    html += '</tr></thead><tbody>'
    for _, row in intent_df.head(30).iterrows():
        html += '<tr>'
        for c in intent_df.columns:
            html += f'<td>{_escape_html(_safe_str(row.get(c, "")))}</td>'
        html += '</tr>'
    html += '</tbody></table></div></div>'
    return html


def _build_constraint_efficacy_section(data_cache: dict) -> str:
    eff = data_cache.get('constraint_efficacy') or {}
    eff_df = eff.get('efficacy_df', pd.DataFrame())
    if eff_df is None or eff_df.empty:
        return ''
    html = '<div class="section"><h2 class="section-title">⚙️ 约束级别分析</h2>'
    html += '<p style="margin-bottom:16px;color:#555">基于 D 维度的效能分级。A: 50%+失分；B: 30-50%；C: &lt;30%；D: 全满分</p>'
    html += '<div style="overflow-x:auto"><table class="ranking-table"><thead><tr>'
    for c in eff_df.columns:
        html += f'<th>{_escape_html(str(c))}</th>'
    html += '</tr></thead><tbody>'
    for _, row in eff_df.iterrows():
        html += '<tr>'
        for c in eff_df.columns:
            html += f'<td>{_escape_html(_safe_str(row.get(c, "")))}</td>'
        html += '</tr>'
    html += '</tbody></table></div>'
    top10 = eff.get('top10_challenging', [])
    if top10:
        html += '<h3 class="subsection-title">最具挑战性的约束 Top10</h3><ul style="padding-left:24px">'
        for i, c in enumerate(top10[:10], 1):
            cp = c.get('约束/维度', '')
            typ = c.get('type', '')
            fail = c.get('平均失分率', '')
            html += f'<li><strong>{_escape_html(str(cp))}</strong>（{_escape_html(str(typ))}）— 平均失分率 {fail}%</li>'
        html += '</ul>'
    html += '</div>'
    return html


def _build_version_progression_section(data_cache: dict) -> str:
    version_progression = data_cache.get('version_progression') or []
    if not version_progression:
        return ''
    html = '<div class="section"><h2 class="section-title">📈 厂商系列版本递进</h2>'
    html += '<p style="margin-bottom:16px;color:#555">按配置的厂商版本顺序展示平均分及较上一版本的提升幅度，便于观察迭代是否带来能力跃升与成长速度。</p>'
    html += '<div style="overflow-x:auto"><table class="ranking-table"><thead><tr>'
    cols = ['厂商', '版本顺序', '模型', '平均分', '较上版提升', '较上版提升率(%)']
    for c in cols:
        html += f'<th>{_escape_html(c)}</th>'
    html += '</tr></thead><tbody>'
    for row in version_progression:
        delta = row.get('较上版提升')
        rate = row.get('较上版提升率(%)')
        delta_str = f'{delta:+.2f}' if delta is not None else '—'
        rate_str = f'{rate:+.2f}%' if rate is not None else '—'
        html += '<tr>'
        html += f'<td>{_escape_html(str(row.get("厂商", "")))}</td>'
        html += f'<td>{_escape_html(str(row.get("版本顺序", "")))}</td>'
        html += f'<td>{_escape_html(str(row.get("模型", "")))}</td>'
        html += f'<td>{_escape_html(str(row.get("平均分", "")))}</td>'
        html += f'<td>{delta_str}</td>'
        html += f'<td>{rate_str}</td>'
        html += '</tr>'
    html += '</tbody></table></div></div>'
    return html


def _build_thinking_comparison_section(data_cache: dict) -> str:
    """思考模型 vs 非思考模型：基于配置的 thinking_models 对比均分与差距"""
    tc = data_cache.get('thinking_comparison')
    if not tc or (tc.get('thinking_avg') is None and tc.get('non_thinking_avg') is None):
        return ''
    html = '<div class="section"><h2 class="section-title">🧠 思考模型 vs 非思考模型</h2>'
    html += '<p style="margin-bottom:16px;color:#555">基于配置的思考模型名单，对比两类模型在本次评测中的平均分差异。</p>'
    html += '<div class="stats-grid">'
    if tc.get('thinking_avg') is not None:
        n = tc.get('thinking_count', 0)
        html += f'<div class="stat-card"><div class="stat-value">{tc["thinking_avg"]:.2f}</div><div class="stat-label">思考模型均分 (n={n})</div></div>'
    if tc.get('non_thinking_avg') is not None:
        n = tc.get('non_thinking_count', 0)
        html += f'<div class="stat-card"><div class="stat-value">{tc["non_thinking_avg"]:.2f}</div><div class="stat-label">非思考模型均分 (n={n})</div></div>'
    if tc.get('delta') is not None:
        delta = tc['delta']
        css = 'score-high' if delta > 0 else ('score-mid' if delta == 0 else 'score-low')
        html += f'<div class="stat-card"><div class="stat-value">{delta:+.2f}</div><div class="stat-label">差值（思考－非思考）</div></div>'
    html += '</div>'
    if tc.get('thinking_models'):
        models_str = ', '.join(_escape_html(str(m)) for m in tc['thinking_models'][:10])
        if len(tc['thinking_models']) > 10:
            models_str += ' …'
        html += f'<p style="margin-top:16px;color:#555"><strong>思考模型</strong>: {models_str}</p>'
    html += '</div>'
    return html


def _build_dimension_stats_section(data_cache: dict) -> str:
    """维度得失分统计（约束类型↔D 维度对应）"""
    dimension_stats = data_cache.get('dimension_stats') or {}
    if not dimension_stats.get('has_data'):
        return ''
    pivot = dimension_stats.get('dimension_pivot_df', pd.DataFrame())
    if pivot is None or pivot.empty:
        return ''
    html = '<div class="section"><h2 class="section-title">📊 维度得失分统计</h2>'
    html += '<p style="margin-bottom:16px;color:#555">基于 rubrics_check 逐条 PASS/FAIL。L2约束→D维度：流程步骤→D2，格式输出→D4，边界范围/数量篇幅→D3。</p>'
    html += '<div style="overflow-x:auto"><table class="ranking-table"><thead><tr>'
    for c in pivot.columns:
        html += f'<th>{_escape_html(str(c))}</th>'
    html += '</tr></thead><tbody>'
    for _, row in pivot.iterrows():
        html += '<tr>'
        for c in pivot.columns:
            html += f'<td>{_escape_html(_safe_str(row.get(c, "")))}</td>'
        html += '</tr>'
    html += '</tbody></table></div></div>'
    return html


def _build_summary_section(data_cache: dict) -> str:
    tiers = data_cache.get('model_tiers') or []
    intent_insights = data_cache.get('intent_insights') or []
    constraint_insights = data_cache.get('constraint_insights') or []
    scenario_guide = data_cache.get('scenario_guide', pd.DataFrame())
    improvement_paths = data_cache.get('improvement_paths') or []
    source_gap = data_cache.get('source_gap_summary') or {}

    html = '<div class="section"><h2 class="section-title">📌 总结与建议</h2>'

    html += '<h3 class="subsection-title">结论与假设验证</h3>'
    html += '<p><strong>自建更难、公开区分度更低</strong>：'
    gap = source_gap.get('公开vs纯人工自建_均分差')
    vr = source_gap.get('纯人工自建vs公开_方差比')
    if gap is not None and not (isinstance(gap, float) and np.isnan(gap)):
        html += f'公开均分较纯人工自建高 {_escape_html(str(gap))} 分，印证自建题目难度更高；'
    if vr is not None and not (isinstance(vr, float) and np.isnan(vr)):
        html += f'自建方差比 {_escape_html(str(vr))}，区分度优于公开。'
    html += '</p><p><strong>维度易出问题</strong>：结合 D1–D5 各维度 ILA 与约束效能分析，可明确哪些维度更易失分，各档位模型在这些维度上差异显著。</p>'
    html += '<p><strong>档位差异</strong>：第一梯队与后续梯队在各维度通过率、完全通过率上拉开差距，中低档模型在流程完整性、边界遵守与格式规范上仍有提升空间。</p>'

    html += '<h3 class="subsection-title">训练与优化建议</h3><ul style="padding-left:24px;line-height:1.8">'
    if improvement_paths:
        for line in improvement_paths:
            html += f'<li>{_escape_html(line)}</li>'
    else:
        html += '<li>针对 ILA 与维度失分集中点，加强对应约束类型的指令微调与强化学习。</li>'
        html += '<li>对 D3/D4 等易失分维度，增加边界与格式类负样本与对比学习。</li>'
    html += '</ul>'

    html += '<h3 class="subsection-title">构建数据建议</h3><ul style="padding-left:24px;line-height:1.8">'
    data_synthesis_suggestions = data_cache.get('data_synthesis_suggestions') or []
    if data_synthesis_suggestions:
        for s in data_synthesis_suggestions:
            html += f'<li>{_escape_html(s)}</li>'
    html += '<li>增加自建题（尤其 H/R/HM 来源）占比，提升评测对真实业务难度的反映。</li>'
    html += '<li>在保证 MECE 的前提下，对易失分维度适当增加检查点与负例，提高区分度。</li>'
    html += '<li>平衡公开与自建题量，便于对比公开基准与自建难度差异。</li></ul>'

    if tiers:
        html += '<h3 class="subsection-title">模型能力梯队</h3><ul style="padding-left:24px;line-height:1.8">'
        tier_groups = {}
        for t in tiers:
            k = t.get('梯队', '')
            if k not in tier_groups:
                tier_groups[k] = []
            tier_groups[k].append(f"{t.get('模型', '')}（{t.get('均分', 0):.1f} 分）")
        for tier in ['第一梯队', '第二梯队', '第三梯队', '第四梯队']:
            if tier in tier_groups:
                html += f'<li><strong>{_escape_html(tier)}</strong>：{", ".join(tier_groups[tier])}</li>'
        html += '</ul>'

    if intent_insights:
        html += '<h3 class="subsection-title">意图级别深度剖析</h3><ul style="padding-left:24px;line-height:1.8">'
        for line in intent_insights[:15]:
            html += f'<li>{_escape_html(line)}</li>'
        html += '</ul>'

    if constraint_insights:
        html += '<h3 class="subsection-title">约束挑战深度解析</h3><ul style="padding-left:24px;line-height:1.8">'
        for line in constraint_insights:
            html += f'<li>{_escape_html(line)}</li>'
        html += '</ul>'

    if scenario_guide is not None and not scenario_guide.empty:
        html += '<h3 class="subsection-title">场景化模型选择指南</h3><div style="overflow-x:auto"><table class="ranking-table"><thead><tr>'
        for c in scenario_guide.columns:
            html += f'<th>{_escape_html(str(c))}</th>'
        html += '</tr></thead><tbody>'
        for _, row in scenario_guide.iterrows():
            html += '<tr>'
            for c in scenario_guide.columns:
                html += f'<td>{_escape_html(_safe_str(row.get(c, "")))}</td>'
            html += '</tr>'
        html += '</tbody></table></div>'

    if improvement_paths:
        html += '<h3 class="subsection-title">模型能力提升路径</h3><ul style="padding-left:24px;line-height:1.8">'
        for line in improvement_paths:
            html += f'<li>{_escape_html(line)}</li>'
        html += '</ul>'

    html += '</div>'
    return html


def generate_html_report(
    output_html: str,
    data: dict,
    data_cache: dict,
    case_analyses: List[dict],
    report_title: str = '多模型能力评测报告',
) -> str:
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    overall_ranking = data_cache.get('overall_ranking', pd.DataFrame())
    top20_df = data_cache.get('top20_questions', pd.DataFrame())
    item_analysis_df = data_cache.get('item_analysis_df', pd.DataFrame())

    replies = data.get('replies', pd.DataFrame())
    questions = data.get('questions', pd.DataFrame())
    model_count = replies['model'].nunique() if not replies.empty else 0
    task_count = _task_count(questions)
    eval_count = replies.shape[0] if not replies.empty else 0
    public_cnt, self_cnt = _source_counts(questions)
    vendor_count = _count_vendors(overall_ranking['模型'].tolist() if not overall_ranking.empty else [])

    html = _html_head(report_title)
    meta = f'评测模型: {model_count} 个 | 厂商约 {vendor_count} 家 | 评测题目: {task_count} 道 | 总评测次数: {eval_count}'
    if public_cnt or self_cnt:
        meta += f' | 公开: {public_cnt} 题 | 自建: {self_cnt} 题'
    html += f"""<body>
<div class="container">
<div class="header">
  <h1>🎯 {_escape_html(report_title)}</h1>
  <div class="meta">
    <p>生成时间: {timestamp}</p>
    <p>{meta}</p>
  </div>
</div>"""

    # EVAL_REPORT_FRAMEWORK_v2 七章结构（精简版：突出核心洞察，图表与叙事串联）
    html += _build_ch1_executive_summary(data, data_cache)
    html += _build_ch2_methodology_section()
    html += _build_ch3_capability_overview(overall_ranking, data, data_cache)
    html += _build_l1_capability_summaries_section(data_cache)  # L1 能力：精简为洞察+摘要
    html += _build_ch5_expert_section(data_cache)
    html += _build_ch6_section(case_analyses, data_cache, top20_df)
    html += _build_ch7_conclusions_section(data_cache)  # 结论中已含 full_pass、dimension 等补充指标

    html += '</div>'
    html += _html_scripts()
    html += '</body></html>'

    os.makedirs(os.path.dirname(os.path.abspath(output_html)), exist_ok=True)
    with open(output_html, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f'  ✓ HTML报告已生成: {output_html}')
    return output_html

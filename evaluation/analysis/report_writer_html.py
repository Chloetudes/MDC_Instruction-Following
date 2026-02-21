# -*- coding: utf-8 -*-
import json
import os
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .report_writer import (
    _get_model_icon, _escape_html, _nl2br, _safe_float, _safe_str
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
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);padding:20px;line-height:1.6}}
.container{{max-width:1400px;margin:0 auto;background:#fff;border-radius:20px;box-shadow:0 20px 60px rgba(0,0,0,.3);overflow:hidden}}
.header{{background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:#fff;padding:60px 40px;text-align:center}}
.header h1{{font-size:38px;margin-bottom:16px;font-weight:700}}
.header .meta{{font-size:15px;opacity:.9}}
.section{{padding:40px;border-bottom:1px solid #e0e0e0}}
.section:last-child{{border-bottom:none}}
.section-title{{font-size:28px;color:#2c3e50;margin-bottom:28px;padding-bottom:12px;border-bottom:3px solid #667eea;display:flex;align-items:center;gap:12px}}
.subsection-title{{font-size:20px;color:#34495e;margin:28px 0 16px;padding-left:14px;border-left:4px solid #3498db}}
.stats-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:18px;margin:24px 0}}
.stat-card{{background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:#fff;padding:28px;border-radius:14px;text-align:center;box-shadow:0 4px 15px rgba(102,126,234,.4);transition:transform .3s}}
.stat-card:hover{{transform:translateY(-4px)}}
.stat-value{{font-size:42px;font-weight:700;margin-bottom:8px}}
.stat-label{{font-size:14px;opacity:.9}}
.ranking-table{{width:100%;border-collapse:collapse;border-radius:12px;overflow:hidden;box-shadow:0 2px 10px rgba(0,0,0,.08)}}
.ranking-table th{{background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:#fff;padding:16px;text-align:left;font-weight:600}}
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
.case-card{{background:#fff;border-radius:14px;margin:24px 0;overflow:hidden;box-shadow:0 4px 18px rgba(0,0,0,.1);transition:box-shadow .3s}}
.case-card:hover{{box-shadow:0 8px 28px rgba(0,0,0,.15)}}
.case-header{{background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:#fff;padding:22px 28px;cursor:pointer;display:flex;justify-content:space-between;align-items:center}}
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
.reply-tab.active{{background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:#fff}}
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
.markdown-content pre{{background:#f8f9fa;padding:14px;border-radius:8px;overflow-x:auto;margin:14px 0;border-left:4px solid #667eea}}
.markdown-content table{{width:100%;border-collapse:collapse;margin:14px 0}}
.markdown-content table th{{background:#f8f9fa;padding:10px;border:1px solid #e0e0e0;font-weight:600}}
.markdown-content table td{{padding:10px;border:1px solid #e0e0e0}}
.failure-table{{width:100%;border-collapse:collapse;border-radius:10px;overflow:hidden;box-shadow:0 2px 6px rgba(0,0,0,.07);margin:14px 0}}
.failure-table th{{background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:#fff;padding:12px;text-align:left;font-size:13px}}
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


def _score_badge(score: float) -> str:
    css = 'score-high' if score >= 80 else ('score-mid' if score >= 60 else 'score-low')
    return f'<span class="score-badge {css}">{score:.1f}</span>'


def _build_overview_section(overall_ranking: pd.DataFrame, data: dict) -> str:
    replies = data.get('replies', pd.DataFrame())
    questions = data.get('questions', pd.DataFrame())
    model_count = replies['model'].nunique() if not replies.empty else 0
    task_count = questions.shape[0] if not questions.empty else 0
    eval_count = replies.shape[0] if not replies.empty else 0

    html = f"""<div class="section">
<h2 class="section-title">📊 整体概况</h2>
<div class="stats-grid">
  <div class="stat-card"><div class="stat-value">{model_count}</div><div class="stat-label">评测模型数</div></div>
  <div class="stat-card"><div class="stat-value">{task_count}</div><div class="stat-label">评测题目数</div></div>
  <div class="stat-card"><div class="stat-value">{eval_count}</div><div class="stat-label">总评测次数</div></div>
</div>"""

    if not overall_ranking.empty:
        html += '<h3 class="subsection-title">模型综合排名</h3><table class="ranking-table"><thead><tr><th>排名</th><th>模型</th><th>平均分</th><th>标准差</th><th>最高分</th><th>最低分</th><th>题目数</th></tr></thead><tbody>'
        for _, row in overall_ranking.iterrows():
            rank = int(row.get('排名', 0))
            rank_cls = f'rank-{rank}' if rank <= 3 else 'rank-other'
            model = _safe_str(row.get('模型', ''))
            icon = _get_model_icon(model)
            html += f"""<tr>
<td><span class="rank-badge {rank_cls}">#{rank}</span></td>
<td><div class="model-info"><img src="{icon}" class="model-icon" onerror="this.src='https://via.placeholder.com/36/667eea/fff?text=AI'" alt="{_escape_html(model)}"><span class="model-name">{_escape_html(model)}</span></div></td>
<td><strong>{_safe_float(row.get('平均分')):.2f}</strong></td>
<td>{_safe_float(row.get('标准差')):.2f}</td>
<td>{_safe_float(row.get('最高分')):.2f}</td>
<td>{_safe_float(row.get('最低分')):.2f}</td>
<td>{int(row.get('评测数量', 0))}</td>
</tr>"""
        html += '</tbody></table>'

    html += '</div>'
    return html


def _build_charts_section(overall_ranking: pd.DataFrame, data: dict) -> str:
    if overall_ranking.empty:
        return ''

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
        z_data = []
        for model in model_list:
            row_scores = []
            for cat in l1_cats:
                subset = replies_with_q[(replies_with_q['model'] == model) & (replies_with_q['L1'] == cat)]
                row_scores.append(round(_safe_float(subset['eval_score'].mean()), 2) if not subset.empty else 0)
            z_data.append(row_scores)
        heatmap_script = f"""
Plotly.newPlot('chart-l1-heatmap',[{{
  z:{json.dumps(z_data)},
  x:{json.dumps(l1_cats, ensure_ascii=False)},
  y:{json.dumps(model_list, ensure_ascii=False)},
  type:'heatmap',
  colorscale:[[0,'#d32f2f'],[0.4,'#ff6b6b'],[0.6,'#ffd93d'],[0.8,'#6bcf7f'],[1,'#27ae60']],
  showscale:true
}}],{{title:{{text:'各模型L1维度得分热力图',font:{{size:18,color:'#2c3e50'}}}},xaxis:{{title:'L1维度'}},yaxis:{{title:'模型'}},paper_bgcolor:'#f8f9fa',plot_bgcolor:'#f8f9fa'}},{{responsive:true}});"""

    difficulty_script = ''
    if not replies_with_q.empty and 'difficulty_level' in replies_with_q.columns:
        priority = {'S': 6, 'A': 5, 'B': 4, 'C': 3, 'D': 2, 'E': 1}
        diff_levels = sorted(replies_with_q['difficulty_level'].dropna().unique(),
                             key=lambda x: priority.get(x, 0), reverse=True)
        model_list = [_safe_str(m) for m in overall_ranking['模型'].tolist()]
        z_data = []
        for model in model_list:
            row_scores = []
            for level in diff_levels:
                subset = replies_with_q[(replies_with_q['model'] == model) & (replies_with_q['difficulty_level'] == level)]
                row_scores.append(round(_safe_float(subset['eval_score'].mean()), 2) if not subset.empty else 0)
            z_data.append(row_scores)
        difficulty_script = f"""
Plotly.newPlot('chart-difficulty-heatmap',[{{
  z:{json.dumps(z_data)},
  x:{json.dumps([str(l) for l in diff_levels])},
  y:{json.dumps(model_list, ensure_ascii=False)},
  type:'heatmap',
  colorscale:[[0,'#d32f2f'],[0.4,'#ff6b6b'],[0.6,'#ffd93d'],[0.8,'#6bcf7f'],[1,'#27ae60']],
  showscale:true
}}],{{title:{{text:'各模型难度等级得分热力图',font:{{size:18,color:'#2c3e50'}}}},xaxis:{{title:'难度等级'}},yaxis:{{title:'模型'}},paper_bgcolor:'#f8f9fa',plot_bgcolor:'#f8f9fa'}},{{responsive:true}});"""

    html = f"""<div class="section">
<h2 class="section-title">📈 数据可视化</h2>
<div class="chart-container"><div id="chart-model-bar"></div></div>
<div class="chart-container"><div id="chart-model-box"></div></div>
{'<div class="chart-container"><div id="chart-l1-heatmap"></div></div>' if heatmap_script else ''}
{'<div class="chart-container"><div id="chart-difficulty-heatmap"></div></div>' if difficulty_script else ''}
</div>
<script>
Plotly.newPlot('chart-model-bar',[{{
  x:{models_json},y:{scores_json},type:'bar',
  error_y:{{type:'data',array:{stds_json},visible:true}},
  marker:{{color:['#667eea','#764ba2','#f093fb','#4facfe','#43e97b','#fa709a','#fee140','#30cfd0','#a18cd1','#fbc2eb']}},
  text:{json.dumps([f'{s:.1f}' for s in scores])},textposition:'outside'
}}],{{title:{{text:'模型平均分对比',font:{{size:18,color:'#2c3e50'}}}},xaxis:{{title:'模型'}},yaxis:{{title:'平均分',range:[0,105]}},paper_bgcolor:'#f8f9fa',plot_bgcolor:'#f8f9fa'}},{{responsive:true}});
{heatmap_script}
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
        display_cols = ['排名', 'qid', 'L1', 'L2', '预设难度', '模型均分', '区分度_D值', '综合价值分', '最佳模型', '最差模型']
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
    difficulty = _safe_str(case.get('difficulty_level', ''))
    model_scores: dict = case.get('model_scores', {})
    model_replies: dict = case.get('model_replies', {})
    model_evaluations: dict = case.get('model_evaluations', {})
    expert_opinion: str = _safe_str(case.get('expert_opinion', ''))
    ai_summary: str = _safe_str(case.get('ai_summary', ''))
    ai_analysis: str = _safe_str(case.get('ai_analysis', ''))
    score_range = _safe_float(case.get('score_range', 0))

    sorted_scores = sorted(model_scores.items(), key=lambda x: x[1], reverse=True)
    scores_text = ' | '.join([f'<strong>{_escape_html(m)}</strong>: {_score_badge(s)}' for m, s in sorted_scores])

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
    <div class="markdown-content" data-md data-raw="{_escape_html(query)}"></div>
  </div>
  <div class="info-box summary">
    <h4>📊 各模型得分</h4>
    <p>{scores_text}</p>
  </div>"""

    if expert_opinion:
        html += f"""<div class="info-box expert">
    <h4>👨‍🔬 专家意见</h4>
    <div class="markdown-content" data-md data-raw="{_escape_html(expert_opinion)}"></div>
  </div>"""

    if ai_summary:
        html += f"""<div class="info-box summary">
    <h4>💡 AI综合评估</h4>
    <div class="markdown-content" data-md data-raw="{_escape_html(ai_summary)}"></div>
  </div>"""

    if ai_analysis:
        html += f"""<div class="analysis-block">
    <h4 style="margin-bottom:12px;color:#2c3e50">🔍 失分点分析</h4>
    <div class="markdown-content" data-md data-raw="{_escape_html(ai_analysis)}"></div>
  </div>"""

    if model_scores:
        html += f'<h4 style="margin:24px 0 12px;color:#2c3e50">各模型完整回复与评估</h4>'
        html += f'<div class="reply-tabs" id="tabs-{case_id}">'
        for idx, (model, _) in enumerate(sorted_scores):
            active = 'active' if idx == 0 else ''
            icon = _get_model_icon(model)
            html += f'<button class="reply-tab {active}" onclick="switchTab(\'{case_id}\',\'{_escape_html(model)}\')">'
            html += f'<img src="{icon}" onerror="this.src=\'https://via.placeholder.com/22/667eea/fff?text=AI\'" alt="">{_escape_html(model)}</button>'
        html += '</div>'

        for idx, (model, score) in enumerate(sorted_scores):
            active = 'active' if idx == 0 else ''
            reply = _safe_str(model_replies.get(model, ''))
            evaluation = _safe_str(model_evaluations.get(model, ''))
            html += f'<div class="reply-content {active}" id="reply-{case_id}-{_escape_html(model)}">'
            html += f'<h5 style="margin-bottom:10px">📝 模型回复（得分: {score:.1f}）</h5>'
            html += f'<div class="reply-text">{_nl2br(reply)}</div>'
            if evaluation:
                html += f'<h5 style="margin:18px 0 10px">📋 评估详情</h5>'
                html += f'<div class="evaluation-text">{_nl2br(evaluation)}</div>'
            html += '</div>'

    html += '</div></div></div>'
    return html


def _build_consistency_section(data_cache: dict) -> str:
    rater_vs_others = data_cache.get('rater_vs_others', pd.DataFrame())
    model_ranking_summary = data_cache.get('model_ranking_summary', pd.DataFrame())

    if rater_vs_others.empty and model_ranking_summary.empty:
        return ''

    html = '<div class="section"><h2 class="section-title">📐 一致性分析摘要</h2>'

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
    task_count = questions.shape[0] if not questions.empty else 0
    eval_count = replies.shape[0] if not replies.empty else 0

    html = _html_head(report_title)
    html += f"""<body>
<div class="container">
<div class="header">
  <h1>🎯 {_escape_html(report_title)}</h1>
  <div class="meta">
    <p>生成时间: {timestamp}</p>
    <p>评测模型: {model_count} 个 | 评测题目: {task_count} 道 | 总评测次数: {eval_count}</p>
  </div>
</div>"""

    html += _build_overview_section(overall_ranking, data)
    html += _build_charts_section(overall_ranking, data)
    html += _build_consistency_section(data_cache)
    html += _build_valuable_questions_section(top20_df, item_analysis_df, case_analyses)

    html += '</div>'
    html += _html_scripts()
    html += '</body></html>'

    os.makedirs(os.path.dirname(os.path.abspath(output_html)), exist_ok=True)
    with open(output_html, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f'  ✓ HTML报告已生成: {output_html}')
    return output_html

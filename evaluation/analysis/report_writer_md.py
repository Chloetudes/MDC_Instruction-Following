# -*- coding: utf-8 -*-
import os
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .report_writer import _safe_float, _safe_str


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
    model_ranking_summary = data_cache.get('model_ranking_summary', pd.DataFrame())
    corrected_ranking = data_cache.get('corrected_ranking', pd.DataFrame())

    replies = data.get('replies', pd.DataFrame())
    questions = data.get('questions', pd.DataFrame())
    model_count = replies['model'].nunique() if not replies.empty else 0
    task_count = questions.shape[0] if not questions.empty else 0
    eval_count = replies.shape[0] if not replies.empty else 0

    lines = []
    lines.append(f'# {report_title}\n')
    lines.append(f'> 生成时间: {timestamp}  \n')
    lines.append(f'> 评测模型: **{model_count}** 个 | 评测题目: **{task_count}** 道 | 总评测次数: **{eval_count}**\n')
    lines.append('\n---\n')

    lines.append(_section('目录'))
    lines.append('1. [整体概况与模型排名](#整体概况)\n')
    lines.append('2. [专家纠偏排名](#专家纠偏排名)\n')
    lines.append('3. [一致性分析](#一致性分析)\n')
    lines.append('4. [价值题目TOP20](#价值题目)\n')
    lines.append('5. [典型题目深度分析](#典型题目分析)\n')
    lines.append('6. [题目质量分析](#题目质量分析)\n')
    lines.append('\n---\n')

    lines.append(_section('整体概况'))
    if not overall_ranking.empty:
        display_cols = [c for c in ['排名', '模型', '评测数量', '平均分', '标准差', '最高分', '最低分', '中位数'] if c in overall_ranking.columns]
        lines.append(_md_table(overall_ranking[display_cols]))
    else:
        lines.append('_（无排名数据）_\n')
    lines.append('\n')

    lines.append(_section('专家纠偏排名'))
    if not corrected_ranking.empty:
        lines.append(_md_table(corrected_ranking))
    else:
        lines.append('_（无专家评分数据，跳过）_\n')
    lines.append('\n')

    lines.append(_section('一致性分析'))
    if not rater_vs_others.empty:
        lines.append(_section('标注员组内一致性', 3))
        lines.append(_md_table(rater_vs_others))
    if not model_ranking_summary.empty:
        lines.append(_section('模型排名一致性（与专家对比）', 3))
        lines.append(_md_table(model_ranking_summary))
    if rater_vs_others.empty and model_ranking_summary.empty:
        lines.append('_（无人工标注数据，跳过）_\n')
    lines.append('\n')

    lines.append(_section('价值题目'))
    if not top20_df.empty:
        display_cols = [c for c in ['排名', 'qid', 'L1', 'L2', '预设难度', '模型均分', '区分度_D值', '综合价值分', '最佳模型', '最差模型'] if c in top20_df.columns]
        lines.append(_md_table(top20_df[display_cols]))
    else:
        lines.append('_（无价值题目数据）_\n')
    lines.append('\n')

    lines.append(_section('典型题目分析'))
    if case_analyses:
        for idx, case in enumerate(case_analyses, 1):
            qid = _safe_str(case.get('qid', ''))
            query = _safe_str(case.get('query', ''))
            l1 = _safe_str(case.get('L1', ''))
            l3 = _safe_str(case.get('L3', ''))
            difficulty = _safe_str(case.get('difficulty_level', ''))
            model_scores: dict = case.get('model_scores', {})
            expert_opinion = _safe_str(case.get('expert_opinion', ''))
            ai_summary = _safe_str(case.get('ai_summary', ''))
            ai_analysis = _safe_str(case.get('ai_analysis', ''))
            score_range = _safe_float(case.get('score_range', 0))

            lines.append(_section(f'案例 {idx}: Q{qid}', 3))
            lines.append(f'- **L1**: {l1} | **L3**: {l3} | **难度**: {difficulty} | **分数范围**: {score_range:.1f}\n')

            if query:
                lines.append(_section('题目内容', 4))
                lines.append(f'> {query[:300]}{"..." if len(query) > 300 else ""}\n\n')

            if model_scores:
                lines.append(_section('各模型得分', 4))
                sorted_scores = sorted(model_scores.items(), key=lambda x: x[1], reverse=True)
                for rank, (model, score) in enumerate(sorted_scores, 1):
                    lines.append(f'{rank}. **{model}**: {score:.1f}\n')
                lines.append('\n')

            if expert_opinion:
                lines.append(_section('专家意见', 4))
                lines.append(f'{expert_opinion}\n\n')

            if ai_summary:
                lines.append(_section('AI综合评估', 4))
                lines.append(f'{ai_summary}\n\n')

            if ai_analysis:
                lines.append(_section('失分点分析', 4))
                lines.append(f'{ai_analysis}\n\n')

            lines.append('---\n\n')
    else:
        lines.append('_（无典型案例分析）_\n')

    lines.append(_section('题目质量分析'))
    if not item_analysis_df.empty:
        display_cols = [c for c in ['排名', 'qid', 'L1', 'L3', '难度等级', '平均质量分', '分数范围', '区分度指数_D', '综合质量分', '题目质量等级'] if c in item_analysis_df.columns]
        lines.append(_md_table(item_analysis_df[display_cols], max_rows=30))
    else:
        lines.append('_（无题目质量数据）_\n')

    content = '\n'.join(lines)
    os.makedirs(os.path.dirname(os.path.abspath(output_md)), exist_ok=True)
    with open(output_md, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f'  ✓ Markdown报告已生成: {output_md}')
    return output_md

# -*- coding: utf-8 -*-
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from tqdm import tqdm

from config import get_provider
from clients.openai_client import OAIClient
from ..core.utils import safe_str, safe_save_excel
from ..managers.sysprompt import SyspromptManager
from ..analysis.data_loader import load_and_preprocess
from ..analysis.ranking import ModelRankingAnalyzer, ExpertCorrectedRankingAnalyzer
from ..analysis.consistency import HumanExpertConsistencyAnalyzer, ModelReliabilityAnalyzer
from ..analysis.valuable_questions import ValuableQuestionAnalyzer
from ..analysis.item_analysis import ItemAnalyzer
from ..analysis.report_writer_html import generate_html_report
from ..analysis.report_writer_md import generate_markdown_report


DEFAULT_REPORT_SYSPROMPT = """你是一位专业的AI模型评测分析师。
请基于提供的题目信息、各模型得分和评估详情，撰写简洁专业的分析报告。

分析要求：
1. 综合评估（100字以内）：概括各模型在该题目上的整体表现差异
2. 失分点分析：逐一分析各模型的主要失分原因，重点关注得分差异大的模型
3. 如有专家意见，优先参考专家意见进行分析
4. 语言简洁专业，避免重复

输出格式（严格按照以下格式）：
【综合评估】
（100字以内的整体评估）

【失分点分析】
（各模型失分原因分析）"""


def _build_case_analysis_prompt(
    qid: str,
    query: str,
    evaluation_criteria: str,
    model_scores: Dict[str, float],
    model_evaluations: Dict[str, str],
    expert_opinion: str,
    sysprompt: str,
) -> Tuple[str, str]:
    sys_content = sysprompt if sysprompt else DEFAULT_REPORT_SYSPROMPT

    sorted_scores = sorted(model_scores.items(), key=lambda x: x[1], reverse=True)
    scores_text = '\n'.join([f'- {model}: {score:.1f}分' for model, score in sorted_scores])

    eval_details = []
    for model, score in sorted_scores[:5]:
        eval_text = model_evaluations.get(model, '')
        if eval_text:
            eval_details.append(f'### {model}（{score:.1f}分）\n{eval_text[:500]}')
    eval_text_combined = '\n\n'.join(eval_details)

    user_content = f"""题目ID: {qid}

【题目内容】
{query[:800]}

【评分标准】
{evaluation_criteria[:600] if evaluation_criteria else '（无）'}

【各模型得分】
{scores_text}

【评估详情（节选）】
{eval_text_combined}
"""

    if expert_opinion:
        user_content += f'\n【专家意见】\n{expert_opinion}\n'

    return sys_content, user_content


def _parse_analysis_response(response_text: str) -> Tuple[str, str]:
    summary = ''
    analysis = ''

    summary_match = re.search(r'【综合评估】\s*(.*?)(?=【|$)', response_text, re.DOTALL)
    if summary_match:
        summary = summary_match.group(1).strip()

    analysis_match = re.search(r'【失分点分析】\s*(.*?)(?=【|$)', response_text, re.DOTALL)
    if analysis_match:
        analysis = analysis_match.group(1).strip()

    if not summary and not analysis:
        summary = response_text[:200].strip()
        analysis = response_text[200:].strip()

    return summary, analysis


def _load_replies_for_report(replies_excel: str, eval_batch_id: str = None) -> pd.DataFrame:
    xls = pd.ExcelFile(replies_excel)
    target_sheet = next(
        (s for s in ('Sheet1', 'replies') if s in xls.sheet_names),
        xls.sheet_names[0]
    )
    df = pd.read_excel(replies_excel, sheet_name=target_sheet)

    eval_cols = [c for c in df.columns if c.startswith('eval_') and not c.endswith('_raw')]
    if eval_batch_id:
        candidate = f'eval_{eval_batch_id}'
        if candidate in df.columns:
            df['eval_score'] = pd.to_numeric(df[candidate], errors='coerce')
            return df
    if eval_cols:
        df['eval_score'] = pd.to_numeric(df[eval_cols[-1]], errors='coerce')
    return df


def generate_evaluation_report(
    questions_excel: str,
    replies_excel: str,
    output_dir: str,
    provider: str,
    model: str,
    sysprompt_manager: SyspromptManager,
    human_excel: str = None,
    eval_batch_id: str = None,
    top_n_cases: int = 20,
    max_workers: int = 3,
    timeout: int = 120,
    temperature: float = 0.3,
    report_title: str = '多模型能力评测报告',
) -> Dict[str, str]:
    print('\n' + '=' * 60)
    print('报告生成阶段 - 价值题目深度分析 + 可视化报告')
    print('=' * 60)

    data = load_and_preprocess(
        questions_excel=questions_excel,
        replies_excel=replies_excel,
        human_excel=human_excel,
        eval_batch_id=eval_batch_id,
    )

    print('\n▶ 构建统计缓存...')
    ranking_analyzer = ModelRankingAnalyzer(data)
    expert_corrected_analyzer = ExpertCorrectedRankingAnalyzer(data)
    human_expert_analyzer = HumanExpertConsistencyAnalyzer(data)
    model_reliability_analyzer = ModelReliabilityAnalyzer(data)
    valuable_analyzer = ValuableQuestionAnalyzer(data)
    item_analyzer = ItemAnalyzer(data)

    rankings = ranking_analyzer.generate_all_rankings()
    corrected_ranking = expert_corrected_analyzer.analyze_corrected_ranking()
    rater_vs_others = human_expert_analyzer.analyze_rater_vs_others()
    model_ranking_summary, _ = model_reliability_analyzer.analyze_model_ranking_consistency()
    top20_df = valuable_analyzer.find_top20_valuable_questions()
    item_analysis_df = item_analyzer.analyze_all_items()

    data_cache = {
        'overall_ranking': rankings.get('overall', pd.DataFrame()),
        'corrected_ranking': corrected_ranking,
        'rater_vs_others': rater_vs_others,
        'model_ranking_summary': model_ranking_summary,
        'top20_questions': top20_df,
        'item_analysis_df': item_analysis_df,
    }

    print(f'\n▶ 筛选价值题目进行深度分析（TOP{top_n_cases}）...')
    candidate_qids = []
    if not top20_df.empty and 'qid' in top20_df.columns:
        candidate_qids = [str(q) for q in top20_df['qid'].tolist()[:top_n_cases]]

    replies_df = data['replies']
    replies_with_q = data['replies_with_question']
    questions_df = data['questions']
    expert_scores_df = data.get('expert_scores', pd.DataFrame())

    report_sysprompt = sysprompt_manager.get('report_analysis', DEFAULT_REPORT_SYSPROMPT)

    provider_obj = get_provider(provider)
    client = OAIClient(
        base_url=provider_obj.base_url,
        api_key=provider_obj.api_key,
        protocol=provider_obj.protocol,
        auth_header=provider_obj.auth_header,
        auth_prefix=provider_obj.auth_prefix,
        extra_headers=provider_obj.extra_headers,
        timeout=timeout,
    )

    print(f'\n▶ AI分析 {len(candidate_qids)} 道价值题目...')
    case_analyses = []

    def analyze_single_case(qid: str) -> Optional[dict]:
        q_replies = replies_with_q[replies_with_q['qid'] == qid]
        if q_replies.empty:
            return None

        first_row = q_replies.iloc[0]
        query = safe_str(first_row.get('query', ''))
        evaluation_criteria = safe_str(first_row.get('evaluation_criteria', ''))
        l1 = safe_str(first_row.get('L1', ''))
        l2 = safe_str(first_row.get('L2', ''))
        l3 = safe_str(first_row.get('L3', ''))
        difficulty = safe_str(first_row.get('difficulty_level', ''))
        score_range = float(q_replies['eval_score'].max() - q_replies['eval_score'].min()) if not q_replies['eval_score'].dropna().empty else 0

        model_scores = dict(q_replies.groupby('model')['eval_score'].mean().dropna())

        eval_col_candidates = [c for c in replies_df.columns if c.startswith('eval_') and c.endswith('_raw')]
        model_evaluations = {}
        for model in model_scores:
            model_row = replies_df[(replies_df['qid'] == qid) & (replies_df['model'] == model)]
            if not model_row.empty:
                for raw_col in eval_col_candidates:
                    raw_val = safe_str(model_row.iloc[0].get(raw_col, ''))
                    if raw_val:
                        model_evaluations[model] = raw_val
                        break

        model_replies = {}
        for model in model_scores:
            model_row = replies_df[(replies_df['qid'] == qid) & (replies_df['model'] == model)]
            if not model_row.empty and 'reply' in replies_df.columns:
                model_replies[model] = safe_str(model_row.iloc[0].get('reply', ''))

        expert_opinion = ''
        if not expert_scores_df.empty:
            expert_rows = expert_scores_df[expert_scores_df['qid'] == qid]
            if not expert_rows.empty:
                opinions = expert_rows['reason'].dropna().tolist()
                expert_opinion = ' | '.join([safe_str(o) for o in opinions if o])

        sys_content, user_content = _build_case_analysis_prompt(
            qid=qid,
            query=query,
            evaluation_criteria=evaluation_criteria,
            model_scores=model_scores,
            model_evaluations=model_evaluations,
            expert_opinion=expert_opinion,
            sysprompt=report_sysprompt,
        )

        try:
            messages = [
                {'role': 'system', 'content': sys_content},
                {'role': 'user', 'content': user_content},
            ]
            response = client.chat(
                messages=messages,
                model=model,
                temperature=temperature,
                timeout=timeout,
            )
            response_text = safe_str(response)
        except Exception as exc:
            print(f'    ⚠️ Q{qid} 分析失败: {exc}')
            response_text = ''

        ai_summary, ai_analysis = _parse_analysis_response(response_text)

        return {
            'qid': qid,
            'query': query,
            'L1': l1,
            'L2': l2,
            'L3': l3,
            'difficulty_level': difficulty,
            'score_range': score_range,
            'model_scores': model_scores,
            'model_replies': model_replies,
            'model_evaluations': model_evaluations,
            'expert_opinion': expert_opinion,
            'ai_summary': ai_summary,
            'ai_analysis': ai_analysis,
        }

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(analyze_single_case, qid): qid for qid in candidate_qids}
        for future in tqdm(as_completed(futures), total=len(futures), desc='分析进度'):
            result = future.result()
            if result:
                case_analyses.append(result)

    case_analyses.sort(key=lambda x: x.get('score_range', 0), reverse=True)

    print(f'\n▶ 生成报告文件...')
    os.makedirs(output_dir, exist_ok=True)
    from datetime import datetime
    timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')

    output_html = os.path.join(output_dir, f'evaluation_report_{timestamp_str}.html')
    output_md = os.path.join(output_dir, f'evaluation_report_{timestamp_str}.md')

    generate_html_report(
        output_html=output_html,
        data=data,
        data_cache=data_cache,
        case_analyses=case_analyses,
        report_title=report_title,
    )

    generate_markdown_report(
        output_md=output_md,
        data=data,
        data_cache=data_cache,
        case_analyses=case_analyses,
        report_title=report_title,
    )

    print(f'\n✓ 报告生成完成！')
    print(f'  HTML: {output_html}')
    print(f'  Markdown: {output_md}')
    print('=' * 60)

    return {'html': output_html, 'markdown': output_md}

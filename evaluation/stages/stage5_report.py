# -*- coding: utf-8 -*-
import os
import pickle
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
import pandas as pd
from tqdm import tqdm

from config import get_provider
from clients.openai_client import OAIClient
from ..core.utils import safe_str, safe_save_excel
from ..managers.sysprompt import SyspromptManager
from ..analysis.data_loader import load_and_preprocess
from ..analysis.ranking import ModelRankingAnalyzer, ExpertCorrectedRankingAnalyzer
from ..analysis.consistency import HumanExpertConsistencyAnalyzer, ModelReliabilityAnalyzer, ExpertHumanMachineConsistencyAnalyzer
from ..analysis.valuable_questions import ValuableQuestionAnalyzer
from ..analysis.item_analysis import ItemAnalyzer
from ..analysis.report_writer_html import generate_html_report
from ..analysis.report_writer_md import generate_markdown_report
from ..analysis.rubric_dimension_analysis import analyze_rubric_dimensions
from ..analysis.framework_sync import sync_framework_with_report_stats
from ..analysis.report import (
    _compute_l1_high_distinction_stats,
    _compute_l1_loss_profiles,
    _compute_model_weakness_summary_light,
    _compute_model_l1_loss_profiles,
    _compute_dimension_fail_rate_tables,
    _compute_d5_fail_by_l1,
    _build_data_synthesis_suggestions,
    _compute_panorama_ranking,
)
from ..analysis.chart_selection import profile_data, select_charts_for_report


CACHE_DIR = '.report_cache'

CHART_INSIGHT_SYSPROMPT = """你是一位专业的评测报告撰写人。请根据图表标题与类型，用约100字总结该图表反映的数据内容与主要结论，帮助读者快速理解图表含义。"""


def _build_chart_insights(
    client: Any,
    model: str,
    data: dict,
    data_cache: dict,
    temperature: float = 0.3,
    timeout: int = 120,
) -> Dict[str, str]:
    """为每张报告图表调用 LLM 生成约 100 字解读，返回 {chart_id: 解读文本}。"""
    try:
        profile = profile_data(data, data_cache)
        configs = select_charts_for_report(data, data_cache, profile)
    except Exception:
        return {}
    insights = {}
    for config in configs:
        user_content = f"""图表标题：{config.title}
图表类型：{config.chart_type}

请用约100字总结该图表反映的内容与结论。"""
        try:
            messages = [
                {'role': 'system', 'content': CHART_INSIGHT_SYSPROMPT},
                {'role': 'user', 'content': user_content},
            ]
            resp = client.chat(messages=messages, model=model, temperature=temperature, timeout=timeout)
            insights[config.chart_id] = safe_str(resp).strip() or ''
        except Exception:
            insights[config.chart_id] = ''
        time.sleep(0.2)
    return insights

L1_CAPABILITY_SYSPROMPT = """你是一位专业的AI模型评测分析师。
请基于以下某L1意图类型的统计和排名数据，用2-3句话概括各模型在该意图类型上的整体能力表现。
要求：客观、数据驱动，突出最佳/最差模型及差距，提及高区分度题目数量以支撑结论。"""

FOCUS_LOSS_SUMMARY_SYSPROMPT = """你是一位AI评测报告撰写人。请根据「第一名」与「对比模型」在各L1意图下的维度通过率、主要失分点及典型失分原因（评语），用约200字总结：对比模型相对第一名的失分差异与典型错误表现，并给出可执行的数据/训练建议。"""


def _build_focus_loss_summary_llm(
    client: Any,
    model: str,
    model_l1_df: pd.DataFrame,
    rank1_model: str,
    focus_model: str,
    temperature: float = 0.3,
    timeout: int = 120,
) -> str:
    """基于模型×L1 失分表，用 LLM 总结「对比模型相对第一名的失分差异与典型错误」。"""
    if model_l1_df.empty or not rank1_model or not focus_model or rank1_model == focus_model:
        return ''
    sub = model_l1_df[model_l1_df['model'].astype(str).str.strip().isin([rank1_model, focus_model])]
    if sub.empty:
        return ''
    parts = []
    for _, row in sub.iterrows():
        m = row.get('model', '')
        l1 = row.get('L1', '')
        main = row.get('主要失分点', '')
        reason = row.get('典型失分原因(评语)', '')
        parts.append(f"【{m}】L1={l1} 主要失分点={main}；典型原因={reason[:150]}…" if reason and len(str(reason)) > 150 else f"【{m}】L1={l1} 主要失分点={main}；典型原因={reason}")
    user_content = f"""第一名模型：{rank1_model}
对比模型：{focus_model}

各 L1 下的失分数据：
{chr(10).join(parts)}

请用约200字总结：对比模型相对第一名的失分差异与典型错误表现，并给出一条可执行的数据或训练建议。"""
    try:
        messages = [
            {'role': 'system', 'content': FOCUS_LOSS_SUMMARY_SYSPROMPT},
            {'role': 'user', 'content': user_content},
        ]
        resp = client.chat(messages=messages, model=model, temperature=temperature, timeout=timeout)
        return safe_str(resp).strip() or ''
    except Exception:
        return ''


CACHE_FILENAME = 'report_cache.pkl'


def _report_cache_path(output_dir: str) -> str:
    return os.path.join(output_dir, CACHE_DIR, CACHE_FILENAME)


def _pick_source_col(df: pd.DataFrame) -> str:
    """在常见列名中选择 source 列。"""
    if df is None or df.empty:
        return ''
    for c in ('source', '数据来源', 'Source', 'SOURCE'):
        if c in df.columns:
            return c
    return ''


def _filter_data_by_source(
    data: dict,
    include_sources: list = None,
    exclude_sources: list = None,
) -> dict:
    """
    仅做“统计口径”的来源筛选：基于题目表（优先）或 replies_with_question 的 source 列按 qid 过滤。
    - include_sources: 仅保留这些来源
    - exclude_sources: 排除这些来源
    若两者都为空，则返回原 data（不筛选）。
    """
    inc = set(str(x).strip() for x in (include_sources or []) if x is not None and str(x).strip())
    exc = set(str(x).strip() for x in (exclude_sources or []) if x is not None and str(x).strip())
    if not inc and not exc:
        return data

    rwq = data.get('replies_with_question', pd.DataFrame())
    qdf = data.get('questions', pd.DataFrame())
    if (qdf is None or qdf.empty) and (rwq is None or rwq.empty):
        return data

    src_col = _pick_source_col(qdf) or _pick_source_col(rwq)
    if not src_col:
        return data

    def _norm_series(s: pd.Series) -> pd.Series:
        return s.astype(str).str.strip()

    qids = set()
    if qdf is not None and not qdf.empty and src_col in qdf.columns and 'qid' in qdf.columns:
        s = _norm_series(qdf[src_col])
        keep = pd.Series([True] * len(qdf), index=qdf.index)
        if inc:
            keep = keep & s.isin(inc)
        if exc:
            keep = keep & (~s.isin(exc))
        qids = set(qdf.loc[keep, 'qid'].astype(str).str.strip().tolist())
    elif rwq is not None and not rwq.empty and src_col in rwq.columns and 'qid' in rwq.columns:
        s = _norm_series(rwq[src_col])
        keep = pd.Series([True] * len(rwq), index=rwq.index)
        if inc:
            keep = keep & s.isin(inc)
        if exc:
            keep = keep & (~s.isin(exc))
        qids = set(rwq.loc[keep, 'qid'].astype(str).str.strip().tolist())

    if not qids:
        return data

    out = dict(data)
    for k in ('questions', 'replies', 'replies_with_question', 'expert_scores', 'rater_scores'):
        df = out.get(k)
        if df is not None and not df.empty and 'qid' in df.columns:
            out[k] = df[df['qid'].astype(str).str.strip().isin(qids)].copy()
    return out


def _filter_analysis_subset(data: dict, exclude_sources: list = None) -> dict:
    """
    分析时排除指定来源的题目（默认排除 R）。
    当前仅用于「典型案例/做错题」等案例分析的候选集筛选，不影响综合榜单/全景统计。
    """
    exclude_sources = exclude_sources or ['R']
    ex = set(str(x).strip().upper() for x in exclude_sources if x is not None and str(x).strip())

    rwq = data.get('replies_with_question', pd.DataFrame())
    qdf = data.get('questions', pd.DataFrame())
    if rwq is None or rwq.empty:
        return data
    src_col = _pick_source_col(rwq) or _pick_source_col(qdf)
    if not src_col:
        return data

    def _norm_series(s: pd.Series) -> pd.Series:
        return s.astype(str).str.strip().str.upper()

    qids = None
    if qdf is not None and not qdf.empty and src_col in qdf.columns and 'qid' in qdf.columns:
        q_src = _norm_series(qdf[src_col])
        qids = set(qdf.loc[~q_src.isin(ex), 'qid'].astype(str).str.strip().tolist())
    else:
        r_src = _norm_series(rwq[src_col])
        qids = set(rwq.loc[~r_src.isin(ex), 'qid'].astype(str).str.strip().tolist())

    if not qids:
        return data

    out = dict(data)
    if out.get('questions') is not None and not out['questions'].empty and 'qid' in out['questions'].columns:
        out['questions'] = out['questions'][out['questions']['qid'].astype(str).str.strip().isin(qids)].copy()
    if out.get('replies') is not None and not out['replies'].empty and 'qid' in out['replies'].columns:
        out['replies'] = out['replies'][out['replies']['qid'].astype(str).str.strip().isin(qids)].copy()
    if out.get('replies_with_question') is not None and not out['replies_with_question'].empty and 'qid' in out['replies_with_question'].columns:
        out['replies_with_question'] = out['replies_with_question'][out['replies_with_question']['qid'].astype(str).str.strip().isin(qids)].copy()
    if out.get('expert_scores') is not None and not out['expert_scores'].empty and 'qid' in out['expert_scores'].columns:
        out['expert_scores'] = out['expert_scores'][out['expert_scores']['qid'].astype(str).str.strip().isin(qids)].copy()
    if out.get('rater_scores') is not None and not out['rater_scores'].empty and 'qid' in out['rater_scores'].columns:
        out['rater_scores'] = out['rater_scores'][out['rater_scores']['qid'].astype(str).str.strip().isin(qids)].copy()
    return out


def _load_report_cache(cache_path: str, questions_excel: str, replies_excel: str,
                       eval_batch_id: str, top_n_cases: int, model_list,
                       cache_max_age_hours: Optional[float], report_cache_key: dict = None) -> Optional[dict]:
    """若缓存有效则加载，否则返回 None。"""
    if not os.path.exists(cache_path):
        return None
    try:
        q_path = os.path.abspath(questions_excel)
        r_path = os.path.abspath(replies_excel)
        q_mtime = os.path.getmtime(q_path) if os.path.exists(q_path) else 0
        r_mtime = os.path.getmtime(r_path) if os.path.exists(r_path) else 0
        with open(cache_path, 'rb') as f:
            cached = pickle.load(f)
        meta = cached.get('meta', {})
        m_q = os.path.abspath(meta.get('questions_file', ''))
        m_r = os.path.abspath(meta.get('replies_file', ''))
        if m_q != q_path or m_r != r_path:
            return None
        if meta.get('eval_batch_id') != eval_batch_id or meta.get('top_n_cases') != top_n_cases:
            return None
        if str(meta.get('model_list')) != str(model_list):
            return None
        if str(meta.get('report_cache_key')) != str(report_cache_key):
            return None
        if meta.get('q_mtime') != q_mtime or meta.get('r_mtime') != r_mtime:
            return None
        if cache_max_age_hours is not None and cache_max_age_hours > 0:
            import datetime
            cached_at = meta.get('cached_at')
            if cached_at:
                age = (datetime.datetime.now() - cached_at).total_seconds() / 3600
                if age > cache_max_age_hours:
                    return None
        return cached
    except Exception:
        return None


def _save_report_cache(cache_path: str, data: dict, data_cache: dict, case_analyses: list,
                       questions_excel: str, replies_excel: str,
                       eval_batch_id: str, top_n_cases: int, model_list, report_cache_key: dict = None):
    """保存报告分析缓存。"""
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    q_path = os.path.abspath(questions_excel)
    r_path = os.path.abspath(replies_excel)
    q_mtime = os.path.getmtime(q_path) if os.path.exists(q_path) else 0
    r_mtime = os.path.getmtime(r_path) if os.path.exists(r_path) else 0
    import datetime
    meta = {
        'questions_file': q_path, 'replies_file': r_path,
        'eval_batch_id': eval_batch_id, 'top_n_cases': top_n_cases, 'model_list': model_list,
        'q_mtime': q_mtime, 'r_mtime': r_mtime,
        'cached_at': datetime.datetime.now(),
        'report_cache_key': report_cache_key,
    }
    try:
        with open(cache_path, 'wb') as f:
            pickle.dump({'data': data, 'data_cache': data_cache, 'case_analyses': case_analyses, 'meta': meta}, f)
    except Exception:
        pass


DEFAULT_REPORT_SYSPROMPT = """你是一位专业的AI模型评测分析师。
请基于提供的题目信息、各模型得分和评估详情，撰写简洁专业的分析报告。

分析要求：
1. 综合评估（100字以内）：概括各模型在该题目上的整体表现差异
2. 模型分档：根据得分将模型分为第一梯队、第二梯队、第三梯队，每个梯队用1-2句话总结该梯队的整体表现特点，不要照搬专家意见原文
3. 如有专家意见，仅作分析参考，请勿照搬到输出中
4. 语言简洁专业，避免重复

输出格式（严格按照以下格式）：
【综合评估】
（100字以内的整体评估）

【模型分档】
- 第一梯队：...（该梯队表现特点总结）. 模型：A, B, C（按得分从高到低）
- 第二梯队：...
- 第三梯队：...（共三档，按分数从高到低划分）

【失分点分析】
（各梯队或代表性模型的失分原因，简要）

请完整输出以上三个部分，不要中途截断。"""


def _compute_tier_models(
    model_scores: Dict[str, float],
    expert_scores_df: pd.DataFrame,
    qid: str,
    num_tiers: int = 3,
) -> List[Tuple[str, List[str]]]:
    """按分数排序后，依模型间分差（相邻分数差）在分差最大处切分为第一/第二/第三梯队，不设固定分数线。优先使用专家打分。"""
    if not model_scores:
        return []
    # 优先专家分：本题有专家打分的模型用专家分均值
    scores_for_tier = dict(model_scores)
    if expert_scores_df is not None and not expert_scores_df.empty:
        expert_rows = expert_scores_df[expert_scores_df['qid'].astype(str) == str(qid)]
        if not expert_rows.empty:
            agg = expert_rows.groupby('model', as_index=False)['score'].mean()
            for _, row in agg.iterrows():
                m = str(row.get('model', '')).strip()
                s = row.get('score')
                if m and pd.notna(s):
                    scores_for_tier[m] = float(s)
    sorted_models = sorted(scores_for_tier.items(), key=lambda x: x[1], reverse=True)
    if not sorted_models:
        return []
    n = len(sorted_models)
    tier_names = ['第一梯队', '第二梯队', '第三梯队'][:min(num_tiers, 3)]
    if n <= num_tiers:
        return [(tier_names[i], [sorted_models[i][0]]) for i in range(min(n, num_tiers))]
    # 按分差切档：在相邻模型分差最大的位置划分梯队（每题区分度不同，不预设固定分数）
    scores_only = [s for _, s in sorted_models]
    gaps = [scores_only[i] - scores_only[i + 1] for i in range(n - 1)]
    num_splits = min(num_tiers - 1, n - 1)
    # 分差最大的 num_splits 个位置作为切分点（gap 下标 i 表示在 model[i] 与 model[i+1] 之间切）
    gap_rank = sorted(range(n - 1), key=lambda i: gaps[i], reverse=True)
    split_after = sorted(gap_rank[:num_splits])
    boundaries = [-1] + split_after + [n - 1]
    result = []
    for i in range(min(num_tiers, len(boundaries) - 1)):
        start, end = boundaries[i] + 1, boundaries[i + 1]
        models = [sorted_models[j][0] for j in range(start, end + 1)]
        if models:
            result.append((tier_names[i], models))
    return result


def _build_case_analysis_prompt(
    qid: str,
    query: str,
    evaluation_criteria: str,
    model_scores: Dict[str, float],
    model_evaluations: Dict[str, str],
    model_replies: Dict[str, str],
    expert_opinion: str,
    tier_models: List[Tuple[str, List[str]]],
    l1: str = '',
    l2: str = '',
    l3: str = '',
    difficulty: str = '',
    difficulty_score: str = '',
    source: str = '',
    dimension_info: str = '',
    reference_answer: str = '',
    sysprompt: str = '',
) -> Tuple[str, str]:
    sys_content = sysprompt if sysprompt else DEFAULT_REPORT_SYSPROMPT

    sorted_scores = sorted(model_scores.items(), key=lambda x: x[1], reverse=True)
    scores_text = '\n'.join([f'- {model}: {score:.1f}分' for model, score in sorted_scores])

    eval_details = []
    for model, score in sorted_scores[:8]:
        eval_text = model_evaluations.get(model, '')
        if eval_text:
            eval_details.append(f'### {model}（{score:.1f}分）\n{eval_text[:600]}')
    eval_text_combined = '\n\n'.join(eval_details)

    meta_parts = []
    if l1:
        meta_parts.append(f'L1: {l1}')
    if l2:
        meta_parts.append(f'L2: {l2}')
    if l3:
        meta_parts.append(f'L3: {l3}')
    if difficulty:
        meta_parts.append(f'难度: {difficulty}')
    if difficulty_score:
        meta_parts.append(f'难度分: {difficulty_score}')
    if source:
        meta_parts.append(f'来源: {source}')
    meta_line = ' | '.join(meta_parts) if meta_parts else '（无元数据）'

    reply_excerpts = []
    for model, score in sorted_scores[:8]:
        reply = (model_replies.get(model) or '').strip()
        if reply:
            excerpt = reply[:400] + '...' if len(reply) > 400 else reply
            reply_excerpts.append(f'### {model}（{score:.1f}分）\n{excerpt}')
    reply_text = '\n\n'.join(reply_excerpts) if reply_excerpts else '（无回复内容）'

    user_content = f"""题目ID: {qid}

【题目元数据】
{meta_line}

【题目内容】
{query[:800]}

【评分标准】
{evaluation_criteria[:800] if evaluation_criteria else '（无）'}
"""

    if reference_answer and str(reference_answer).strip():
        ref = (reference_answer[:1200] + '...') if len(str(reference_answer)) > 1200 else str(reference_answer).strip()
        user_content += f'\n【参考答案】（请结合参考答案分析模型回复的符合度与偏差）\n{ref}\n'

    user_content += f"""
【各模型得分】
{scores_text}
"""

    if dimension_info:
        user_content += f'\n【本题各模型维度表现】\n{dimension_info}\n'

    user_content += f"""
【评估详情（含 Rubric 逐条 PASS/FAIL）】
{eval_text_combined}

【各模型回复（节选，用于查找证据）】
{reply_text}
"""

    if tier_models:
        tier_text = '\n'.join([f'- {name}：{", ".join(models)}（按得分从高到低）' for name, models in tier_models])
        user_content += f'\n【预分梯队与模型列表】（请据此撰写各梯队表现总结，勿照搬专家意见）\n{tier_text}\n'

    if expert_opinion:
        user_content += f'\n【专家意见（仅供参考，请勿照搬到输出）】\n{expert_opinion}\n'

    return sys_content, user_content


def _parse_analysis_response(response_text: str) -> Tuple[str, str]:
    summary = ''
    analysis = ''

    summary_match = re.search(r'【综合评估】\s*(.*?)(?=【|$)', response_text, re.DOTALL)
    if summary_match:
        summary = summary_match.group(1).strip()

    tier_match = re.search(r'【模型分档】\s*(.*?)(?=【|$)', response_text, re.DOTALL)
    analysis_match = re.search(r'【失分点分析】\s*(.*?)(?=【|$)', response_text, re.DOTALL)
    tier_part = tier_match.group(1).strip() if tier_match else ''
    analysis_part = analysis_match.group(1).strip() if analysis_match else ''
    if tier_part and analysis_part:
        analysis = f"【模型分档】\n{tier_part}\n\n【失分点分析】\n{analysis_part}"
    elif analysis_part:
        analysis = analysis_part
    elif tier_part:
        analysis = tier_part

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

    eval_cols = [c for c in df.columns if isinstance(c, str) and c.startswith('eval_') and not c.endswith('_raw')]
    if eval_batch_id:
        candidate = f'eval_{eval_batch_id}'
        if candidate in df.columns:
            df['eval_score'] = pd.to_numeric(df[candidate], errors='coerce')
            return df
    if eval_cols:
        df['eval_score'] = pd.to_numeric(df[eval_cols[-1]], errors='coerce')
    return df


def _parse_version_from_model_name(model_name: str) -> tuple:
    """
    从模型名中解析版本号用于排序，如 glm4.5 -> (4, 5), glm4.6 -> (4, 6), glm5 -> (5,)。
    取名字中最后一组「数字.数字...」或单数字，按数值元组比较，便于 4.5 < 4.6 < 5。
    """
    if not model_name or not isinstance(model_name, str):
        return (0,)
    # 匹配最后一组版本号：数字 或 数字.数字...
    matches = re.findall(r'\d+(?:\.\d+)*', model_name)
    if not matches:
        return (0,)
    last = matches[-1]
    try:
        parts = last.split('.')
        return tuple(int(p) for p in parts)
    except (ValueError, AttributeError):
        return (0,)


def _compute_source_stats(replies_with_q: pd.DataFrame, questions_df: pd.DataFrame) -> pd.DataFrame:
    """
    按 source 分组统计：题目数、模型均分、标准差。source：公开=to_b/nlp_* 等；自建=H/R/HM/M；
    自建=H(人工)/R(真实来源)/HM(人机协作)/M(模型合成)。
    """
    if replies_with_q.empty or 'source' not in replies_with_q.columns:
        return pd.DataFrame()
    rows = []
    for src in replies_with_q['source'].dropna().unique():
        src = str(src).strip()
        subset = replies_with_q[replies_with_q['source'] == src]
        q_count = subset['qid'].nunique()
        scores = subset['eval_score'].dropna()
        mean_s = float(scores.mean()) if not scores.empty else np.nan
        std_s = float(scores.std()) if len(scores) > 1 else 0.0
        group_label = '自建数据' if src in ('H', 'R', 'HM', 'M') else '公开数据'
        rows.append({
            'source': src,
            '分组': group_label,
            '题目数': int(q_count),
            '模型均分': round(mean_s, 2) if not np.isnan(mean_s) else 'N/A',
            '标准差': round(std_s, 2) if not np.isnan(mean_s) else 'N/A',
        })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values('source').reset_index(drop=True)


def _compute_full_pass_summary(replies_df: pd.DataFrame) -> dict:
    """
    计算完全通过率（ILA：全部检查点 PASS 的题目占比）。
    三指标之一，参考 EIFBench，用于拉大模型间差距。
    """
    if replies_df.empty or 'full_pass' not in replies_df.columns:
        return {}
    valid = replies_df.dropna(subset=['full_pass'])
    if valid.empty:
        return {}
    per_model = valid.groupby('model').agg(
        full_pass_count=('full_pass', 'sum'),
        total=('full_pass', 'count'),
    ).reset_index()
    cnt = pd.to_numeric(per_model['full_pass_count'], errors='coerce').fillna(0)
    tot = pd.to_numeric(per_model['total'], errors='coerce').fillna(0)
    per_model['完全通过数'] = cnt.astype(int)
    per_model['完全通过率(%)'] = np.where(tot > 0, (cnt / tot * 100).round(2), np.nan)
    overall_pass = int(valid['full_pass'].sum())
    overall_total = len(valid)
    return {
        'per_model_df': per_model[['model', '完全通过数', 'total', '完全通过率(%)']].rename(columns={'total': '评测数', 'model': '模型'}),
        'overall_pass': overall_pass,
        'overall_total': overall_total,
        'overall_rate': round(overall_pass / overall_total * 100, 2) if overall_total > 0 else 0,
    }


def _get_primary_dim_col(df: pd.DataFrame) -> Optional[str]:
    """根据题干实际字段返回主维度列：L1 > L2 > L3，用于意图/分组统计。不同批次字段不同，如 prof 仅 L3。"""
    if df is None or df.empty:
        return None
    for col in ('L1', 'L2', 'L3'):
        if col in df.columns and df[col].notna().any():
            return col
    return None


def _select_typical_qids_by_l1(
    top20_df: pd.DataFrame,
    replies_with_q: pd.DataFrame,
    top_n_cases: int,
) -> List[str]:
    """结合维度（L1/L2/L3 按存在优先）从价值题目中分层选取典型案例。"""
    if top20_df.empty or 'qid' not in top20_df.columns:
        return []
    all_qids = [str(q) for q in top20_df['qid'].tolist()]
    if top_n_cases <= 0:
        return []
    if top_n_cases >= len(all_qids):
        return all_qids[:top_n_cases]
    dim_col = _get_primary_dim_col(top20_df) or _get_primary_dim_col(replies_with_q)
    qid_to_dim = {}
    if dim_col:
        if dim_col in top20_df.columns:
            qid_to_dim = dict(zip(top20_df['qid'].astype(str), top20_df[dim_col].astype(str)))
        elif not replies_with_q.empty and dim_col in replies_with_q.columns:
            first = replies_with_q.drop_duplicates('qid')[['qid', dim_col]]
            qid_to_dim = dict(zip(first['qid'].astype(str), first[dim_col].astype(str)))
    if not qid_to_dim:
        return all_qids[:top_n_cases]
    from collections import defaultdict
    by_dim = defaultdict(list)
    for qid in all_qids:
        by_dim[qid_to_dim.get(qid, '')].append(qid)
    # 每个 L1 至少选 2 个典型案例，再按剩余名额补足
    chosen = []
    for _, qids in sorted(by_dim.items(), key=lambda x: x[0]):
        chosen.extend(qids[:2])
    chosen = list(dict.fromkeys(chosen))
    if len(chosen) >= top_n_cases:
        return chosen[:top_n_cases]
    remaining = [q for q in all_qids if q not in chosen]
    for q in remaining:
        if len(chosen) >= top_n_cases:
            break
        chosen.append(q)
    return chosen[:top_n_cases]


def _compute_dimension_ila_df(replies_df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """D1–D5 各维度 ILA 通过率（按模型），供报告与 LLM 分析使用。"""
    if replies_df.empty:
        return None
    dim_cols = [c for c in ['D1_ila', 'D2_ila', 'D3_ila', 'D4_ila', 'D5_ila'] if c in replies_df.columns]
    if not dim_cols:
        return None
    rows = []
    for model in replies_df['model'].dropna().unique():
        sub = replies_df[replies_df['model'] == model]
        row = {'模型': model}
        for col in dim_cols:
            dim_valid = sub[col].dropna()
            if len(dim_valid) == 0:
                row[col.replace('_ila', '_ILA率(%)')] = np.nan
            else:
                rate = (dim_valid.astype(bool).sum() / len(dim_valid) * 100)
                row[col.replace('_ila', '_ILA率(%)')] = round(float(rate), 2)
        rows.append(row)
    df = pd.DataFrame(rows)
    col_order = ['模型'] + [c.replace('_ila', '_ILA率(%)') for c in dim_cols]
    return df[[c for c in col_order if c in df.columns]]


def _compute_source_gap_summary(replies_with_q: pd.DataFrame) -> dict:
    """
    计算公开 vs 自建 对比摘要，突出差距：将自建拆为 纯人工自建(H/R/HM) 与 M合成。
    M 合成题目由模型生成，评估时模型打分可能偏高，单独统计便于对比。
    """
    if replies_with_q.empty or 'source_group_3' not in replies_with_q.columns:
        return {}
    rwq = replies_with_q.dropna(subset=['eval_score'])
    if rwq.empty:
        return {}

    result = {}
    for grp in ['公开数据', '纯人工自建', 'M合成']:
        sub = rwq[rwq['source_group_3'] == grp]
        if sub.empty:
            result[f'{grp}_均分'] = np.nan
            result[f'{grp}_题数'] = 0
            result[f'{grp}_标准差'] = np.nan
        else:
            s = sub['eval_score']
            result[f'{grp}_均分'] = round(float(s.mean()), 2)
            result[f'{grp}_题数'] = int(sub['qid'].nunique())
            result[f'{grp}_标准差'] = round(float(s.std()), 2) if len(s) > 1 else 0

    pub_mean = result.get('公开数据_均分')
    human_mean = result.get('纯人工自建_均分')
    m_mean = result.get('M合成_均分')

    if not np.isnan(pub_mean) and not np.isnan(human_mean):
        result['公开vs纯人工自建_均分差'] = round(float(pub_mean - human_mean), 2)
    if not np.isnan(m_mean) and not np.isnan(human_mean):
        result['M合成vs纯人工自建_均分差'] = round(float(m_mean - human_mean), 2)

    # 纯人工自建 vs 公开 方差比（>1 表示纯人工自建离散度更大）
    pub_s = rwq[rwq['source_group_3'] == '公开数据']['eval_score']
    human_s = rwq[rwq['source_group_3'] == '纯人工自建']['eval_score']
    if len(pub_s) > 1 and len(human_s) > 1 and pub_s.var() > 0:
        result['纯人工自建vs公开_方差比'] = round(float(human_s.var() / pub_s.var()), 2)

    result['M合成打分说明'] = (
        'M 合成题目由模型生成，评估模型对其打分往往偏高，实际难度可能高于显示分数；'
        '纯人工自建(H/R/HM)更能反映真实业务难度，公开vs纯人工自建差距是核心指标。'
    )
    return result


def _compute_version_progression(
    overall_ranking: pd.DataFrame,
    vendor_series: Dict[str, List[str]],
) -> List[Dict[str, Any]]:
    """
    按厂商配置计算版本递进：每厂商内按版本顺序比较平均分、较上版提升、提升率。
    vendor_series: { "GLM": ["glm4.5", "glm4.6", "glm5"], ... }；
    同一厂商下的模型列表会按「模型名中的版本号」自动从早到晚排序（如 4.5 < 4.6 < 5），
    无需手动按时间顺序填写。
    """
    if not vendor_series or overall_ranking.empty or '模型' not in overall_ranking.columns or '平均分' not in overall_ranking.columns:
        return []
    model_to_score = dict(zip(overall_ranking['模型'].astype(str).str.strip(), overall_ranking['平均分']))
    rows = []
    for vendor_name, model_order in vendor_series.items():
        # 按模型名中的版本号从早到晚排序（glm4.5, glm4.6, glm5）
        order = sorted(
            [str(m).strip() for m in model_order],
            key=lambda m: _parse_version_from_model_name(m),
        )
        prev_avg = None
        for ver_idx, model in enumerate(order):
            avg = model_to_score.get(model)
            if avg is None:
                continue
            delta = (float(avg) - prev_avg) if prev_avg is not None else None
            rate = (delta / prev_avg * 100) if prev_avg and prev_avg != 0 else None
            rows.append({
                '厂商': vendor_name,
                '版本顺序': ver_idx + 1,
                '模型': model,
                '平均分': round(float(avg), 2),
                '较上版提升': round(delta, 2) if delta is not None else None,
                '较上版提升率(%)': round(rate, 2) if rate is not None else None,
            })
            prev_avg = float(avg)
    return rows


def _compute_thinking_comparison(
    replies_df: pd.DataFrame,
    thinking_models: List[str],
) -> Optional[Dict[str, Any]]:
    """
    对比思考模型与非思考模型在本次报告模型集合内的均分与差距。
    thinking_models: 视为「思考模型」的模型名列表（子集）。
    """
    if not thinking_models or replies_df.empty or 'eval_score' not in replies_df.columns or 'model' not in replies_df.columns:
        return None
    thinking_set = {str(m).strip() for m in thinking_models}
    replies_df = replies_df.dropna(subset=['eval_score'])
    if replies_df.empty:
        return None
    thinking_scores = replies_df[replies_df['model'].astype(str).str.strip().isin(thinking_set)]['eval_score']
    non_scores = replies_df[~replies_df['model'].astype(str).str.strip().isin(thinking_set)]['eval_score']
    if thinking_scores.empty and non_scores.empty:
        return None
    thinking_avg = float(thinking_scores.mean()) if not thinking_scores.empty else None
    non_avg = float(non_scores.mean()) if not non_scores.empty else None
    thinking_models_in = list(replies_df[replies_df['model'].astype(str).str.strip().isin(thinking_set)]['model'].unique())
    non_models_in = list(replies_df[~replies_df['model'].astype(str).str.strip().isin(thinking_set)]['model'].unique())
    delta = (thinking_avg - non_avg) if thinking_avg is not None and non_avg is not None else None
    return {
        'thinking_avg': round(thinking_avg, 2) if thinking_avg is not None else None,
        'non_thinking_avg': round(non_avg, 2) if non_avg is not None else None,
        'delta': round(delta, 2) if delta is not None else None,
        'thinking_models': thinking_models_in,
        'non_thinking_models': non_models_in,
        'thinking_count': len(thinking_models_in),
        'non_thinking_count': len(non_models_in),
    }


def _build_l1_capability_summaries(
    client: 'OAIClient',
    data_cache: dict,
    model: str,
    temperature: float = 0.3,
    timeout: int = 120,
) -> Dict[str, str]:
    """
    借助 LLM 对每个 L1 意图类型生成 2-3 句能力总结。
    输入：intent_level_analysis、l1_high_distinction_stats、corrected_ranking_by_l1
    """
    intent_df = data_cache.get('intent_level_analysis', pd.DataFrame())
    high_dist_df = data_cache.get('l1_high_distinction_stats', pd.DataFrame())
    ranking_by_l1 = data_cache.get('corrected_ranking_by_l1') or {}

    if intent_df.empty:
        return {}

    summaries = {}
    l1_list = intent_df['意图'].astype(str).tolist()
    high_map = {}
    if not high_dist_df.empty and 'L1' in high_dist_df.columns:
        for _, r in high_dist_df.iterrows():
            high_map[str(r['L1'])] = f"总{int(r.get('总题目数', 0))}题，高区分度(≥0.3){int(r.get('高区分度题目数', 0))}题，占比{float(r.get('占比(%)', 0)):.1f}%"

    for l1 in l1_list[:20]:
        row = intent_df[intent_df['意图'] == l1].iloc[0]
        rank_df = ranking_by_l1.get(l1, pd.DataFrame())
        rank_str = ''
        if not rank_df.empty and '模型' in rank_df.columns:
            top5 = rank_df.head(5)
            def _sc(v):
                try:
                    return f"{float(v):.1f}" if v is not None and pd.notna(v) else ""
                except (TypeError, ValueError):
                    return str(v) if v else ""
            rank_str = ' | '.join(f"{r.get('排名','')}.{r.get('模型','')}({_sc(r.get('纠偏后均分'))})" for _, r in top5.iterrows())

        user_content = f"""L1意图类型：{l1}

【意图级别统计】
- 题目数：{row.get('题目数','')}
- 平均分数方差：{row.get('平均分数方差','')}
- 最佳模型：{row.get('最佳模型','')}
- 最差模型：{row.get('最差模型','')}
- 各模型平均分：{row.get('各模型平均分','')}

【高区分度题目】{high_map.get(l1, '无')}

【专家纠偏排名(前5)】{rank_str or '无'}

请用2-3句话概括各模型在该L1意图上的能力表现，突出差距与典型特征。"""
        try:
            messages = [
                {'role': 'system', 'content': L1_CAPABILITY_SYSPROMPT},
                {'role': 'user', 'content': user_content},
            ]
            resp = client.chat(messages=messages, model=model, temperature=temperature, timeout=timeout)
            summaries[l1] = safe_str(resp).strip() or '—'
        except Exception as e:
            summaries[l1] = f'(分析异常: {e})'
        time.sleep(0.3)

    return summaries


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
    report_filename_prefix: str = 'evaluation_report',
    max_workers: int = 3,
    timeout: int = 120,
    temperature: float = 0.3,
    report_title: str = '多模型能力评测报告',
    model_list: List[str] = None,
    vendor_series: Dict[str, List[str]] = None,
    thinking_models: List[str] = None,
    use_report_cache: bool = True,
    cache_max_age_hours: Optional[float] = None,
    force_refresh: bool = False,
    generate_html: bool = False,
    report_config: dict = None,
) -> Dict[str, str]:
    print('\n' + '=' * 60)
    print('报告生成阶段 - 价值题目深度分析 + 可视化报告')
    print('=' * 60)
    report_config = report_config or {}

    cache_path = _report_cache_path(output_dir)
    report_cache_key = {
        'l1_loss_scope': report_config.get('l1_loss_scope', 'summary_only'),
        'focus_models_for_loss': report_config.get('focus_models_for_loss') or [],
        'stats_source_scope': report_config.get('stats_source_scope', 'all'),
        'stats_include_sources': report_config.get('stats_include_sources') or [],
        'stats_exclude_sources': report_config.get('stats_exclude_sources') or [],
    }
    if use_report_cache and not force_refresh:
        cached = _load_report_cache(
            cache_path, questions_excel, replies_excel,
            eval_batch_id, top_n_cases, model_list, cache_max_age_hours, report_cache_key=report_cache_key
        )
        if cached:
            data = cached['data']
            data_cache = cached['data_cache']
            case_analyses = cached['case_analyses']
            # 若缓存无扩展数据，补充计算（保证新旧缓存兼容）
            if 'score_distribution' not in data_cache or data_cache.get('score_distribution') is None:
                from ..analysis.report_expansion import (
                    compute_score_distribution,
                    analyze_intent_level,
                    analyze_constraint_efficacy,
                    compute_model_tiers,
                    build_intent_insights,
                    build_constraint_challenge_insights,
                    build_scenario_guide,
                    build_improvement_path,
                )
                replies = data.get('replies', pd.DataFrame())
                rwq = data.get('replies_with_question', pd.DataFrame())
                dim_stats = data_cache.get('dimension_stats') or {}
                overall = data_cache.get('overall_ranking', pd.DataFrame())
                eval_col = data.get('eval_column', '')
                data_cache['score_distribution'] = compute_score_distribution(replies)
                _dim = _get_primary_dim_col(rwq) or 'L1'
                data_cache['intent_level_analysis'] = analyze_intent_level(rwq, _dim, 50)
                data_cache['constraint_efficacy'] = analyze_constraint_efficacy(replies, dim_stats, eval_col)
                data_cache['model_tiers'] = compute_model_tiers(overall)
                data_cache['intent_insights'] = build_intent_insights(data_cache['intent_level_analysis'])
                data_cache['constraint_insights'] = build_constraint_challenge_insights(data_cache['constraint_efficacy'])
                data_cache['scenario_guide'] = build_scenario_guide(data_cache['intent_level_analysis'], overall)
                data_cache['improvement_paths'] = build_improvement_path(data_cache['model_tiers'], dim_stats)
                if 'l1_high_distinction_stats' not in data_cache or data_cache.get('l1_high_distinction_stats') is None:
                    item_df = data_cache.get('item_analysis_df', pd.DataFrame())
                    data_cache['l1_high_distinction_stats'] = _compute_l1_high_distinction_stats(item_df) if not item_df.empty else pd.DataFrame()
                if 'l1_capability_summaries' not in data_cache:
                    data_cache['l1_capability_summaries'] = {}
                if 'panorama_df' not in data_cache or data_cache.get('panorama_df') is None:
                    data_cache['panorama_df'] = _compute_panorama_ranking(data)
            # 缓存兼容：缺失时补算 L1 失分特征（不依赖上述 score_distribution 分支）
            if 'l1_loss_profiles' not in data_cache or data_cache.get('l1_loss_profiles') is None or (isinstance(data_cache.get('l1_loss_profiles'), pd.DataFrame) and data_cache['l1_loss_profiles'].empty):
                _rwq = data.get('replies_with_question', pd.DataFrame())
                _dim_stats = data_cache.get('dimension_stats') or {}
                _eval_col = data.get('eval_column', '') or ''
                data_cache['l1_loss_profiles'] = _compute_l1_loss_profiles(_rwq, _dim_stats, eval_column=_eval_col)
            if 'model_l1_loss_profiles' not in data_cache or data_cache.get('model_weakness_summary') is None:
                _rwq = data.get('replies_with_question', pd.DataFrame())
                _dim_stats = data_cache.get('dimension_stats') or {}
                # 缓存补算时仅做轻量汇总，避免全量解析
                data_cache['model_l1_loss_profiles'] = pd.DataFrame()
                data_cache['model_weakness_summary'] = _compute_model_weakness_summary_light(_rwq, _dim_stats) or {}
            if 'data_synthesis_suggestions' not in data_cache or not data_cache.get('data_synthesis_suggestions'):
                data_cache['data_synthesis_suggestions'] = _build_data_synthesis_suggestions(
                    data_cache.get('l1_loss_profiles', pd.DataFrame()),
                    data_cache.get('model_l1_loss_profiles', pd.DataFrame()),
                    data_cache.get('model_weakness_summary') or {},
                    data_cache.get('dimension_stats') or {},
                )
            print('  ✓ 使用缓存（跳过统计与 AI 分析）')
            print(f'\n▶ 生成报告文件...')
            os.makedirs(output_dir, exist_ok=True)
            from datetime import datetime
            timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
            prefix = report_filename_prefix or 'evaluation_report'
            output_md = os.path.join(output_dir, f'{prefix}_{timestamp_str}.md')
            generate_markdown_report(output_md=output_md, data=data, data_cache=data_cache,
                                    case_analyses=case_analyses, report_title=report_title)
            output_html = None
            if generate_html:
                output_html = os.path.join(output_dir, f'{prefix}_{timestamp_str}.html')
                generate_html_report(output_html=output_html, data=data, data_cache=data_cache,
                                    case_analyses=case_analyses, report_title=report_title)
                print(f'  HTML: {output_html}')
            _fp = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'docs', 'EVAL_REPORT_FRAMEWORK.md')
            if sync_framework_with_report_stats(data, data_cache, _fp):
                print(f'  ✓ EVAL_REPORT_FRAMEWORK.md 已同步本次统计')
            print(f'\n✓ 报告生成完成！（来自缓存）')
            print(f'  Markdown: {output_md}')
            print('=' * 60)
            return {'html': output_html, 'markdown': output_md}

    data = load_and_preprocess(
        questions_excel=questions_excel,
        replies_excel=replies_excel,
        human_excel=human_excel,
        eval_batch_id=eval_batch_id,
    )

    # 按厂商/版本出专项报告：只保留指定模型，排名与典型案例均基于该子集
    if model_list and len(model_list) > 0:
        model_set = {str(m).strip() for m in model_list}
        data['replies'] = data['replies'][data['replies']['model'].astype(str).str.strip().isin(model_set)]
        data['replies_with_question'] = data['replies_with_question'][
            data['replies_with_question']['model'].astype(str).str.strip().isin(model_set)
        ]
        if data.get('expert_scores') is not None and not data['expert_scores'].empty:
            data['expert_scores'] = data['expert_scores'][data['expert_scores']['model'].astype(str).str.strip().isin(model_set)]
        if data.get('rater_scores') is not None and not data['rater_scores'].empty:
            data['rater_scores'] = data['rater_scores'][data['rater_scores']['model'].astype(str).str.strip().isin(model_set)]
        print(f"  专项报告：仅包含 {len(model_set)} 个模型 — {', '.join(sorted(model_set)[:8])}{'...' if len(model_set) > 8 else ''}")
        if data['replies'].empty:
            raise RuntimeError('model_list 过滤后无回复数据，请检查 model_list 与回复表中的 model 列是否一致')

    # 统计口径：按题目来源筛选（可配置）。其余统计/分析逻辑保持一致。
    stats_source_scope = report_config.get('stats_source_scope', 'all')
    include_sources = report_config.get('stats_include_sources') or []
    exclude_sources = report_config.get('stats_exclude_sources') or []
    data_for_stats = data
    stats_scope_note = '全量数据（公开+自建）'
    if stats_source_scope == 'public_only':
        # 公开数据：排除自建四类 H/R/HM/M，剩余即公开基准源
        data_for_stats = _filter_data_by_source(data, include_sources=[], exclude_sources=['H', 'R', 'HM', 'M'])
        stats_scope_note = '仅公开数据'
    elif stats_source_scope == 'self_built_only':
        data_for_stats = _filter_data_by_source(data, include_sources=['H', 'R', 'HM', 'M'], exclude_sources=[])
        stats_scope_note = '仅自建数据（含R）'
    elif stats_source_scope == 'custom':
        data_for_stats = _filter_data_by_source(data, include_sources=include_sources, exclude_sources=exclude_sources)
        stats_scope_note = f"自定义筛选（include={include_sources} exclude={exclude_sources}）"

    try:
        n_all = int(data.get('replies_with_question', pd.DataFrame())['qid'].nunique()) if not data.get('replies_with_question', pd.DataFrame()).empty else 0
        n_use = int(data_for_stats.get('replies_with_question', pd.DataFrame())['qid'].nunique()) if not data_for_stats.get('replies_with_question', pd.DataFrame()).empty else 0
        print(f"\n▶ 构建统计缓存...（统计口径：{stats_scope_note}，题目 {n_use}/{n_all}）")
    except Exception:
        print(f"\n▶ 构建统计缓存...（统计口径：{stats_scope_note}）")

    # 综合榜单/全景统计：基于 data_for_stats；仅案例分析阶段排除 R
    ranking_analyzer = ModelRankingAnalyzer(data_for_stats)
    expert_corrected_analyzer = ExpertCorrectedRankingAnalyzer(data_for_stats)
    human_expert_analyzer = HumanExpertConsistencyAnalyzer(data_for_stats)
    model_reliability_analyzer = ModelReliabilityAnalyzer(data_for_stats)
    expert_hm_analyzer = ExpertHumanMachineConsistencyAnalyzer(data_for_stats)
    valuable_analyzer = ValuableQuestionAnalyzer(data_for_stats)
    item_analyzer = ItemAnalyzer(data_for_stats)

    rankings = ranking_analyzer.generate_all_rankings()
    corrected_ranking = expert_corrected_analyzer.analyze_corrected_ranking()
    corrected_ranking_by_l1 = expert_corrected_analyzer.analyze_corrected_ranking_by_l1()
    rater_vs_others = human_expert_analyzer.analyze_rater_vs_others()
    model_expert_overall, model_expert_detail = model_reliability_analyzer.analyze_model_vs_expert()
    model_ranking_summary, _ = model_reliability_analyzer.analyze_model_ranking_consistency()
    expert_human_machine_summary, expert_human_machine_per_question = expert_hm_analyzer.analyze()
    top20_df = valuable_analyzer.find_top20_valuable_questions()
    item_analysis_df = item_analyzer.analyze_all_items()

    # 基于 eval_*_raw 中的 rubrics_check 按 D1/D2/D3/D4/D5 维度统计通过率（得失分分析）
    eval_column = data_for_stats.get('eval_column', data.get('eval_column', ''))
    dimension_stats = analyze_rubric_dimensions(replies_df=data_for_stats['replies'], eval_column=eval_column)
    if dimension_stats.get('has_data'):
        print(f"  ✓ 维度得失分统计: 已解析 rubrics_check，共 {dimension_stats['model_dimension_df'].shape[0]} 条模型×维度记录")
    dimension_fail_tables = _compute_dimension_fail_rate_tables(dimension_stats)
    rwq = data_for_stats.get('replies_with_question', pd.DataFrame())
    d5_by_l1_df = _compute_d5_fail_by_l1(rwq, dimension_stats) if dimension_stats.get('has_data') else pd.DataFrame()

    # 厂商系列版本递进：按配置的 vendor_series 计算各厂商内部版本间提升与跃升幅度
    version_progression = _compute_version_progression(
        rankings.get('overall', pd.DataFrame()),
        vendor_series or {},
    )
    if version_progression:
        print(f"  ✓ 厂商版本递进: {len(version_progression)} 个厂商系列")

    # 思考模型 vs 非思考模型：按 thinking_models 配置对比均分与差距
    thinking_comparison = _compute_thinking_comparison(
        data_for_stats['replies'],
        thinking_models or [],
    )
    if thinking_comparison:
        print(f"  ✓ 思考/非思考对比: 思考模型 {thinking_comparison.get('thinking_count', 0)} 个，非思考 {thinking_comparison.get('non_thinking_count', 0)} 个")

    # 按 source 分组统计：题目数、模型均分、标准差（供报告「按 source 分组得分」使用）
    source_stats = _compute_source_stats(data_for_stats.get('replies_with_question', pd.DataFrame()), data_for_stats.get('questions', pd.DataFrame()))
    if not source_stats.empty:
        print(f"  ✓ 按 source 分组: {len(source_stats)} 个 source")
    source_gap_summary = _compute_source_gap_summary(data_for_stats.get('replies_with_question', pd.DataFrame()))
    if source_gap_summary:
        gap = source_gap_summary.get('公开vs纯人工自建_均分差', '')
        print(f"  ✓ 公开vs纯人工自建 均分差: {gap}")

    full_pass_summary = _compute_full_pass_summary(data_for_stats.get('replies', pd.DataFrame()))
    if full_pass_summary:
        print(f"  ✓ 完全通过率(ILA): 整体 {full_pass_summary.get('overall_pass', 0)}/{full_pass_summary.get('overall_total', 0)}")
    dimension_ila_df = _compute_dimension_ila_df(data_for_stats.get('replies', pd.DataFrame()))

    # 报告扩展：分数分布、意图级别、约束效能、梯队、场景指南等
    from ..analysis.report_expansion import (
        compute_score_distribution,
        analyze_intent_level,
        analyze_constraint_efficacy,
        compute_model_tiers,
        build_intent_insights,
        build_constraint_challenge_insights,
        build_scenario_guide,
        build_improvement_path,
    )
    score_distribution_df = compute_score_distribution(data_for_stats['replies'])
    rwq = data_for_stats.get('replies_with_question', pd.DataFrame())
    primary_dim = _get_primary_dim_col(rwq) or 'L1'
    intent_level_df = analyze_intent_level(rwq, dim_col=primary_dim, top_n=50)
    constraint_result = analyze_constraint_efficacy(data_for_stats['replies'], dimension_stats, eval_column=eval_column)
    model_tiers = compute_model_tiers(rankings.get('overall', pd.DataFrame()))
    intent_insights = build_intent_insights(intent_level_df)
    constraint_insights = build_constraint_challenge_insights(constraint_result)
    scenario_guide_df = build_scenario_guide(intent_level_df, rankings.get('overall', pd.DataFrame()))
    improvement_paths = build_improvement_path(model_tiers, dimension_stats)
    if score_distribution_df is not None and not score_distribution_df.empty:
        print(f"  ✓ 分数分布: {len(score_distribution_df)} 个模型")
    if not intent_level_df.empty:
        print(f"  ✓ 意图级别分析: {len(intent_level_df)} 个意图 (维度列: {primary_dim})")
    if constraint_result.get('total_constraints'):
        print(f"  ✓ 约束效能分析: {constraint_result['total_constraints']} 个维度")

    l1_high_distinction_stats = _compute_l1_high_distinction_stats(item_analysis_df)
    l1_loss_profiles = _compute_l1_loss_profiles(rwq, dimension_stats, eval_column=eval_column or '')
    # L1 失分统计范围：summary_only=仅汇总(轻量)、focus=第一名+指定模型(解析评语)、full=全模型
    l1_loss_scope = (report_config or {}).get('l1_loss_scope', 'summary_only')
    focus_models_for_loss = list((report_config or {}).get('focus_models_for_loss') or [])
    rank1_model = None
    if not rankings.get('overall', pd.DataFrame()).empty and '模型' in rankings['overall'].columns:
        rank1_model = str(rankings['overall'].iloc[0].get('模型', '')).strip()
    if l1_loss_scope == 'summary_only':
        model_l1_df = pd.DataFrame()
        model_weakness_summary = _compute_model_weakness_summary_light(rwq, dimension_stats)
    elif l1_loss_scope == 'focus':
        focus_set = []
        if rank1_model:
            focus_set.append(rank1_model)
        for m in focus_models_for_loss:
            m = str(m).strip()
            if m and m not in focus_set:
                focus_set.append(m)
        model_l1_df, model_weakness_summary = _compute_model_l1_loss_profiles(
            rwq, dimension_stats, eval_column=eval_column or '', focus_models=focus_set if focus_set else None
        )
    else:
        model_l1_df, model_weakness_summary = _compute_model_l1_loss_profiles(
            rwq, dimension_stats, eval_column=eval_column or '', focus_models=None
        )
    data_synthesis_suggestions = _build_data_synthesis_suggestions(
        l1_loss_profiles if l1_loss_profiles is not None and not l1_loss_profiles.empty else pd.DataFrame(),
        model_l1_df if model_l1_df is not None and not model_l1_df.empty else pd.DataFrame(),
        model_weakness_summary or {},
        dimension_stats,
    )

    data_cache = {
        'overall_ranking': rankings.get('overall', pd.DataFrame()),
        'rankings': rankings,
        'full_pass_summary': full_pass_summary,
        'dimension_ila_df': dimension_ila_df if dimension_ila_df is not None and not dimension_ila_df.empty else pd.DataFrame(),
        'source_stats': source_stats,
        'source_gap_summary': source_gap_summary,
        'corrected_ranking': corrected_ranking,
        'corrected_ranking_by_l1': corrected_ranking_by_l1,
        'l1_high_distinction_stats': l1_high_distinction_stats if l1_high_distinction_stats is not None and not l1_high_distinction_stats.empty else pd.DataFrame(),
        'l1_loss_profiles': l1_loss_profiles if l1_loss_profiles is not None and not l1_loss_profiles.empty else pd.DataFrame(),
        'model_l1_loss_profiles': model_l1_df if model_l1_df is not None and not model_l1_df.empty else pd.DataFrame(),
        'model_weakness_summary': model_weakness_summary or {},
        'data_synthesis_suggestions': data_synthesis_suggestions or [],
        'rater_vs_others': rater_vs_others,
        'model_expert_overall': model_expert_overall,
        'model_expert_detail': model_expert_detail if model_expert_detail is not None else pd.DataFrame(),
        'expert_human_machine_summary': expert_human_machine_summary if expert_human_machine_summary is not None and not expert_human_machine_summary.empty else pd.DataFrame(),
        'expert_human_machine_per_question': expert_human_machine_per_question if expert_human_machine_per_question is not None and not expert_human_machine_per_question.empty else pd.DataFrame(),
        'model_ranking_summary': model_ranking_summary,
        'top20_questions': top20_df,
        'item_analysis_df': item_analysis_df,
        'dimension_stats': dimension_stats,
        'dimension_fail_tables': dimension_fail_tables or {},
        'd5_fail_by_l1': d5_by_l1_df if d5_by_l1_df is not None else pd.DataFrame(),
        'version_progression': version_progression,
        'thinking_comparison': thinking_comparison,
        'score_distribution': score_distribution_df if score_distribution_df is not None else pd.DataFrame(),
        'intent_level_analysis': intent_level_df,
        'primary_dim_col': primary_dim,
        'constraint_efficacy': constraint_result,
        'model_tiers': model_tiers,
        'intent_insights': intent_insights,
        'constraint_insights': constraint_insights,
        'scenario_guide': scenario_guide_df if scenario_guide_df is not None else pd.DataFrame(),
        'improvement_paths': improvement_paths,
        'rankings_source_scope': f'统计口径：{stats_scope_note}（案例分析阶段排除 R）',
    }
    panorama_df = _compute_panorama_ranking(data_for_stats)
    if not panorama_df.empty:
        data_cache['panorama_df'] = panorama_df
        print(f"  ✓ 全景总榜: {len(panorama_df)} 个模型")
    else:
        data_cache['panorama_df'] = pd.DataFrame()

    print(f'\n▶ 筛选价值题目进行深度分析（TOP{top_n_cases}）...')
    # 排除题目来源 source=R 的题（不进入典型案例）；优先选自建（H/HM/M）高难度高区分度题，公开数据也可选；每 L1 至少 2 题
    top20_for_cases = top20_df
    if not top20_df.empty and '数据来源' in top20_df.columns:
        src = top20_df['数据来源'].astype(str).str.strip().str.upper()
        top20_for_cases = top20_df[src != 'R'].copy()
        if top20_for_cases.empty:
            print('  提示：价值 TOP20 中题目来源均为 R，已全部排除，无典型案例候选')
        else:
            # 自建（H/HM/M）优先，再按综合价值分降序
            self_built = top20_for_cases['数据来源'].astype(str).str.strip().str.upper().isin(['H', 'HM', 'M'])
            top20_for_cases = top20_for_cases.assign(_自建优先=(~self_built).astype(int))
            val_col = '综合价值分'
            if val_col in top20_for_cases.columns:
                top20_for_cases[val_col] = pd.to_numeric(top20_for_cases[val_col], errors='coerce')
            sort_by = ['_自建优先', val_col] if val_col in top20_for_cases.columns else ['_自建优先']
            sort_asc = [True, False] if len(sort_by) == 2 else [True]
            top20_for_cases = top20_for_cases.sort_values(
                by=sort_by, ascending=sort_asc
            ).drop(columns=['_自建优先'], errors='ignore').reset_index(drop=True)
    expert_scores_df = data.get('expert_scores', pd.DataFrame())
    qids_with_expert = set(expert_scores_df['qid'].astype(str).unique()) if expert_scores_df is not None and not expert_scores_df.empty else set()
    candidate_qids = _select_typical_qids_by_l1(
        top20_for_cases, data.get('replies_with_question', pd.DataFrame()), top_n_cases
    )
    if qids_with_expert:
        candidate_qids = [q for q in candidate_qids if q in qids_with_expert]
        print(f'  仅分析有专家打分的题目: {len(candidate_qids)} 道（已从价值题中筛选）')
    else:
        candidate_qids = []
        print('  无专家打分数据，跳过典型案例深度分析')

    replies_df = data['replies']
    replies_with_q = data['replies_with_question']
    questions_df = data['questions']
    dimension_stats = data_cache.get('dimension_stats', {})
    row_level_df = dimension_stats.get('row_level_df', pd.DataFrame())
    dim_labels = dimension_stats.get('dimension_labels', {})

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

    # 聚焦模式下：用 LLM 总结「对比模型 vs 第一名」的失分差异与典型错误
    focus_model_loss_summary = {}
    if report_config.get('l1_loss_scope') == 'focus':
        ml_df = data_cache.get('model_l1_loss_profiles', pd.DataFrame())
        if ml_df is not None and not ml_df.empty:
            rank1 = None
            overall = data_cache.get('overall_ranking', pd.DataFrame())
            if not overall.empty and '模型' in overall.columns:
                rank1 = str(overall.iloc[0].get('模型', '')).strip()
            focus_list = list(report_config.get('focus_models_for_loss') or [])
            for fm in focus_list:
                fm = str(fm).strip()
                if fm and fm != rank1:
                    text = _build_focus_loss_summary_llm(client, model, ml_df, rank1 or '', fm, temperature, timeout)
                    if text:
                        focus_model_loss_summary[fm] = text
                    time.sleep(0.3)
            if focus_model_loss_summary:
                data_cache['focus_model_loss_summary'] = focus_model_loss_summary
                print(f"  ✓ 聚焦模型失分总结(LLM): {len(focus_model_loss_summary)} 个模型")

    print(f'\n▶ AI分析 {len(candidate_qids)} 道价值题目...')
    case_analyses = []

    def analyze_single_case(qid: str, _judge_model=model) -> Optional[dict]:
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
        difficulty_score = first_row.get('difficulty_score', '')
        if isinstance(difficulty_score, (int, float)) and not (isinstance(difficulty_score, float) and np.isnan(difficulty_score)):
            difficulty_score = f'{float(difficulty_score):.2f}'
        else:
            difficulty_score = safe_str(difficulty_score)
        source = safe_str(first_row.get('source', ''))
        score_range = float(q_replies['eval_score'].max() - q_replies['eval_score'].min()) if not q_replies['eval_score'].dropna().empty else 0

        dimension_info = ''
        if not row_level_df.empty and 'qid' in row_level_df.columns:
            q_rows = row_level_df[row_level_df['qid'].astype(str).str.strip() == str(qid).strip()]
            if not q_rows.empty:
                dim_order = ['D2', 'D3', 'D4', 'D5']
                lines = []
                for _, r in q_rows.iterrows():
                    model = r.get('model', '')
                    parts = []
                    for d in dim_order:
                        p, t = r.get(f'{d}_pass', 0), r.get(f'{d}_total', 0)
                        if t and t > 0:
                            label = dim_labels.get(d, d)
                            parts.append(f'{label}:{p}/{t}')
                    if parts:
                        lines.append(f'- {model}: ' + ' | '.join(parts))
                if lines:
                    dimension_info = '\n'.join(lines)

        model_scores = dict(q_replies.groupby('model')['eval_score'].mean().dropna())

        eval_col_candidates = [c for c in replies_df.columns if isinstance(c, str) and c.startswith('eval_') and c.endswith('_raw')]
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
        if not replies_with_q.empty:
            q_rows = replies_with_q[replies_with_q['qid'].astype(str).str.strip() == str(qid).strip()]
            if not q_rows.empty:
                insight = q_rows.iloc[0].get('专家洞察', '')
                if pd.notna(insight) and str(insight).strip():
                    expert_opinion = str(insight).strip()
        if not expert_opinion and not expert_scores_df.empty:
            expert_rows = expert_scores_df[expert_scores_df['qid'] == qid]
            if not expert_rows.empty:
                opinions = expert_rows['reason'].dropna().tolist()
                expert_opinion = ' | '.join([safe_str(o) for o in opinions if o])

        reference_answer = ''
        if not q_replies.empty:
            ref = q_replies.iloc[0].get('reference', '') or q_replies.iloc[0].get('参考答案', '')
            if pd.notna(ref) and str(ref).strip():
                reference_answer = str(ref).strip()

        tier_models = _compute_tier_models(model_scores, expert_scores_df, qid, num_tiers=3)
        sys_content, user_content = _build_case_analysis_prompt(
            qid=qid,
            query=query,
            evaluation_criteria=evaluation_criteria,
            model_scores=model_scores,
            model_evaluations=model_evaluations,
            model_replies=model_replies,
            expert_opinion=expert_opinion,
            tier_models=tier_models,
            l1=l1,
            l2=l2,
            l3=l3,
            difficulty=difficulty,
            source=source,
            difficulty_score=difficulty_score,
            dimension_info=dimension_info,
            reference_answer=reference_answer,
            sysprompt=report_sysprompt,
        )

        try:
            messages = [
                {'role': 'system', 'content': sys_content},
                {'role': 'user', 'content': user_content},
            ]
            response = client.chat(
                messages=messages,
                model=_judge_model,
                temperature=temperature,
                timeout=timeout,
                max_tokens=8192,
            )
            response_text = safe_str(response)
        except Exception as exc:
            print(f'    ⚠️ Q{qid} 分析失败: {exc}')
            response_text = ''

        ai_summary, ai_analysis = _parse_analysis_response(response_text)

        # 本题最佳得分与各模型与最佳的差距（便于厂商看与强模型差距）
        best_score = float(max(model_scores.values())) if model_scores else 0.0
        best_model = next((m for m, s in model_scores.items() if float(s) == best_score), None)
        model_gaps = {m: round(best_score - float(s), 2) for m, s in model_scores.items()}

        return {
            'qid': qid,
            'query': query,
            'L1': l1,
            'L2': l2,
            'L3': l3,
            'difficulty_level': difficulty,
            'difficulty_score': difficulty_score,
            'score_range': score_range,
            'model_scores': model_scores,
            'model_replies': model_replies,
            'model_evaluations': model_evaluations,
            'tier_models': tier_models,
            'expert_opinion': expert_opinion,
            'ai_summary': ai_summary,
            'ai_analysis': ai_analysis,
            'best_score': best_score,
            'best_model': best_model,
            'model_gaps': model_gaps,
            'dimension_info': dimension_info,
        }

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(analyze_single_case, qid): qid for qid in candidate_qids}
        for future in tqdm(as_completed(futures), total=len(futures), desc='分析进度'):
            result = future.result()
            if result:
                case_analyses.append(result)

    case_analyses.sort(key=lambda x: x.get('score_range', 0), reverse=True)

    print('\n▶ L1 意图能力总结（LLM 分析）...')
    l1_summaries = _build_l1_capability_summaries(
        client=client,
        data_cache=data_cache,
        model=model,
        temperature=temperature,
        timeout=timeout,
    )
    data_cache['l1_capability_summaries'] = l1_summaries
    if l1_summaries:
        print(f'  ✓ 已生成 {len(l1_summaries)} 个 L1 能力总结')

    print('\n▶ 图表解读（LLM 约100字/图）...')
    chart_insights = _build_chart_insights(client, model, data, data_cache, temperature, timeout)
    data_cache['chart_insights'] = chart_insights
    if chart_insights:
        print(f'  ✓ 已生成 {len(chart_insights)} 张图表的解读')

    if use_report_cache:
        _save_report_cache(
            cache_path, data, data_cache, case_analyses,
            questions_excel, replies_excel, eval_batch_id, top_n_cases, model_list,
            report_cache_key=report_cache_key,
        )

    print(f'\n▶ 生成报告文件...')
    os.makedirs(output_dir, exist_ok=True)
    from datetime import datetime
    timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    prefix = report_filename_prefix or 'evaluation_report'

    output_md = os.path.join(output_dir, f'{prefix}_{timestamp_str}.md')
    generate_markdown_report(
        output_md=output_md,
        data=data,
        data_cache=data_cache,
        case_analyses=case_analyses,
        report_title=report_title,
    )

    output_html = None
    if generate_html:
        output_html = os.path.join(output_dir, f'{prefix}_{timestamp_str}.html')
        generate_html_report(
            output_html=output_html,
            data=data,
            data_cache=data_cache,
            case_analyses=case_analyses,
            report_title=report_title,
        )
        print(f'  HTML: {output_html}')

    _framework_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        'docs', 'EVAL_REPORT_FRAMEWORK.md'
    )
    if sync_framework_with_report_stats(data, data_cache, _framework_path):
        print(f'  ✓ EVAL_REPORT_FRAMEWORK.md 已同步本次统计')

    print(f'\n✓ 报告生成完成！')
    print(f'  Markdown: {output_md}')
    print('=' * 60)

    return {'html': output_html, 'markdown': output_md}

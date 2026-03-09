# -*- coding: utf-8 -*-
"""
专家评估汇总：从回复表第二个 sheet 读专家打分，用 LLM 归纳为「专家洞察」写入题目表。
注入裁判时使用精炼后的洞察，替代原样罗列三十多 models 的原始打分，提升参考价值。
"""
from typing import Dict, Optional

import pandas as pd

from ..core.utils import safe_str, safe_save_excel
from clients.openai_client import OAIClient
from config import get_provider


EXPERT_SUMMARY_SYSPROMPT = """你是一位专业的 AI 评测分析师。请根据专家对同一题目下多份模型回复的打分与意见，归纳总结出精炼的「专家洞察」，供后续裁判模型对齐尺度时参考。

归纳要点：
1. **打分偏好与力度**：专家整体偏严/偏松，各分数段的典型特征
2. **核心问题点**：专家最关注、最容易扣分的几类问题（与 D 维度或约束对应更佳）
3. **思路与尺度**：专家判断「好回复」vs「差回复」的主要区分逻辑

输出格式（200-400 字，简洁专业）：
【打分偏好】...
【核心问题点】...
【尺度与思路】...
"""


def _aggregate_expert_per_qid(expert_df: pd.DataFrame) -> Dict[str, str]:
    """按 qid 聚合专家打分与理由。"""
    if expert_df.empty or 'qid' not in expert_df.columns:
        return {}
    has_score = '专家打分' in expert_df.columns
    has_reason = '专家理由' in expert_df.columns
    has_opinion = '专家意见' in expert_df.columns
    if not (has_score or has_reason or has_opinion):
        return {}

    out = {}
    for qid, grp in expert_df.groupby('qid'):
        lines = []
        for _, r in grp.iterrows():
            model_name = safe_str(r.get('model', ''))
            score_val = r.get('专家打分') if has_score else None
            reason_val = r.get('专家理由') if has_reason else (r.get('专家意见') if has_opinion else None)
            if pd.isna(score_val) and (pd.isna(reason_val) or not str(reason_val).strip()):
                continue
            part = f"模型 {model_name}:"
            if score_val is not None and not (isinstance(score_val, float) and pd.isna(score_val)):
                part += f" 得分 {score_val}"
            if reason_val is not None and str(reason_val).strip() and str(reason_val).lower() not in ('nan', 'none', ''):
                part += f"; 意见: {safe_str(reason_val)[:600]}"
            lines.append(part)
        if lines:
            out[str(qid).strip()] = "\n".join(lines)
    return out


def summarize_expert_assessments(
    replies_excel: str,
    questions_excel: str,
    output_questions_excel: Optional[str] = None,
    provider: str = '',
    model: str = '',
    temperature: float = 0.3,
    timeout: int = 120,
) -> int:
    """
    从回复表第二个 sheet 读专家评估，LLM 归纳后写入题目表「专家洞察」列。
    :return: 成功归纳的题目数
    """
    def _normalize_qid(val):
        s = str(val).strip()
        try:
            f = float(s)
            if not pd.isna(f) and f == int(f):
                return str(int(f))
        except (ValueError, TypeError):
            pass
        return s

    xls = pd.ExcelFile(replies_excel)
    sheet_names = xls.sheet_names
    expert_df = pd.DataFrame()
    for name in sheet_names:
        if name in ('Sheet1', 'replies', 'batch_log', 'Batch_log'):
            continue
        df = pd.read_excel(replies_excel, sheet_name=name)
        if 'qid' in df.columns and 'model' in df.columns and ('专家打分' in df.columns or '专家理由' in df.columns or '专家意见' in df.columns):
            expert_df = df
            break
    if expert_df.empty and len(sheet_names) >= 2:
        cand = sheet_names[1]
        if cand not in ('batch_log', 'Batch_log'):
            df = pd.read_excel(replies_excel, sheet_name=cand)
            if 'qid' in df.columns and 'model' in df.columns and ('专家打分' in df.columns or '专家理由' in df.columns or '专家意见' in df.columns):
                expert_df = df

    if expert_df.empty:
        print("  ⚠️ 回复表无专家评估 sheet（需含 qid, model, 专家打分/专家理由/专家意见）")
        return 0

    expert_df['qid'] = expert_df['qid'].astype(str).str.strip().map(_normalize_qid)
    expert_per_qid = _aggregate_expert_per_qid(expert_df)
    if not expert_per_qid:
        print("  ⚠️ 专家表中无有效打分或理由")
        return 0

    questions_df = pd.read_excel(questions_excel)
    questions_df['qid'] = questions_df['qid'].astype(str).str.strip().map(_normalize_qid)
    if '专家洞察' not in questions_df.columns:
        questions_df['专家洞察'] = ''

    qid_to_query = {}
    if 'query' in questions_df.columns:
        for _, r in questions_df.iterrows():
            qid_to_query[str(r['qid'])] = safe_str(r.get('query', ''))[:500]

    pc = get_provider(provider)
    client = OAIClient(
        base_url=pc.base_url,
        api_key=pc.api_key,
        protocol=pc.protocol,
        auth_header=pc.auth_header,
        auth_prefix=pc.auth_prefix,
        extra_headers=getattr(pc, 'extra_headers', None) or {},
        timeout=timeout,
    )
    eval_model = model or getattr(pc, 'model', 'claude-sonnet-4-20250514')

    success_count = 0
    for qid, raw_text in expert_per_qid.items():
        query_preview = qid_to_query.get(qid, '')[:200]
        user_content = f"""题目ID: {qid}

【题目内容（节选）】
{query_preview}

【专家对本题目各模型回复的评分与意见】
{raw_text}

请按 sysprompt 要求归纳总结。"""

        try:
            messages = [
                {'role': 'system', 'content': EXPERT_SUMMARY_SYSPROMPT},
                {'role': 'user', 'content': user_content},
            ]
            resp = client.chat(messages=messages, model=eval_model, temperature=temperature, timeout=timeout)
            insight = safe_str(resp).strip()[:2000]
            if insight and not insight.startswith('<error'):
                mask = questions_df['qid'] == qid
                if mask.any():
                    questions_df.loc[mask, '专家洞察'] = insight
                    success_count += 1
        except Exception as e:
            print(f"    ⚠️ Q{qid} 归纳失败: {e}")

    out_path = output_questions_excel or questions_excel
    safe_save_excel(questions_df, out_path)
    print(f"  ✓ 专家洞察已写入题目表: {out_path}  共 {success_count}/{len(expert_per_qid)} 题")
    return success_count


def batch_summarize_expert_assessments(
    replies_excel: str,
    questions_excel: str,
    output_questions_excel: Optional[str] = None,
    provider: str = '',
    model: str = '',
    temperature: float = 0.3,
    max_workers: int = 2,
    timeout: int = 120,
) -> int:
    """并发归纳专家评估（可扩展；当前单线程逐题调用）。"""
    return summarize_expert_assessments(
        replies_excel=replies_excel,
        questions_excel=questions_excel,
        output_questions_excel=output_questions_excel,
        provider=provider,
        model=model,
        temperature=temperature,
        timeout=timeout,
    )

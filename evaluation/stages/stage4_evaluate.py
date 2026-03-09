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
from ..core.cache_messages import build_cached_messages, detect_provider_type
from ..managers.sysprompt import SyspromptManager


def is_evaluated(value) -> bool:
    if pd.isna(value):
        return False
    if isinstance(value, (int, float)):
        return not np.isnan(value)
    value_str = str(value).strip().lower()
    if value_str in ('', 'nan', 'none', 'null', 'na', '<na>'):
        return False
    return not value_str.startswith('<error')


def extract_scores_from_evaluation(eval_text: str) -> Dict[str, float]:
    scores = {}
    if not eval_text or not isinstance(eval_text, str):
        return scores

    # 优先解析 JSON 中的 FINAL_SCORE（如 "60% (18/30)"），取百分号前的数字
    try:
        text = eval_text.strip()
        if text.startswith('{') or '{"FINAL_SCORE"' in text or '"FINAL_SCORE"' in text:
            # 提取 FINAL_SCORE 的值
            m = re.search(r'"FINAL_SCORE"\s*:\s*"(\d+)%\s*\(\d+/\d+\)"', text)
            if m:
                scores['total_score'] = float(m.group(1))
                return scores
            # 兼容 "FINAL_SCORE": "80" 或 "80%"
            m = re.search(r'"FINAL_SCORE"\s*:\s*"(\d+)(?:%)?[^"]*"', text)
            if m:
                scores['total_score'] = float(m.group(1))
                return scores
    except Exception:
        pass

    total_patterns = [
        r'总分[:：]\s*(\d+(?:\.\d+)?)\s*(?:/|分)',
        r'总分\s*=\s*(\d+(?:\.\d+)?)',
        r'总体得分[:：]\s*(\d+(?:\.\d+)?)',
        r'最终得分[:：]\s*(\d+(?:\.\d+)?)',
        r'score[:：]\s*(\d+(?:\.\d+)?)',
        r'分数[:：]\s*(\d+(?:\.\d+)?)',
        r'总得分[:：]\s*(\d+(?:\.\d+)?)'
    ]
    for pattern in total_patterns:
        match = re.search(pattern, eval_text, re.IGNORECASE)
        if match:
            try:
                scores['total_score'] = float(match.group(1))
                break
            except Exception:
                pass

    if 'total_score' not in scores:
        # 匹配 "60% (18/30)" 或 "80% (24/27)" 等格式（含 FINAL_SCORE 的 JSON 或纯文本）
        m = re.search(r'(\d+)%\s*\(\d+/\d+\)', eval_text)
        if m:
            scores['total_score'] = float(m.group(1))
        else:
            for pattern in [r'(\d+(?:\.\d+)?)\s*/\s*\d+(?:\.\d+)?\s*分',
                             r'(\d+(?:\.\d+)?)\s*分\s*/\s*\d+(?:\.\d+)?',
                             r'得分\s*(\d+(?:\.\d+)?)\s*分']:
                match = re.search(pattern, eval_text)
                if match:
                    try:
                        scores['total_score'] = float(match.group(1))
                        break
                    except Exception:
                        pass

    for pattern in [r'(\w+)[:：]\s*(\d+(?:\.\d+)?)\s*(?:/|分)',
                    r'(\w+)\s*=\s*(\d+(?:\.\d+)?)',
                    r'(\w+)\s*得分[:：]\s*(\d+(?:\.\d+)?)']:
        for key, value in re.findall(pattern, eval_text, re.IGNORECASE):
            try:
                scores[key.lower().replace(' ', '_')] = float(value)
            except Exception:
                pass

    return scores


def evaluate_single_reply_with_cache(
        client: OAIClient,
        eval_model: str,
        provider_type: str,
        sys_prompt: str,
        query: str,
        evaluation_criteria: str,
        reference: str,
        reply: str,
        model_name: str,
        reference_type: str = 'model',
        temperature: float = 0.3,
        retries: int = 3,
        history_context: str = '',
        expert_opinions: str = '',
) -> Tuple[str, str]:
    messages = build_cached_messages(
        provider_type, sys_prompt, query, evaluation_criteria,
        reference, reply, model_name, reference_type, history_context, expert_opinions
    )

    last_err = None
    for attempt in range(retries):
        try:
            kwargs = {"model": eval_model, "messages": messages, "temperature": temperature}

            if hasattr(client, "chat_with_meta"):
                try:
                    resp = client.chat_with_meta(**kwargs)
                    if isinstance(resp, dict):
                        eval_text = resp.get("text", "")
                    elif isinstance(resp, (tuple, list)) and len(resp) >= 2:
                        eval_text = resp[0]
                    else:
                        eval_text = str(resp)
                except Exception:
                    eval_text = client.chat(**kwargs)
            else:
                eval_text = client.chat(**kwargs)

            if eval_text and not eval_text.startswith("<error"):
                return eval_text, ""

        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                err_str = str(e).strip()
                # 命中资源限制/限流时延长等待再重试
                if "资源限制" in err_str or "限流" in err_str or "rate limit" in err_str.lower() or "quota" in err_str.lower():
                    wait = 30 + 20 * attempt  # 30s, 50s, 70s...
                    time.sleep(wait)
                else:
                    time.sleep(1.0 + (2 * attempt))

    return "", f"<error: {last_err}>"


def _sort_replies_by_qid_model(df: pd.DataFrame) -> pd.DataFrame:
    """按题目 qid、再按 model 排序，便于同一题集中对比。qid 按数值排（1,2,...,10 而非 1,10,2）。"""
    if df.empty or 'qid' not in df.columns or 'model' not in df.columns:
        return df
    out = df.copy()
    out['_qid_num'] = pd.to_numeric(out['qid'], errors='coerce')
    out = out.sort_values(by=['_qid_num', 'model']).drop(columns=['_qid_num'])
    return out


def _load_preserved_sheets(output_excel: str) -> dict:
    """读取需保留的 sheet（非 Sheet1/replies、batch_log），评估时只更新主表与 batch_log。"""
    if not os.path.exists(output_excel):
        return {}
    try:
        xls = pd.ExcelFile(output_excel)
        preserved = {}
        for name in xls.sheet_names:
            if name in ('Sheet1', 'replies', 'batch_log', 'Batch_log'):
                continue
            preserved[name] = pd.read_excel(output_excel, sheet_name=name)
        return preserved
    except Exception:
        return {}


def save_results(df_replies: pd.DataFrame, df_batch_log: pd.DataFrame,
                 results: List[dict], batch_id: str, output_excel: str,
                 main_sheet_name: str = 'Sheet1') -> bool:
    if '出题人' not in df_replies.columns:
        df_replies = df_replies.copy()
        df_replies['出题人'] = ''
    try:
        df_to_write = _sort_replies_by_qid_model(df_replies)
        temp_path = output_excel.replace('.xlsx', f'_temp_{int(time.time())}.xlsx')
        preserved = _load_preserved_sheets(output_excel)
        with pd.ExcelWriter(temp_path, engine='openpyxl') as writer:
            df_to_write.to_excel(writer, sheet_name=main_sheet_name, index=False)
            if not df_batch_log.empty:
                df_batch_log.to_excel(writer, sheet_name='batch_log', index=False)
            for name, frame in preserved.items():
                frame.to_excel(writer, sheet_name=name[:31], index=False)  # Excel sheet 名最长 31

        test_df = pd.read_excel(temp_path, sheet_name=main_sheet_name, nrows=5)
        if len(test_df) > 0:
            if os.path.exists(output_excel):
                os.replace(temp_path, output_excel)
            else:
                os.rename(temp_path, output_excel)
            if os.path.exists(temp_path):
                os.remove(temp_path)
            return True

        print(f"⚠️  保存的文件验证失败")
        return False

    except Exception as e:
        print(f"⚠️  保存结果失败: {e}")
        try:
            df_to_write = _sort_replies_by_qid_model(df_replies)
            preserved = _load_preserved_sheets(output_excel)
            with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
                df_to_write.to_excel(writer, sheet_name=main_sheet_name, index=False)
                if not df_batch_log.empty:
                    df_batch_log.to_excel(writer, sheet_name='batch_log', index=False)
                for name, frame in preserved.items():
                    frame.to_excel(writer, sheet_name=name[:31], index=False)
            return True
        except Exception as e2:
            print(f"❌ 简单保存也失败: {e2}")
            return False


def batch_evaluate_responses_with_cache(
        questions_excel: str,
        replies_excel: str,
        output_excel: str,
        provider: str,
        model: str,
        sysprompt_manager: SyspromptManager,
        batch_id: str = None,
        data_filters: dict = None,
        temperature: float = 0.3,
        max_workers: int = 5,
        checkpoint_interval: int = 10,
        timeout: int = 120,
        overwrite_mode: str = 'skip',
):
    print(f"\n{'=' * 60}")
    print(f"🚀 模块4: 批量评估回复（并发评估版）")
    print(f"{'=' * 60}\n")

    pc = get_provider(provider)
    client = OAIClient(
        base_url=pc.base_url, api_key=pc.api_key, protocol=pc.protocol,
        auth_header=pc.auth_header, auth_prefix=pc.auth_prefix,
        extra_headers=pc.extra_headers, timeout=timeout
    )
    print(f"✅ 客户端初始化成功\n")

    provider_type = detect_provider_type(provider, model)
    print(f"📋 Provider类型: {provider_type}  并发数: {max_workers}  覆盖策略: {overwrite_mode}")
    if provider_type in ('claude', 'openai', 'gemini'):
        print(f"✅ 支持Prompt Caching，将启用缓存优化")
    print()

    sys_prompt = sysprompt_manager.get('reply_evaluation', '')
    if not sys_prompt:
        print("⚠️  未配置 reply_evaluation sysprompt")

    df_questions = pd.read_excel(questions_excel)
    required_cols_q = ['qid', 'query', 'evaluation_criteria']
    missing_cols = [col for col in required_cols_q if col not in df_questions.columns]
    if missing_cols:
        raise ValueError(f"题目表缺少必需列: {', '.join(missing_cols)}")

    has_reference = 'reference' in df_questions.columns
    has_reference_type = 'reference_type' in df_questions.columns
    has_history_context = 'history_context' in df_questions.columns
    print(f"  题目数量: {len(df_questions)}  包含参考答案: {'是' if has_reference else '否'}  多轮对话: {'是' if has_history_context else '否'}\n")

    try:
        xls = pd.ExcelFile(replies_excel)
        sheet_names = xls.sheet_names
        print(f"  发现sheet: {sheet_names}")

        target_sheet = next((s for s in ('Sheet1', 'replies') if s in sheet_names), sheet_names[0])
        df_replies = pd.read_excel(replies_excel, sheet_name=target_sheet)
        print(f"  从{target_sheet}读取回复表: {len(df_replies)} 行")

        batch_log_sheet = next((s for s in ('batch_log', 'batch_logs') if s in sheet_names), None)
        df_batch_log = (
            pd.read_excel(replies_excel, sheet_name=batch_log_sheet)
            if batch_log_sheet
            else pd.DataFrame(columns=['batch_id', 'timestamp', 'total_tasks', 'completed',
                                       'failed', 'eval_model', 'temperature', 'max_workers'])
        )
    except Exception as e:
        print(f"⚠️  读取Excel文件失败，尝试直接读取: {e}")
        df_replies = pd.read_excel(replies_excel)
        df_batch_log = pd.DataFrame(columns=['batch_id', 'timestamp', 'total_tasks', 'completed',
                                              'failed', 'eval_model', 'temperature', 'max_workers'])

    required_cols_r = ['qid', 'model', 'reply']
    missing_cols = [col for col in required_cols_r if col not in df_replies.columns]
    if missing_cols:
        raise ValueError(f"回复表缺少必需列: {', '.join(missing_cols)}")

    def _normalize_qid_for_merge(val):
        """统一 qid 格式便于关联：Excel 读成 400.0 的转为 \"400\"，与回复表的 \"1\" \"2\" 一致。"""
        s = str(val).strip()
        try:
            f = float(s)
            if not np.isnan(f) and f == int(f):
                return str(int(f))
        except (ValueError, TypeError):
            pass
        return s

    def _inject_anchor_replies_from_questions(df_replies: pd.DataFrame, df_questions: pd.DataFrame) -> pd.DataFrame:
        """
        从题目表中的 reference/reply1/reply2 锚点自动整理到回复表中：
          - reference          → model='ref'，分数取 ref_score / reference_score / 参考得分
          - reply1, reply2     → 使用 reply1_model / reply2_model 作为 model
          - reply*_score/reason → 写入 专家打分 / 专家理由，并保留题目表中的「专家」列作为 rater
        题目表中的专家分数（含 ref、reply1、reply2）均同步到回复表，供人机一致性计算使用。
        已存在的 (qid, model) 行会被补充专家信息；不存在则新增一行。
        """
        if 'qid' not in df_questions.columns:
            return df_replies

        df_replies = df_replies.copy()
        df_questions = df_questions.copy()
        df_replies['qid'] = df_replies['qid'].astype(str).str.strip().map(_normalize_qid_for_merge)
        df_replies['model'] = df_replies['model'].astype(str).str.strip()
        df_questions['qid'] = df_questions['qid'].astype(str).str.strip().map(_normalize_qid_for_merge)

        has_expert_col = '专家' in df_questions.columns

        def _coerce_score(val):
            """题目表分数转为 float；支持纯数字或「57 是否指出...」「62% (8/13)」等混排，取首个有效数字。"""
            if val is None or pd.isna(val):
                return None
            s = str(val).strip()
            if not s or s.lower() in ('nan', 'none', 'null', '-', '—'):
                return None
            try:
                f = float(s)
                return f if not np.isnan(f) else None
            except (ValueError, TypeError):
                pass
            # 混排时取首个数字（如 "57 是否指出..." -> 57；"62% (8/13)" -> 62）
            m = re.search(r'(\d+)\s*%?', s)
            if m:
                try:
                    return float(m.group(1))
                except (ValueError, TypeError):
                    pass
            return None

        def _upsert_row(qid, model_name, reply_text, score_val, reason_val, expert_name):
            nonlocal df_replies
            if model_name is None and reply_text is None:
                return
            if model_name is None or not str(model_name).strip():
                return
            model_name_str = str(model_name).strip()
            qid_str = str(qid).strip()
            # 题目表 reply 为空/NaN/占位字符串时，不向回复表生成行
            if reply_text is None:
                return
            if isinstance(reply_text, float) and np.isnan(reply_text):
                return
            reply_text_str = str(reply_text).strip()
            if not reply_text_str or reply_text_str.lower() in ('nan', 'none'):
                return
            score_val = _coerce_score(score_val)

            mask = (df_replies['qid'] == qid_str) & (df_replies['model'] == model_name_str)
            if mask.any():
                idx = df_replies.index[mask][0]
                if 'reply' in df_replies.columns:
                    df_replies.at[idx, 'reply'] = reply_text_str
                if score_val is not None and not (isinstance(score_val, float) and np.isnan(score_val)):
                    df_replies.at[idx, '专家打分'] = score_val
                if reason_val is not None and str(reason_val).strip():
                    df_replies.at[idx, '专家理由'] = str(reason_val)
                if expert_name and has_expert_col:
                    df_replies.at[idx, '专家'] = str(expert_name)
            else:
                row = {
                    'qid': qid_str,
                    'model': model_name_str,
                    'reply': reply_text_str,
                }
                if score_val is not None and not (isinstance(score_val, float) and np.isnan(score_val)):
                    row['专家打分'] = score_val
                if reason_val is not None and str(reason_val).strip():
                    row['专家理由'] = str(reason_val)
                if expert_name and has_expert_col:
                    row['专家'] = str(expert_name)
                df_replies = pd.concat([df_replies, pd.DataFrame([row])], ignore_index=True)

        for _, q in df_questions.iterrows():
            qid = q.get('qid')
            expert_name = q.get('专家') if has_expert_col else None

            # reference 视作 model='ref'；无题目表分数时默认专家认为参考回复 100 分；支持列名 reference/参考/参考答案
            ref_text_col = next((c for c in ['reference', 'reference_answer', '参考', '参考答案', '参考回复'] if c in df_questions.columns), None)
            if ref_text_col:
                ref_text = q.get(ref_text_col, None)
                if pd.notna(ref_text) and str(ref_text).strip():
                    ref_score = _coerce_score(
                        next((q.get(c) for c in ['ref_score', 'reference_score', '参考得分', 'ref分数', '参考分数'] if c in df_questions.columns and pd.notna(q.get(c))), None)
                    )
                    if ref_score is None:
                        ref_score = 100.0
                    ref_reason = next((q.get(c) for c in ['ref_reason', 'reference_reason', '参考理由'] if c in df_questions.columns and pd.notna(q.get(c)) and str(q.get(c)).strip()), None)
                    ref_reason = str(ref_reason).strip() if ref_reason is not None else None
                    _upsert_row(qid, 'ref', ref_text, ref_score, ref_reason, expert_name)

            # reply1 / reply2 锚点；支持多列名：reply1/回复1、reply1_score/回复1得分/评估1 等
            for idx_anchor in (1, 2):
                text_candidates = [f'reply{idx_anchor}', f'回复{idx_anchor}', f'回复{"一二"[idx_anchor-1]}']
                r_col = next((c for c in text_candidates if c in df_questions.columns), None)
                if r_col is None:
                    continue
                reply_text = q.get(r_col, None)
                model_candidates = [f'reply{idx_anchor}_model', f'回复{idx_anchor}_model', f'回复{idx_anchor}模型']
                m_col = next((c for c in model_candidates if c in df_questions.columns), None)
                model_name = q.get(m_col, None) if m_col else None
                score_candidates = [f'reply{idx_anchor}_score', f'回复{idx_anchor}得分', f'评估{idx_anchor}', f'得分{idx_anchor}', f'评估结果{idx_anchor}']
                score_val = next((q.get(c) for c in score_candidates if c in df_questions.columns and pd.notna(q.get(c))), None)
                score_val = _coerce_score(score_val) if score_val is not None else None
                reason_col = next((c for c in [f'reply{idx_anchor}_reason', f'回复{idx_anchor}_reason'] if c in df_questions.columns), None)
                reason_val = q.get(reason_col, None) if reason_col else None
                if pd.isna(model_name) and (reply_text is None or (isinstance(reply_text, float) and np.isnan(reply_text))):
                    continue
                _upsert_row(qid, model_name, reply_text, score_val, reason_val, expert_name)

        return df_replies

    df_replies['qid'] = df_replies['qid'].astype(str).str.strip().map(_normalize_qid_for_merge)

    # 从题目表把 reference / reply1 / reply2 及分数正确传到回复表（含专家打分与理由）；ref 默认满分 100
    df_replies = _inject_anchor_replies_from_questions(df_replies, df_questions)
    ref_count = ((df_replies['model'].astype(str).str.strip().str.lower() == 'ref').sum() if 'model' in df_replies.columns else 0)
    if ref_count > 0:
        print(f"  📌 题目表 ref/reply1/reply2 已注入回复表: ref 共 {ref_count} 条（默认专家打分=100），将参与裁判评估")

    # 出题人 = 题目表【专家】或【出题人】列，按 qid 写入回复表；统计阶段仅基于回复表即可
    df_questions['qid'] = df_questions['qid'].astype(str).str.strip().map(_normalize_qid_for_merge)
    expert_source_col = next((c for c in ['专家', '出题人'] if c in df_questions.columns), None)
    if expert_source_col:
        qid_to_expert = df_questions.drop_duplicates('qid').set_index('qid')[expert_source_col].astype(str)
        df_replies['出题人'] = df_replies['qid'].map(qid_to_expert)
        n_with = (df_replies['出题人'].notna() & (df_replies['出题人'].astype(str).str.strip() != '')).sum()
        if n_with > 0:
            print(f"  📌 已按 qid 将题目表【{expert_source_col}】写入回复表「出题人」列，共 {n_with} 条")
    else:
        df_replies['出题人'] = ''
        print(f"  ⚠️  题目表无「专家」或「出题人」列，已建空列，请补题目表后重跑以填充")

    # 传递核对：题目表 vs 回复表 (qid, 专家打分) 对应情况
    if '专家打分' in df_replies.columns:
        n_reply_score = df_replies['专家打分'].notna().sum()
        qids_with_score = df_replies.loc[df_replies['专家打分'].notna(), 'qid'].nunique()
        print(f"  📌 核对: 回复表中 专家打分 非空 {n_reply_score} 条，涉及 {qids_with_score} 题（统计将仅基于回复表 qid/reply/专家打分/出题人）")

    # 若第一个 sheet 无专家列，尝试从第二个 sheet 加载专家评估并合并（供裁判 prompt 使用）
    if '专家打分' not in df_replies.columns and '专家理由' not in df_replies.columns:
        for sh_name in sheet_names:
            if sh_name in ('Sheet1', 'replies', 'batch_log', 'Batch_log'):
                continue
            ex_df = pd.read_excel(replies_excel, sheet_name=sh_name)
            if 'qid' in ex_df.columns and 'model' in ex_df.columns and ('专家打分' in ex_df.columns or '专家理由' in ex_df.columns):
                ex_df = ex_df.copy()
                ex_df['qid'] = ex_df['qid'].astype(str).str.strip().map(_normalize_qid_for_merge)
                ex_df['model'] = ex_df['model'].astype(str).str.strip()
                ex_cols = [c for c in ['专家打分', '专家理由', '专家意见'] if c in ex_df.columns]
                ex_sub = ex_df[['qid', 'model'] + ex_cols].drop_duplicates(subset=['qid', 'model'], keep='first')
                df_replies = df_replies.merge(ex_sub, on=['qid', 'model'], how='left')
                print(f"  📌 从 sheet「{sh_name}」加载专家评估 {len(ex_sub)} 条，已合并")
                break

    df_replies['model'] = df_replies['model'].astype(str).str.strip()
    df_questions['qid'] = df_questions['qid'].astype(str).str.strip().map(_normalize_qid_for_merge)

    # 专家洞察来源优先级：题目表「专家洞察」列（LLM 归纳）> 回复表专家 sheet 原始汇总
    # 题目表专家洞察：由 summarize_expert_assessments 阶段生成，精炼后注入更有效
    expert_insight_from_questions: Dict[str, str] = {}
    if '专家洞察' in df_questions.columns:
        for _, r in df_questions.iterrows():
            qid = str(r['qid']).strip()
            insight = r.get('专家洞察', '')
            if pd.notna(insight) and str(insight).strip() and str(insight).lower() not in ('nan', 'none', ''):
                expert_insight_from_questions[qid] = str(insight).strip()[:2000]

    # 按题目汇总原始专家评估（当题目表无专家洞察时使用）
    raw_expert_per_qid: Dict[str, str] = {}
    has_expert_score = '专家打分' in df_replies.columns
    has_expert_reason = '专家理由' in df_replies.columns
    has_expert_opinion = '专家意见' in df_replies.columns
    if has_expert_score or has_expert_reason or has_expert_opinion:
        for qid, grp in df_replies.groupby('qid'):
            lines = []
            for _, r in grp.iterrows():
                score_val = r.get('专家打分') if has_expert_score else None
                reason_val = r.get('专家理由') if has_expert_reason else (r.get('专家意见') if has_expert_opinion else None)
                if pd.isna(score_val) and (pd.isna(reason_val) or not str(reason_val).strip()):
                    continue
                model_name_val = safe_str(r.get('model', ''))
                part = f"模型 {model_name_val}:"
                if score_val is not None and not (isinstance(score_val, float) and np.isnan(score_val)):
                    part += f" 得分 {score_val}"
                if reason_val is not None and str(reason_val).strip() and str(reason_val).lower() not in ('nan', 'none', ''):
                    part += f"; 专家意见: {safe_str(reason_val)[:500]}"
                lines.append(part)
            if lines:
                raw_expert_per_qid[str(qid).strip()] = "\n".join(lines)

    expert_opinions_per_qid: Dict[str, str] = {}
    for qid in set(expert_insight_from_questions) | set(raw_expert_per_qid):
        if qid in expert_insight_from_questions:
            expert_opinions_per_qid[qid] = expert_insight_from_questions[qid]
        else:
            expert_opinions_per_qid[qid] = raw_expert_per_qid.get(qid, '')
    # 以少博大：无本题专家时，用同 L2 类型的专家洞察作为参考（迁移视角）
    l2_to_insight: Dict[str, str] = {}
    if 'L2' in df_questions.columns and expert_opinions_per_qid:
        qid_to_l2 = dict(zip(df_questions['qid'].astype(str), df_questions['L2'].astype(str)))
        for qid, insight in expert_opinions_per_qid.items():
            l2 = qid_to_l2.get(qid, '').strip()
            if l2 and l2 not in l2_to_insight:
                l2_to_insight[l2] = f"【同类型（L2={l2}）题目专家洞察参考】\n{insight[:1500]}"
    if expert_opinions_per_qid:
        insight_count = sum(1 for q in expert_opinions_per_qid if q in expert_insight_from_questions)
        if insight_count:
            print(f"  📌 已加载 {len(expert_opinions_per_qid)} 题的专家参考（其中 {insight_count} 题为 LLM 归纳的专家洞察）")
        else:
            print(f"  📌 已加载 {len(expert_opinions_per_qid)} 题的专家评估示范，将作为裁判参考锚点")

    eval_columns = [col for col in df_replies.columns if isinstance(col, str) and col.startswith('eval_')]
    print(f"\n📊 回复表列名: {list(df_replies.columns)}")
    print(f"  发现评估列: {eval_columns}")

    df_merged = df_replies.merge(df_questions, on='qid', how='left')
    missing_questions = df_merged['query'].isna().sum()
    if missing_questions > 0:
        print(f"⚠️  警告: {missing_questions} 条回复找不到对应题目，将不参与评估（无法补齐这些行的分数）")
        if missing_questions == len(df_merged) and len(df_merged) > 0:
            q_reply = df_replies['qid'].drop_duplicates().head(5).tolist()
            q_quest = df_questions['qid'].drop_duplicates().head(5).tolist()
            print(f"  📌 诊断: 题目表 qid 样例（共 {len(df_questions)} 题）: {q_quest}")
            print(f"  📌 诊断: 回复表 qid 样例（共 {df_replies['qid'].nunique()} 个不同 qid）: {q_reply}")
            print(f"  📌 请检查两表是否同一批题目、qid 格式是否一致（如 1 vs \"1\"、\"Q1\" vs \"1\"、避免 Excel 把数字读成 1.0）")
        df_merged = df_merged[df_merged['query'].notna()]
    print(f"  关联后参与评估的数据量: {len(df_merged)} 条\n")

    if has_history_context and 'session_id' in df_questions.columns and 'turn_id' in df_questions.columns:
        print(f"  🔄 检测到多轮对话数据，按 session_id + turn_id 排序")
        df_merged = df_merged.sort_values(
            by=['session_id', 'turn_id'],
            key=lambda col: col.fillna('').astype(str) if col.name == 'session_id' else col.fillna(0).astype(int)
        ).reset_index(drop=True)

    if data_filters:
        original_count = len(df_merged)
        # 若启用 expert_qids_only，仅重评有专家评估的题目（充分利用专家洞察，可换裁判模型再测一遍）
        if data_filters.get('expert_qids_only') and expert_opinions_per_qid:
            expert_qids = [str(q).strip() for q in expert_opinions_per_qid.keys()]
            df_merged = df_merged[df_merged['qid'].isin(expert_qids)]
            print(f"  📌 仅重评有专家评估的题目: {len(expert_qids)} 题 | 数据量 {original_count} → {len(df_merged)} 条")
            original_count = len(df_merged)
        if data_filters.get('qid_list'):
            qid_list = [str(q).strip() for q in data_filters['qid_list']]
            df_merged = df_merged[df_merged['qid'].isin(qid_list)]
            print(f"  📌 按QID筛选: {original_count} → {len(df_merged)} 条")
            original_count = len(df_merged)
        if data_filters.get('model_list'):
            model_list = [str(m).strip() for m in data_filters['model_list']]
            df_merged = df_merged[df_merged['model'].isin(model_list)]
            print(f"  📌 按模型筛选: {original_count} → {len(df_merged)} 条")
            original_count = len(df_merged)
        if data_filters.get('reference_type') and has_reference_type:
            df_merged = df_merged[df_merged['reference_type'].isin(data_filters['reference_type'])]
            print(f"  📌 按参考类型筛选: {original_count} → {len(df_merged)} 条")
            original_count = len(df_merged)
        if data_filters.get('batch_size') and len(df_merged) > data_filters['batch_size']:
            df_merged = df_merged.head(data_filters['batch_size'])
            print(f"  📌 限制批次大小: {original_count} → {len(df_merged)} 条")
        print(f"  ✅ 筛选后数据量: {len(df_merged)} 条\n")

    if len(df_merged) == 0:
        print("⚠️  筛选后无数据需要处理")
        return

    if not batch_id:
        batch_id = f"eval_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}"
    print(f"📋 评估批次ID: {batch_id}")

    eval_column = f"eval_{batch_id}"
    eval_raw_column = f"{eval_column}_raw"

    # 补齐模式：若指定列不存在，尝试与已有评估列名对齐（如 batch_1 ↔ eval_batch1）
    if eval_column not in df_replies.columns and overwrite_mode == 'skip':
        eval_cols = [c for c in df_replies.columns if isinstance(c, str) and c.startswith('eval_') and not c.endswith('_raw')]
        alt = batch_id.replace('_', '')  # batch_1 -> batch1
        alt2 = batch_id.replace('batch', 'batch_') if 'batch' in batch_id else batch_id  # batch1 -> batch_1
        for cand in [f"eval_{alt}", f"eval_{alt2}"]:
            if cand != eval_column and cand in df_replies.columns:
                eval_column = cand
                eval_raw_column = f"{eval_column}_raw"
                print(f"  📌 补齐模式：将写入已有列 {eval_column}（与 batch_id 对应）")
                break

    if eval_column in df_replies.columns:
        existing_mask = df_replies[eval_column].apply(is_evaluated)
        if eval_raw_column in df_replies.columns:
            existing_mask = existing_mask | df_replies[eval_raw_column].apply(is_evaluated)
        existing_evaluated = existing_mask.sum()
        print(f"📊 发现已有评估列: {eval_column}  已评估: {existing_evaluated} 条")

        if existing_evaluated > 0:
            if overwrite_mode == 'overwrite':
                print(f"  ⚠️  overwrite_mode=overwrite，将覆盖所有已有评估结果")
                df_replies[eval_column] = np.nan
                if eval_raw_column in df_replies.columns:
                    df_replies[eval_raw_column] = ''
            elif overwrite_mode == 'new_batch':
                batch_id = f"eval_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}"
                eval_column = f"eval_{batch_id}"
                eval_raw_column = f"{eval_column}_raw"
                print(f"  🆕 overwrite_mode=new_batch，新批次ID: {batch_id}")
            else:
                print(f"  ✅ overwrite_mode=skip，跳过已有评估，只评估空白数据")

    if eval_column not in df_replies.columns:
        df_replies[eval_column] = np.nan
        print(f"  📌 列 {eval_column} 不存在，已新建（将评估全部合并数据）")
    if eval_raw_column not in df_replies.columns:
        df_replies[eval_raw_column] = ''

    df_merged_reset = df_merged.reset_index(drop=True)
    already_evaluated = 0
    tasks = []
    seen_qm = set()  # 按 (qid, model) 去重，题目表可能同一 qid 多行导致合并后重复

    for i, row in df_merged_reset.iterrows():
        qid = str(row['qid']).strip()
        model_name = str(row['model']).strip()
        if (qid, model_name) in seen_qm:
            continue
        seen_qm.add((qid, model_name))
        reply_mask = (df_replies['qid'] == qid) & (df_replies['model'] == model_name)

        if not reply_mask.any():
            continue

        reply_idx = df_replies[reply_mask].index[0]
        eval_value = df_replies.loc[reply_idx, eval_column]
        raw_value = df_replies.loc[reply_idx, eval_raw_column] if eval_raw_column in df_replies.columns else np.nan

        if is_evaluated(eval_value) or is_evaluated(raw_value):
            already_evaluated += 1
            continue

        history_context_value = ''
        if has_history_context and 'history_context' in row.index:
            raw_hc = row['history_context']
            if not pd.isna(raw_hc):
                history_context_value = str(raw_hc)

        expert_opinions_text = expert_opinions_per_qid.get(qid, '')
        if not expert_opinions_text and l2_to_insight and 'L2' in row.index:
            l2_val = str(row.get('L2', '')).strip()
            expert_opinions_text = l2_to_insight.get(l2_val, '')
        tasks.append({
            'merged_index': i, 'qid': qid, 'model': model_name,
            'query': safe_str(row['query']),
            'evaluation_criteria': safe_str(row['evaluation_criteria']),
            'reference': safe_str(row['reference']) if has_reference else '',
            'reference_type': safe_str(row['reference_type']) if has_reference_type else 'model',
            'reply': safe_str(row['reply']),
            'history_context': history_context_value,
            'expert_opinions': expert_opinions_text,
            'batch_id': batch_id, 'eval_column': eval_column,
            'eval_raw_column': eval_raw_column, 'reply_idx': reply_idx
        })

    total_merged = len(seen_qm)
    print(f"📊 合并去重后: {total_merged} 条；将写入/补齐列: {eval_column}；已在该列有分数: {already_evaluated} 条，本次将评估: {len(tasks)} 条")
    if not tasks and total_merged > 0 and already_evaluated < total_merged:
        print(f"  💡 若预期有空白需补齐：请确认 CONFIG 中 batch_id 与回复表列名一致（列名为 eval_{{batch_id}}，如 batch_1 → eval_batch_1）；或检查上述「因无对应题目而丢弃」的回复是否包含待补齐行。")

    if not tasks:
        print("✅ 所有任务已完成（无空白需评估）")
        if '出题人' in df_replies.columns:
            print(f"  📌 保存回复表（含出题人列）至 {output_excel} 的「{target_sheet}」sheet")
        save_results(df_replies, df_batch_log, [], batch_id, output_excel, main_sheet_name=target_sheet)
        return

    print(f"\n⚡ 开始并发评估 ({max_workers} workers)...")
    print(f"   结果写入: {output_excel}  每 {checkpoint_interval} 条会保存一次，可关闭 Excel 后重新打开该文件查看进度。\n")

    def evaluate_task(task: dict) -> dict:
        try:
            row = df_merged_reset.iloc[task['merged_index']]
            # 评估 model='ref' 时 deliberately 不提供 reference，避免裁判偷懒直接对比给满分
            # 裁判须仅按 rubrics 评估，reference 满分为 rubrics 自洽性的真实检验
            is_ref_model = str(task.get('model', '')).strip().lower() == 'ref'
            ref_for_prompt = '' if is_ref_model else (safe_str(row['reference']) if has_reference else '')
            raw_eval, error_msg = evaluate_single_reply_with_cache(
                client, model, provider_type, sys_prompt,
                safe_str(row['query']), safe_str(row['evaluation_criteria']),
                ref_for_prompt,
                safe_str(row['reply']), task['model'],
                safe_str(row['reference_type']) if has_reference_type else 'model',
                temperature, retries=5,
                history_context=task.get('history_context', ''),
                expert_opinions=task.get('expert_opinions', ''),
            )

            if error_msg:
                return {'qid': task['qid'], 'model': task['model'], 'batch_id': task['batch_id'],
                        'raw_evaluation': error_msg, 'scores': {}, 'total_score': np.nan,
                        'error': error_msg, 'status': 'error', 'reply_idx': task['reply_idx'],
                        'eval_column': task['eval_column'], 'eval_raw_column': task['eval_raw_column']}

            # 评估阶段只写裁判解析的总分，快；维度加权分在分析阶段从 raw 算，用于排名/报告并可对比
            scores = extract_scores_from_evaluation(raw_eval)
            total_score = scores.get('total_score', np.nan)
            return {'qid': task['qid'], 'model': task['model'], 'batch_id': task['batch_id'],
                    'raw_evaluation': raw_eval, 'scores': scores,
                    'total_score': total_score,
                    'error': '', 'status': 'ok', 'reply_idx': task['reply_idx'],
                    'eval_column': task['eval_column'], 'eval_raw_column': task['eval_raw_column']}

        except Exception as e:
            return {'qid': task['qid'], 'model': task['model'], 'batch_id': task['batch_id'],
                    'raw_evaluation': f"<error: {str(e)}>", 'scores': {}, 'total_score': np.nan,
                    'error': str(e), 'status': 'error', 'reply_idx': task['reply_idx'],
                    'eval_column': task['eval_column'], 'eval_raw_column': task['eval_raw_column']}

    eval_results = []
    failed_count = 0
    completed_count = 0
    total_tasks = len(tasks)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_task = {executor.submit(evaluate_task, task): task for task in tasks}

        for future in tqdm(as_completed(future_to_task), total=total_tasks, desc="🔄 评估进度", ncols=100):
            task = future_to_task[future]
            try:
                result = future.result()
                eval_results.append(result)

                result_eval_col = result.get('eval_column', eval_column)
                result_raw_col = result.get('eval_raw_column', eval_raw_column)

                if result_eval_col not in df_replies.columns:
                    df_replies[result_eval_col] = np.nan
                if result_raw_col not in df_replies.columns:
                    df_replies[result_raw_col] = ''

                idx = result['reply_idx']
                if idx is not None:
                    df_replies.loc[idx, result_eval_col] = result['total_score']
                    df_replies.loc[idx, result_raw_col] = result['raw_evaluation']
                else:
                    mask = (df_replies['qid'] == result['qid']) & (df_replies['model'] == result['model'])
                    if mask.any():
                        df_replies.loc[mask.idxmax(), result_eval_col] = result['total_score']
                        df_replies.loc[mask.idxmax(), result_raw_col] = result['raw_evaluation']

                completed_count += 1
                if result['status'] == 'error':
                    failed_count += 1

                if completed_count % checkpoint_interval == 0:
                    if save_results(df_replies, df_batch_log, eval_results, batch_id, output_excel, main_sheet_name=target_sheet):
                        tqdm.write(f"💾 检查点: 已处理 {completed_count}/{total_tasks}，已写入 {output_excel}")
                    else:
                        tqdm.write(f"⚠️  检查点保存失败（若回复表正在被 Excel 打开，请关闭后再跑或等全部完成）")

            except Exception as e:
                tqdm.write(f"❌ 任务处理异常 [{task['qid']}][{task['model']}]: {e}")
                failed_count += 1

    batch_log_entry = {
        'batch_id': batch_id, 'timestamp': pd.Timestamp.now(),
        'total_tasks': total_tasks, 'completed': total_tasks - failed_count,
        'failed': failed_count, 'eval_model': f"{provider}/{model}",
        'temperature': temperature, 'max_workers': max_workers,
        'success_rate': (total_tasks - failed_count) / total_tasks if total_tasks > 0 else 0
    }
    df_batch_log = pd.concat([df_batch_log, pd.DataFrame([batch_log_entry])], ignore_index=True)

    try:
        if '出题人' not in df_replies.columns:
            df_replies['出题人'] = ''
        df_to_write = _sort_replies_by_qid_model(df_replies)
        preserved = _load_preserved_sheets(output_excel)
        with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
            df_to_write.to_excel(writer, sheet_name=target_sheet, index=False)
            df_batch_log.to_excel(writer, sheet_name='batch_log', index=False)
            for name, frame in preserved.items():
                frame.to_excel(writer, sheet_name=name[:31], index=False)
        print(f"  📌 回复表已写入「{target_sheet}」sheet（含出题人列），统计阶段将仅基于回复表")
        print(f"📊 批次日志已更新: {output_excel}（已按 qid、model 排序，同一题集中，已保留专家 sheet）")
    except Exception as e:
        print(f"⚠️  最终保存失败: {e}")
        backup_path = output_excel.replace('.xlsx', f'_backup_{batch_id}.xlsx')
        try:
            df_to_write = _sort_replies_by_qid_model(df_replies)
            preserved = _load_preserved_sheets(output_excel)
            with pd.ExcelWriter(backup_path, engine='openpyxl') as writer:
                df_to_write.to_excel(writer, sheet_name=target_sheet, index=False)
                df_batch_log.to_excel(writer, sheet_name='batch_log', index=False)
                for name, frame in preserved.items():
                    frame.to_excel(writer, sheet_name=name[:31], index=False)
            print(f"💾 已保存到备份文件: {backup_path}")
        except Exception:
            print(f"❌ 备份保存也失败")

    print(f"\n{'=' * 60}")
    print(f"✅ 评估完成!  总任务: {total_tasks}  成功: {total_tasks - failed_count}  失败: {failed_count}")

    successful_results = [r for r in eval_results if r['status'] == 'ok' and not np.isnan(r.get('total_score', np.nan))]
    if successful_results:
        scores = [r['total_score'] for r in successful_results]
        print(f"  平均分: {np.mean(scores):.2f}  最高: {np.max(scores):.2f}  最低: {np.min(scores):.2f}")

    print(f"  评估结果列: {eval_column}")
    print(f"{'=' * 60}\n")

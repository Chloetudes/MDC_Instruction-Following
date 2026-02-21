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
from evaluation.core.utils import safe_str, safe_save_excel
from evaluation.core.cache_messages import build_cached_messages, detect_provider_type
from evaluation.managers.sysprompt import SyspromptManager


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
        retries: int = 3
) -> Tuple[str, str]:
    messages = build_cached_messages(
        provider_type, sys_prompt, query, evaluation_criteria,
        reference, reply, model_name, reference_type
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
                time.sleep(1.0 + (2 * attempt))

    return "", f"<error: {last_err}>"


def save_results(df_replies: pd.DataFrame, df_batch_log: pd.DataFrame,
                 results: List[dict], batch_id: str, output_excel: str) -> bool:
    try:
        temp_path = output_excel.replace('.xlsx', f'_temp_{int(time.time())}.xlsx')
        with pd.ExcelWriter(temp_path, engine='openpyxl') as writer:
            df_replies.to_excel(writer, sheet_name='Sheet1', index=False)
            if not df_batch_log.empty:
                df_batch_log.to_excel(writer, sheet_name='batch_log', index=False)

        test_df = pd.read_excel(temp_path, sheet_name='Sheet1', nrows=5)
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
            with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
                df_replies.to_excel(writer, sheet_name='Sheet1', index=False)
                if not df_batch_log.empty:
                    df_batch_log.to_excel(writer, sheet_name='batch_log', index=False)
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
        timeout: int = 120
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
    print(f"📋 Provider类型: {provider_type}  并发数: {max_workers}")
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
    print(f"  题目数量: {len(df_questions)}  包含参考答案: {'是' if has_reference else '否'}\n")

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

    df_replies['qid'] = df_replies['qid'].astype(str).str.strip()
    df_replies['model'] = df_replies['model'].astype(str).str.strip()
    df_questions['qid'] = df_questions['qid'].astype(str).str.strip()

    eval_columns = [col for col in df_replies.columns if col.startswith('eval_')]
    print(f"\n📊 回复表列名: {list(df_replies.columns)}")
    print(f"  发现评估列: {eval_columns}")

    df_merged = df_replies.merge(df_questions, on='qid', how='left')
    missing_questions = df_merged['query'].isna().sum()
    if missing_questions > 0:
        print(f"⚠️  警告: {missing_questions} 条回复找不到对应的题目")
        df_merged = df_merged[df_merged['query'].notna()]
    print(f"  关联后数据量: {len(df_merged)} 条\n")

    if data_filters:
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
        print(f"  ✅ 筛���后数据量: {len(df_merged)} 条\n")

    if len(df_merged) == 0:
        print("⚠️  筛选后无数据需要处理")
        return

    if not batch_id:
        batch_id = f"eval_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}"
    print(f"📋 评估批次ID: {batch_id}")

    eval_column = f"eval_{batch_id}"
    eval_raw_column = f"{eval_column}_raw"

    if eval_column in df_replies.columns:
        print(f"📊 发现已有评估列: {eval_column}")
        existing_mask = df_replies[eval_column].apply(is_evaluated) | df_replies[eval_raw_column].apply(is_evaluated)
        existing_evaluated = existing_mask.sum()
        print(f"  已有评估结果: {existing_evaluated} 条  未评估: {len(df_replies) - existing_evaluated} 条")

        if existing_evaluated > 0:
            print(f"  🤔 如何处理已有评估结果？")
            print(f"    1. 跳过已有评估，只评估空白的 (默认)")
            print(f"    2. 覆盖所有评估")
            print(f"    3. 创建新的批次")
            choice = input(f"  请选择 (1/2/3): ").strip()

            if choice == '2':
                print("  ⚠️  将覆盖所有评估结果")
                df_replies[eval_column] = np.nan
                df_replies[eval_raw_column] = ''
            elif choice == '3':
                batch_id = f"eval_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}"
                eval_column = f"eval_{batch_id}"
                eval_raw_column = f"{eval_column}_raw"
                print(f"  新的批次ID: {batch_id}")
            else:
                print("  ✅ 将跳过已有评估，只评估空白数据")

    if eval_column not in df_replies.columns:
        df_replies[eval_column] = np.nan
    if eval_raw_column not in df_replies.columns:
        df_replies[eval_raw_column] = ''

    df_merged_reset = df_merged.reset_index(drop=True)
    already_evaluated = 0
    tasks = []

    for i, row in df_merged_reset.iterrows():
        qid = str(row['qid']).strip()
        model_name = str(row['model']).strip()
        reply_mask = (df_replies['qid'] == qid) & (df_replies['model'] == model_name)

        if not reply_mask.any():
            continue

        reply_idx = df_replies[reply_mask].index[0]
        eval_value = df_replies.loc[reply_idx, eval_column]
        raw_value = df_replies.loc[reply_idx, eval_raw_column]

        if is_evaluated(eval_value) or is_evaluated(raw_value):
            already_evaluated += 1
            continue

        tasks.append({
            'merged_index': i, 'qid': qid, 'model': model_name,
            'query': safe_str(row['query']),
            'evaluation_criteria': safe_str(row['evaluation_criteria']),
            'reference': safe_str(row['reference']) if has_reference else '',
            'reference_type': safe_str(row['reference_type']) if has_reference_type else 'model',
            'reply': safe_str(row['reply']),
            'batch_id': batch_id, 'eval_column': eval_column,
            'eval_raw_column': eval_raw_column, 'reply_idx': reply_idx
        })

    print(f"📊 总数据量: {len(df_merged)}  已评估: {already_evaluated}  待评估: {len(tasks)}")

    if not tasks:
        print("✅ 所有任务已完成")
        save_results(df_replies, df_batch_log, [], batch_id, output_excel)
        return

    print(f"\n⚡ 开始并发评估 ({max_workers} workers)...\n")

    def evaluate_task(task: dict) -> dict:
        try:
            row = df_merged_reset.iloc[task['merged_index']]
            raw_eval, error_msg = evaluate_single_reply_with_cache(
                client, model, provider_type, sys_prompt,
                safe_str(row['query']), safe_str(row['evaluation_criteria']),
                safe_str(row['reference']) if has_reference else '',
                safe_str(row['reply']), task['model'],
                safe_str(row['reference_type']) if has_reference_type else 'model',
                temperature, retries=3
            )

            if error_msg:
                return {'qid': task['qid'], 'model': task['model'], 'batch_id': task['batch_id'],
                        'raw_evaluation': error_msg, 'scores': {}, 'total_score': np.nan,
                        'error': error_msg, 'status': 'error', 'reply_idx': task['reply_idx']}

            scores = extract_scores_from_evaluation(raw_eval)
            return {'qid': task['qid'], 'model': task['model'], 'batch_id': task['batch_id'],
                    'raw_evaluation': raw_eval, 'scores': scores,
                    'total_score': scores.get('total_score', np.nan),
                    'error': '', 'status': 'ok', 'reply_idx': task['reply_idx']}

        except Exception as e:
            return {'qid': task['qid'], 'model': task['model'], 'batch_id': task['batch_id'],
                    'raw_evaluation': f"<error: {str(e)}>", 'scores': {}, 'total_score': np.nan,
                    'error': str(e), 'status': 'error', 'reply_idx': task['reply_idx']}

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

                idx = result['reply_idx']
                if idx is not None:
                    df_replies.loc[idx, task['eval_column']] = result['total_score']
                    df_replies.loc[idx, task['eval_raw_column']] = result['raw_evaluation']
                else:
                    mask = (df_replies['qid'] == result['qid']) & (df_replies['model'] == result['model'])
                    if mask.any():
                        df_replies.loc[mask.idxmax(), task['eval_column']] = result['total_score']
                        df_replies.loc[mask.idxmax(), task['eval_raw_column']] = result['raw_evaluation']

                completed_count += 1
                if result['status'] == 'error':
                    failed_count += 1

                if completed_count % checkpoint_interval == 0:
                    if save_results(df_replies, df_batch_log, eval_results, batch_id, output_excel):
                        tqdm.write(f"💾 检查点: 已处理 {completed_count}/{total_tasks}")
                    else:
                        tqdm.write(f"⚠️  检查点保存失败")

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
        with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
            df_replies.to_excel(writer, sheet_name='Sheet1', index=False)
            df_batch_log.to_excel(writer, sheet_name='batch_log', index=False)
        print(f"📊 批次日志已更新: {output_excel}")
    except Exception as e:
        print(f"⚠️  最终保存失败: {e}")
        backup_path = output_excel.replace('.xlsx', f'_backup_{batch_id}.xlsx')
        try:
            with pd.ExcelWriter(backup_path, engine='openpyxl') as writer:
                df_replies.to_excel(writer, sheet_name='Sheet1', index=False)
                df_batch_log.to_excel(writer, sheet_name='batch_log', index=False)
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

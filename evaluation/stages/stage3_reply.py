# -*- coding: utf-8 -*-
import json
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from typing import Dict, List, Optional, Tuple

import pandas as pd
from tqdm import tqdm

from config import get_provider_for_model
from clients.openai_client import OAIClient
from ..core.utils import safe_str, safe_save_excel
from ..core.blacklist import MODEL_BLACKLIST, is_permission_error


def _build_messages_for_reply(query: str, history_context: str = '') -> List[Dict]:
    if not history_context or history_context.strip() in ('', '[]', 'nan', 'none', 'null'):
        return [{"role": "user", "content": query}]

    try:
        history = json.loads(history_context)
        if not isinstance(history, list) or len(history) == 0:
            return [{"role": "user", "content": query}]

        messages = []
        for turn in history:
            user_text = turn.get('user', '')
            assistant_text = turn.get('assistant', '')
            if user_text:
                messages.append({"role": "user", "content": user_text})
            if assistant_text:
                messages.append({"role": "assistant", "content": assistant_text})

        messages.append({"role": "user", "content": query})
        return messages
    except (json.JSONDecodeError, TypeError):
        return [{"role": "user", "content": query}]


def generate_reply(
        client: OAIClient,
        model: str,
        query: str,
        temperature: float = 0.7,
        enable_thinking: bool = False,
        retries: int = 5,
        history_context: str = '',
) -> Tuple[str, Optional[str], Optional[str]]:
    if isinstance(query, list):
        query = '\n'.join(str(item) for item in query if item is not None)
    elif not isinstance(query, str):
        query = str(query)

    messages = _build_messages_for_reply(query, history_context)
    last_err = None
    time.sleep(random.uniform(0.3, 0.8))

    for attempt in range(retries):
        try:
            kwargs = {"model": model, "messages": messages, "temperature": temperature}
            if enable_thinking:
                kwargs["enable_thinking"] = True

            if hasattr(client, "chat_with_meta"):
                text, finish_reason, reasoning = client.chat_with_meta(**kwargs)
            else:
                text = client.chat(**kwargs)
                finish_reason = None
                reasoning = None

            if isinstance(text, str):
                is_html_error = (
                    '<a id="a-link"' in text or
                    'bixi.alicdn.com/punish' in text or
                    text.strip().startswith('<!DOCTYPE') or
                    text.strip().startswith('<html')
                )
                if is_html_error:
                    if attempt < retries - 1:
                        wait_time = 3.0 + (2 * attempt)
                        print(f"⚠️  模型 {model} 触发风控拦截，等待 {wait_time:.1f} 秒后重试 ({attempt + 1}/{retries})")
                        time.sleep(wait_time)
                        continue
                    else:
                        return "<error: 触发风控拦截>", None, None

            return text, finish_reason, reasoning

        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                wait_time = 2.0 + (2 * attempt)
                print(f"⚠️  模型 {model} 调用失败，{wait_time:.1f}秒后重试 ({attempt + 1}/{retries}): {e}")
                time.sleep(wait_time)

    return f"<error: {repr(last_err)}>", None, None


def batch_generate_replies(
        questions_excel: str,
        model_configs: List[Dict[str, str]],
        output_excel: str,
        temperature: float = 0.7,
        max_workers: int = 4,
        checkpoint_interval: int = 10,
        timeout: int = 120
) -> pd.DataFrame:
    print(f"\n{'=' * 60}")
    print(f"🚀 模块3: 批量生成回复")
    print(f"{'=' * 60}\n")

    try:
        df_questions = pd.read_excel(questions_excel)
    except Exception as e:
        raise FileNotFoundError(f"无法读取题目文件: {e}")

    required_cols = ['qid', 'query']
    missing_cols = [col for col in required_cols if col not in df_questions.columns]
    if missing_cols:
        raise ValueError(f"题目表缺少必需列: {', '.join(missing_cols)}")

    has_history_context = 'history_context' in df_questions.columns
    print(f"  题目数量: {len(df_questions)}  模型数量: {len(model_configs)}  多轮对话: {'是' if has_history_context else '否'}")
    print(f"  总任务数: {len(df_questions) * len(model_configs)}\n")

    clients: Dict[str, OAIClient] = {}
    client_lock = Lock()
    enriched_configs = []

    for cfg in model_configs:
        model_name = cfg['model']
        try:
            provider_config = get_provider_for_model(model_name)
            enriched_configs.append({
                'model': model_name,
                'provider': provider_config.name,
                'provider_config': provider_config,
                'enable_thinking': cfg.get('enable_thinking', False)
            })
            if provider_config.name not in clients:
                clients[provider_config.name] = OAIClient(
                    base_url=provider_config.base_url, api_key=provider_config.api_key,
                    protocol=provider_config.protocol, auth_header=provider_config.auth_header,
                    auth_prefix=provider_config.auth_prefix, extra_headers=provider_config.extra_headers,
                    timeout=timeout
                )
                print(f"  ✅ {provider_config.name} 客户端初始化成功 (协议: {provider_config.protocol})")
        except ValueError as e:
            print(f"  ❌ 模型 {model_name} 配置失败: {e}")

    print()

    results = []
    existing_keys = set()

    if os.path.exists(output_excel):
        try:
            df_existing = pd.read_excel(output_excel)
            for _, row in df_existing.iterrows():
                existing_keys.add((str(row['qid']), str(row['model'])))
                results.append(row.to_dict())
            print(f"💾 发现已有结果: {len(existing_keys)} 条，将跳过\n")
        except Exception as e:
            print(f"⚠️  读取已有结果失败: {e}\n")

    tasks = []
    for _, row in df_questions.iterrows():
        qid = safe_str(row['qid'])
        query_raw = row['query']
        query = '\n'.join(str(i) for i in query_raw if i is not None) if isinstance(query_raw, list) else safe_str(query_raw)
        history_context_value = ''
        if has_history_context:
            raw_hc = row['history_context']
            if not pd.isna(raw_hc):
                history_context_value = str(raw_hc)

        for cfg in enriched_configs:
            model_name = cfg['model']
            provider_name = cfg['provider']
            if (qid, model_name) in existing_keys:
                continue
            if MODEL_BLACKLIST.is_blacklisted(provider_name, model_name):
                continue
            tasks.append({
                'qid': qid, 'query': query,
                'provider': provider_name, 'model': model_name,
                'model_name': model_name,
                'enable_thinking': cfg.get('enable_thinking', False),
                'history_context': history_context_value,
            })

    print(f"📝 待处理任务: {len(tasks)} 条\n")

    if not tasks:
        print("✅ 所有任务已完成")
        MODEL_BLACKLIST.print_summary()
        return pd.read_excel(output_excel) if os.path.exists(output_excel) else pd.DataFrame(results)

    def generate_task(task: dict):
        query = task['query']
        if not isinstance(query, str):
            query = '\n'.join(str(i) for i in query if i is not None) if isinstance(query, list) else str(query)
            task['query'] = query

        if MODEL_BLACKLIST.is_blacklisted(task['provider'], task['model']):
            return None

        with client_lock:
            client = clients[task['provider']]

        reply, finish_reason, reasoning = generate_reply(
            client, task['model'], task['query'], temperature,
            enable_thinking=task.get('enable_thinking', False), retries=3,
            history_context=task.get('history_context', '')
        )

        if reply.startswith('<error'):
            if not MODEL_BLACKLIST.is_first_task_tested(task['provider'], task['model']):
                if is_permission_error(reply):
                    MODEL_BLACKLIST.add(task['provider'], task['model'], reply)
                    tqdm.write(f"⚠️  模型首次调用失败，已加入黑名单: {task['provider']} / {task['model']}")
                    return None
                else:
                    MODEL_BLACKLIST.mark_first_task_tested(task['provider'], task['model'])
        else:
            MODEL_BLACKLIST.mark_first_task_tested(task['provider'], task['model'])

        return {
            'qid': task['qid'], 'model': task['model_name'],
            'reply': reply, 'reasoning': reasoning or '',
            'reply_len': len(reply) if isinstance(reply, str) else 0,
            'reasoning_len': len(reasoning) if reasoning else 0,
            'finish_reason': finish_reason,
            'enable_thinking': task.get('enable_thinking', False),
            'status': 'ok' if not reply.startswith('<error') else 'error',
            'timestamp': pd.Timestamp.now()
        }

    new_results = []
    failed_count = 0
    skipped_count = 0
    completed = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(generate_task, task): task for task in tasks}
        for future in tqdm(as_completed(futures), total=len(futures), desc="🔄 生成进度", ncols=100):
            try:
                result = future.result()
                if result is None:
                    skipped_count += 1
                else:
                    new_results.append(result)
                    if result['status'] == 'error':
                        failed_count += 1
                completed += 1

                if completed % checkpoint_interval == 0:
                    df_temp = pd.DataFrame(results + new_results)
                    if safe_save_excel(df_temp, output_excel):
                        tqdm.write(f"💾 检查点: 已保存 {len(results) + len(new_results)} 条")
            except Exception as e:
                tqdm.write(f"❌ 任务失败: {e}")
                failed_count += 1
                completed += 1

    results.extend(new_results)

    if not results:
        return pd.DataFrame()

    df_final = pd.DataFrame(results)
    if safe_save_excel(df_final, output_excel):
        print(f"\n✅ 保存成功: {output_excel}")

    print(f"\n{'=' * 60}")
    print(f"✅ 回复生成完成!")
    print(f"{'=' * 60}")
    print(f"  总结果数: {len(results)}  新增: {len(new_results)}")
    print(f"  成功: {sum(1 for r in results if r['status'] == 'ok')}  失败: {failed_count}  跳过: {skipped_count}")

    thinking_rows = df_final[df_final['enable_thinking'] == True]
    if len(thinking_rows) > 0:
        print(f"  开启 thinking: {len(thinking_rows)} 条  平均推理长度: {thinking_rows['reasoning_len'].mean():.0f} 字符")

    print(f"{'=' * 60}\n")
    MODEL_BLACKLIST.print_summary()
    return df_final

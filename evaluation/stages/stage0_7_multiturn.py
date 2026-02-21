# -*- coding: utf-8 -*-
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional

import pandas as pd
from tqdm import tqdm

from config import get_provider
from clients.openai_client import OAIClient
from evaluation.core.utils import safe_str, safe_save_excel
from evaluation.managers.sysprompt import SyspromptManager


def _build_multiturn_prompt(
    qid: str,
    query: str,
    min_turns: int,
    max_turns: int,
) -> str:
    return (
        f"请将以下单轮指令扩展为一段自然的多轮对话，对话轮次控制在 {min_turns}-{max_turns} 轮之间。\n\n"
        f"题目ID: {qid}\n\n"
        f"【原始指令】\n{query}\n\n"
        f"要求：\n"
        f"1. 以 JSON 数组格式输出，每个元素代表一轮对话\n"
        f"2. 每个元素包含 user_query（用户输入）和 assistant_reply（助手回复）两个字段\n"
        f"3. 对话要自然流畅，逐步深入，体现真实的多轮交互场景\n"
        f"4. 第一轮的 user_query 应基于原始指令，后续轮次自然延伸\n\n"
        f"输出格式示例：\n"
        f'[\n'
        f'  {{"user_query": "用户第一轮输入...", "assistant_reply": "助手第一轮回复..."}},\n'
        f'  {{"user_query": "用户第二轮输入...", "assistant_reply": "助手第二轮回复..."}}\n'
        f']\n\n'
        f"只输出 JSON 数组，不要有其他说明文字。"
    )


def _parse_multiturn_response(response_text: str) -> Optional[List[Dict]]:
    if not response_text:
        return None

    import re
    json_text = response_text.strip()

    code_block_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', json_text)
    if code_block_match:
        json_text = code_block_match.group(1).strip()

    array_match = re.search(r'\[[\s\S]*\]', json_text)
    if array_match:
        json_text = array_match.group(0)

    try:
        turns = json.loads(json_text)
        if isinstance(turns, list) and len(turns) > 0:
            return turns
    except json.JSONDecodeError:
        pass

    return None


def _build_history_context(turns: List[Dict], up_to_turn: int) -> str:
    history = []
    for turn_index in range(up_to_turn):
        if turn_index < len(turns):
            turn = turns[turn_index]
            history.append({
                'turn': turn_index + 1,
                'user': turn.get('user_query', ''),
                'assistant': turn.get('assistant_reply', ''),
            })
    return json.dumps(history, ensure_ascii=False)


def expand_to_multiturn(
        input_excel: str,
        output_excel: str,
        provider: str,
        model: str,
        sysprompt_manager: SyspromptManager,
        min_turns: int = 3,
        max_turns: int = 8,
        temperature: float = 0.8,
        max_workers: int = 3,
        checkpoint_interval: int = 10,
        timeout: int = 180,
) -> pd.DataFrame:
    print(f"\n{'=' * 60}")
    print(f"🚀 模块0.7: 单轮→多轮对话扩展")
    print(f"{'=' * 60}\n")

    try:
        pc = get_provider(provider)
        client = OAIClient(
            base_url=pc.base_url, api_key=pc.api_key, protocol=pc.protocol,
            auth_header=pc.auth_header, auth_prefix=pc.auth_prefix,
            extra_headers=pc.extra_headers, timeout=timeout
        )
        print(f"✅ 客户端初始化成功\n")
    except Exception as e:
        raise RuntimeError(f"多轮扩展模型初始化失败，流程终止: {e}")

    sys_prompt = sysprompt_manager.get('multiturn_expansion', '')

    df = pd.read_excel(input_excel)
    required_cols = ['qid', 'query']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"缺少必需列: {', '.join(missing_cols)}")

    print(f"  输入数据: {len(df)} 条\n")

    results = []
    existing_session_ids = set()

    if os.path.exists(output_excel):
        try:
            df_existing = pd.read_excel(output_excel)
            if 'session_id' in df_existing.columns:
                for session_id in df_existing['session_id'].unique():
                    existing_session_ids.add(str(session_id))
                for _, row in df_existing.iterrows():
                    results.append(row.to_dict())
                print(f"💾 发现已有结果: {len(existing_session_ids)} 个会话\n")
        except Exception:
            pass

    tasks = []
    for _, row in df.iterrows():
        qid = safe_str(row['qid'])
        if qid in existing_session_ids:
            continue
        task_type = safe_str(row.get('task_type', '')) if 'task_type' in df.columns else ''
        tasks.append({
            'qid': qid,
            'query': safe_str(row['query']),
            'task_type': task_type,
        })

    print(f"📝 待处理任务: {len(tasks)} 条\n")
    if not tasks:
        print("✅ 所有任务已完成")
        return pd.DataFrame(results) if results else pd.DataFrame()

    def expand_single_task(task: dict) -> Optional[List[dict]]:
        user_prompt = _build_multiturn_prompt(
            task['qid'], task['query'], min_turns, max_turns
        )
        messages = []
        if sys_prompt:
            messages.append({"role": "system", "content": sys_prompt})
        messages.append({"role": "user", "content": user_prompt})

        try:
            response = client.chat(model=model, messages=messages, temperature=temperature)
            turns = _parse_multiturn_response(response)
            if not turns:
                return None

            session_rows = []
            for turn_index, turn in enumerate(turns, 1):
                user_query = turn.get('user_query', '')
                assistant_reply = turn.get('assistant_reply', '')
                if not user_query:
                    continue

                history_context = _build_history_context(turns, turn_index - 1)
                turn_qid = f"{task['qid']}_T{turn_index}"

                session_rows.append({
                    'session_id': task['qid'],
                    'turn_id': turn_index,
                    'qid': turn_qid,
                    'query': user_query,
                    'assistant_reply': assistant_reply,
                    'history_context': history_context,
                    'task_type': task['task_type'],
                    'total_turns': len(turns),
                })
            return session_rows
        except Exception as e:
            tqdm.write(f"❌ 任务 {task['qid']} 扩展失败: {e}")
            return None

    new_results = []
    failed_count = 0
    completed_count = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_task = {executor.submit(expand_single_task, task): task for task in tasks}
        for future in tqdm(as_completed(future_to_task), total=len(tasks), desc="🔄 扩展进度", ncols=100):
            task = future_to_task[future]
            try:
                session_rows = future.result()
                if session_rows:
                    new_results.extend(session_rows)
                else:
                    failed_count += 1
            except Exception as e:
                tqdm.write(f"❌ 任务异常 [{task['qid']}]: {e}")
                failed_count += 1

            completed_count += 1
            if completed_count % checkpoint_interval == 0:
                df_temp = pd.DataFrame(results + new_results)
                if safe_save_excel(df_temp, output_excel):
                    tqdm.write(f"💾 检查点: 已保存 {len(results) + len(new_results)} 条")

    results.extend(new_results)
    df_result = pd.DataFrame(results) if results else pd.DataFrame()

    if len(df_result) > 0 and safe_save_excel(df_result, output_excel):
        session_count = df_result['session_id'].nunique() if 'session_id' in df_result.columns else 0
        print(f"\n✅ 多轮扩展完成: {output_excel}")
        print(f"  会话数: {session_count}  总轮次: {len(df_result)}  失败: {failed_count}")

    return df_result

# -*- coding: utf-8 -*-
import json
import re
from typing import List

import pandas as pd
from tqdm import tqdm

from ..core.utils import safe_save_excel


def _parse_json_response(response_text: str, original_id: str) -> List[dict]:
    if pd.isna(response_text) or not response_text:
        return []

    json_text = response_text.strip()

    code_block_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', json_text)
    if code_block_match:
        json_text = code_block_match.group(1).strip()

    array_match = re.search(r'\[[\s\S]*\]', json_text)
    if array_match:
        json_text = array_match.group(0)

    try:
        items = json.loads(json_text)
    except json.JSONDecodeError:
        return []

    if not isinstance(items, list):
        if isinstance(items, dict):
            items = [items]
        else:
            return []

    results = []
    for item_index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            continue

        task_type = str(item.get('task_type', '')).strip()
        query_raw = item.get('query', '')

        if isinstance(query_raw, list):
            query = json.dumps(query_raw, ensure_ascii=False)
        elif isinstance(query_raw, str):
            query = query_raw.strip()
        else:
            query = str(query_raw).strip()

        if not query or query.lower() in ('nan', 'none', 'null', ''):
            continue

        qid = f"{original_id}_Q{item_index}"
        results.append({
            'qid': qid,
            'original_id': original_id,
            'item_num': item_index,
            'task_type': task_type,
            'query': query,
        })

    return results


def extract_structured_instructions(input_excel: str, output_excel: str) -> pd.DataFrame:
    print(f"\n{'=' * 60}")
    print(f"🚀 模块0.5: 提取结构化指令（JSON 解析模式）")
    print(f"{'=' * 60}\n")

    print(f"📖 读取输入: {input_excel}")
    df = pd.read_excel(input_excel)

    if 'id' not in df.columns or 'response' not in df.columns:
        raise ValueError("Excel文件必须包含'id'和'response'列")

    print(f"  数据行数: {len(df)}\n")

    all_instructions = []
    parse_failed = 0

    for _, row in tqdm(df.iterrows(), total=len(df), desc="🔄 提取进度", ncols=100):
        parsed = _parse_json_response(row['response'], row['id'])
        if parsed:
            all_instructions.extend(parsed)
        else:
            parse_failed += 1

    result_df = pd.DataFrame(all_instructions)
    if len(result_df) > 0:
        result_df = result_df[['qid', 'original_id', 'item_num', 'task_type', 'query']]
        result_df['query'] = result_df['query'].apply(str.strip)

    if safe_save_excel(result_df, output_excel):
        print(f"\n✅ 指令提取完成: {output_excel}  共提取 {len(result_df)} 条指令")
        if parse_failed > 0:
            print(f"⚠️  解析失败批次: {parse_failed} 个（可能是模型未按 JSON 格式输出）")

    return result_df

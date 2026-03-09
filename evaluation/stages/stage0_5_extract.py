# -*- coding: utf-8 -*-
"""
Stage 0.5: 指令提取
优先解析 JSON 数组；若解析失败则尝试从纯文本中按「指令N：」或类似格式提取，避免整批丢失。
"""
import json
import os
import re
from typing import List, Tuple

import pandas as pd
from tqdm import tqdm

from ..core.utils import safe_save_excel


def _try_json_loads(json_text: str) -> Tuple[bool, list]:
    """尝试解析 JSON 数组，必要时做简单修复后重试。返回 (成功与否, 列表)。"""
    if not json_text or not json_text.strip():
        return False, []

    text = json_text.strip()
    # 先直接解析
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return True, data
        if isinstance(data, dict):
            return True, [data]
        return False, []
    except json.JSONDecodeError:
        pass

    # 常见修复：去掉末尾多余逗号（如 [ {...}, ] ）
    try:
        fixed = re.sub(r',\s*]', ']', text)
        fixed = re.sub(r',\s*}', '}', fixed)
        data = json.loads(fixed)
        if isinstance(data, list):
            return True, data
        if isinstance(data, dict):
            return True, [data]
    except json.JSONDecodeError:
        pass

    return False, []


def _parse_json_response(response_text: str, original_id: str) -> List[dict]:
    """优先按 JSON 数组解析；支持从 markdown 代码块或正文中抽取 [...] 再解析。"""
    if pd.isna(response_text) or not response_text:
        return []

    raw = response_text.strip()
    if not raw:
        return []

    # 1) 从 ```json ... ``` 或 ``` ... ``` 中取内容
    code_block = re.search(r'```(?:json)?\s*([\s\S]*?)```', raw)
    if code_block:
        ok, items = _try_json_loads(code_block.group(1))
        if ok and items:
            return _items_to_instructions(items, original_id)

    # 2) 从正文中找第一个完整的 [...] 数组（按括号匹配）
    start = raw.find('[')
    if start != -1:
        depth = 0
        end = -1
        for i in range(start, len(raw)):
            if raw[i] == '[':
                depth += 1
            elif raw[i] == ']':
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end != -1:
            ok, items = _try_json_loads(raw[start : end + 1])
            if ok and items:
                return _items_to_instructions(items, original_id)

    # 3) 简单正则取 [...]（可能被截断时用）
    array_match = re.search(r'\[[\s\S]*\]', raw)
    if array_match:
        ok, items = _try_json_loads(array_match.group(0))
        if ok and items:
            return _items_to_instructions(items, original_id)

    return []


def _items_to_instructions(items: list, original_id: str) -> List[dict]:
    """将解析出的 list 转为标准指令列表。"""
    results = []
    for idx, item in enumerate(items, 1):
        if not isinstance(item, dict):
            continue
        task_type = str(item.get('task_type', '')).strip()
        query_raw = item.get('query', '')
        if isinstance(query_raw, list):
            query = json.dumps(query_raw, ensure_ascii=False)
        elif isinstance(query_raw, str):
            query = query_raw.strip()
        else:
            query = str(query_raw).strip() if query_raw is not None else ''
        if not query or query.lower() in ('nan', 'none', 'null', ''):
            continue
        qid = f"{original_id}_Q{idx}"
        results.append({
            'qid': qid,
            'original_id': original_id,
            'item_num': idx,
            'task_type': task_type,
            'query': query,
        })
    return results


def _parse_text_fallback(response_text: str, original_id: str) -> List[dict]:
    """
    当 JSON 解析失败时，从纯文本中按「指令N：」或「N. 类型 ...」等格式提取指令，
    减少因模型偶尔输出非 JSON 导致的整批丢失。
    """
    if pd.isna(response_text) or not response_text:
        return []

    text = response_text.strip()
    results = []

    # 策略1：按「指令N：」或「指令 N：」切分（与常见 sysprompt 要求一致）
    # split 带捕获组得 [前文, num1, content1, num2, content2, ...]
    parts = re.split(r'(?:\n|^)\s*指令\s*(\d+)\s*[：:]\s*', '\n' + text)
    if len(parts) >= 3:
        for i in range(1, len(parts) - 1, 2):
            num_str = (parts[i] or '').strip()
            content = (parts[i + 1] or '').strip()
            next_header = re.search(r'\n\s*指令\s*\d+\s*[：:]\s*', content)
            if next_header:
                content = content[: next_header.start()].strip()
            if num_str.isdigit() and len(content) >= 3:
                num = int(num_str)
                qid = f"{original_id}_Q{num}"
                results.append({
                    'qid': qid,
                    'original_id': original_id,
                    'item_num': num,
                    'task_type': '',
                    'query': content,
                })
        if results:
            return results

    # 策略2：按「N. 」或「N、」分段（数字编号列表）；split 得 [前文, num1, content1, num2, content2, ...]
    parts = re.split(r'(?:\n|^)\s*(\d+)[.．、]\s*', '\n' + text)
    if len(parts) >= 3:
        for i in range(1, len(parts) - 1, 2):
            num_str = (parts[i] or '').strip()
            content = (parts[i + 1] or '').strip()
            # 截断到下一个「N. 」或换行后的「N. 」
            next_num = re.search(r'(?:\n|\s)\d+[.．、]\s*', content)
            if next_num:
                content = content[: next_num.start()].strip()
            if num_str.isdigit() and len(content) >= 3:
                qid = f"{original_id}_Q{int(num_str)}"
                results.append({
                    'qid': qid,
                    'original_id': original_id,
                    'item_num': int(num_str),
                    'task_type': '',
                    'query': content,
                })
        if results:
            return results

    return results


def extract_structured_instructions(input_excel: str, output_excel: str) -> pd.DataFrame:
    print(f"\n{'=' * 60}")
    print(f"🚀 模块0.5: 提取结构化指令（JSON 解析模式）")
    print(f"{'=' * 60}\n")

    if not os.path.exists(input_excel):
        raise RuntimeError(
            f"extract_instructions: 找不到输入文件\n"
            f"  路径: {input_excel}\n"
            f"  请先运行 'generate_instructions' 阶段生成原始指令批次，再执行本阶段。"
        )

    print(f"📖 读取输入: {input_excel}")
    df = pd.read_excel(input_excel)

    if 'id' not in df.columns or 'response' not in df.columns:
        raise ValueError("Excel文件必须包含'id'和'response'列")

    print(f"  数据行数: {len(df)}\n")

    all_instructions = []
    parse_failed = 0

    for _, row in tqdm(df.iterrows(), total=len(df), desc="🔄 提取进度", ncols=100):
        parsed = _parse_json_response(row['response'], row['id'])
        if not parsed:
            parsed = _parse_text_fallback(row['response'], row['id'])
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
            print(f"⚠️  仍有 {parse_failed} 个批次无法解析（JSON 与文本回退均未匹配到指令）")

    return result_df

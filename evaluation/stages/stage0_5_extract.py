# -*- coding: utf-8 -*-
import re
from typing import List

import pandas as pd
from tqdm import tqdm

from evaluation.core.utils import safe_save_excel


def _extract_from_response(response_text: str, original_id: str) -> List[dict]:
    if pd.isna(response_text):
        return []

    sections = response_text.split('$')
    instructions = []
    current_instruction = None

    for section in sections:
        section = section.strip()
        if not section:
            continue

        header_match = re.match(r'^指令(\d+)[：:]\s*(.+?)(?:\n|$)', section, re.MULTILINE)
        if header_match:
            if current_instruction is not None:
                instructions.append(current_instruction)

            instruction_num = header_match.group(1)
            task_type = header_match.group(2).strip()
            query_content = section[header_match.end():].strip()

            current_instruction = {
                'original_id': original_id,
                'id': f"{original_id}_INS{instruction_num}",
                'instruction_num': f'指令{instruction_num}',
                'task_type': task_type,
                'query': query_content
            }
        elif current_instruction is not None:
            separator = '\n' if current_instruction['query'] else ''
            current_instruction['query'] += separator + section

    if current_instruction is not None:
        instructions.append(current_instruction)

    return instructions


def extract_structured_instructions(input_excel: str, output_excel: str) -> pd.DataFrame:
    print(f"\n{'=' * 60}")
    print(f"🚀 模块0.5: 提取结构化指令")
    print(f"{'=' * 60}\n")

    print(f"📖 读取输入: {input_excel}")
    df = pd.read_excel(input_excel)

    if 'id' not in df.columns or 'response' not in df.columns:
        raise ValueError("Excel文件必须包含'id'和'response'列")

    print(f"  数据行数: {len(df)}\n")

    all_instructions = []
    for _, row in tqdm(df.iterrows(), total=len(df), desc="🔄 提取进度", ncols=100):
        all_instructions.extend(_extract_from_response(row['response'], row['id']))

    result_df = pd.DataFrame(all_instructions)
    if len(result_df) > 0:
        result_df = result_df[['id', 'original_id', 'instruction_num', 'task_type', 'query']]
        result_df['query'] = result_df['query'].apply(str.strip)

    if safe_save_excel(result_df, output_excel):
        print(f"\n✅ 指令提取完成: {output_excel}  共提取 {len(result_df)} 条指令")

    return result_df

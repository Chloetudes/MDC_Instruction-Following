# -*- coding: utf-8 -*-
import os

import pandas as pd
from tqdm import tqdm

from config import get_provider
from clients.openai_client import OAIClient
from evaluation.core.utils import safe_save_excel
from evaluation.managers.sysprompt import SyspromptManager


def generate_instructions(
        output_excel: str,
        provider: str,
        model: str,
        sysprompt_manager: SyspromptManager,
        num_batches: int = 4,
        temperature: float = 0.8,
        timeout: int = 120
):
    print(f"\n{'=' * 60}")
    print(f"🚀 模块0: 生成优质指令")
    print(f"{'=' * 60}\n")

    pc = get_provider(provider)
    client = OAIClient(
        base_url=pc.base_url, api_key=pc.api_key, protocol=pc.protocol,
        auth_header=pc.auth_header, auth_prefix=pc.auth_prefix,
        extra_headers=pc.extra_headers, timeout=timeout
    )

    sys_prompt = sysprompt_manager.get('instruction_generation', '')
    if not sys_prompt:
        print("⚠️  未配置 instruction_generation sysprompt")
        return

    results = []
    existing_ids = set()

    if os.path.exists(output_excel):
        try:
            df_existing = pd.read_excel(output_excel)
            for _, row in df_existing.iterrows():
                existing_ids.add(str(row['id']))
                results.append(row.to_dict())
            print(f"💾 发现已有结果: {len(existing_ids)} 条\n")
        except Exception:
            pass

    remaining = num_batches - len(existing_ids)
    if remaining <= 0:
        print(f"✅ 已有足够的批次 ({len(existing_ids)} 条)")
        return

    print(f"📝 需要生成: {remaining} 个批次\n")

    for batch_idx in tqdm(range(remaining), desc="🔄 生成进度", ncols=100):
        try:
            messages = [{"role": "system", "content": sys_prompt},
                        {"role": "user", "content": "请生成指令。"}]
            response = client.chat(model=model, messages=messages, temperature=temperature)
            batch_id = f"BATCH{len(results) + 1:04d}"
            results.append({'id': batch_id, 'response': response})
        except Exception as e:
            tqdm.write(f"❌ 批次 {batch_idx + 1} 生成失败: {e}")

    if results:
        df_final = pd.DataFrame(results)
        if safe_save_excel(df_final, output_excel):
            print(f"\n✅ 指令生成完成: {output_excel}  总批次数: {len(df_final)}")

# -*- coding: utf-8 -*-
import os
import random
from typing import Optional

import pandas as pd
from tqdm import tqdm

from config import get_provider
from clients.openai_client import OAIClient
from evaluation.core.utils import safe_str, safe_save_excel
from evaluation.managers.sysprompt import SyspromptManager


def _load_schema(schema_excel: str) -> list:
    if not schema_excel or not os.path.exists(schema_excel):
        return []
    try:
        df = pd.read_excel(schema_excel)
        required_cols = {'task_type', 'count'}
        if not required_cols.issubset(set(df.columns)):
            print(f"⚠️  schema.xlsx 缺少必需列（task_type, count），将忽略 schema 配置")
            return []
        tasks = []
        for _, row in df.iterrows():
            task_type = safe_str(row['task_type'])
            count = int(row['count']) if pd.notna(row['count']) else 1
            difficulty = safe_str(row.get('difficulty', '')) if 'difficulty' in df.columns else ''
            description = safe_str(row.get('description', '')) if 'description' in df.columns else ''
            for _ in range(count):
                tasks.append({
                    'task_type': task_type,
                    'difficulty': difficulty,
                    'description': description,
                })
        print(f"✅ 加载 schema.xlsx: {len(tasks)} 个生成任务（{len(df)} 种类型）")
        return tasks
    except Exception as e:
        print(f"⚠️  读取 schema.xlsx 失败: {e}，将忽略 schema 配置")
        return []


def _load_seeds(see_excel: str) -> list:
    if not see_excel or not os.path.exists(see_excel):
        return []
    try:
        df = pd.read_excel(see_excel)
        if 'query' not in df.columns:
            print(f"⚠️  see.xlsx 缺少 query 列，将忽略示例种子")
            return []
        seeds = []
        for _, row in df.iterrows():
            query = safe_str(row['query'])
            if query and query.lower() not in ('nan', 'none', 'null'):
                task_type = safe_str(row.get('task_type', '')) if 'task_type' in df.columns else ''
                seeds.append({'query': query, 'task_type': task_type})
        print(f"✅ 加载 see.xlsx: {len(seeds)} 条示例种子")
        return seeds
    except Exception as e:
        print(f"⚠️  读取 see.xlsx 失败: {e}，将忽略示例种子")
        return []


def _build_user_prompt(task_spec: Optional[dict], seeds: list) -> str:
    parts = []

    if task_spec:
        task_type = task_spec.get('task_type', '')
        difficulty = task_spec.get('difficulty', '')
        description = task_spec.get('description', '')

        constraint_parts = []
        if task_type:
            constraint_parts.append(f"任务类型：{task_type}")
        if difficulty:
            constraint_parts.append(f"难度等级：{difficulty}")
        if description:
            constraint_parts.append(f"补充说明：{description}")

        if constraint_parts:
            parts.append("【本批次生成要求】\n" + "\n".join(constraint_parts))

    if seeds:
        sample_count = min(3, len(seeds))
        if task_spec and task_spec.get('task_type'):
            task_type = task_spec['task_type']
            type_seeds = [s for s in seeds if s.get('task_type') == task_type]
            sample_seeds = type_seeds[:sample_count] if type_seeds else random.sample(seeds, sample_count)
        else:
            sample_seeds = random.sample(seeds, sample_count)

        seed_text = "\n\n".join(
            f"示例{i + 1}：{s['query']}" for i, s in enumerate(sample_seeds)
        )
        parts.append(f"【参考示例（仅供风格参考，请勿直接复制）】\n{seed_text}")

    parts.append("请生成指令。")
    return "\n\n".join(parts)


def generate_instructions(
        output_excel: str,
        provider: str,
        model: str,
        sysprompt_manager: SyspromptManager,
        num_batches: int = 4,
        temperature: float = 0.8,
        timeout: int = 120,
        schema_excel: Optional[str] = None,
        see_excel: Optional[str] = None,
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

    schema_tasks = _load_schema(schema_excel) if schema_excel else []
    seeds = _load_seeds(see_excel) if see_excel else []

    if schema_tasks:
        print(f"  模式：Schema 驱动（按类型分配生成任务）")
    elif seeds:
        print(f"  模式：种子驱动（随机抽取示例作为 few-shot）")
    else:
        print(f"  模式：纯 Sysprompt 驱动")
    print()

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

    if schema_tasks:
        pending_tasks = schema_tasks[len(existing_ids):]
        total_batches = len(schema_tasks)
    else:
        remaining = num_batches - len(existing_ids)
        pending_tasks = [None] * max(0, remaining)
        total_batches = num_batches

    if not pending_tasks:
        print(f"✅ 已有足够的批次 ({len(existing_ids)} 条)")
        return

    print(f"📝 需要生成: {len(pending_tasks)} 个批次（共 {total_batches} 个）\n")

    for batch_idx, task_spec in enumerate(tqdm(pending_tasks, desc="🔄 生成进度", ncols=100)):
        try:
            user_prompt = _build_user_prompt(task_spec, seeds)
            messages = [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
            ]
            response = client.chat(model=model, messages=messages, temperature=temperature)
            batch_id = f"BATCH{len(results) + 1:04d}"

            result_row = {'id': batch_id, 'response': response}
            if task_spec:
                result_row['task_type'] = task_spec.get('task_type', '')
                result_row['difficulty'] = task_spec.get('difficulty', '')
            results.append(result_row)
        except Exception as e:
            tqdm.write(f"❌ 批次 {batch_idx + 1} 生成失败: {e}")

    if results:
        df_final = pd.DataFrame(results)
        if safe_save_excel(df_final, output_excel):
            print(f"\n✅ 指令生成完成: {output_excel}  总批次数: {len(df_final)}")

# -*- coding: utf-8 -*-
import os
import random
from typing import Optional, List, Dict

import pandas as pd
from tqdm import tqdm

from config import get_provider
from clients.openai_client import OAIClient
from evaluation.core.utils import safe_str, safe_save_excel
from evaluation.managers.sysprompt import SyspromptManager


def _load_schema(schema_excel: str) -> tuple:
    """
    加载 schema.xlsx，返回 (task_specs, counter_df, schema_df)。

    Sheet1（任务体系表）必需列：L1, L2, L3, count
    可选列：difficulty, description, example（示范案例）

    Sheet2（计数器表）由系统自动维护，记录每个 L3 子类型已合成的数量。
    若 Sheet2 不存在则自动初始化。
    """
    if not schema_excel or not os.path.exists(schema_excel):
        return [], pd.DataFrame(), pd.DataFrame()

    try:
        xl = pd.ExcelFile(schema_excel)
    except Exception as e:
        print(f"⚠️  读取 schema.xlsx 失败: {e}")
        return [], pd.DataFrame(), pd.DataFrame()

    if 'Sheet1' not in xl.sheet_names and xl.sheet_names:
        schema_sheet = xl.sheet_names[0]
    else:
        schema_sheet = 'Sheet1'

    try:
        df_schema = xl.parse(schema_sheet)
    except Exception as e:
        print(f"⚠️  解析 schema Sheet1 失败: {e}")
        return [], pd.DataFrame(), pd.DataFrame()

    required_cols = {'L1', 'L2', 'L3', 'count'}
    if not required_cols.issubset(set(df_schema.columns)):
        missing = required_cols - set(df_schema.columns)
        print(f"⚠️  schema.xlsx Sheet1 缺少必需列: {missing}，将忽略 schema 配置")
        return [], pd.DataFrame(), pd.DataFrame()

    if 'Sheet2' in xl.sheet_names:
        try:
            df_counter = xl.parse('Sheet2')
        except Exception:
            df_counter = pd.DataFrame()
    else:
        df_counter = pd.DataFrame()

    if df_counter.empty or 'L3' not in df_counter.columns:
        df_counter = pd.DataFrame({
            'L1': df_schema['L1'].tolist(),
            'L2': df_schema['L2'].tolist(),
            'L3': df_schema['L3'].tolist(),
            'target_count': df_schema['count'].tolist(),
            'synthesized_count': [0] * len(df_schema),
        })

    task_specs = []
    for _, row in df_schema.iterrows():
        l1 = safe_str(row.get('L1', ''))
        l2 = safe_str(row.get('L2', ''))
        l3 = safe_str(row.get('L3', ''))
        count = int(row['count']) if pd.notna(row['count']) else 1
        difficulty = safe_str(row.get('difficulty', '')) if 'difficulty' in df_schema.columns else ''
        description = safe_str(row.get('description', '')) if 'description' in df_schema.columns else ''
        example = safe_str(row.get('example', '')) if 'example' in df_schema.columns else ''

        for _ in range(count):
            task_specs.append({
                'L1': l1,
                'L2': l2,
                'L3': l3,
                'task_type': l3 or l2 or l1,
                'difficulty': difficulty,
                'description': description,
                'schema_example': example,
            })

    total_types = len(df_schema)
    total_tasks = len(task_specs)
    print(f"✅ 加载 schema.xlsx: {total_types} 种子类型，共 {total_tasks} 个生成任务")
    for _, row in df_schema.iterrows():
        l1 = safe_str(row.get('L1', ''))
        l2 = safe_str(row.get('L2', ''))
        l3 = safe_str(row.get('L3', ''))
        count = int(row['count']) if pd.notna(row['count']) else 1
        print(f"  {l1} > {l2} > {l3}: {count} 批次")

    return task_specs, df_counter, df_schema


def _save_counter(schema_excel: str, df_counter: pd.DataFrame, df_schema: pd.DataFrame):
    """将更新后的计数器写回 schema.xlsx 的 Sheet2。"""
    if schema_excel and not df_counter.empty:
        try:
            with pd.ExcelWriter(schema_excel, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
                df_schema.to_excel(writer, sheet_name='Sheet1', index=False)
                df_counter.to_excel(writer, sheet_name='Sheet2', index=False)
        except Exception as e:
            print(f"⚠️  更新 schema 计数器失败: {e}")


def _load_seeds(see_excel: str) -> List[Dict]:
    """
    加载 see.xlsx 种子库。

    必需列：query
    可选列：L1, L2, L3, task_type（用于按类型优先匹配）
    """
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
            if not query or query.lower() in ('nan', 'none', 'null'):
                continue
            seed = {'query': query}
            for col in ['L1', 'L2', 'L3', 'task_type']:
                if col in df.columns:
                    seed[col] = safe_str(row.get(col, ''))
            seeds.append(seed)
        print(f"✅ 加载 see.xlsx: {len(seeds)} 条示例种子")
        return seeds
    except Exception as e:
        print(f"⚠️  读取 see.xlsx 失败: {e}，将忽略示例种子")
        return []


def _pick_seeds(seeds: List[Dict], task_spec: Optional[Dict], max_count: int = 3) -> List[Dict]:
    """按 L3 > L2 > L1 优先级匹配种子，不足时从全库补充。"""
    if not seeds or not task_spec:
        return random.sample(seeds, min(max_count, len(seeds))) if seeds else []

    l3 = task_spec.get('L3', '')
    l2 = task_spec.get('L2', '')
    l1 = task_spec.get('L1', '')

    matched = []
    if l3:
        matched = [s for s in seeds if s.get('L3') == l3 or s.get('task_type') == l3]
    if len(matched) < max_count and l2:
        extra = [s for s in seeds if s not in matched and (s.get('L2') == l2)]
        matched.extend(extra)
    if len(matched) < max_count and l1:
        extra = [s for s in seeds if s not in matched and (s.get('L1') == l1)]
        matched.extend(extra)
    if len(matched) < max_count:
        extra = [s for s in seeds if s not in matched]
        matched.extend(extra)

    return random.sample(matched, min(max_count, len(matched)))


def _build_user_prompt(task_spec: Optional[Dict], seeds: List[Dict]) -> str:
    parts = []

    if task_spec:
        l1 = task_spec.get('L1', '')
        l2 = task_spec.get('L2', '')
        l3 = task_spec.get('L3', '')
        difficulty = task_spec.get('difficulty', '')
        description = task_spec.get('description', '')
        schema_example = task_spec.get('schema_example', '')

        constraint_parts = []
        if l1:
            constraint_parts.append(f"一级类型（L1）：{l1}")
        if l2:
            constraint_parts.append(f"二级类型（L2）：{l2}")
        if l3:
            constraint_parts.append(f"三级类型（L3）：{l3}")
        if difficulty:
            constraint_parts.append(f"难度等级：{difficulty}")
        if description:
            constraint_parts.append(f"特征描述：{description}")

        if constraint_parts:
            parts.append("【本批次生成要求】\n" + "\n".join(constraint_parts))

        if schema_example and schema_example.lower() not in ('nan', 'none', 'null'):
            parts.append(f"【体系示范案例】\n{schema_example}")

    picked_seeds = _pick_seeds(seeds, task_spec)
    if picked_seeds:
        seed_text = "\n\n".join(
            f"示例{i + 1}：{s['query']}" for i, s in enumerate(picked_seeds)
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

    schema_tasks, df_counter, df_schema = _load_schema(schema_excel) if schema_excel else ([], pd.DataFrame(), pd.DataFrame())
    seeds = _load_seeds(see_excel) if see_excel else []

    if schema_tasks:
        print(f"  模式：Schema 驱动（L1/L2/L3 层级体系，含计数器）")
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

    counter_updates: Dict[str, int] = {}

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
                result_row['L1'] = task_spec.get('L1', '')
                result_row['L2'] = task_spec.get('L2', '')
                result_row['L3'] = task_spec.get('L3', '')
                result_row['difficulty'] = task_spec.get('difficulty', '')

                l3_key = task_spec.get('L3', '')
                if l3_key:
                    counter_updates[l3_key] = counter_updates.get(l3_key, 0) + 1

            results.append(result_row)
        except Exception as e:
            tqdm.write(f"❌ 批次 {batch_idx + 1} 生成失败: {e}")

    if results:
        df_final = pd.DataFrame(results)
        if safe_save_excel(df_final, output_excel):
            print(f"\n✅ 指令生成完成: {output_excel}  总批次数: {len(df_final)}")

    if counter_updates and not df_counter.empty and schema_excel:
        for l3_key, increment in counter_updates.items():
            mask = df_counter['L3'] == l3_key
            if mask.any():
                df_counter.loc[mask, 'synthesized_count'] = (
                    df_counter.loc[mask, 'synthesized_count'].fillna(0).astype(int) + increment
                )
        _save_counter(schema_excel, df_counter, df_schema)
        print(f"\n📊 计数器已更新（schema.xlsx Sheet2）：")
        for l3_key, increment in counter_updates.items():
            row = df_counter[df_counter['L3'] == l3_key]
            if not row.empty:
                synthesized = int(row['synthesized_count'].values[0])
                target = int(row['target_count'].values[0])
                print(f"  {l3_key}: {synthesized}/{target}")

# -*- coding: utf-8 -*-
import os
from typing import Tuple

import pandas as pd
from tqdm import tqdm

from config import get_provider
from clients.openai_client import OAIClient
from evaluation.core.utils import safe_str, safe_save_excel
from evaluation.managers.sysprompt import SyspromptManager
from evaluation.managers.constraint_library import ConstraintLibraryManager


class InstructionQualityEvaluator:
    def __init__(self, client: OAIClient, model: str,
                 sysprompt_manager: SyspromptManager, temperature: float = 0.3):
        self.client = client
        self.model = model
        self.sysprompt_manager = sysprompt_manager
        self.temperature = temperature

    def evaluate(self, query: str) -> Tuple[str, str]:
        sys_prompt = self.sysprompt_manager.get('instruction_quality_evaluation', '')
        user_prompt = f"请评估以下指令的质量，并提取所有约束。\n\n【指令】\n{query}"

        try:
            messages = []
            if sys_prompt:
                messages.append({"role": "system", "content": sys_prompt})
            messages.append({"role": "user", "content": user_prompt})
            response = self.client.chat(model=self.model, messages=messages, temperature=self.temperature)
            return response, ""
        except Exception as e:
            return "", f"<error: {str(e)}>"


def batch_evaluate_instruction_quality(
        input_excel: str,
        output_excel: str,
        provider: str,
        model: str,
        sysprompt_manager: SyspromptManager,
        constraint_library: ConstraintLibraryManager,
        temperature: float = 0.3,
        max_workers: int = 4,
        checkpoint_interval: int = 10,
        timeout: int = 120
) -> pd.DataFrame:
    print(f"\n{'=' * 60}")
    print(f"🚀 模块1: 指令质量评估与约束提取")
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
        raise RuntimeError(f"评估模型初始化失败，流程终止: {e}")

    evaluator = InstructionQualityEvaluator(client, model, sysprompt_manager, temperature)

    df = pd.read_excel(input_excel)
    required_cols = ['qid', 'query']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"缺少必需列: {', '.join(missing_cols)}")

    has_reference = 'reference' in df.columns
    print(f"  数据行数: {len(df)}\n")

    results = []
    existing_qids = set()

    if os.path.exists(output_excel):
        try:
            df_existing = pd.read_excel(output_excel)
            for _, row in df_existing.iterrows():
                existing_qids.add(str(row['qid']))
                results.append(row.to_dict())
            print(f"💾 发现已有结果: {len(existing_qids)} 条")
        except Exception:
            pass

    tasks = []
    for _, row in df.iterrows():
        qid = safe_str(row['qid'])
        if qid in existing_qids:
            continue
        task = {'qid': qid, 'query': safe_str(row['query'])}
        if has_reference:
            task['reference'] = safe_str(row['reference'])
        for col in ['original_id', 'item_num', 'task_type', 'session_id', 'turn_id', 'history_context']:
            if col in df.columns:
                task[col] = safe_str(row[col])
        tasks.append(task)

    print(f"📝 待处理任务: {len(tasks)} 条\n")
    if not tasks:
        print("✅ 所有任务已完成")
        return pd.DataFrame(results) if results else pd.DataFrame()

    new_results = []
    failed_count = 0
    consecutive_failures = 0
    MAX_CONSECUTIVE_FAILURES = 3

    for i, task in enumerate(tqdm(tasks, desc="🔄 评估进度", ncols=100)):
        try:
            raw_response, error_msg = evaluator.evaluate(task['query'])

            if error_msg:
                tqdm.write(f"⚠️  任务 {task['qid']} 评估失败")
                failed_count += 1
                consecutive_failures += 1
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    raise RuntimeError(f"连续 {MAX_CONSECUTIVE_FAILURES} 次评估失败，评估模型可能不可用")
                continue

            consecutive_failures = 0
            result_row = {
                'qid': task['qid'], 'query': task['query'],
                'raw_response': raw_response, 'error': error_msg,
                'status': 'ok', 'timestamp': pd.Timestamp.now()
            }
            if has_reference and 'reference' in task:
                result_row['reference'] = task['reference']
            for col in ['original_id', 'item_num', 'task_type', 'session_id', 'turn_id', 'history_context']:
                if col in task:
                    result_row[col] = task[col]
            new_results.append(result_row)

            if (i + 1) % checkpoint_interval == 0:
                df_temp = pd.DataFrame(results + new_results)
                if safe_save_excel(df_temp, output_excel):
                    tqdm.write(f"💾 检查点: 已保存 {len(results) + len(new_results)} 条")

        except RuntimeError:
            raise
        except Exception as e:
            tqdm.write(f"❌ 任务 {task['qid']} 异常: {e}")
            failed_count += 1
            consecutive_failures += 1
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                raise RuntimeError(f"连续 {MAX_CONSECUTIVE_FAILURES} 次评估异常，评估模型可能不可用")

    results.extend(new_results)
    df_result = pd.DataFrame(results) if results else pd.DataFrame()

    if len(df_result) > 0 and safe_save_excel(df_result, output_excel):
        print(f"\n✅ 评估结果已保存: {output_excel}  数量: {len(df_result)}")

    if failed_count > 0:
        print(f"\n⚠️  评估失败: {failed_count} 条")

    return df_result

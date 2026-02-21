# -*- coding: utf-8 -*-
import os
from typing import Tuple

import pandas as pd
from tqdm import tqdm

from config import get_provider
from clients.openai_client import OAIClient
from ..core.utils import safe_str, safe_save_excel
from ..managers.sysprompt import SyspromptManager


def _is_valid(value: str) -> bool:
    return bool(value and value.strip() and value.lower() not in ('nan', 'none', 'null'))


MULTITURN_PASSTHROUGH_COLS = ['session_id', 'turn_id', 'history_context']
METADATA_PASSTHROUGH_COLS = ['task_type', 'source', 'original_id', 'item_num', 'L1', 'L2', 'L3']


class ReferenceAnswerGenerator:
    def __init__(self, client: OAIClient, model: str,
                 sysprompt_manager: SyspromptManager, temperature: float = 0.7):
        self.client = client
        self.model = model
        self.sysprompt_manager = sysprompt_manager
        self.temperature = temperature

    def generate(
        self,
        qid: str,
        query: str,
        evaluation_criteria: str,
        reply_evaluation: str = '',
    ) -> Tuple[str, str]:
        sys_prompt = self.sysprompt_manager.get('reference_generation', '')

        parts = [
            f"请根据以下指令和评分标准，生成高质量的参考答案。\n\n"
            f"题目ID: {qid}\n\n"
            f"【指令内容】\n{query}\n\n"
            f"【评分标准】\n{evaluation_criteria}"
        ]

        if _is_valid(reply_evaluation):
            parts.append(
                f"\n【专家评分说明】\n{reply_evaluation}\n\n"
                f"请参考专家评分说明中提炼的核心答题方向和评分要点，"
                f"确保参考答案充分覆盖高分要素。"
            )
        else:
            parts.append(f"\n\n请生成一个符合评分标准的高质量参考答案。")

        user_prompt = '\n'.join(parts)

        try:
            messages = []
            if sys_prompt:
                messages.append({"role": "system", "content": sys_prompt})
            messages.append({"role": "user", "content": user_prompt})
            response = self.client.chat(model=self.model, messages=messages, temperature=self.temperature)
            return response, ""
        except Exception as e:
            return "", f"<error: {str(e)}>"


def batch_generate_references(
        input_excel: str,
        output_excel: str,
        provider: str,
        model: str,
        sysprompt_manager: SyspromptManager,
        temperature: float = 0.7,
        max_workers: int = 1,
        checkpoint_interval: int = 10,
        timeout: int = 120
) -> pd.DataFrame:
    print(f"\n{'=' * 60}")
    print(f"🚀 模块2: 批量生成参考答案")
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
        raise RuntimeError(f"参考答案生成模型初始化失败，流程终止: {e}")

    generator = ReferenceAnswerGenerator(client, model, sysprompt_manager, temperature)

    df = pd.read_excel(input_excel)
    required_cols = ['qid', 'query', 'evaluation_criteria']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"缺少必需列: {', '.join(missing_cols)}")

    has_reference = 'reference' in df.columns
    has_reply_evaluation = 'reply_evaluation' in df.columns
    detected_multiturn = [col for col in MULTITURN_PASSTHROUGH_COLS if col in df.columns]
    print(f"  数据行数: {len(df)}")
    if has_reference:
        print(f"  已有参考答案: {df['reference'].notna().sum()} 条")
    if has_reply_evaluation:
        valid_eval_count = df['reply_evaluation'].apply(
            lambda v: _is_valid(safe_str(v))
        ).sum()
        print(f"  专家评分说明: {valid_eval_count} 条")
    if detected_multiturn:
        print(f"  检测到多轮字段: {', '.join(detected_multiturn)}（将透传到输出）")
    print()

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

    all_passthrough_cols = METADATA_PASSTHROUGH_COLS + MULTITURN_PASSTHROUGH_COLS

    tasks = []
    for _, row in df.iterrows():
        qid = safe_str(row['qid'])
        if qid in existing_qids:
            continue

        existing_ref = safe_str(row['reference']) if has_reference else ''
        has_existing = _is_valid(existing_ref)

        task = {
            'qid': qid,
            'query': safe_str(row['query']),
            'evaluation_criteria': safe_str(row['evaluation_criteria']),
            'has_existing_reference': has_existing,
            'existing_reference': existing_ref if has_existing else '',
            'reply_evaluation': safe_str(row['reply_evaluation']) if has_reply_evaluation else '',
        }
        for col in all_passthrough_cols:
            if col in df.columns:
                task[col] = safe_str(row[col])
        tasks.append(task)

    print(f"📝 待处理任务: {len(tasks)} 条\n")
    if not tasks:
        print("✅ 所有任务已完成")
        return pd.DataFrame(results) if results else pd.DataFrame()

    new_results = []
    failed_count = 0
    human_ref_count = 0
    model_ref_count = 0

    for i, task in enumerate(tqdm(tasks, desc="🔄 处理进度", ncols=100)):
        try:
            if task['has_existing_reference']:
                reference = task['existing_reference']
                reference_type = "human"
                error_msg = ""
                human_ref_count += 1
            else:
                reference, error_msg = generator.generate(
                    qid=task['qid'],
                    query=task['query'],
                    evaluation_criteria=task['evaluation_criteria'],
                    reply_evaluation=task.get('reply_evaluation', ''),
                )
                reference_type = "model"
                if error_msg:
                    tqdm.write(f"⚠️  任务 {task['qid']} 生成失败")
                    failed_count += 1
                else:
                    model_ref_count += 1

            result_row = {
                'qid': task['qid'],
                'query': task['query'],
                'evaluation_criteria': task['evaluation_criteria'],
                'reference': reference,
                'reference_type': reference_type,
                'error': error_msg,
                'status': 'ok' if not error_msg else 'error',
                'timestamp': pd.Timestamp.now(),
            }
            if has_reply_evaluation:
                result_row['reply_evaluation'] = task.get('reply_evaluation', '')
            for col in all_passthrough_cols:
                if col in task:
                    result_row[col] = task[col]
            new_results.append(result_row)

            if (i + 1) % checkpoint_interval == 0:
                df_temp = pd.DataFrame(results + new_results)
                if safe_save_excel(df_temp, output_excel):
                    tqdm.write(f"💾 检查点: 已保存 {len(results) + len(new_results)} 条")

        except Exception as e:
            tqdm.write(f"❌ 任务 {task['qid']} 异常: {e}")
            failed_count += 1

    results.extend(new_results)
    df_result = pd.DataFrame(results) if results else pd.DataFrame()

    if len(df_result) > 0 and safe_save_excel(df_result, output_excel):
        print(f"\n✅ 参考答案处理完成: {output_excel}")
        print(f"  总数量: {len(df_result)}  人工参考: {human_ref_count}  模型参考: {model_ref_count}  失败: {failed_count}")

    return df_result

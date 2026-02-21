# -*- coding: utf-8 -*-
import os
from typing import Tuple

import pandas as pd
from tqdm import tqdm

from config import get_provider
from clients.openai_client import OAIClient
from evaluation.core.utils import safe_str, safe_save_excel
from evaluation.managers.sysprompt import SyspromptManager


def _is_valid(value: str) -> bool:
    return bool(value and value.strip() and value.lower() not in ('nan', 'none', 'null'))


class CriteriaGenerator:
    def __init__(self, client: OAIClient, model: str,
                 sysprompt_manager: SyspromptManager, temperature: float = 0.3):
        self.client = client
        self.model = model
        self.sysprompt_manager = sysprompt_manager
        self.temperature = temperature

    def generate(
        self,
        qid: str,
        query: str,
        human_rubrics: str = '',
        reference: str = '',
        reply_evaluation: str = '',
    ) -> Tuple[str, str]:
        has_human_rubrics = _is_valid(human_rubrics)
        has_expert_demo = _is_valid(reference) or _is_valid(reply_evaluation)

        if has_expert_demo:
            sys_prompt = self.sysprompt_manager.get(
                'criteria_generation_with_expert',
                self.sysprompt_manager.get('criteria_generation', '')
            )
            user_prompt = self._build_expert_prompt(
                qid, query, human_rubrics if has_human_rubrics else '',
                reference, reply_evaluation
            )
        elif has_human_rubrics:
            sys_prompt = self.sysprompt_manager.get(
                'criteria_generation_with_human',
                self.sysprompt_manager.get('criteria_generation', '')
            )
            user_prompt = self._build_human_rubrics_prompt(qid, query, human_rubrics)
        else:
            sys_prompt = self.sysprompt_manager.get('criteria_generation', '')
            user_prompt = self._build_base_prompt(qid, query)

        try:
            messages = []
            if sys_prompt:
                messages.append({"role": "system", "content": sys_prompt})
            messages.append({"role": "user", "content": user_prompt})
            response = self.client.chat(model=self.model, messages=messages, temperature=self.temperature)
            return response, ""
        except Exception as e:
            return "", f"<error: {str(e)}>"

    @staticmethod
    def _build_base_prompt(qid: str, query: str) -> str:
        return (
            f"请为以下指令设计详细的评分标准（rubrics）。\n\n"
            f"题目ID: {qid}\n\n"
            f"【指令内容】\n{query}"
        )

    @staticmethod
    def _build_human_rubrics_prompt(qid: str, query: str, human_rubrics: str) -> str:
        return (
            f"请基于人工初版评分标准，对以下指令的评分标准进行定向优化和完善。\n\n"
            f"题目ID: {qid}\n\n"
            f"【指令内容】\n{query}\n\n"
            f"【人工初版评分标准】\n{human_rubrics}\n\n"
            f"请在保留人工标准核心意图的基础上，补充遗漏的约束条目、明确评分细则、完善分值分配。"
        )

    @staticmethod
    def _build_expert_prompt(
        qid: str,
        query: str,
        human_rubrics: str,
        reference: str,
        reply_evaluation: str,
    ) -> str:
        parts = [
            f"请结合专家示范，为以下指令生成或优化评分标准（rubrics）。\n\n"
            f"题目ID: {qid}\n\n"
            f"【指令内容】\n{query}"
        ]

        if _is_valid(human_rubrics):
            parts.append(f"\n【人工初版评分标准】\n{human_rubrics}")

        if _is_valid(reference):
            parts.append(f"\n【专家示范回复】\n{reference}")

        if _is_valid(reply_evaluation):
            parts.append(f"\n【专家对示范回复的评分说明】\n{reply_evaluation}")

        parts.append(
            "\n请参考专家示范回复和评分说明，提炼核心答题方向和评分要点，"
            "补充或优化评分标准，确保标准能有效区分高质量与低质量回复。"
        )

        return '\n'.join(parts)


def batch_generate_criteria(
        input_excel: str,
        output_excel: str,
        provider: str,
        model: str,
        sysprompt_manager: SyspromptManager,
        temperature: float = 0.3,
        max_workers: int = 1,
        checkpoint_interval: int = 10,
        timeout: int = 120
) -> pd.DataFrame:
    print(f"\n{'=' * 60}")
    print(f"🚀 模块1.5: 批量生成评估标准")
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

    generator = CriteriaGenerator(client, model, sysprompt_manager, temperature)

    df = pd.read_excel(input_excel)
    required_cols = ['qid', 'query']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"缺少必需列: {', '.join(missing_cols)}")

    optional_cols = ['human_rubrics', 'reference', 'reply_evaluation']
    detected_optional = [col for col in optional_cols if col in df.columns]
    print(f"  数据行数: {len(df)}")
    if detected_optional:
        print(f"  检测到可选列: {', '.join(detected_optional)}")
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

    tasks = []
    for _, row in df.iterrows():
        qid = safe_str(row['qid'])
        if qid in existing_qids:
            continue
        task = {'qid': qid, 'query': safe_str(row['query'])}
        for col in optional_cols + ['task_type', 'source']:
            if col in df.columns:
                task[col] = safe_str(row[col])
        tasks.append(task)

    print(f"📝 待处理任务: {len(tasks)} 条\n")
    if not tasks:
        print("✅ 所有任务已完成")
        return pd.DataFrame(results) if results else pd.DataFrame()

    mode_counts = {'base': 0, 'human': 0, 'expert': 0}
    new_results = []
    failed_count = 0

    for i, task in enumerate(tqdm(tasks, desc="🔄 生成进度", ncols=100)):
        human_rubrics = task.get('human_rubrics', '')
        reference = task.get('reference', '')
        reply_evaluation = task.get('reply_evaluation', '')

        has_expert = _is_valid(reference) or _is_valid(reply_evaluation)
        has_human = _is_valid(human_rubrics)
        if has_expert:
            mode_counts['expert'] += 1
        elif has_human:
            mode_counts['human'] += 1
        else:
            mode_counts['base'] += 1

        try:
            criteria, error_msg = generator.generate(
                qid=task['qid'],
                query=task['query'],
                human_rubrics=human_rubrics,
                reference=reference,
                reply_evaluation=reply_evaluation,
            )
            if error_msg:
                tqdm.write(f"⚠️  任务 {task['qid']} 生成失败")
                failed_count += 1
                continue

            result_row = {
                'qid': task['qid'],
                'query': task['query'],
                'evaluation_criteria': criteria,
                'error': error_msg,
                'status': 'ok',
                'timestamp': pd.Timestamp.now(),
            }
            for col in optional_cols + ['task_type', 'source']:
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
        print(f"\n✅ 评估标准已保存: {output_excel}  数量: {len(df_result)}")
        print(f"  模式分布 — 纯模型: {mode_counts['base']}  人工初版: {mode_counts['human']}  专家示范: {mode_counts['expert']}")

    if failed_count > 0:
        print(f"\n⚠️  生成失败: {failed_count} 条")

    return df_result

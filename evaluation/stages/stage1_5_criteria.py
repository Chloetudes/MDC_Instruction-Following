# -*- coding: utf-8 -*-
import os
from typing import Tuple

import pandas as pd
from tqdm import tqdm

from config import get_provider
from clients.openai_client import OAIClient
from ..core.utils import safe_str, safe_save_excel, compute_input_fingerprint
from ..managers.sysprompt import SyspromptManager

# 用于智能增量：仅当这些输入列变化时才重新生成 evaluation_criteria
CRITERIA_INPUT_COLS = ['query', 'human_rubrics', 'reference', 'reply_evaluation', 'history_context', 'session_id', 'turn_id']


def _is_valid(value: str) -> bool:
    return bool(value and value.strip() and value.lower() not in ('nan', 'none', 'null'))


MULTITURN_PASSTHROUGH_COLS = ['session_id', 'turn_id', 'history_context']
# 透传到后续题目表，供分析统计使用（含难度等维度）
METADATA_PASSTHROUGH_COLS = ['task_type', 'source', 'original_id', 'item_num', 'L1', 'L2', 'L3', 'difficulty_score', 'difficulty_level']


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
        history_context: str = '',
        previous_turn_criteria: str = '',
    ) -> Tuple[str, str]:
        has_human_rubrics = _is_valid(human_rubrics)
        has_expert_demo = _is_valid(reference) or _is_valid(reply_evaluation)
        history_section = _format_history_context(history_context) if _is_valid(history_context) else ''
        has_previous_criteria = _is_valid(previous_turn_criteria)

        if has_expert_demo:
            sys_prompt = self.sysprompt_manager.get(
                'criteria_generation_with_expert',
                self.sysprompt_manager.get('criteria_generation', '')
            )
            user_prompt = self._build_expert_prompt(
                qid, query, human_rubrics if has_human_rubrics else '',
                reference, reply_evaluation, history_section, previous_turn_criteria
            )
        elif has_human_rubrics:
            sys_prompt = self.sysprompt_manager.get(
                'criteria_generation_with_human',
                self.sysprompt_manager.get('criteria_generation', '')
            )
            user_prompt = self._build_human_rubrics_prompt(qid, query, human_rubrics, history_section, previous_turn_criteria)
        else:
            sys_prompt = self.sysprompt_manager.get('criteria_generation', '')
            user_prompt = self._build_base_prompt(qid, query, history_section, previous_turn_criteria)

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
    def _build_base_prompt(qid: str, query: str, history_section: str = '', previous_turn_criteria: str = '') -> str:
        parts = [
            "请为以下指令设计详细的评分标准（rubrics）。",
            "",
            f"题目ID: {qid}",
            "",
            "【指令内容】",
            query,
        ]
        if _is_valid(previous_turn_criteria):
            parts.extend([
                "",
                "【上一轮评分标准】",
                previous_turn_criteria,
                "",
                "请在本轮标准中叠加/延续上一轮相关要点并增加本轮新要点；若本轮意图与历史轮次产生冲突，可删减不适用的标准。多轮话题关联，标准随轮次累积或按冲突调整。",
            ])
        if history_section:
            parts.extend(["", history_section, "", "说明：以上为多轮对话，当前轮为用户最后一轮输入。评分标准需考虑回复与对话历史的连贯性、不重复此前内容、符合当前轮语境。"])
        return "\n".join(parts)

    @staticmethod
    def _build_human_rubrics_prompt(qid: str, query: str, human_rubrics: str, history_section: str = '', previous_turn_criteria: str = '') -> str:
        parts = [
            "请基于人工初版评分标准，对以下指令的评分标准进行定向优化和完善。",
            "",
            f"题目ID: {qid}",
            "",
            "【指令内容】",
            query,
        ]
        if _is_valid(previous_turn_criteria):
            parts.extend(["", "【上一轮评分标准】", previous_turn_criteria, "", "请在本轮中叠加/延续相关要点并增加本轮新要点；若与历史冲突可删减。"])
        if history_section:
            parts.extend(["", history_section, "", "说明：以上为多轮对话，评分标准需考虑与对话历史的连贯性。"])
        parts.extend([
            "",
            "【人工初版评分标准】",
            human_rubrics,
            "",
            "请在保留人工标准核心意图的基础上，补充遗漏的约束条目、明确评分细则、完善分值分配。",
        ])
        return "\n".join(parts)

    @staticmethod
    def _build_expert_prompt(
        qid: str,
        query: str,
        human_rubrics: str,
        reference: str,
        reply_evaluation: str,
        history_section: str = '',
        previous_turn_criteria: str = '',
    ) -> str:
        parts = [
            "请结合专家示范，为以下指令生成或优化评分标准（rubrics）。",
            "",
            f"题目ID: {qid}",
            "",
            "【指令内容】",
            query,
        ]
        if _is_valid(previous_turn_criteria):
            parts.extend(["", "【上一轮评分标准】", previous_turn_criteria, "", "请在本轮中叠加/延续相关要点并增加本轮新要点；若与历史冲突可删减。"])
        if history_section:
            parts.extend(["", history_section, "", "说明：以上为多轮对话，当前轮为用户最后一轮输入，评分标准需考虑与对话历史的连贯性。"])
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
        return "\n".join(parts)


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

    if 'session_id' in df.columns and 'turn_id' in df.columns:
        try:
            df = df.sort_values(
                by=['session_id', 'turn_id'],
                key=lambda c: c.fillna('').astype(str) if c.name == 'session_id' else pd.to_numeric(c, errors='coerce').fillna(0)
            ).reset_index(drop=True)
            print(f"  多轮数据已按 session_id, turn_id 排序，将按轮次叠加评分标准")
        except Exception:
            pass

    optional_cols = ['human_rubrics', 'reference', 'reply_evaluation']
    detected_optional = [col for col in optional_cols if col in df.columns]
    detected_multiturn = [col for col in MULTITURN_PASSTHROUGH_COLS if col in df.columns]
    print(f"  数据行数: {len(df)}")
    if detected_optional:
        print(f"  检测到可选列: {', '.join(detected_optional)}")
    if detected_multiturn:
        print(f"  检测到多轮字段: {', '.join(detected_multiturn)}（将透传到输出）")
    print()

    all_passthrough_cols = optional_cols + METADATA_PASSTHROUGH_COLS + MULTITURN_PASSTHROUGH_COLS
    criteria_input_cols = [c for c in CRITERIA_INPUT_COLS if c in df.columns]
    if not criteria_input_cols:
        criteria_input_cols = ['query']

    prev_criteria_from_existing = {}
    existing_by_qid = {}
    existing_fp_by_qid = {}

    if os.path.exists(output_excel):
        try:
            df_existing = pd.read_excel(output_excel)
            if 'session_id' in df_existing.columns and 'turn_id' in df_existing.columns and 'evaluation_criteria' in df_existing.columns:
                df_ex = df_existing.sort_values(
                    by=['session_id', 'turn_id'],
                    key=lambda c: c.fillna('').astype(str) if c.name == 'session_id' else pd.to_numeric(c, errors='coerce').fillna(0)
                )
                for _, row in df_ex.iterrows():
                    sid = safe_str(row.get('session_id', ''))
                    if sid and _is_valid(safe_str(row.get('evaluation_criteria', ''))):
                        prev_criteria_from_existing[sid] = safe_str(row['evaluation_criteria'])
            for _, row in df_existing.iterrows():
                qid = str(row['qid']).strip()
                existing_by_qid[qid] = row.to_dict()
                row_dict = {c: safe_str(row.get(c, '')) for c in criteria_input_cols if c in row.index}
                for c in criteria_input_cols:
                    if c not in row_dict:
                        row_dict[c] = ''
                existing_fp_by_qid[qid] = compute_input_fingerprint(row_dict, criteria_input_cols)
            print(f"💾 发现已有结果: {len(existing_by_qid)} 条")
        except Exception:
            pass

    input_order = []
    tasks = []
    unchanged_count = 0
    for _, row in df.iterrows():
        qid = safe_str(row['qid'])
        row_dict = {c: safe_str(row.get(c, '')) for c in criteria_input_cols if c in df.columns}
        for c in criteria_input_cols:
            if c not in row_dict:
                row_dict[c] = ''
        current_fp = compute_input_fingerprint(row_dict, criteria_input_cols)
        is_unchanged = qid in existing_fp_by_qid and existing_fp_by_qid[qid] == current_fp
        if is_unchanged:
            input_order.append((qid, True, existing_by_qid[qid]))
            unchanged_count += 1
        else:
            task = {'qid': qid, 'query': safe_str(row['query'])}
            for col in all_passthrough_cols:
                if col in df.columns:
                    task[col] = safe_str(row[col])
            tasks.append(task)
            input_order.append((qid, False, row))  # 保留完整行，写回时合并以保留所有列

    if unchanged_count > 0:
        print(f"💾 输入未变化（跳过重新生成）: {unchanged_count} 条")
    print(f"📝 待处理任务（新增或输入已变更）: {len(tasks)} 条\n")
    if not tasks:
        df_result = pd.DataFrame([item[2] for item in input_order])
        if len(df_result) > 0 and safe_save_excel(df_result, output_excel):
            print("✅ 所有题目输入未变化，已按当前输入顺序写回")
        return df_result

    mode_counts = {'base': 0, 'human': 0, 'expert': 0}
    new_results_ordered = [None] * len(tasks)  # 按任务顺序存放，便于与 input_order 对齐
    failed_count = 0
    prev_criteria_by_session = dict(prev_criteria_from_existing)

    for i, task in enumerate(tqdm(tasks, desc="🔄 生成进度", ncols=100)):
        human_rubrics = task.get('human_rubrics', '')
        reference = task.get('reference', '')
        reply_evaluation = task.get('reply_evaluation', '')

        session_id = safe_str(task.get('session_id', ''))
        turn_id_raw = task.get('turn_id', '')
        try:
            turn_id_int = int(float(turn_id_raw)) if turn_id_raw not in (None, '', 'nan') else 0
        except (TypeError, ValueError):
            turn_id_int = 0
        previous_turn_criteria = ''
        if session_id and turn_id_int >= 2:
            previous_turn_criteria = prev_criteria_by_session.get(session_id, '')

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
                history_context=task.get('history_context', ''),
                previous_turn_criteria=previous_turn_criteria,
            )
            if error_msg:
                tqdm.write(f"⚠️  任务 {task['qid']} 生成失败")
                failed_count += 1
                continue

            if session_id:
                prev_criteria_by_session[session_id] = criteria

            result_row = {
                'qid': task['qid'],
                'query': task['query'],
                'evaluation_criteria': criteria,
                'error': error_msg,
                'status': 'ok',
                'timestamp': pd.Timestamp.now(),
            }
            for col in all_passthrough_cols:
                if col in task:
                    result_row[col] = task[col]
            new_results_ordered[i] = result_row

            if (i + 1) % checkpoint_interval == 0:
                unchanged_rows = [ex for (_, is_unchanged, ex) in input_order if is_unchanged]
                merged_new = []
                task_idx = 0
                for _qid, is_unchanged, row in input_order:
                    if is_unchanged:
                        continue
                    if task_idx < len(new_results_ordered) and new_results_ordered[task_idx] is not None:
                        full = row.to_dict() if hasattr(row, 'to_dict') else {}
                        full.update(new_results_ordered[task_idx])
                        merged_new.append(full)
                    task_idx += 1
                df_temp = pd.DataFrame(unchanged_rows + merged_new)
                if safe_save_excel(df_temp, output_excel):
                    tqdm.write(f"💾 检查点: 已保存 {len(unchanged_rows) + len(merged_new)} 条")

        except Exception as e:
            tqdm.write(f"❌ 任务 {task['qid']} 异常: {e}")
            failed_count += 1

    task_idx = 0
    final_rows = []
    for qid, is_unchanged, existing_row_or_input_row in input_order:
        if is_unchanged:
            final_rows.append(existing_row_or_input_row)
        else:
            result_row = new_results_ordered[task_idx] if task_idx < len(new_results_ordered) else None
            task_idx += 1
            if result_row is not None:
                # 与输入行合并，保留题目表全部列（专家、reply1、reply2 等）
                full = existing_row_or_input_row.to_dict() if hasattr(existing_row_or_input_row, 'to_dict') else dict(existing_row_or_input_row)
                full.update({k: v for k, v in result_row.items() if v is not None or k in full})
                final_rows.append(full)
            elif qid in existing_by_qid:
                fallback = dict(existing_by_qid[qid])
                fallback['error'] = '本次生成失败，保留旧数据'
                fallback['status'] = 'error'
                final_rows.append(fallback)
            else:
                full = existing_row_or_input_row.to_dict() if hasattr(existing_row_or_input_row, 'to_dict') else {}
                full.update({'evaluation_criteria': full.get('evaluation_criteria', ''), 'error': '生成失败', 'status': 'error', 'timestamp': pd.Timestamp.now()})
                final_rows.append(full)

    df_result = pd.DataFrame(final_rows) if final_rows else pd.DataFrame()

    if len(df_result) > 0 and safe_save_excel(df_result, output_excel):
        print(f"\n✅ 评估标准已保存: {output_excel}  数量: {len(df_result)}")
        print(f"  模式分布 — 纯模型: {mode_counts['base']}  人工初版: {mode_counts['human']}  专家示范: {mode_counts['expert']}")

    if failed_count > 0:
        print(f"\n⚠️  生成失败: {failed_count} 条")

    return df_result

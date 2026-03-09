# -*- coding: utf-8 -*-
import os
from typing import Tuple

import pandas as pd
from tqdm import tqdm

from config import get_provider
from clients.openai_client import OAIClient
from ..core.utils import safe_str, safe_save_excel, compute_input_fingerprint
from ..managers.sysprompt import SyspromptManager

# 用于智能增量：仅当这些输入列变化时才重新生成 reference
REFERENCE_INPUT_COLS = ['query', 'evaluation_criteria', 'reply_evaluation', 'history_context', 'session_id', 'turn_id']


def _is_valid(value: str) -> bool:
    return bool(value and value.strip() and value.lower() not in ('nan', 'none', 'null'))


MULTITURN_PASSTHROUGH_COLS = ['session_id', 'turn_id', 'history_context']
# 透传到 questions_complete，供分析统计使用（与 stage1_5 一致）
METADATA_PASSTHROUGH_COLS = ['task_type', 'source', 'original_id', 'item_num', 'L1', 'L2', 'L3', 'difficulty_score', 'difficulty_level']


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
        history_context: str = '',
    ) -> Tuple[str, str]:
        sys_prompt = self.sysprompt_manager.get('reference_generation', '')

        parts = [
            "请根据以下指令和评分标准，生成高质量的参考答案。",
            "",
            f"题目ID: {qid}",
            "",
            "【指令内容】",
            query,
            "",
            "【评分标准】",
            evaluation_criteria,
        ]

        history_section = _format_history_context(history_context) if _is_valid(history_context) else ''
        if history_section:
            parts.extend(["", history_section, "", "说明：以上为多轮对话，当前轮为用户最后一轮输入。请生成符合当前轮语境、与历史对话连贯且不重复前文的参考答案。"])

        if _is_valid(reply_evaluation):
            parts.append(
                f"\n【专家评分说明】\n{reply_evaluation}\n\n"
                "请参考专家评分说明中提炼的核心答题方向和评分要点，"
                "确保参考答案充分覆盖高分要素。"
            )
        else:
            parts.append("\n\n请生成一个符合评分标准的高质量参考答案。")

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

    all_passthrough_cols = METADATA_PASSTHROUGH_COLS + MULTITURN_PASSTHROUGH_COLS
    ref_input_cols = [c for c in REFERENCE_INPUT_COLS if c in df.columns]
    if not ref_input_cols:
        ref_input_cols = ['query', 'evaluation_criteria']

    existing_by_qid = {}
    existing_fp_by_qid = {}
    if os.path.exists(output_excel):
        try:
            df_existing = pd.read_excel(output_excel)
            for _, row in df_existing.iterrows():
                qid = str(row['qid']).strip()
                existing_by_qid[qid] = row.to_dict()
                row_dict = {c: safe_str(row.get(c, '')) for c in ref_input_cols if c in row.index}
                for c in ref_input_cols:
                    if c not in row_dict:
                        row_dict[c] = ''
                existing_fp_by_qid[qid] = compute_input_fingerprint(row_dict, ref_input_cols)
            print(f"💾 发现已有结果: {len(existing_by_qid)} 条")
        except Exception:
            pass

    def _row_to_result(row_dict: dict, reference: str, reference_type: str, error_msg: str = "") -> dict:
        out = {
            'qid': row_dict['qid'],
            'query': row_dict['query'],
            'evaluation_criteria': row_dict['evaluation_criteria'],
            'reference': reference,
            'reference_type': reference_type,
            'error': error_msg,
            'status': 'ok' if not error_msg else 'error',
            'timestamp': pd.Timestamp.now(),
        }
        for col in all_passthrough_cols:
            if col in row_dict:
                out[col] = row_dict[col]
        if has_reply_evaluation and 'reply_evaluation' in row_dict:
            out['reply_evaluation'] = row_dict['reply_evaluation']
        return out

    def _merge_row_result(full_row, result_dict):
        """合并输入行与生成结果，保留题目表全部列"""
        if full_row is None:
            return result_dict
        d = full_row.to_dict() if hasattr(full_row, 'to_dict') else {}
        d.update({k: v for k, v in result_dict.items() if v is not None or k in d})
        return d

    input_order = []
    tasks = []
    unchanged_count = 0
    human_ref_count = 0
    for _, row in df.iterrows():
        qid = safe_str(row['qid'])
        row_dict = {'qid': qid, 'query': safe_str(row['query']), 'evaluation_criteria': safe_str(row['evaluation_criteria'])}
        if has_reply_evaluation:
            row_dict['reply_evaluation'] = safe_str(row['reply_evaluation'])
        for col in all_passthrough_cols:
            if col in df.columns:
                row_dict[col] = safe_str(row[col])
        fp_dict = {c: row_dict.get(c, '') for c in ref_input_cols}
        for c in ref_input_cols:
            if c not in fp_dict:
                fp_dict[c] = ''
        current_fp = compute_input_fingerprint(fp_dict, ref_input_cols)
        is_unchanged = qid in existing_fp_by_qid and existing_fp_by_qid[qid] == current_fp
        if is_unchanged:
            input_order.append(('unchanged', existing_by_qid[qid], None, None, None))
            unchanged_count += 1
        else:
            existing_ref = safe_str(row['reference']) if has_reference else ''
            if _is_valid(existing_ref):
                input_order.append(('human', None, row_dict, existing_ref, row))
                human_ref_count += 1
            else:
                tasks.append(row_dict)
                input_order.append(('task', None, row_dict, None, row))

    if unchanged_count > 0:
        print(f"  输入未变化（跳过重新生成）: {unchanged_count} 条")
    print(f"  已有参考(reference_type=human，直接透传): {human_ref_count} 条")
    print(f"  需模型API生成: {len(tasks)} 条\n")

    if not tasks:
        final_rows = []
        for kind, existing_row, row_dict, ref_text, full_row in input_order:
            if kind == 'unchanged':
                final_rows.append(existing_row)
            else:
                final_rows.append(_merge_row_result(full_row, _row_to_result(row_dict, ref_text, "human")))
        df_result = pd.DataFrame(final_rows) if final_rows else pd.DataFrame()
        if len(df_result) > 0 and safe_save_excel(df_result, output_excel):
            print("✅ 所有题目已就绪（无待生成项），已按当前输入顺序写回")
        return df_result

    new_results = []
    failed_count = 0
    model_ref_count = 0

    for i, task in enumerate(tqdm(tasks, desc="🔄 生成进度", ncols=100)):
        try:
            reference, error_msg = generator.generate(
                qid=task['qid'],
                query=task['query'],
                evaluation_criteria=task['evaluation_criteria'],
                reply_evaluation=task.get('reply_evaluation', ''),
                history_context=task.get('history_context', ''),
            )
            if error_msg:
                tqdm.write(f"⚠️  任务 {task['qid']} 生成失败")
                failed_count += 1
            else:
                model_ref_count += 1

            result_row = _row_to_result(task, reference, "model", error_msg)
            if has_reply_evaluation:
                result_row['reply_evaluation'] = task.get('reply_evaluation', '')
            for col in all_passthrough_cols:
                if col in task:
                    result_row[col] = task[col]
            new_results.append(result_row)  # 与 full_row 的合并在 final_rows 中做

            if (i + 1) % checkpoint_interval == 0:
                partial = []
                task_idx = 0
                for kind, existing_row, row_dict, ref_text, full_row in input_order:
                    if kind == 'unchanged':
                        partial.append(existing_row)
                    elif kind == 'human':
                        partial.append(_merge_row_result(full_row, _row_to_result(row_dict, ref_text, "human")))
                    else:
                        r = new_results[task_idx] if task_idx < len(new_results) else _row_to_result(row_dict, '', 'model', '生成中')
                        partial.append(_merge_row_result(full_row, r))
                        task_idx += 1
                df_temp = pd.DataFrame(partial)
                if safe_save_excel(df_temp, output_excel):
                    tqdm.write(f"💾 检查点: 已保存 {len(partial)} 条")

        except Exception as e:
            tqdm.write(f"❌ 任务 {task['qid']} 异常: {e}")
            failed_count += 1

    task_idx = 0
    final_rows = []
    for kind, existing_row, row_dict, ref_text, full_row in input_order:
        if kind == 'unchanged':
            final_rows.append(existing_row)
        elif kind == 'human':
            final_rows.append(_merge_row_result(full_row, _row_to_result(row_dict, ref_text, "human")))
        else:
            r = new_results[task_idx] if task_idx < len(new_results) else _row_to_result(row_dict, '', 'model', '生成失败，保留旧数据')
            final_rows.append(_merge_row_result(full_row, r))
            task_idx += 1

    df_result = pd.DataFrame(final_rows) if final_rows else pd.DataFrame()

    if len(df_result) > 0 and safe_save_excel(df_result, output_excel):
        print(f"\n✅ 参考答案处理完成: {output_excel}")
        print(f"  总数量: {len(df_result)}  未变化: {unchanged_count}  人工参考: {human_ref_count}  模型参考: {model_ref_count}  失败: {failed_count}")

    return df_result

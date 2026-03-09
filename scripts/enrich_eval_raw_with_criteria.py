#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
为 eval_*_raw 中的 rubrics_check 添加 content 字段，记录原始评估标准内容，便于人工对比分析。

默认输入（与 main CONFIG 一致）:
  - 题目表: evaluation/outputs/questions/questions_complete.xlsx
  - 回复表: evaluation/outputs/replies/replies_6m.xlsx

用法:
  python scripts/enrich_eval_raw_with_criteria.py                    # 直接运行，覆盖原 replies_6m.xlsx
  python scripts/enrich_eval_raw_with_criteria.py --batch batch_3
  python scripts/enrich_eval_raw_with_criteria.py --replies path/to/replies.xlsx --output path/to/out.xlsx

输出: 在 replies 表中新增列 eval_{batch}_raw_enriched，默认直接写回原回复表。
"""
import argparse
import json
import os
import re
import sys

import pandas as pd

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


def _normalize_qid(val):
    """统一 qid 格式，如 123.0 -> '123'，与 data_loader 一致。"""
    s = str(val).strip()
    try:
        f = float(s)
        if f == int(f):
            return str(int(f))
    except (ValueError, TypeError):
        pass
    return s


def _strip_markdown_fence(s: str) -> str:
    s = s.strip()
    for prefix in ('```json', '```JSON', '```'):
        if s.startswith(prefix):
            s = s[len(prefix):].strip()
            if s.endswith('```'):
                s = s[:-3].strip()
            break
    return s


def _fix_json_newlines(s: str) -> str:
    """将 JSON 字符串值内的未转义换行替换为空格。"""
    result, i, in_str, escape, qc = [], 0, False, False, None
    while i < len(s):
        c = s[i]
        if escape:
            result.append(c)
            escape = False
            i += 1
            continue
        if c == '\\' and in_str:
            result.append(c)
            escape = True
            i += 1
            continue
        if in_str:
            if c == qc:
                in_str = False
            elif c in ('\n', '\r'):
                result.append(' ')
                i += 1
                if c == '\r' and i < len(s) and s[i] == '\n':
                    i += 1
                continue
            result.append(c)
            i += 1
            continue
        if c in ('"', "'"):
            in_str, qc = True, c
        result.append(c)
        i += 1
    return ''.join(result)


def parse_criteria_to_rubric_content(evaluation_criteria: str) -> dict:
    """
    从 evaluation_criteria 文本解析出 rubric_id -> 检查点内容 的映射。
    支持格式: **D2_1**: 是否xxx？(E)(F)  或  D2_1: content  或  - D2_1: content
    """
    result = {}
    if not evaluation_criteria or (isinstance(evaluation_criteria, float) and pd.isna(evaluation_criteria)):
        return result
    text = str(evaluation_criteria).strip()
    for line in text.split('\n'):
        line = line.strip()
        # 匹配 **D2_1**: content 或 D2_1: content 或 - D2_1: content 或 1. D2_1: content
        m = re.match(r'^[\d\-\•\*\.]*\s*(?:\*\*)?(D\d+_\d+)(?:\*\*)?\s*[:：]\s*(.+)', line)
        if m:
            rid = m.group(1)
            content = m.group(2).strip()
            # 去掉行末的 (E)(F)、(E/I)(F) 等标记
            content = re.sub(r'\s*\([EIF/]+\)(?:\s*\([EIF/]+\))?\s*$', '', content).strip()
            if content:
                result[rid] = content
    return result


def _parse_eval_raw_json(raw_text: str) -> dict:
    """解析 eval_*_raw 为 JSON 对象。"""
    if not raw_text or not str(raw_text).strip():
        return {}
    s = str(raw_text).strip()
    s = _strip_markdown_fence(s)
    s = _fix_json_newlines(s)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        # 尝试提取最外层 {}
        start = s.find('{')
        if start >= 0:
            depth = 0
            for i, c in enumerate(s[start:], start):
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(s[start : i + 1])
                        except json.JSONDecodeError:
                            pass
                        break
    return {}


def enrich_rubrics_with_content(eval_raw: str, rubric_content_map: dict) -> str:
    """
    在 eval_*_raw 的 rubrics_check 中为每个条目添加 content 字段。
    rubric_content_map: { D2_1: "是否xxx？", D2_2: "是否yyy？", ... }
    """
    obj = _parse_eval_raw_json(eval_raw)
    if not obj:
        return eval_raw

    rubrics_keys = ('rubrics_check', 'rubrics_check_result', 'rubric_check', 'Rubrics_check', 'checkpoints')
    rubrics = None
    rubrics_key = None
    for k in rubrics_keys:
        v = obj.get(k)
        if isinstance(v, dict):
            rubrics = v
            rubrics_key = k
            break

    if not rubrics:
        return eval_raw

    enriched = dict(rubrics)
    for cp_id, item in rubrics.items():
        if isinstance(item, dict):
            content = rubric_content_map.get(str(cp_id).strip(), '')
            new_item = {'content': content, **item} if content else dict(item)
            enriched[cp_id] = new_item

    obj[rubrics_key] = enriched
    return json.dumps(obj, ensure_ascii=False, indent=2)


def run(replies_excel: str, questions_excel: str, eval_batch_id: str, output_excel: str = None, diagnose: bool = False) -> None:
    eval_col = f'eval_{eval_batch_id}'
    raw_col = f'{eval_col}_raw'
    enriched_col = f'{eval_col}_raw_enriched'

    if not os.path.exists(replies_excel):
        print(f"❌ 回复表不存在: {replies_excel}")
        return

    if not os.path.exists(questions_excel):
        print(f"❌ 题目表不存在: {questions_excel}")
        return

    # 加载题目表：qid, evaluation_criteria
    qdf = pd.read_excel(questions_excel, engine='openpyxl')
    # 尝试列名：evaluation_criteria、human_rubrics、评估标准
    crit_col = 'evaluation_criteria'
    if crit_col not in qdf.columns:
        for c in qdf.columns:
            if c in ('evaluation_criteria', 'human_rubrics', '评估标准') or ('evaluation' in str(c).lower() and 'criteria' in str(c).lower()):
                qdf = qdf.rename(columns={c: crit_col})
                break
        if crit_col not in qdf.columns:
            print("❌ 题目表需含 qid、evaluation_criteria 列")
            return

    qdf['qid'] = qdf['qid'].astype(str).str.strip().map(_normalize_qid)
    qid_to_criteria = dict(zip(qdf['qid'], qdf[crit_col].fillna('')))

    # 加载回复表
    xls = pd.ExcelFile(replies_excel, engine='openpyxl')
    sheet = next((s for s in ('Sheet1', 'replies') if s in xls.sheet_names), xls.sheet_names[0])
    rdf = pd.read_excel(replies_excel, sheet_name=sheet, engine='openpyxl')

    if raw_col not in rdf.columns:
        print(f"❌ 回复表无 {raw_col} 列")
        return

    rdf['qid'] = rdf['qid'].astype(str).str.strip().map(_normalize_qid)

    # 逐行 enrichment
    enriched_values = []
    n_ok = 0
    n_skip = 0
    diag = {'empty_raw': 0, 'qid_not_in_questions': 0, 'empty_criteria': 0, 'parse_no_match': 0}
    for _, row in rdf.iterrows():
        qid = row.get('qid', '')
        raw_val = row.get(raw_col, '')
        criteria_text = qid_to_criteria.get(qid, '') or ''
        content_map = parse_criteria_to_rubric_content(criteria_text)

        if pd.isna(raw_val) or not str(raw_val).strip():
            enriched_values.append('')
            diag['empty_raw'] += 1
            n_skip += 1
            continue

        if qid not in qid_to_criteria:
            diag['qid_not_in_questions'] += 1
        elif not str(qid_to_criteria.get(qid, '')).strip():
            diag['empty_criteria'] += 1
        elif not content_map:
            diag['parse_no_match'] += 1

        enriched = enrich_rubrics_with_content(str(raw_val), content_map)
        enriched_values.append(enriched)
        if content_map:
            n_ok += 1
        else:
            n_skip += 1

    rdf[enriched_col] = enriched_values

    # 默认直接覆盖原始回复表
    out_path = output_excel if output_excel else replies_excel
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or '.', exist_ok=True)

    with pd.ExcelWriter(out_path, engine='openpyxl') as w:
        rdf.to_excel(w, sheet_name=sheet, index=False)
        # 保留原有的其他 sheet（如 batch_log）
        for s in xls.sheet_names:
            if s != sheet:
                extra = pd.read_excel(replies_excel, sheet_name=s, engine='openpyxl')
                extra.to_excel(w, sheet_name=s, index=False)

    print(f"✓ 已写入 {enriched_col} 列")
    print(f"  输出: {out_path}")
    print(f"  已补充 content: {n_ok} 条, 未补充: {n_skip} 条")
    if diagnose or n_skip > 0:
        print(f"  未补充原因: 空raw={diag['empty_raw']}, qid不在题目表={diag['qid_not_in_questions']}, "
              f"题目无criteria={diag['empty_criteria']}, criteria格式不匹配={diag['parse_no_match']}")


if __name__ == '__main__':
    proj = _project_root
    default_replies = os.path.join(proj, 'evaluation', 'outputs', 'replies', 'replies_6m.xlsx')
    default_questions = os.path.join(proj, 'evaluation', 'outputs', 'questions', 'questions_complete.xlsx')

    ap = argparse.ArgumentParser(description='为 eval_*_raw 的 rubrics_check 添加原始评估标准 content')
    ap.add_argument('--replies', default=default_replies, help=f'回复表路径，默认 {default_replies}')
    ap.add_argument('--questions', default=default_questions, help=f'题目表路径，默认 {default_questions}')
    ap.add_argument('--batch', default='batch_3', help='eval batch id')
    ap.add_argument('--output', default='', help='输出路径，默认覆盖原 replies')
    ap.add_argument('--diagnose', action='store_true', help='打印未补充原因的详细统计')
    args = ap.parse_args()

    replies_path = args.replies if os.path.isabs(args.replies) else os.path.join(proj, args.replies)
    questions_path = args.questions if os.path.isabs(args.questions) else os.path.join(proj, args.questions)
    output_path = os.path.join(proj, args.output) if args.output and not os.path.isabs(args.output) else args.output

    run(replies_path, questions_path, args.batch, output_path if args.output else None, diagnose=args.diagnose)

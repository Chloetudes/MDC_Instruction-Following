#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
诊断 rubrics_check 解析：检查 eval_*_raw 是否可正确解析并计算维度加权分。
用法: python scripts/diagnose_rubrics_parse.py --replies path/to/replies.xlsx --batch batch_2
"""
import argparse
import os
import sys

import pandas as pd

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


def diagnose(replies_excel: str, eval_batch_id: str = 'batch_2') -> None:
    eval_col = f'eval_{eval_batch_id}'
    raw_col = f'{eval_col}_raw'

    if not os.path.exists(replies_excel):
        print(f"❌ 文件不存在: {replies_excel}")
        return

    xls = pd.ExcelFile(replies_excel)
    sheet = next((s for s in ('Sheet1', 'replies') if s in xls.sheet_names), xls.sheet_names[0])
    df = pd.read_excel(replies_excel, sheet_name=sheet)

    print(f"\n📂 文件: {replies_excel}")
    print(f"   列: {list(df.columns)}")
    print(f"\n🔍 检查 {eval_col} / {raw_col}:")

    if eval_col not in df.columns:
        print(f"   ❌ 未找到 {eval_col} 列")
    else:
        n_score = df[eval_col].notna().sum()
        print(f"   ✓ {eval_col}: {n_score} 条有值")

    if raw_col not in df.columns:
        print(f"   ❌ 未找到 {raw_col} 列 — 无法计算维度加权分")
        return
    n_raw = df[raw_col].apply(lambda x: bool(x) and str(x).strip()).sum()
    print(f"   ✓ {raw_col}: {n_raw} 条有内容")

    from evaluation.analysis.rubric_dimension_analysis import (
        parse_rubrics_check_from_eval_raw,
        compute_composite_from_rubrics_check,
    )

    ok = 0
    fail = 0
    samples = []
    for idx, row in df.iterrows():
        raw = row.get(raw_col, '')
        if pd.isna(raw) or not str(raw).strip():
            continue
        check = parse_rubrics_check_from_eval_raw(str(raw))
        if check:
            ok += 1
            if len(samples) < 2:
                res = compute_composite_from_rubrics_check(check)
                samples.append({
                    'qid': row.get('qid'), 'model': row.get('model'),
                    'checkpoints': len(check), 'cla': res['cla_score'],
                    'dim_weighted': res['composite_score'], 'full_pass': res['full_pass'],
                })
        else:
            fail += 1
            if fail <= 2:
                print(f"\n   ⚠️ 解析失败示例 (行{idx}): 前100字符: {str(raw)[:100]}...")

    print(f"\n📊 解析结果: {ok} 条成功, {fail} 条失败")
    if ok == 0 and n_raw > 0:
        print("   ❌ 全部解析失败！请检查 raw 列格式是否为 JSON，且含 rubrics_check")
        print("   期望格式: {\"rubrics_check\":{\"D2_1\":{\"result\":\"PASS\",\"reason\":\"\"},...}}")
        return

    if samples:
        print("\n   ✓ 解析成功示例:")
        for s in samples:
            print(f"      qid={s['qid']} model={s['model']}: {s['checkpoints']} 检查点, CLA={s['cla']}, 维度加权={s['dim_weighted']}, 全过={s['full_pass']}")

    if ok > 0:
        print("\n✅ 可正常运行 analyze_results + generate_report，平均分将使用维度加权")
    print()


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='诊断 rubrics_check 解析')
    ap.add_argument('--replies', default='', help='replies.xlsx 路径')
    ap.add_argument('--batch', default='batch_2', help='eval batch id，如 batch_2')
    args = ap.parse_args()
    path = args.replies
    if not path:
        path = os.path.join(_project_root, 'evaluation', 'outputs', 'replies', 'replies_6m.xlsx')
    if not os.path.isabs(path):
        path = os.path.join(_project_root, path)
    diagnose(path, args.batch)

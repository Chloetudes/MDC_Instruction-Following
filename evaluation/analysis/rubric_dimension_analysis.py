# -*- coding: utf-8 -*-
"""
维度加权与 rubrics_check 解析：从 eval_*_raw 提取检查点 PASS/FAIL，计算 CLA、维度加权分、完全通过率。
与 data_loader、stage5_report、series_report、report_expansion 共用。
"""
import json
import re
from typing import Dict, List, Any, Optional

import numpy as np
import pandas as pd


# D1 不参与加权；D2–D5 权重与评测设计一致
DIMENSION_WEIGHTS = {
    'D1': 0.00,
    'D2': 0.22,
    'D3': 0.20,
    'D4': 0.08,
    'D5': 0.50,
}

DIMENSION_LABELS = {
    'D1': '业务理解',
    'D2': '流程步骤',
    'D3': '边界范围',
    'D4': '格式形式',
    'D5': '内容质量',
}


def _is_pass(val: Any) -> bool:
    """从检查点取值判断是否通过：支持 "PASS"/"FAIL" 字符串或 dict 含 result 键。"""
    if val is None:
        return False
    if isinstance(val, str):
        return str(val).strip().upper() == 'PASS'
    if isinstance(val, dict):
        r = val.get('result') or val.get('status')
        return str(r).strip().upper() == 'PASS'
    return False


# 解析时期望的 rubrics 块键名（按优先级）
_RUBRICS_CHECK_KEYS = (
    'rubrics_check', 'rubrics_check_result', 'rubric_check', 'Rubrics_check',
    'Rubrics_Check', 'checkpoints', 'check_result', 'results',
)


def _strip_markdown_code_fence(s: str) -> str:
    """去掉 ```json ... ``` 或 ``` ... ``` 包裹，便于整体解析。"""
    s = s.strip()
    for prefix in ('```json', '```JSON', '```'):
        if s.startswith(prefix):
            s = s[len(prefix):].strip()
            if s.endswith('```'):
                s = s[:-3].strip()
            break
    return s


def _fix_unescaped_newlines_in_json(s: str) -> str:
    """
    将 JSON 字符串值内的未转义换行替换为空格，使 json.loads 能解析。
    裁判模型有时在 reason 等字段里输出真实换行，导致 JSON 无效。
    """
    result = []
    i = 0
    in_string = False
    escape_next = False
    quote_char = None
    while i < len(s):
        c = s[i]
        if escape_next:
            result.append(c)
            escape_next = False
            i += 1
            continue
        if c == '\\' and in_string:
            result.append(c)
            escape_next = True
            i += 1
            continue
        if in_string:
            if c == quote_char:
                in_string = False
                result.append(c)
                i += 1
                continue
            if c in ('\n', '\r'):
                result.append(' ')
                i += 1
                if c == '\r' and i < len(s) and s[i] == '\n':
                    i += 1
                continue
            result.append(c)
            i += 1
            continue
        if c in ('"', "'"):
            in_string = True
            quote_char = c
            result.append(c)
            i += 1
            continue
        result.append(c)
        i += 1
    return ''.join(result)


def _extract_outer_json(s: str) -> Optional[str]:
    """从文本中按括号匹配提取最外层 {...}，支持任意层级嵌套。"""
    start = s.find('{')
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    quote = None
    i = start
    while i < len(s):
        c = s[i]
        if escape:
            escape = False
            i += 1
            continue
        if c == '\\' and in_string:
            escape = True
            i += 1
            continue
        if in_string:
            if c == quote:
                in_string = False
            i += 1
            continue
        if c in ('"', "'"):
            in_string = True
            quote = c
            i += 1
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
        i += 1
    return None


def _get_rubrics_check_dict(obj: dict) -> Optional[Dict[str, Any]]:
    """从解析后的 JSON 对象中取出 rubrics_check 类字典。"""
    if not isinstance(obj, dict):
        return None
    for key in _RUBRICS_CHECK_KEYS:
        val = obj.get(key)
        if isinstance(val, dict):
            return val
    return None


def parse_rubrics_check_from_eval_raw(raw_text: str) -> Dict[str, Dict[str, str]]:
    """
    从 eval_*_raw 文本中解析出 rubrics_check 字典。
    返回: { "D2_1": {"result": "PASS", "reason": ""}, "D3_1": {...}, ... }
    若解析失败返回空 dict。支持值为直接 "PASS"/"FAIL" 或 {"result": "PASS", "reason": "..."}。
    支持：整体 JSON、Markdown 代码块包裹、仅最外层括号匹配提取。
    """
    if not raw_text or not str(raw_text).strip():
        return {}
    s = str(raw_text).strip()
    # 去掉 markdown 代码块，避免 ```json ... ``` 导致整体无法解析
    s = _strip_markdown_code_fence(s)
    # 修复 reason 等字段内的未转义换行（裁判有时会输出真实换行导致 JSON 无效）
    s = _fix_unescaped_newlines_in_json(s)
    # 1) 整体解析
    try:
        obj = json.loads(s)
        check = _get_rubrics_check_dict(obj)
        if check is not None:
            return _normalize_rubrics_check(check)
    except json.JSONDecodeError:
        pass
    # 2) 按括号匹配提取最外层 JSON（支持多层嵌套的 rubrics_check）
    outer = _extract_outer_json(s)
    if outer:
        try:
            obj = json.loads(outer)
            check = _get_rubrics_check_dict(obj)
            if check is not None:
                return _normalize_rubrics_check(check)
        except json.JSONDecodeError:
            pass
    # 3) 单层嵌套的简单正则兜底
    match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', s, re.DOTALL)
    if match:
        try:
            obj = json.loads(match.group(0))
            check = _get_rubrics_check_dict(obj)
            if check is not None:
                return _normalize_rubrics_check(check)
        except json.JSONDecodeError:
            pass
    return {}


def _normalize_rubrics_check(check: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """将 rubrics_check 值统一为 {"result": "PASS"/"FAIL", "reason": "..."}。"""
    out = {}
    for k, v in check.items():
        if not k or not str(k).strip():
            continue
        key = str(k).strip()
        if isinstance(v, str):
            out[key] = {'result': v.strip().upper() if v.strip().upper() in ('PASS', 'FAIL') else v.strip(), 'reason': ''}
        elif isinstance(v, dict):
            r = (v.get('result') or v.get('status') or '').strip().upper()
            if r not in ('PASS', 'FAIL'):
                r = str(v.get('result', '')).strip() or 'FAIL'
            out[key] = {'result': r, 'reason': str(v.get('reason', '') or v.get('description', '')).strip()}
        else:
            out[key] = {'result': 'FAIL', 'reason': ''}
    return out


def get_dimension_from_checkpoint(checkpoint_id: str) -> str:
    """从检查点 ID 提取维度，如 D2_1 -> D2，D5_3 -> D5。"""
    if not checkpoint_id:
        return ''
    s = str(checkpoint_id).strip()
    for dim in ('D1', 'D2', 'D3', 'D4', 'D5'):
        if s == dim or s.startswith(dim + '_') or s.startswith(dim + '-'):
            return dim
    if s.startswith('D') and len(s) >= 2 and s[1].isdigit():
        return s[:2]
    return ''


def compute_composite_from_rubrics_check(check: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
    """
    根据解析后的 rubrics_check 计算 CLA、维度加权分、是否全过。
    返回: {
        "total": int,
        "passed": int,
        "cla_score": float (0-100),
        "full_pass": bool,
        "composite_score": float (0-100，维度加权；无权重时用 cla_score),
    }
    """
    if not check:
        return {
            'total': 0,
            'passed': 0,
            'cla_score': np.nan,
            'full_pass': False,
            'composite_score': np.nan,
        }
    total = len(check)
    passed = sum(1 for v in check.values() if _is_pass(v))
    cla_score = (passed / total * 100.0) if total > 0 else np.nan
    full_pass = (passed == total) and total > 0

    # 按维度聚合：每个维度的通过率 × 权重
    dim_scores = {}
    for cp_id, v in check.items():
        dim = get_dimension_from_checkpoint(cp_id)
        if not dim or dim not in DIMENSION_WEIGHTS:
            continue
        if dim not in dim_scores:
            dim_scores[dim] = {'pass': 0, 'total': 0}
        dim_scores[dim]['total'] += 1
        if _is_pass(v):
            dim_scores[dim]['pass'] += 1

    weighted_sum = 0.0
    weight_sum = 0.0
    for dim, w in DIMENSION_WEIGHTS.items():
        if w <= 0:
            continue
        if dim in dim_scores:
            d = dim_scores[dim]
            if d['total'] > 0:
                weighted_sum += (d['pass'] / d['total']) * w
            weight_sum += w
        else:
            weight_sum += w
    if weight_sum > 0 and dim_scores:
        dim_weighted_score = (weighted_sum / weight_sum) * 100.0
    else:
        dim_weighted_score = np.nan
    composite_score = dim_weighted_score if not np.isnan(dim_weighted_score) else cla_score

    # 各维度 ILA：该维度下全部检查点均 PASS 为 True，有任一 FAIL 为 False，该维度无检查点为 np.nan
    dimension_ila = {}
    for dim in ('D1', 'D2', 'D3', 'D4', 'D5'):
        if dim in dim_scores and dim_scores[dim]['total'] > 0:
            d = dim_scores[dim]
            dimension_ila[dim] = d['pass'] == d['total']
        else:
            dimension_ila[dim] = np.nan

    return {
        'total': total,
        'passed': passed,
        'cla_score': cla_score,
        'full_pass': full_pass,
        'composite_score': composite_score,
        'dimension_ila': dimension_ila,
    }


def compute_main_score_lianzuo(check: Dict[str, Dict[str, str]]) -> float:
    """
    主分数（连坐机制）：前置 D1、D2 任一 Fail 则该题 0 分；
    否则得分为所有 Pass 维度的权重之和 * 100。
    权重：D5=50%, D2=22%, D3=20%, D4=8%；D1 不参与加权，仅作前置。
    """
    if not check:
        return np.nan
    res = compute_composite_from_rubrics_check(check)
    dim_ila = res.get('dimension_ila') or {}
    # 连坐：D1 或 D2 任一维度有 FAIL 则 0 分
    d1_ok = dim_ila.get('D1')
    d2_ok = dim_ila.get('D2')
    if d1_ok is False or d2_ok is False:
        return 0.0
    # 无 D1/D2 检查点时，nan 视为通过
    score = 0.0
    for dim in ('D2', 'D3', 'D4', 'D5'):
        w = DIMENSION_WEIGHTS.get(dim, 0)
        if w <= 0:
            continue
        if dim_ila.get(dim) is True:
            score += w
    return round(score * 100.0, 2)


def parse_rubrics_check_detailed(raw_text: str) -> Dict[str, Dict[str, str]]:
    """
    与 parse_rubrics_check_from_eval_raw 一致，返回检查点 -> {result, reason}，供失分点分析使用。
    """
    return parse_rubrics_check_from_eval_raw(raw_text)


def analyze_rubric_dimensions(
    replies_df: pd.DataFrame,
    eval_column: str,
) -> Dict[str, Any]:
    """
    基于 eval_*_raw 解析 rubrics_check，按 D1–D5 统计每行（qid×model）的维度通过情况，
    并聚合为模型×维度统计。供 stage5_report、series_report 使用。

    返回: {
        "has_data": bool,
        "row_level_df": DataFrame 列含 qid, model, D2_pass, D2_total, D3_pass, D3_total, ...,
        "model_dimension_df": DataFrame 每模型每维度一行（model, dimension, pass_count, total_count, pass_rate）,
        "dimension_labels": dict D1–D5 -> 中文标签,
    }
    """
    result = {
        'has_data': False,
        'row_level_df': pd.DataFrame(),
        'model_dimension_df': pd.DataFrame(),
        'dimension_pivot_df': pd.DataFrame(),
        'dimension_labels': DIMENSION_LABELS.copy(),
    }
    if replies_df is None or replies_df.empty or not eval_column:
        return result
    raw_col = f"{eval_column}_raw" if not eval_column.endswith('_raw') else eval_column
    if raw_col not in replies_df.columns:
        raw_col = next((c for c in replies_df.columns if isinstance(c, str) and c.startswith('eval_') and c.endswith('_raw')), '')
    if not raw_col:
        return result

    rows = []
    for _, row in replies_df.iterrows():
        qid = row.get('qid')
        model = row.get('model')
        raw_val = row.get(raw_col, '')
        if pd.isna(raw_val) or not str(raw_val).strip():
            continue
        check = parse_rubrics_check_from_eval_raw(str(raw_val))
        if not check:
            continue
        rec = {'qid': qid, 'model': model}
        for dim in ('D1', 'D2', 'D3', 'D4', 'D5'):
            dim_items = [(k, v) for k, v in check.items() if get_dimension_from_checkpoint(k) == dim]
            total = len(dim_items)
            pass_count = sum(1 for _, v in dim_items if _is_pass(v))
            rec[f'{dim}_pass'] = pass_count
            rec[f'{dim}_total'] = total
        rows.append(rec)

    if not rows:
        return result
    row_level_df = pd.DataFrame(rows)

    # 模型×维度聚合
    model_dim_rows = []
    for dim in ('D1', 'D2', 'D3', 'D4', 'D5'):
        pcol = f'{dim}_pass'
        tcol = f'{dim}_total'
        if pcol not in row_level_df.columns:
            continue
        agg = row_level_df.groupby('model').agg({pcol: 'sum', tcol: 'sum'}).reset_index()
        agg.columns = ['model', 'pass_count', 'total_count']
        agg['dimension'] = dim
        agg['pass_rate'] = np.where(
            agg['total_count'] > 0,
            (agg['pass_count'] / agg['total_count'] * 100).round(2),
            np.nan,
        )
        model_dim_rows.append(agg)
    model_dimension_df = pd.concat(model_dim_rows, ignore_index=True) if model_dim_rows else pd.DataFrame()

    # 透视表：每行一模型，列为 D1–D5 通过率（报告与 framework_sync 使用）
    dimension_pivot_df = pd.DataFrame()
    if not model_dimension_df.empty and 'model' in model_dimension_df.columns and 'dimension' in model_dimension_df.columns:
        pivot = model_dimension_df.pivot(index='model', columns='dimension', values='pass_rate').reset_index()
        pivot.columns = [str(c) for c in pivot.columns]
        pivot = pivot.rename(columns={'model': '模型'})
        for d in ('D1', 'D2', 'D3', 'D4', 'D5'):
            if d in pivot.columns:
                pivot = pivot.rename(columns={d: f'{d}通过率'})
        dimension_pivot_df = pivot

    result['has_data'] = True
    result['row_level_df'] = row_level_df
    result['model_dimension_df'] = model_dimension_df
    result['dimension_pivot_df'] = dimension_pivot_df
    result['dimension_labels'] = DIMENSION_LABELS.copy()
    return result

# -*- coding: utf-8 -*-
"""
将报告统计数据同步更新到 EVAL_REPORT_FRAMEWORK.md。
报告生成后调用，填充 1.3 关键数据、source 分组、维度统计等。
"""
import os
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd


def _task_count(questions) -> int:
    if questions is None or questions.empty:
        return 0
    if 'qid' in questions.columns:
        return int(questions['qid'].dropna().nunique())
    return questions.shape[0]


def _source_counts(questions) -> tuple:
    public_cnt = self_cnt = 0
    if questions is None or questions.empty or 'source' not in questions.columns or 'qid' not in questions.columns:
        return 0, 0
    _self = {'H', 'R', 'HM', 'M'}
    for src, grp in questions.groupby('source', dropna=False):
        cnt = grp['qid'].dropna().nunique()
        if str(src).strip() in _self:
            self_cnt += cnt
        else:
            public_cnt += cnt
    return int(public_cnt), int(self_cnt)


def _source_counts_3(questions) -> tuple:
    """返回 (公开题数, 纯人工自建题数, M合成题数)"""
    pub = human = m_cnt = 0
    if questions is None or questions.empty or 'source' not in questions.columns or 'qid' not in questions.columns:
        return 0, 0, 0
    _human = {'H', 'R', 'HM'}
    for src, grp in questions.groupby('source', dropna=False):
        cnt = int(grp['qid'].dropna().nunique())
        s = str(src).strip()
        if s == 'M':
            m_cnt += cnt
        elif s in _human:
            human += cnt
        else:
            pub += cnt
    return pub, human, m_cnt


def sync_framework_with_report_stats(
    data: dict,
    data_cache: dict,
    framework_path: str,
) -> bool:
    """
    根据报告统计数据更新 EVAL_REPORT_FRAMEWORK.md 中的「本次运行统计快照」部分。

    Args:
        data: load_and_preprocess 返回的 data
        data_cache: 报告用的 data_cache（含 overall_ranking, source_stats, dimension_stats 等）
        framework_path: EVAL_REPORT_FRAMEWORK.md 的绝对路径

    Returns:
        是否成功更新
    """
    if not os.path.exists(framework_path):
        return False
    questions = data.get('questions', pd.DataFrame())
    replies = data.get('replies', pd.DataFrame())
    overall = data_cache.get('overall_ranking', pd.DataFrame())
    source_stats = data_cache.get('source_stats', pd.DataFrame())
    dimension_stats = data_cache.get('dimension_stats') or {}

    model_count = replies['model'].nunique() if not replies.empty else 0
    task_count = _task_count(questions)
    eval_count = replies.shape[0] if not replies.empty else 0
    public_cnt, self_cnt = _source_counts(questions)
    pub_cnt_3, human_cnt_3, m_cnt_3 = _source_counts_3(questions)

    d2_d4_note = ''
    dim_pivot = dimension_stats.get('dimension_pivot_df', pd.DataFrame())
    if not dim_pivot.empty and 'D2通过率' in dim_pivot.columns and 'D4通过率' in dim_pivot.columns:
        d2_ser = pd.to_numeric(dim_pivot['D2通过率'], errors='coerce')
        d4_ser = pd.to_numeric(dim_pivot['D4通过率'], errors='coerce')
        d2_std = d2_ser.std()
        d4_std = d4_ser.std()
        d2_d4_note = f'D2 通过率标准差 {d2_std:.2f}%，D4 通过率标准差 {d4_std:.2f}%'
    else:
        d2_d4_note = '（需 rubrics_check 解析）'

    var_ratio = ''
    var_ratio_human = ''
    pub_human_gap = ''
    rwq = data.get('replies_with_question', pd.DataFrame())
    source_gap = data_cache.get('source_gap_summary') or {}
    if source_gap:
        vr_h = source_gap.get('纯人工自建vs公开_方差比')
        var_ratio_human = f'{vr_h:.2f}' if vr_h is not None and not (isinstance(vr_h, float) and np.isnan(vr_h)) else ''
        gap = source_gap.get('公开vs纯人工自建_均分差')
        pub_human_gap = f'{gap}' if gap is not None else ''
    if not var_ratio_human and not rwq.empty and 'source_group_3' in rwq.columns:
        pub_s = rwq[rwq['source_group_3'] == '公开数据']['eval_score'].dropna()
        human_s = rwq[rwq['source_group_3'] == '纯人工自建']['eval_score'].dropna()
        if len(pub_s) > 1 and len(human_s) > 1 and pub_s.var() > 0:
            var_ratio_human = f'{float(human_s.var() / pub_s.var()):.2f}'
    if not var_ratio_human:
        var_ratio_human = '（待计算）'
    var_ratio = var_ratio_human  # 主展示用纯人工自建

    score_std = ''
    if not overall.empty and '平均分' in overall.columns:
        score_std = f"{overall['平均分'].std():.2f}"

    ts = datetime.now().strftime('%Y-%m-%d %H:%M')
    gap_row = f"| 公开 vs 纯人工自建 均分差 | {pub_human_gap} | 核心指标，越大越体现自建难度 |\n" if pub_human_gap else ""
    content = f"""| 指标 | 数值 | 说明 |
|------|------|------|
| 评测模型数 | {model_count} | 模型清单 |
| 题目总数 | {task_count} | questions 表 unique qid |
| 总评测次数 | {eval_count} | 回复表行数 |
| 公开数据题 | {public_cnt} | source 非 H/R/HM/M |
| 纯人工自建题(H/R/HM) | {human_cnt_3} | 更能反映真实业务难度 |
| M合成题 | {m_cnt_3} | 模型生成，打分可能偏高 |
| 模型均分标准差（离散度） | {score_std} | 整体排名表 |
| D2–D5 维度通过率离散度 | {d2_d4_note} | dimension_stats |
| 纯人工自建 vs 公开 方差比 | {var_ratio_human} | >1 表示自建离散度更大 |
{gap_row}_更新时间：{ts}_"""

    if not source_stats.empty:
        content += "\n\n**按 Source 分组得分**\n\n"
        content += "| source | 分组 | 题目数 | 模型均分 | 标准差 |\n"
        content += "|--------|------|--------|----------|--------|\n"
        for _, row in source_stats.iterrows():
            content += f"| {row.get('source', '')} | {row.get('分组', '')} | {row.get('题目数', '')} | {row.get('模型均分', '')} | {row.get('标准差', '')} |\n"

    try:
        with open(framework_path, 'r', encoding='utf-8') as f:
            text = f.read()
        start_m = '<!-- FRAMEWORK_STATS_SYNC_START -->'
        end_m = '<!-- FRAMEWORK_STATS_SYNC_END -->'
        if start_m in text and end_m in text:
            before = text.split(start_m)[0]
            after = text.split(end_m)[1]
            new_text = before + start_m + '\n' + content + '\n' + end_m + after
            with open(framework_path, 'w', encoding='utf-8') as f:
                f.write(new_text)
            return True
    except Exception:
        pass
    return False

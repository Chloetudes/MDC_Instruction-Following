# -*- coding: utf-8 -*-
"""
模型系列定向报告生成器

支持按公司/系列聚合模型，输出：
1. 系列内版本纵向对比（不同版本能力变化）
2. 系列与其他系列横向对比（相对优劣势）
3. 各维度（L1/L2/L3/难度）的系列表现
4. Excel 与 Markdown 双格式报告
"""
import os
from datetime import datetime
import warnings
import numpy as np
import pandas as pd
from typing import Dict, List, Optional
from scipy.stats import mannwhitneyu

import time
from .data_loader import _normalize_qid
from .chart_selection import profile_data, select_charts_for_report, render_charts_to_markdown
from .report_writer import _safe_float, _safe_str, _sanitize_excel_text

warnings.filterwarnings('ignore')


def _safe_str_stage5(x):
    return str(x).strip() if x is not None and not (isinstance(x, float) and np.isnan(x)) else ''

# 厂商/系列候选：展示名 -> 匹配 pattern 列表（用于交互式选择时展示与匹配）
VENDOR_OPTIONS = [
    ('Qwen（阿里）', ['qwen', 'qwen3', 'qwen-']),
    ('GLM（智谱）', ['glm', 'glm4', 'glm5']),
    ('Claude（Anthropic）', ['claude']),
    ('GPT（OpenAI）', ['gpt', 'gpt-4', 'gpt-5']),
    ('Gemini（Google）', ['gemini']),
    ('DeepSeek', ['deepseek']),
    ('Kimi/Moonshot', ['kimi', 'moonshot']),
    ('Doubao（字节）', ['doubao']),
    ('MiniMax', ['minimax']),
    ('Ernie（百度）', ['ernie', 'erine']),
    ('Hunyuan（腾讯）', ['hunyuan']),
    ('Grok（xAI）', ['grok']),
    ('Yi（零一）', ['yi']),
    ('LongCat', ['longcat']),
    ('MiMo/Step', ['mimo', 'step']),
]


def _match_series(model_name: str, series_patterns: List[str]) -> bool:
    model_lower = model_name.lower()
    for pattern in series_patterns:
        if pattern.lower() in model_lower:
            return True
    return False


def _build_series_mapping(all_models: List[str], model_series_config: Dict[str, List[str]]) -> Dict[str, str]:
    model_to_series = {}
    for model in all_models:
        for series_name, patterns in model_series_config.items():
            if _match_series(model, patterns):
                model_to_series[model] = series_name
                break
        else:
            model_to_series[model] = '其他'
    return model_to_series


def _compute_model_overall(replies_df: pd.DataFrame, total_questions: int = 0) -> pd.DataFrame:
    results = []
    for model in replies_df['model'].unique():
        model_df = replies_df[replies_df['model'] == model]
        scores = model_df['eval_score'].dropna()
        if len(scores) == 0:
            continue
        question_count = model_df['qid'].nunique()
        coverage = round(question_count / total_questions * 100, 1) if total_questions > 0 else None
        row = {
            'model': model,
            '评测题目数': question_count,
            '评测数量': len(scores),
            '平均分': round(float(scores.mean()), 2),
            '标准差': round(float(scores.std()), 2),
            '中位数': round(float(scores.median()), 2),
            '最高分': round(float(scores.max()), 2),
            '最低分': round(float(scores.min()), 2),
        }
        if coverage is not None:
            row['题目覆盖率(%)'] = coverage
        results.append(row)
    return pd.DataFrame(results)


def _compute_dimension_scores(replies_df: pd.DataFrame, dim_col: str) -> pd.DataFrame:
    if dim_col not in replies_df.columns:
        return pd.DataFrame()
    pivot = (
        replies_df.groupby(['model', dim_col])['eval_score']
        .mean()
        .reset_index()
        .pivot(index='model', columns=dim_col, values='eval_score')
        .round(2)
    )
    pivot.columns = [str(c) for c in pivot.columns]
    pivot = pivot.reset_index()
    return pivot


def generate_series_report(
    replies_df: pd.DataFrame,
    questions_df: pd.DataFrame,
    series_name: str,
    series_patterns: List[str],
    all_series_config: Dict[str, List[str]],
    output_excel: str,
    eval_column: str = None,
    provider: str = None,
    model: str = None,
    sysprompt_manager=None,
    focus_model: str = None,
) -> Optional[str]:
    """
    为单个模型系列生成定向分析报告。

    Args:
        replies_df: 包含 eval_score、eval_*_raw、reply 的回复表
        questions_df: 题目表（含 L1/L2/L3/difficulty_level）
        series_name: 当前系列名称，如 "Qwen"
        series_patterns: 当前系列的匹配前缀列表，如 ["qwen", "qwen2"]
        all_series_config: 全部系列配置，用于横向对比
        output_excel: 输出路径
        provider: 可选，LLM 调用 provider，与 model 同时传入时对「重点模型做错题」做与主体报告同框架的案例分析
        model: 可选，LLM 模型名
        sysprompt_manager: 可选，报告分析用 sysprompt
        focus_model: 可选，重点关注的模型（如 qwen3.5-plus）；不传则默认取本系列内均分最低的模型
    """
    # 统一 qid 类型，避免 merge 时 object 与 int64 冲突
    replies_df = replies_df.copy()
    questions_df = questions_df.copy()
    if 'qid' in replies_df.columns:
        replies_df['qid'] = replies_df['qid'].astype(str).str.strip().map(_normalize_qid)
    if 'qid' in questions_df.columns:
        questions_df['qid'] = questions_df['qid'].astype(str).str.strip().map(_normalize_qid)

    all_models = replies_df['model'].unique().tolist()
    model_to_series = _build_series_mapping(all_models, all_series_config)

    target_models = [m for m in all_models if _match_series(m, series_patterns)]
    if not target_models:
        print(f"  ⚠️ 系列 [{series_name}] 未匹配到任何模型，跳过")
        return None

    other_models = [m for m in all_models if m not in target_models]

    target_df = replies_df[replies_df['model'].isin(target_models)].copy()
    other_df = replies_df[replies_df['model'].isin(other_models)].copy()

    total_questions = replies_df['qid'].nunique()

    merge_cols = ['qid', 'L1', 'L2', 'L3', 'difficulty_level', 'source', 'source_group']
    merge_cols = [c for c in merge_cols if c in questions_df.columns]
    if 'source' in questions_df.columns and 'source_group' not in questions_df.columns:
        _self = {'H', 'R', 'HM', 'M'}
        questions_df = questions_df.copy()
        questions_df['source_group'] = questions_df['source'].apply(
            lambda x: '自建数据' if str(x).strip() in _self else '公开数据'
        )
        merge_cols = [c for c in merge_cols if c in questions_df.columns] + (['source_group'] if 'source_group' not in merge_cols else [])
    replies_with_q = replies_df.merge(
        questions_df[[c for c in merge_cols if c in questions_df.columns]],
        on='qid', how='left'
    )
    target_with_q = replies_with_q[replies_with_q['model'].isin(target_models)].copy()

    print(f"\n  📊 生成 [{series_name}] 系列报告 ({len(target_models)} 个模型)...")

    os.makedirs(os.path.dirname(os.path.abspath(output_excel)), exist_ok=True)

    with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:

        _write_series_overview(writer, series_name, target_models, target_df, other_df, model_to_series, total_questions)

        _write_version_comparison(writer, series_name, target_models, target_df, target_with_q)

        _write_cross_series_comparison(writer, series_name, replies_with_q, model_to_series, all_series_config)

        _write_dimension_analysis(writer, series_name, target_with_q, replies_with_q, model_to_series)

        _write_strength_weakness(writer, series_name, target_with_q, replies_with_q, model_to_series)

    dimension_stats = {}
    if eval_column:
        try:
            from .rubric_dimension_analysis import analyze_rubric_dimensions
            dimension_stats = analyze_rubric_dimensions(replies_df, eval_column)
        except Exception:
            pass

    case_analyses = []
    focus_for_report = focus_model
    if provider and model and not target_with_q.empty:
        if not focus_for_report:
            overall = _compute_model_overall(target_df, total_questions)
            if not overall.empty:
                overall = overall.sort_values('平均分', ascending=True).reset_index(drop=True)
                focus_for_report = str(overall.iloc[0]['model']).strip()
        if focus_for_report:
            print(f"  ▶ 重点模型做错题案例分析（{focus_for_report}）...")
            case_analyses = _run_series_focus_case_analyses(
                focus_model=focus_for_report,
                target_models=target_models,
                target_with_q=target_with_q,
                replies_df=replies_df,
                dimension_stats=dimension_stats,
                eval_column=eval_column or '',
                provider=provider,
                model=model,
                sysprompt_manager=sysprompt_manager,
                max_cases=15,
                score_threshold=60.0,
            )
            if case_analyses:
                print(f"    已分析 {len(case_analyses)} 道做错/低分题（与主体报告同框架）")

    output_md = os.path.splitext(output_excel)[0] + '.md'
    generate_series_markdown_report(
        series_name=series_name,
        target_models=target_models,
        target_df=target_df,
        other_df=other_df,
        target_with_q=target_with_q,
        replies_with_q=replies_with_q,
        model_to_series=model_to_series,
        all_series_config=all_series_config,
        total_questions=total_questions,
        output_md=output_md,
        dimension_stats=dimension_stats,
        eval_column=eval_column,
        focus_model=focus_for_report,
        case_analyses=case_analyses,
    )

    print(f"  ✓ [{series_name}] 报告已生成: {output_excel} | {output_md}")
    return output_excel


def _write_series_overview(
    writer: pd.ExcelWriter,
    series_name: str,
    target_models: List[str],
    target_df: pd.DataFrame,
    other_df: pd.DataFrame,
    model_to_series: Dict[str, str],
    total_questions: int = 0,
):
    overall_target = _compute_model_overall(target_df, total_questions)
    if overall_target.empty:
        return

    overall_target = overall_target.sort_values('平均分', ascending=False).reset_index(drop=True)
    overall_target.insert(0, '系列内排名', overall_target.index + 1)

    if not other_df.empty:
        overall_other = _compute_model_overall(other_df, total_questions)
        overall_other['所属系列'] = overall_other['model'].map(model_to_series)

        target_scores = target_df['eval_score'].dropna().values
        series_rows = []
        for series_label, group in overall_other.groupby('所属系列'):
            other_scores = other_df[other_df['model'].isin(
                overall_other[overall_other['所属系列'] == series_label]['model']
            )]['eval_score'].dropna().values
            p_value = np.nan
            if len(target_scores) >= 3 and len(other_scores) >= 3:
                try:
                    _, p_value = mannwhitneyu(target_scores, other_scores, alternative='two-sided')
                except Exception:
                    pass
            series_rows.append({
                '所属系列': series_label,
                '系列平均分': round(float(group['平均分'].mean()), 2),
                '模型数量': len(group),
                '显著性p值': round(float(p_value), 4) if not np.isnan(p_value) else 'N/A',
                '差异显著': ('是' if (not np.isnan(p_value) and p_value < 0.05) else '否') if not np.isnan(p_value) else 'N/A',
            })

        series_avg = pd.DataFrame(series_rows).sort_values('系列平均分', ascending=False).reset_index(drop=True)
        series_avg.insert(0, '系列排名', series_avg.index + 1)

        target_series_avg = round(float(target_df['eval_score'].dropna().mean()), 2)
        target_row = pd.DataFrame([{
            '系列排名': '—',
            '所属系列': f'{series_name}（本系列）',
            '系列平均分': target_series_avg,
            '模型数量': len(target_models),
            '显著性p值': '—',
            '差异显著': '—',
        }])
        series_avg = pd.concat([target_row, series_avg], ignore_index=True)
    else:
        series_avg = pd.DataFrame()

    start_row = 0
    pd.DataFrame([[f'【{series_name} 系列模型整体表现（含题目覆盖率）】']]).to_excel(
        writer, sheet_name='1_系列总览', startrow=start_row, index=False, header=False
    )
    start_row += 1
    overall_target.to_excel(writer, sheet_name='1_系列总览', startrow=start_row, index=False)
    start_row += len(overall_target) + 3

    if not series_avg.empty:
        pd.DataFrame([[f'【各系列横向对比（Mann-Whitney U 显著性检验）】']]).to_excel(
            writer, sheet_name='1_系列总览', startrow=start_row, index=False, header=False
        )
        start_row += 1
        series_avg.to_excel(writer, sheet_name='1_系列总览', startrow=start_row, index=False)

    print(f"    ✓ 1_系列总览")


def _write_version_comparison(
    writer: pd.ExcelWriter,
    series_name: str,
    target_models: List[str],
    target_df: pd.DataFrame,
    target_with_q: pd.DataFrame,
):
    if len(target_models) < 2:
        return

    overall = _compute_model_overall(target_df).sort_values('平均分', ascending=False).reset_index(drop=True)
    overall.insert(0, '版本排名', overall.index + 1)
    overall = overall.rename(columns={'model': '模型版本'})

    best_model = overall.iloc[0]['模型版本']
    worst_model = overall.iloc[-1]['模型版本']

    score_matrix = (
        target_df.groupby(['qid', 'model'])['eval_score']
        .mean()
        .reset_index()
        .pivot(index='qid', columns='model', values='eval_score')
        .round(2)
    )
    score_matrix.columns = [str(c) for c in score_matrix.columns]
    score_matrix = score_matrix.reset_index()

    start_row = 0
    pd.DataFrame([[f'【{series_name} 系列版本纵向对比】']]).to_excel(
        writer, sheet_name='2_版本纵向对比', startrow=start_row, index=False, header=False
    )
    start_row += 1
    overall.to_excel(writer, sheet_name='2_版本纵向对比', startrow=start_row, index=False)
    start_row += len(overall) + 3

    pd.DataFrame([[f'【各题目版本得分矩阵（行=题目，列=模型版本）】']]).to_excel(
        writer, sheet_name='2_版本纵向对比', startrow=start_row, index=False, header=False
    )
    start_row += 1
    score_matrix.to_excel(writer, sheet_name='2_版本纵向对比', startrow=start_row, index=False)

    if 'L1' in target_with_q.columns:
        l1_pivot = _compute_dimension_scores(target_with_q, 'L1')
        if not l1_pivot.empty:
            start_row += len(score_matrix) + 4
            pd.DataFrame([[f'【L1维度版本对比】']]).to_excel(
                writer, sheet_name='2_版本纵向对比', startrow=start_row, index=False, header=False
            )
            start_row += 1
            l1_pivot.to_excel(writer, sheet_name='2_版本纵向对比', startrow=start_row, index=False)

    print(f"    ✓ 2_版本纵向对比")


def _write_cross_series_comparison(
    writer: pd.ExcelWriter,
    series_name: str,
    replies_with_q: pd.DataFrame,
    model_to_series: Dict[str, str],
    all_series_config: Dict[str, List[str]],
):
    replies_with_q = replies_with_q.copy()
    replies_with_q['series'] = replies_with_q['model'].map(model_to_series)

    series_overall = (
        replies_with_q.groupby('series')['eval_score']
        .agg(['mean', 'std', 'count'])
        .reset_index()
        .rename(columns={'series': '系列', 'mean': '平均分', 'std': '标准差', 'count': '评测数量'})
    )
    series_overall['平均分'] = series_overall['平均分'].round(2)
    series_overall['标准差'] = series_overall['标准差'].round(2)
    series_overall = series_overall.sort_values('平均分', ascending=False).reset_index(drop=True)
    series_overall.insert(0, '系列排名', series_overall.index + 1)

    target_rank = series_overall[series_overall['系列'] == series_name].index
    target_rank_val = int(target_rank[0]) + 1 if len(target_rank) > 0 else 'N/A'

    start_row = 0
    pd.DataFrame([[f'【{series_name} vs 其他系列整体对比（系列排名第 {target_rank_val} 位）】']]).to_excel(
        writer, sheet_name='3_系列横向对比', startrow=start_row, index=False, header=False
    )
    start_row += 1
    series_overall.to_excel(writer, sheet_name='3_系列横向对比', startrow=start_row, index=False)
    start_row += len(series_overall) + 3

    for dim_col, dim_label in [('L1', 'L1维度'), ('difficulty_level', '难度等级')]:
        if dim_col not in replies_with_q.columns:
            continue
        dim_pivot = (
            replies_with_q.groupby(['series', dim_col])['eval_score']
            .mean()
            .reset_index()
            .pivot(index='series', columns=dim_col, values='eval_score')
            .round(2)
        )
        dim_pivot.columns = [str(c) for c in dim_pivot.columns]
        dim_pivot = dim_pivot.reset_index().rename(columns={'series': '系列'})

        pd.DataFrame([[f'【{dim_label}系列对比】']]).to_excel(
            writer, sheet_name='3_系列横向对比', startrow=start_row, index=False, header=False
        )
        start_row += 1
        dim_pivot.to_excel(writer, sheet_name='3_系列横向对比', startrow=start_row, index=False)
        start_row += len(dim_pivot) + 3

    print(f"    ✓ 3_系列横向对比")


def _write_dimension_analysis(
    writer: pd.ExcelWriter,
    series_name: str,
    target_with_q: pd.DataFrame,
    all_with_q: pd.DataFrame,
    model_to_series: Dict[str, str],
):
    start_row = 0

    for dim_col, dim_label in [('L1', 'L1'), ('L2', 'L2'), ('L3', 'L3'), ('difficulty_level', '难度等级')]:
        if dim_col not in target_with_q.columns:
            continue

        target_dim = (
            target_with_q.groupby(dim_col)['eval_score']
            .agg(['mean', 'count'])
            .reset_index()
            .rename(columns={dim_col: dim_label, 'mean': f'{series_name}系列均分', 'count': '评测数量'})
        )
        target_dim[f'{series_name}系列均分'] = target_dim[f'{series_name}系列均分'].round(2)

        all_dim = (
            all_with_q.groupby(dim_col)['eval_score']
            .mean()
            .reset_index()
            .rename(columns={dim_col: dim_label, 'eval_score': '全体均分'})
        )
        all_dim['全体均分'] = all_dim['全体均分'].round(2)

        merged = target_dim.merge(all_dim, on=dim_label, how='left')
        merged['相对全体差值'] = (merged[f'{series_name}系列均分'] - merged['全体均分']).round(2)
        merged = merged.sort_values(f'{series_name}系列均分', ascending=False).reset_index(drop=True)

        pd.DataFrame([[f'【{dim_label}维度分析】']]).to_excel(
            writer, sheet_name='4_维度深度分析', startrow=start_row, index=False, header=False
        )
        start_row += 1
        merged.to_excel(writer, sheet_name='4_维度深度分析', startrow=start_row, index=False)
        start_row += len(merged) + 3

    print(f"    ✓ 4_维度深度分析")


def _write_strength_weakness(
    writer: pd.ExcelWriter,
    series_name: str,
    target_with_q: pd.DataFrame,
    all_with_q: pd.DataFrame,
    model_to_series: Dict[str, str],
):
    if 'L2' not in target_with_q.columns:
        return

    target_l2 = (
        target_with_q.groupby('L2')['eval_score']
        .mean()
        .reset_index()
        .rename(columns={'eval_score': f'{series_name}均分'})
    )
    all_l2 = (
        all_with_q.groupby('L2')['eval_score']
        .mean()
        .reset_index()
        .rename(columns={'eval_score': '全体均分'})
    )
    merged = target_l2.merge(all_l2, on='L2', how='inner')
    merged['相对优势'] = (merged[f'{series_name}均分'] - merged['全体均分']).round(2)
    merged['评测数量'] = target_with_q.groupby('L2')['eval_score'].count().reindex(merged['L2']).values

    strengths = merged.nlargest(10, '相对优势').reset_index(drop=True)
    strengths.insert(0, '优势排名', strengths.index + 1)

    weaknesses = merged.nsmallest(10, '相对优势').reset_index(drop=True)
    weaknesses.insert(0, '劣势排名', weaknesses.index + 1)

    start_row = 0
    pd.DataFrame([[f'【{series_name} 系列相对优势 TOP10（L2维度）】']]).to_excel(
        writer, sheet_name='5_优劣势分析', startrow=start_row, index=False, header=False
    )
    start_row += 1
    strengths.to_excel(writer, sheet_name='5_优劣势分析', startrow=start_row, index=False)
    start_row += len(strengths) + 3

    pd.DataFrame([[f'【{series_name} 系列相对劣势 TOP10（L2维度）】']]).to_excel(
        writer, sheet_name='5_优劣势分析', startrow=start_row, index=False, header=False
    )
    start_row += 1
    weaknesses.to_excel(writer, sheet_name='5_优劣势分析', startrow=start_row, index=False)

    print(f"    ✓ 5_优劣势分析")


def _df_to_md_table(df: pd.DataFrame, max_rows: int = 100) -> str:
    """将 DataFrame 转为 Markdown 表格。"""
    if df is None or df.empty:
        return '_（无数据）_\n'
    display_df = df.head(max_rows)
    cols = list(display_df.columns)
    lines = ['| ' + ' | '.join(str(c) for c in cols) + ' |']
    lines.append('| ' + ' | '.join(['---'] * len(cols)) + ' |')
    for _, row in display_df.iterrows():
        cells = []
        for col in cols:
            val = row[col]
            if isinstance(val, float) and not np.isnan(val):
                cells.append(f'{val:.3f}' if abs(val) < 10 else f'{val:.2f}')
            else:
                cells.append(str(val) if pd.notna(val) else '')
        lines.append('| ' + ' | '.join(cells) + ' |')
    return '\n'.join(lines) + '\n'


L2_D_MAPPING_DESC = """L2 约束类型与 D 维度对应：流程步骤→D2 操作执行逻辑，格式输出→D4 格式要求，边界范围/数量篇幅→D3 边界限制；便于从约束设计与模型能力两端对齐分析。"""


def _identify_series_badcases(
    target_with_q: pd.DataFrame,
    replies_with_q: pd.DataFrame,
    target_models: List[str],
    min_gap: float = 15,
    max_cases: int = 15,
) -> List[dict]:
    """
    找出本系列明显落后于全体均分的题目（badcase）。
    返回 [{"qid": qid, "series_avg": x, "all_avg": y, "gap": series_avg - all_avg}, ...]，按 gap 升序（最差优先）。
    """
    target_set = {str(m).strip() for m in target_models}
    q_stats = []
    for qid in replies_with_q['qid'].unique():
        all_q = replies_with_q[replies_with_q['qid'] == qid]
        target_q = all_q[all_q['model'].astype(str).str.strip().isin(target_set)]
        if target_q.empty:
            continue
        all_scores = all_q['eval_score'].dropna()
        target_scores = target_q['eval_score'].dropna()
        if all_scores.empty or target_scores.empty:
            continue
        all_avg = float(all_scores.mean())
        series_avg = float(target_scores.mean())
        gap = series_avg - all_avg
        if gap <= -min_gap:  # 系列显著低于全体
            q_stats.append({'qid': str(qid).strip(), 'series_avg': round(series_avg, 2), 'all_avg': round(all_avg, 2), 'gap': round(gap, 2)})
    q_stats.sort(key=lambda x: x['gap'])
    return q_stats[:max_cases]


def _identify_series_good_cases(
    target_with_q: pd.DataFrame,
    replies_with_q: pd.DataFrame,
    target_models: List[str],
    min_gap: float = 10,
    max_cases: int = 5,
) -> List[dict]:
    """
    找出本系列明显领先于全体均分的题目（典型案例）。
    返回 [{"qid": qid, "series_avg": x, "all_avg": y, "gap": series_avg - all_avg}, ...]，按 gap 降序。
    若没有符合条件的题目则返回空列表。
    """
    target_set = {str(m).strip() for m in target_models}
    q_stats = []
    for qid in replies_with_q['qid'].unique():
        all_q = replies_with_q[replies_with_q['qid'] == qid]
        target_q = all_q[all_q['model'].astype(str).str.strip().isin(target_set)]
        if target_q.empty:
            continue
        all_scores = all_q['eval_score'].dropna()
        target_scores = target_q['eval_score'].dropna()
        if all_scores.empty or target_scores.empty:
            continue
        all_avg = float(all_scores.mean())
        series_avg = float(target_scores.mean())
        gap = series_avg - all_avg
        if gap >= min_gap:
            q_stats.append({'qid': str(qid).strip(), 'series_avg': round(series_avg, 2), 'all_avg': round(all_avg, 2), 'gap': round(gap, 2)})
    q_stats.sort(key=lambda x: x['gap'], reverse=True)
    return q_stats[:max_cases]


def _build_series_case_analysis(
    qid: str,
    target_with_q: pd.DataFrame,
    replies_with_q: pd.DataFrame,
    target_models: List[str],
    dimension_stats: dict,
    eval_column: str = None,
    is_badcase: bool = True,
) -> Optional[dict]:
    """
    构建单题的案例分析（参考综合报告格式），含题目、得分、维度得失分、失分点分析。
    is_badcase=True 时侧重失分点分析；False 时为典型案例简要分析。
    """
    try:
        from .rubric_dimension_analysis import (
            DIMENSION_LABELS,
            get_dimension_from_checkpoint,
            parse_rubrics_check_detailed,
        )
    except ImportError:
        DIMENSION_LABELS = {}
        get_dimension_from_checkpoint = lambda x: ''
        parse_rubrics_check_detailed = lambda x: {}

    target_set = {str(m).strip() for m in target_models}
    q_target = target_with_q[(target_with_q['qid'].astype(str).str.strip() == str(qid).strip()) &
                            (target_with_q['model'].astype(str).str.strip().isin(target_set))]
    q_all = replies_with_q[replies_with_q['qid'].astype(str).str.strip() == str(qid).strip()]
    if q_target.empty or q_all.empty:
        return None

    first = q_target.iloc[0]
    query = str(first.get('query', ''))[:500]
    l1 = str(first.get('L1', ''))
    l2 = str(first.get('L2', ''))
    l3 = str(first.get('L3', ''))
    difficulty = str(first.get('difficulty_level', ''))

    model_scores = dict(q_target.groupby('model')['eval_score'].mean().round(2))
    all_scores = dict(q_all.groupby('model')['eval_score'].mean().dropna())
    best_score = float(max(all_scores.values())) if all_scores else 0.0
    best_model = next((m for m, s in all_scores.items() if float(s) == best_score), '')
    model_gaps = {m: round(best_score - float(s), 2) for m, s in model_scores.items()}

    dimension_info = ''
    dim_pass_rates = {}
    row_level_df = dimension_stats.get('row_level_df', pd.DataFrame())
    dim_labels = dimension_stats.get('dimension_labels', DIMENSION_LABELS)
    if not row_level_df.empty and 'qid' in row_level_df.columns:
        q_rows = row_level_df[(row_level_df['qid'].astype(str).str.strip() == str(qid).strip()) &
                              (row_level_df['model'].astype(str).str.strip().isin(target_set))]
        if not q_rows.empty:
            lines = []
            for _, r in q_rows.iterrows():
                model = r.get('model', '')
                parts = []
                for d in ['D2', 'D3', 'D4', 'D5']:
                    p, t = r.get(f'{d}_pass', 0), r.get(f'{d}_total', 0)
                    if t and t > 0:
                        rate = round(p / t * 100, 1)
                        dim_pass_rates[f'{model}_{d}'] = rate
                        label = dim_labels.get(d, d)
                        parts.append(f'{label}:{p}/{t}({rate}%)')
                if parts:
                    lines.append(f'- {model}: ' + ' | '.join(parts))
            if lines:
                dimension_info = '\n'.join(lines)

    loss_analysis = ''
    if is_badcase and eval_column:
        raw_col = f"{eval_column}_raw" if not eval_column.endswith('_raw') else eval_column
        if raw_col in target_with_q.columns:
            failed_by_dim: Dict[str, List[str]] = {}
            reasons_by_dim: Dict[str, List[str]] = {}
            for model in model_scores:
                row = q_target[q_target['model'] == model]
                if row.empty:
                    continue
                raw_val = row.iloc[0].get(raw_col, '')
                if pd.isna(raw_val) or not str(raw_val).strip():
                    continue
                detailed = parse_rubrics_check_detailed(str(raw_val))
                for cp, info in detailed.items():
                    if info.get('result') == 'FAIL':
                        dim = get_dimension_from_checkpoint(cp)
                        if dim:
                            if dim not in failed_by_dim:
                                failed_by_dim[dim] = []
                                reasons_by_dim[dim] = []
                            if cp not in failed_by_dim[dim]:
                                failed_by_dim[dim].append(cp)
                            r = (info.get('reason') or '').strip()[:150]
                            if r and r not in reasons_by_dim[dim]:
                                reasons_by_dim[dim].append(r)

            dim_order = ['D2', 'D3', 'D4', 'D5']
            parts = []
            for d in dim_order:
                if d not in failed_by_dim or not failed_by_dim[d]:
                    continue
                label = dim_labels.get(d, d)
                cps = failed_by_dim[d]
                reasons = reasons_by_dim.get(d, [])
                reason_summary = ''
                if reasons:
                    reason_summary = '；'.join(reasons[:2])
                part = f"**{label}**：本系列在 {', '.join(cps[:5])}{'...' if len(cps) > 5 else ''} 等子项上失分"
                if reason_summary:
                    part += f"。主要表现为：{reason_summary}"
                part += '。'
                parts.append(part)
            if parts:
                loss_analysis = '\n\n'.join(parts)

    return {
        'qid': qid,
        'query': query,
        'L1': l1,
        'L2': l2,
        'L3': l3,
        'difficulty_level': difficulty,
        'model_scores': model_scores,
        'model_gaps': model_gaps,
        'best_score': best_score,
        'best_model': best_model,
        'all_avg': round(float(q_all['eval_score'].mean()), 2),
        'series_avg': round(float(q_target['eval_score'].mean()), 2),
        'dimension_info': dimension_info,
        'loss_analysis': loss_analysis,
        'is_badcase': is_badcase,
    }


def _run_series_focus_case_analyses(
    focus_model: str,
    target_models: List[str],
    target_with_q: pd.DataFrame,
    replies_df: pd.DataFrame,
    dimension_stats: dict,
    eval_column: str,
    provider: str,
    model: str,
    sysprompt_manager=None,
    max_cases: int = 15,
    score_threshold: float = 60.0,
    temperature: float = 0.3,
    timeout: int = 120,
) -> List[dict]:
    """
    针对重点模型（如 qwen3.5-plus）做错的题，按与主体报告相同的分析逻辑与格式做案例分析：
    分数排序 + 分差划分第一/第二/第三梯队，调用 LLM 生成综合评估与失分点分析。
    返回与主体报告案例结构一致的 case 列表，供系列报告以同框架渲染。
    """
    try:
        from config import get_provider
        from ..stages.stage5_report import (
            _compute_tier_models,
            _build_case_analysis_prompt,
            _parse_analysis_response,
        )
    except ImportError:
        return []
    focus_model = str(focus_model).strip()
    target_set = {str(m).strip() for m in target_models}
    if focus_model not in target_set:
        return []
    # 找出重点模型得分低的题目：按该模型本题得分升序取最差 max_cases 题（或先取低于阈值的题）
    fm_scores = target_with_q[target_with_q['model'].astype(str).str.strip() == focus_model][['qid', 'eval_score']]
    if fm_scores.empty:
        return []
    qid_means = fm_scores.groupby('qid')['eval_score'].mean()
    below = qid_means[qid_means < score_threshold].sort_values().index.tolist()
    worst_any = qid_means.sort_values().index.tolist()[:max_cases]
    bad_qids = (below + [q for q in worst_any if q not in below])[:max_cases] if below else worst_any
    if not bad_qids:
        return []
    provider_obj = get_provider(provider)
    from clients.openai_client import OAIClient
    client = OAIClient(
        base_url=provider_obj.base_url,
        api_key=provider_obj.api_key,
        protocol=provider_obj.protocol,
        auth_header=provider_obj.auth_header,
        auth_prefix=provider_obj.auth_prefix,
        extra_headers=provider_obj.extra_headers or {},
        timeout=timeout,
    )
    report_sysprompt = ''
    if sysprompt_manager:
        report_sysprompt = (sysprompt_manager.get('report_analysis', '') or '') if hasattr(sysprompt_manager, 'get') else ''
    from ..stages.stage5_report import DEFAULT_REPORT_SYSPROMPT
    sysprompt = report_sysprompt or DEFAULT_REPORT_SYSPROMPT
    row_level_df = dimension_stats.get('row_level_df', pd.DataFrame())
    dim_labels = dimension_stats.get('dimension_labels', {})
    eval_col_candidates = [c for c in replies_df.columns if isinstance(c, str) and c.startswith('eval_') and c.endswith('_raw')]
    case_analyses = []
    for qid in bad_qids:
        qid = str(qid).strip()
        q_target = target_with_q[(target_with_q['qid'].astype(str).str.strip() == qid) &
                                 (target_with_q['model'].astype(str).str.strip().isin(target_set))]
        if q_target.empty or q_target['model'].nunique() < 2:
            continue
        first = q_target.iloc[0]
        query = _safe_str_stage5(first.get('query', ''))
        evaluation_criteria = _safe_str_stage5(first.get('evaluation_criteria', ''))
        l1 = _safe_str_stage5(first.get('L1', ''))
        l2 = _safe_str_stage5(first.get('L2', ''))
        l3 = _safe_str_stage5(first.get('L3', ''))
        difficulty = _safe_str_stage5(first.get('difficulty_level', ''))
        ds = first.get('difficulty_score', '')
        difficulty_score = f'{float(ds):.2f}' if isinstance(ds, (int, float)) and not (isinstance(ds, float) and np.isnan(ds)) else _safe_str_stage5(ds)
        model_scores = dict(q_target.groupby('model')['eval_score'].mean().dropna())
        score_range = float(max(model_scores.values()) - min(model_scores.values())) if model_scores else 0
        dimension_info = ''
        if not row_level_df.empty and 'qid' in row_level_df.columns:
            q_rows = row_level_df[(row_level_df['qid'].astype(str).str.strip() == qid) &
                                (row_level_df['model'].astype(str).str.strip().isin(target_set))]
            if not q_rows.empty:
                lines = []
                for _, r in q_rows.iterrows():
                    model = r.get('model', '')
                    parts = []
                    for d in ['D2', 'D3', 'D4', 'D5']:
                        p, t = r.get(f'{d}_pass', 0), r.get(f'{d}_total', 0)
                        if t and t > 0:
                            label = dim_labels.get(d, d)
                            parts.append(f'{label}:{p}/{t}')
                    if parts:
                        lines.append(f'- {model}: ' + ' | '.join(parts))
                if lines:
                    dimension_info = '\n'.join(lines)
        model_evaluations = {}
        for m in model_scores:
            row = replies_df[(replies_df['qid'].astype(str).str.strip() == qid) & (replies_df['model'].astype(str).str.strip() == str(m).strip())]
            if not row.empty:
                for raw_col in eval_col_candidates:
                    raw_val = row.iloc[0].get(raw_col, '')
                    if pd.notna(raw_val) and str(raw_val).strip():
                        model_evaluations[m] = str(raw_val).strip()
                        break
        model_replies = {}
        for m in model_scores:
            row = replies_df[(replies_df['qid'].astype(str).str.strip() == qid) & (replies_df['model'].astype(str).str.strip() == str(m).strip())]
            if not row.empty and 'reply' in replies_df.columns:
                model_replies[m] = _safe_str_stage5(row.iloc[0].get('reply', ''))
        reference_answer = ''
        if not q_target.empty:
            ref = q_target.iloc[0].get('reference', '') or q_target.iloc[0].get('参考答案', '')
            if pd.notna(ref) and str(ref).strip():
                reference_answer = str(ref).strip()
        tier_models = _compute_tier_models(model_scores, None, qid, num_tiers=3)
        sys_content, user_content = _build_case_analysis_prompt(
            qid=qid,
            query=query,
            evaluation_criteria=evaluation_criteria,
            model_scores=model_scores,
            model_evaluations=model_evaluations,
            model_replies=model_replies,
            expert_opinion='',
            tier_models=tier_models,
            l1=l1, l2=l2, l3=l3,
            difficulty=difficulty,
            difficulty_score=difficulty_score,
            source='',
            dimension_info=dimension_info,
            reference_answer=reference_answer,
            sysprompt=sysprompt,
        )
        try:
            response = client.chat(
                messages=[{'role': 'system', 'content': sys_content}, {'role': 'user', 'content': user_content}],
                model=model,
                temperature=temperature,
                timeout=timeout,
                max_tokens=8192,
            )
            response_text = _safe_str_stage5(response)
        except Exception:
            response_text = ''
        ai_summary, ai_analysis = _parse_analysis_response(response_text)
        best_score = float(max(model_scores.values())) if model_scores else 0.0
        best_model = next((m for m, s in model_scores.items() if float(s) == best_score), '')
        model_gaps = {m: round(best_score - float(s), 2) for m, s in model_scores.items()}
        case_analyses.append({
            'qid': qid,
            'query': query,
            'L1': l1, 'L2': l2, 'L3': l3,
            'difficulty_level': difficulty,
            'difficulty_score': difficulty_score,
            'model_scores': model_scores,
            'model_gaps': model_gaps,
            'best_model': best_model,
            'best_score': best_score,
            'score_range': score_range,
            'dimension_info': dimension_info,
            'tier_models': tier_models,
            'ai_summary': ai_summary,
            'ai_analysis': ai_analysis,
        })
        time.sleep(0.3)
    return case_analyses


def _render_series_case_like_main(case: dict) -> List[str]:
    """按主体报告同一框架输出单条案例：题目内容、模型分档表现、维度表现、AI综合评估、失分点分析。"""
    from .report_writer_md import _section
    lines = []
    qid = _safe_str(case.get('qid', ''))
    query = _safe_str(case.get('query', ''))
    l1 = _safe_str(case.get('L1', ''))
    l3 = _safe_str(case.get('L3', ''))
    difficulty_level = _safe_str(case.get('difficulty_level', ''))
    difficulty_score = _safe_str(case.get('difficulty_score', ''))
    difficulty = f'{difficulty_level}' + (f' / {difficulty_score}分' if difficulty_score and str(difficulty_score) not in ('', 'nan', 'None') else '')
    model_scores = case.get('model_scores', {})
    best_model = _safe_str(case.get('best_model', ''))
    best_score = _safe_float(case.get('best_score', 0))
    ai_summary = _safe_str(case.get('ai_summary', ''))
    ai_analysis = _safe_str(case.get('ai_analysis', ''))
    score_range = _safe_float(case.get('score_range', 0))
    dimension_info = _safe_str(case.get('dimension_info', ''))
    tier_models = case.get('tier_models', [])
    lines.append(_section(f'案例 Q{qid}', 4))
    lines.append(f'- **L1**: {l1} | **L3**: {l3} | **难度**: {difficulty} | **分数范围**: {score_range:.1f}\n')
    if query:
        q = _sanitize_excel_text(query)
        lines.append(_section('题目内容', 5))
        lines.append(f'> {q[:300]}{"..." if len(q) > 300 else ""}\n\n')
    if model_scores:
        lines.append(_section('模型分档表现', 5))
        if best_model and best_score is not None:
            lines.append(f'- **本题最佳**：{best_model}（{best_score:.1f} 分）\n')
        for tier_name, models in tier_models:
            lines.append(f'- **{tier_name}**：{", ".join(models[:8])}{"…" if len(models) > 8 else ""}\n')
        lines.append('\n')
    if dimension_info:
        lines.append(_section('本题目各模型维度表现（D2/D3/D4/D5 通过情况）', 5))
        lines.append(f'```\n{dimension_info}\n```\n\n')
    if ai_summary:
        lines.append(_section('AI综合评估', 5))
        lines.append(f'{_sanitize_excel_text(ai_summary)}\n\n')
    if ai_analysis:
        lines.append(_section('失分点分析', 5))
        lines.append(f'{_sanitize_excel_text(ai_analysis)}\n\n')
    lines.append('---\n\n')
    return lines


def generate_series_markdown_report(
    series_name: str,
    target_models: List[str],
    target_df: pd.DataFrame,
    other_df: pd.DataFrame,
    target_with_q: pd.DataFrame,
    replies_with_q: pd.DataFrame,
    model_to_series: Dict[str, str],
    all_series_config: Dict[str, List[str]],
    total_questions: int,
    output_md: str,
    dimension_stats: dict = None,
    eval_column: str = None,
    focus_model: str = None,
    case_analyses: List[dict] = None,
) -> Optional[str]:
    """生成厂商专项报告的 Markdown 详细分析版本。结构与主体报告对齐，侧重厂商关心的版本迭代、优劣势、与竞品差距，含典型案例与 Badcase 分析。
    若传入 case_analyses（重点模型做错题的 LLM 案例分析），则增加「重点模型做错题案例分析」一节，与主体报告同框架。"""
    dimension_stats = dimension_stats or {}
    case_analyses = case_analyses or []
    lines = []
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    lines.append(f'# {series_name} 系列评测专项报告\n')
    lines.append(f'> 生成时间: {ts}  \n')
    lines.append(f'> 系列模型数: **{len(target_models)}** | 评测题目数: **{total_questions}**\n')
    lines.append('\n---\n')
    lines.append('**目录**：1. [系列总览](#1-系列总览) | 2. [按数据来源分组](#2-按数据来源分组) | 3. [版本纵向对比](#3-版本纵向对比) | 4. [系列横向对比](#4-系列横向对比) | 5. [维度深度分析](#5-维度深度分析) | 6. [D 维度得失分](#6-d-维度得失分) | 7. [优劣势分析](#7-优劣势分析) | 8. [厂商视角小结](#8-厂商视角小结) | 9. [重点模型做错题案例分析](#9-重点模型做错题案例分析) | 10. [典型案例](#10-典型案例) | 11. [Badcase 案例分析](#11-badcase-案例分析)\n')
    lines.append('\n---\n')

    # 1. 系列总览
    lines.append('## 1. 系列总览\n')
    overall_target = _compute_model_overall(target_df, total_questions)
    if not overall_target.empty:
        overall_target = overall_target.sort_values('平均分', ascending=False).reset_index(drop=True)
        overall_target.insert(0, '系列内排名', overall_target.index + 1)
        overall_target = overall_target.rename(columns={'model': '模型'})
        lines.append('### 本系列模型整体表现\n')
        lines.append(_df_to_md_table(overall_target))
    else:
        lines.append('_（无数据）_\n')

    series_avg = None
    if not other_df.empty:
        overall_other = _compute_model_overall(other_df, total_questions)
        overall_other['所属系列'] = overall_other['model'].map(model_to_series)
        target_scores = target_df['eval_score'].dropna().values
        series_rows = []
        for series_label, group in overall_other.groupby('所属系列'):
            other_scores = other_df[other_df['model'].isin(
                overall_other[overall_other['所属系列'] == series_label]['model']
            )]['eval_score'].dropna().values
            p_value = np.nan
            if len(target_scores) >= 3 and len(other_scores) >= 3:
                try:
                    _, p_value = mannwhitneyu(target_scores, other_scores, alternative='two-sided')
                except Exception:
                    pass
            series_rows.append({
                '所属系列': series_label,
                '系列平均分': round(float(group['平均分'].mean()), 2),
                '模型数量': len(group),
                '显著性p值': round(float(p_value), 4) if not np.isnan(p_value) else 'N/A',
                '差异显著': ('是' if (not np.isnan(p_value) and p_value < 0.05) else '否') if not np.isnan(p_value) else 'N/A',
            })
        series_avg = pd.DataFrame(series_rows).sort_values('系列平均分', ascending=False).reset_index(drop=True)
        series_avg.insert(0, '系列排名', series_avg.index + 1)
        target_series_avg = round(float(target_df['eval_score'].dropna().mean()), 2)
        target_row = pd.DataFrame([{
            '系列排名': '—',
            '所属系列': f'{series_name}（本系列）',
            '系列平均分': target_series_avg,
            '模型数量': len(target_models),
            '显著性p值': '—',
            '差异显著': '—',
        }])
        series_avg = pd.concat([target_row, series_avg], ignore_index=True)
        lines.append('### 各系列横向对比（Mann-Whitney U 显著性检验）\n')
        lines.append(_df_to_md_table(series_avg))
    lines.append('\n')

    # 1.1 数据可视化（本系列模型柱状图、L1 热力图等，与主体报告图表风格一致）
    try:
        series_data = {'replies': target_df, 'replies_with_question': target_with_q}
        series_cache = {
            'overall_ranking': overall_target.copy() if not overall_target.empty else pd.DataFrame(),
            'dimension_stats': dimension_stats or {},
        }
        profile = profile_data(series_data, series_cache)
        chart_configs = select_charts_for_report(series_data, series_cache, profile)
        if chart_configs:
            chart_md = render_charts_to_markdown(series_data, series_cache, chart_configs, output_md)
            if chart_md:
                lines.append('### 数据可视化\n\n')
                lines.append(chart_md)
                lines.append('\n')
    except Exception as e:
        lines.append(f'_（系列图表生成跳过: {e}）_\n\n')

    # 2. 按数据来源分组（优先 公开/纯人工自建/M合成 三分组，突出自建难度）
    lines.append('## 2. 按数据来源分组\n')
    if 'source_group_3' in target_with_q.columns:
        src_pivot = (
            target_with_q.groupby('source_group_3')['eval_score']
            .agg(['mean', 'std', 'count'])
            .reset_index()
            .rename(columns={'source_group_3': '数据来源', 'mean': '本系列均分', 'std': '标准差', 'count': '评测数量'})
        )
        # 固定顺序：公开数据、纯人工自建、M合成
        order_map = {'公开数据': 0, '纯人工自建': 1, 'M合成': 2}
        src_pivot['_ord'] = src_pivot['数据来源'].map(lambda x: order_map.get(x, 9))
        src_pivot = src_pivot.sort_values('_ord').drop('_ord', axis=1).reset_index(drop=True)
        src_pivot['本系列均分'] = src_pivot['本系列均分'].round(2)
        src_pivot['标准差'] = src_pivot['标准差'].round(2)
        lines.append('本系列在公开/纯人工自建(H/R/HM)/M合成 三分组上的得分（纯人工自建更能反映真实业务难度，M合成打分可能偏高）：\n')
        lines.append(_df_to_md_table(src_pivot))
    elif 'source_group' in target_with_q.columns:
        src_pivot = (
            target_with_q.groupby('source_group')['eval_score']
            .agg(['mean', 'std', 'count'])
            .reset_index()
            .rename(columns={'source_group': '数据来源', 'mean': '本系列均分', 'std': '标准差', 'count': '评测数量'})
        )
        src_pivot['本系列均分'] = src_pivot['本系列均分'].round(2)
        src_pivot['标准差'] = src_pivot['标准差'].round(2)
        lines.append('本系列在公开数据与自建数据上的得分分布（与主体报告 source 八值分组一致）：\n')
        lines.append(_df_to_md_table(src_pivot))
    else:
        lines.append('_（无 source 分组数据）_\n')
    lines.append('\n')

    # 3. 版本纵向对比
    lines.append('## 3. 版本纵向对比\n')
    if len(target_models) >= 2:
        overall = _compute_model_overall(target_df).sort_values('平均分', ascending=False).reset_index(drop=True)
        overall.insert(0, '版本排名', overall.index + 1)
        overall = overall.rename(columns={'model': '模型版本'})
        lines.append('### 本系列版本排名\n')
        lines.append(_df_to_md_table(overall))
        score_matrix = (
            target_df.groupby(['qid', 'model'])['eval_score']
            .mean().reset_index()
            .pivot(index='qid', columns='model', values='eval_score')
            .round(2)
        )
        score_matrix.columns = [str(c) for c in score_matrix.columns]
        score_matrix = score_matrix.reset_index()
        lines.append('### 各题目版本得分矩阵（行=题目，列=模型版本）\n')
        lines.append(_df_to_md_table(score_matrix, max_rows=30))
        if 'L1' in target_with_q.columns:
            l1_pivot = _compute_dimension_scores(target_with_q, 'L1')
            if not l1_pivot.empty:
                l1_pivot = l1_pivot.rename(columns={'model': '模型'})
                lines.append('### L1 维度版本对比\n')
                lines.append(_df_to_md_table(l1_pivot))
    else:
        lines.append('_（本系列仅 1 个模型，无版本对比）_\n')
    lines.append('\n')

    # 4. 系列横向对比
    lines.append('## 4. 系列横向对比\n')
    replies_with_q = replies_with_q.copy()
    replies_with_q['series'] = replies_with_q['model'].map(model_to_series)
    series_overall = (
        replies_with_q.groupby('series')['eval_score']
        .agg(['mean', 'std', 'count'])
        .reset_index()
        .rename(columns={'series': '系列', 'mean': '平均分', 'std': '标准差', 'count': '评测数量'})
    )
    series_overall['平均分'] = series_overall['平均分'].round(2)
    series_overall['标准差'] = series_overall['标准差'].round(2)
    series_overall = series_overall.sort_values('平均分', ascending=False).reset_index(drop=True)
    series_overall.insert(0, '系列排名', series_overall.index + 1)
    target_rank = series_overall[series_overall['系列'] == series_name].index
    target_rank_val = int(target_rank[0]) + 1 if len(target_rank) > 0 else 'N/A'
    lines.append(f'### 整体对比（本系列排名第 {target_rank_val} 位）\n')
    lines.append(_df_to_md_table(series_overall))
    for dim_col, dim_label in [('L1', 'L1 维度'), ('difficulty_level', '难度等级')]:
        if dim_col not in replies_with_q.columns:
            continue
        dim_pivot = (
            replies_with_q.groupby(['series', dim_col])['eval_score']
            .mean().reset_index()
            .pivot(index='series', columns=dim_col, values='eval_score')
            .round(2)
        )
        dim_pivot.columns = [str(c) for c in dim_pivot.columns]
        dim_pivot = dim_pivot.reset_index().rename(columns={'series': '系列'})
        lines.append(f'### {dim_label} 系列对比\n')
        lines.append(_df_to_md_table(dim_pivot))
    lines.append('\n')

    # 5. 维度深度分析
    lines.append('## 5. 维度深度分析\n')
    for dim_col, dim_label in [('L1', 'L1'), ('L2', 'L2'), ('L3', 'L3'), ('difficulty_level', '难度等级')]:
        if dim_col not in target_with_q.columns:
            continue
        target_dim = (
            target_with_q.groupby(dim_col)['eval_score']
            .agg(['mean', 'count'])
            .reset_index()
            .rename(columns={dim_col: dim_label, 'mean': f'{series_name}系列均分', 'count': '评测数量'})
        )
        target_dim[f'{series_name}系列均分'] = target_dim[f'{series_name}系列均分'].round(2)
        all_dim = (
            replies_with_q.groupby(dim_col)['eval_score']
            .mean().reset_index()
            .rename(columns={dim_col: dim_label, 'eval_score': '全体均分'})
        )
        all_dim['全体均分'] = all_dim['全体均分'].round(2)
        merged = target_dim.merge(all_dim, on=dim_label, how='left')
        merged['相对全体差值'] = (merged[f'{series_name}系列均分'] - merged['全体均分']).round(2)
        merged = merged.sort_values(f'{series_name}系列均分', ascending=False).reset_index(drop=True)
        lines.append(f'### {dim_label} 维度\n')
        lines.append(_df_to_md_table(merged))
    lines.append('\n')

    # 6. D 维度得失分（与主体报告一致，约束类型↔D 维度对应）
    lines.append('## 6. D 维度得失分\n')
    if dimension_stats.get('has_data'):
        pivot = dimension_stats.get('dimension_pivot_df', pd.DataFrame())
        if not pivot.empty:
            model_col = '模型' if '模型' in pivot.columns else 'model'
            series_pivot = pivot[pivot[model_col].astype(str).str.strip().isin([str(m).strip() for m in target_models])]
            if not series_pivot.empty:
                lines.append(L2_D_MAPPING_DESC + '\n\n')
                lines.append('本系列各模型 D1–D5 通过率（与主体报告维度得失分统计一致）：\n')
                lines.append(_df_to_md_table(series_pivot))
            else:
                lines.append('_（本系列无维度统计数据）_\n')
        else:
            lines.append('_（无维度透视数据）_\n')
    else:
        lines.append('_（需 eval_*_raw 中的 rubrics_check 解析，未获取到维度数据）_\n')
    lines.append('\n')

    # 7. 优劣势分析
    lines.append('## 7. 优劣势分析（L2 维度）\n')
    if 'L2' in target_with_q.columns:
        target_l2 = (
            target_with_q.groupby('L2')['eval_score']
            .mean().reset_index()
            .rename(columns={'eval_score': f'{series_name}均分'})
        )
        all_l2 = (
            replies_with_q.groupby('L2')['eval_score']
            .mean().reset_index()
            .rename(columns={'eval_score': '全体均分'})
        )
        merged = target_l2.merge(all_l2, on='L2', how='inner')
        merged['相对优势'] = (merged[f'{series_name}均分'] - merged['全体均分']).round(2)
        merged['评测数量'] = target_with_q.groupby('L2')['eval_score'].count().reindex(merged['L2']).values
        strengths = merged.nlargest(10, '相对优势').reset_index(drop=True)
        strengths.insert(0, '优势排名', strengths.index + 1)
        weaknesses = merged.nsmallest(10, '相对优势').reset_index(drop=True)
        weaknesses.insert(0, '劣势排名', weaknesses.index + 1)
        lines.append('### 相对优势 TOP10\n')
        lines.append(_df_to_md_table(strengths))
        lines.append('### 相对劣势 TOP10\n')
        lines.append(_df_to_md_table(weaknesses))
    else:
        lines.append('_（无 L2 维度数据）_\n')
    lines.append('\n')

    # 8. 厂商视角小结
    lines.append('## 8. 厂商视角小结\n')
    target_avg = round(float(target_df['eval_score'].dropna().mean()), 2) if not target_df['eval_score'].dropna().empty else 0
    all_avg = round(float(replies_with_q['eval_score'].dropna().mean()), 2) if not replies_with_q['eval_score'].dropna().empty else 0
    gap = target_avg - all_avg
    gap_str = f'高于全体均分 {gap:+.2f} 分' if gap > 0 else (f'低于全体均分 {-gap:.2f} 分' if gap < 0 else '与全体均分持平')
    lines.append(f'- **本系列均分**：{target_avg:.2f}（{gap_str}）\n')
    _overall = _compute_model_overall(target_df, total_questions)
    if not _overall.empty and len(_overall) >= 2:
        _overall = _overall.sort_values('平均分', ascending=False).reset_index(drop=True)
        best_m = _overall.iloc[0]['model']
        lines.append(f'- **系列内最佳**：{best_m}，建议作为基准对比后续版本。\n')
    lines.append('- **建议关注**：优劣势分析中的相对劣势 L2 类型，可针对性加强训练数据；D 维度得失分中 D2/D4 比值可验证「重格式、轻逻辑」现象；Badcase 分析中识别的薄弱题目与维度需重点改进。\n')
    lines.append('\n')

    # 9. 重点模型做错题案例分析（与主体报告同逻辑、同格式：模型分档+AI综合评估+失分点分析）
    if case_analyses and focus_model:
        lines.append('## 9. 重点模型做错题案例分析\n')
        lines.append(f'以下针对本系列重点模型 **{focus_model}** 做错或低分题目，按与主体报告相同的分析逻辑与格式整理：模型分档（按分差划分第一/第二/第三梯队）、AI 综合评估、失分点分析。\n\n')
        for case in case_analyses:
            lines.extend(_render_series_case_like_main(case))
    else:
        lines.append('## 9. 重点模型做错题案例分析\n')
        lines.append('_（未配置 LLM 或未指定重点模型时，本节不生成；可在生成系列报告时传入 provider / model / focus_model 以启用）_\n\n')

    # 10. 典型案例（本系列表现优于全体的题目，若有则 2–5 个）
    good_cases_raw = _identify_series_good_cases(target_with_q, replies_with_q, target_models, min_gap=10, max_cases=5)
    good_case_analyses = []
    for g in good_cases_raw:
        case = _build_series_case_analysis(
            g['qid'], target_with_q, replies_with_q, target_models,
            dimension_stats, eval_column, is_badcase=False,
        )
        if case:
            case['gap'] = g['gap']
            good_case_analyses.append(case)

    lines.append('## 10. 典型案例\n')
    if good_case_analyses:
        lines.append('本系列表现显著优于全体均分的题目（与全体差距 ≥ 10 分），供参考。\n')
        for idx, case in enumerate(good_case_analyses, 1):
            qid = case.get('qid', '')
            query = str(case.get('query', ''))[:300] + ('...' if len(str(case.get('query', ''))) > 300 else '')
            l1 = case.get('L1', '')
            l2 = case.get('L2', '')
            l3 = case.get('L3', '')
            difficulty = case.get('difficulty_level', '')
            series_avg = case.get('series_avg', 0)
            all_avg = case.get('all_avg', 0)
            gap = case.get('gap', series_avg - all_avg)
            lines.append(f'### 案例 {idx}: Q{qid}\n')
            lines.append(f'- **L1**: {l1} | **L2**: {l2} | **L3**: {l3} | **难度**: {difficulty}\n')
            lines.append(f'- **本系列均分**: {series_avg} | **全体均分**: {all_avg} | **相对优势**: +{gap:.2f} 分\n')
            if query:
                lines.append(f'- **题目摘要**: {query}\n')
            if case.get('model_scores'):
                sorted_s = sorted(case['model_scores'].items(), key=lambda x: x[1], reverse=True)
                scores_str = ' | '.join([f'{m}: {s:.1f}' for m, s in sorted_s])
                lines.append(f'- **本系列各模型得分**: {scores_str}\n')
            lines.append('\n')
    else:
        lines.append('_（本系列暂无明显优于全体均分的典型案例，本节不展示）_\n')
    lines.append('\n')

    # 11. Badcase 案例分析（重点：本系列在哪些题目、哪些维度上容易失分）
    bad_cases_raw = _identify_series_badcases(target_with_q, replies_with_q, target_models, min_gap=15, max_cases=15)
    bad_case_analyses = []
    for b in bad_cases_raw:
        case = _build_series_case_analysis(
            b['qid'], target_with_q, replies_with_q, target_models,
            dimension_stats, eval_column, is_badcase=True,
        )
        if case:
            case['gap'] = b['gap']
            bad_case_analyses.append(case)

    lines.append('## 11. Badcase 案例分析\n')
    if bad_case_analyses:
        lines.append('本系列明显落后于全体均分的题目（与全体差距 ≤ -15 分），指明在哪些题目、哪些维度上易失分及具体表现。\n')
        for idx, case in enumerate(bad_case_analyses, 1):
            qid = case.get('qid', '')
            query = str(case.get('query', ''))[:350] + ('...' if len(str(case.get('query', ''))) > 350 else '')
            l1 = case.get('L1', '')
            l2 = case.get('L2', '')
            l3 = case.get('L3', '')
            difficulty = case.get('difficulty_level', '')
            series_avg = case.get('series_avg', 0)
            all_avg = case.get('all_avg', 0)
            gap = case.get('gap', 0)
            best_model = case.get('best_model', '')
            best_score = case.get('best_score', 0)
            lines.append(f'### Badcase {idx}: Q{qid}\n')
            lines.append(f'- **L1**: {l1} | **L2**: {l2} | **L3**: {l3} | **难度**: {difficulty}\n')
            lines.append(f'- **本系列均分**: {series_avg} | **全体均分**: {all_avg} | **与全体差距**: {gap:.2f} 分 | **本题最佳**: {best_score:.1f}（{best_model}）\n')
            if query:
                lines.append(f'- **题目内容**\n\n> {query}\n\n')
            if case.get('model_scores'):
                sorted_s = sorted(case['model_scores'].items(), key=lambda x: x[1], reverse=True)
                lines.append('- **本系列各模型得分（与本题最佳对比）**\n')
                for m, s in sorted_s:
                    g = case.get('model_gaps', {}).get(m)
                    if g is not None and g == 0 and best_model:
                        lines.append(f'  - {m}: {s:.1f} _（本题最佳）_\n')
                    elif g is not None and g > 0:
                        lines.append(f'  - {m}: {s:.1f} _（与最佳差 {g:.1f} 分）_\n')
                    else:
                        lines.append(f'  - {m}: {s:.1f}\n')
            if case.get('dimension_info'):
                lines.append('- **本系列维度表现（D2/D3/D4/D5 通过情况）**\n\n')
                lines.append(case['dimension_info'] + '\n\n')
            if case.get('loss_analysis'):
                lines.append('- **失分点分析**\n\n')
                lines.append(case['loss_analysis'] + '\n\n')
            lines.append('---\n\n')
    else:
        lines.append('_（本系列暂无明显落后于全体的 Badcase，或题目数量不足）_\n')
    lines.append('\n')

    os.makedirs(os.path.dirname(os.path.abspath(output_md)), exist_ok=True)
    with open(output_md, 'w', encoding='utf-8') as f:
        f.write(''.join(lines))
    return output_md


def _detect_available_vendors(replies_df: pd.DataFrame) -> List[tuple]:
    """从回复表中检测有数据的厂商列表，返回 [(展示名, patterns), ...]。"""
    models = [str(m).strip() for m in replies_df['model'].unique().tolist() if m]
    available = []
    for disp_name, patterns in VENDOR_OPTIONS:
        matched = [m for m in models if _match_series(m, patterns)]
        if matched:
            available.append((disp_name, patterns, len(matched)))
    return available


def select_series_interactive(replies_df: pd.DataFrame) -> Optional[Dict[str, List[str]]]:
    """
    输出有数据的厂商列表，交互式选择要生成专项报告的厂商。
    返回 model_series_config  dict，空或取消则返回 None。
    """
    available = _detect_available_vendors(replies_df)
    if not available:
        print("  ⚠️ 未检测到可识别的厂商系列，跳过专项报告。")
        return None

    print(f"\n{'=' * 60}")
    print(f"📋 专项报告 - 厂商列表（本次数据中存在）")
    print(f"{'=' * 60}")
    for i, (disp, _, cnt) in enumerate(available, 1):
        print(f"  {i:2d}. {disp}  （{cnt} 个模型）")
    print(f"{'=' * 60}")
    print("  输入要生成专项报告的编号，逗号分隔（如 1,3,5），或 all 全选，直接回车=跳过：", end="")
    try:
        choice = input().strip()
    except EOFError:
        choice = ""
    if not choice:
        return None
    selected = []
    if choice.strip().lower() == "all":
        selected = [(disp, pat) for disp, pat, _ in available]
    else:
        for part in choice.split(","):
            part = part.strip()
            if not part.isdigit():
                continue
            idx = int(part) - 1
            if 0 <= idx < len(available):
                disp, pat, _ = available[idx]
                selected.append((disp, pat))
    if not selected:
        return None
    config = {disp: pat for disp, pat in selected}
    print(f"\n  ✅ 已选择 {len(config)} 个厂商系列: {', '.join(config.keys())}")
    return config


def generate_all_series_reports(
    replies_df: pd.DataFrame,
    questions_df: pd.DataFrame,
    model_series_config: Dict[str, List[str]],
    output_dir: str,
    eval_column: str = None,
    provider: str = None,
    model: str = None,
    sysprompt_manager=None,
    focus_model: str = None,
) -> List[str]:
    """
    批量为所有配置的模型系列生成定向报告。

    Args:
        replies_df: 包含 eval_score、eval_*_raw、reply 的回复表
        questions_df: 题目表
        model_series_config: 系列配置，如 {"Qwen": ["qwen"], "GPT": ["gpt-4", "gpt-3"]}
        output_dir: 报告输出目录
        eval_column: 评估列名（用于解析 rubrics_check 得 D 维度），None 时跳过维度得失分
        provider: 可选，LLM provider，与 model 同时传入时对「重点模型做错题」做与主体报告同框架的案例分析
        model: 可选，LLM 模型名
        sysprompt_manager: 可选，报告分析用 sysprompt
        focus_model: 可选，重点关注的模型（如 qwen3.5-plus）；不传则每系列取均分最低的模型

    Returns:
        生成的报告路径列表
    """
    if not model_series_config:
        return []

    print(f"\n▶ 生成系列定向报告 ({len(model_series_config)} 个系列)...")
    generated = []

    for series_name, patterns in model_series_config.items():
        output_path = os.path.join(output_dir, f'series_report_{series_name}.xlsx')
        result = generate_series_report(
            replies_df=replies_df,
            questions_df=questions_df,
            series_name=series_name,
            series_patterns=patterns,
            all_series_config=model_series_config,
            output_excel=output_path,
            eval_column=eval_column,
            provider=provider,
            model=model,
            sysprompt_manager=sysprompt_manager,
            focus_model=focus_model,
        )
        if result:
            generated.append(result)

    print(f"  ✓ 系列报告生成完毕: {len(generated)} 份")
    return generated

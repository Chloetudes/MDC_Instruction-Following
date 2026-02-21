# -*- coding: utf-8 -*-
"""
模型系列定向报告生成器

支持按公司/系列聚合模型，输出：
1. 系列内版本纵向对比（不同版本能力变化）
2. 系列与其他系列横向对比（相对优劣势）
3. 各维度（L1/L2/L3/难度）的系列表现
"""
import os
import warnings
import numpy as np
import pandas as pd
from typing import Dict, List, Optional

warnings.filterwarnings('ignore')


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


def _compute_model_overall(replies_df: pd.DataFrame) -> pd.DataFrame:
    results = []
    for model in replies_df['model'].unique():
        scores = replies_df[replies_df['model'] == model]['eval_score'].dropna()
        if len(scores) == 0:
            continue
        results.append({
            'model': model,
            '评测数量': len(scores),
            '平均分': round(float(scores.mean()), 2),
            '标准差': round(float(scores.std()), 2),
            '中位数': round(float(scores.median()), 2),
            '最高分': round(float(scores.max()), 2),
            '最低分': round(float(scores.min()), 2),
        })
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
) -> Optional[str]:
    """
    为单个模型系列生成定向分析报告。

    Args:
        replies_df: 包含 eval_score 的回复表
        questions_df: 题目表（含 L1/L2/L3/difficulty_level）
        series_name: 当前系列名称，如 "Qwen"
        series_patterns: 当前系列的匹配前缀列表，如 ["qwen", "qwen2"]
        all_series_config: 全部系列配置，用于横向对比
        output_excel: 输出路径
    """
    all_models = replies_df['model'].unique().tolist()
    model_to_series = _build_series_mapping(all_models, all_series_config)

    target_models = [m for m in all_models if _match_series(m, series_patterns)]
    if not target_models:
        print(f"  ⚠️ 系列 [{series_name}] 未匹配到任何模型，跳过")
        return None

    other_models = [m for m in all_models if m not in target_models]

    target_df = replies_df[replies_df['model'].isin(target_models)].copy()
    other_df = replies_df[replies_df['model'].isin(other_models)].copy()

    replies_with_q = replies_df.merge(
        questions_df[[c for c in ['qid', 'L1', 'L2', 'L3', 'difficulty_level'] if c in questions_df.columns]],
        on='qid', how='left'
    )
    target_with_q = replies_with_q[replies_with_q['model'].isin(target_models)].copy()

    print(f"\n  📊 生成 [{series_name}] 系列报告 ({len(target_models)} 个模型)...")

    os.makedirs(os.path.dirname(os.path.abspath(output_excel)), exist_ok=True)

    with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:

        _write_series_overview(writer, series_name, target_models, target_df, other_df, model_to_series)

        _write_version_comparison(writer, series_name, target_models, target_df, target_with_q)

        _write_cross_series_comparison(writer, series_name, replies_with_q, model_to_series, all_series_config)

        _write_dimension_analysis(writer, series_name, target_with_q, replies_with_q, model_to_series)

        _write_strength_weakness(writer, series_name, target_with_q, replies_with_q, model_to_series)

    print(f"  ✓ [{series_name}] 报告已生成: {output_excel}")
    return output_excel


def _write_series_overview(
    writer: pd.ExcelWriter,
    series_name: str,
    target_models: List[str],
    target_df: pd.DataFrame,
    other_df: pd.DataFrame,
    model_to_series: Dict[str, str],
):
    overall_target = _compute_model_overall(target_df)
    if overall_target.empty:
        return

    overall_target = overall_target.sort_values('平均分', ascending=False).reset_index(drop=True)
    overall_target.insert(0, '系列内排名', overall_target.index + 1)

    if not other_df.empty:
        overall_other = _compute_model_overall(other_df)
        overall_other['所属系列'] = overall_other['model'].map(model_to_series)
        series_avg = (
            overall_other.groupby('所属系列')['平均分']
            .mean()
            .reset_index()
            .rename(columns={'平均分': '系列平均分'})
            .sort_values('系列平均分', ascending=False)
            .reset_index(drop=True)
        )
        series_avg.insert(0, '系列排名', series_avg.index + 1)

        target_series_avg = round(float(target_df['eval_score'].dropna().mean()), 2)
        target_row = pd.DataFrame([{
            '系列排名': '—',
            '所属系列': f'{series_name}（本系列）',
            '系列平均分': target_series_avg,
        }])
        series_avg = pd.concat([target_row, series_avg], ignore_index=True)
    else:
        series_avg = pd.DataFrame()

    start_row = 0
    pd.DataFrame([[f'【{series_name} 系列模型整体表现】']]).to_excel(
        writer, sheet_name='1_系列总览', startrow=start_row, index=False, header=False
    )
    start_row += 1
    overall_target.to_excel(writer, sheet_name='1_系列总览', startrow=start_row, index=False)
    start_row += len(overall_target) + 3

    if not series_avg.empty:
        pd.DataFrame([[f'【各系列横向对比（系列平均分）】']]).to_excel(
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


def generate_all_series_reports(
    replies_df: pd.DataFrame,
    questions_df: pd.DataFrame,
    model_series_config: Dict[str, List[str]],
    output_dir: str,
) -> List[str]:
    """
    批量为所有配置的模型系列生成定向报告。

    Args:
        replies_df: 包含 eval_score 的回复表
        questions_df: 题目表
        model_series_config: 系列配置，如 {"Qwen": ["qwen"], "GPT": ["gpt-4", "gpt-3"]}
        output_dir: 报告输出目录

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
        )
        if result:
            generated.append(result)

    print(f"  ✓ 系列报告生成完毕: {len(generated)} 份")
    return generated

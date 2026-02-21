# -*- coding: utf-8 -*-
import os
import warnings
import numpy as np
import pandas as pd
from scipy.stats import pearsonr

from .data_loader import load_and_preprocess
from .ranking import ModelRankingAnalyzer, ExpertCorrectedRankingAnalyzer
from .consistency import (
    HumanModelConsistencyAnalyzer,
    HumanExpertConsistencyAnalyzer,
    ModelReliabilityAnalyzer,
)
from .valuable_questions import ValuableQuestionAnalyzer
from .item_analysis import (
    ItemAnalyzer,
    ConstraintTypeAnalyzer,
    TypicalCaseSelector,
    generate_metric_definitions,
)

warnings.filterwarnings('ignore')


def generate_analysis_report(
    questions_excel: str,
    replies_excel: str,
    output_excel: str,
    human_excel: str = None,
    eval_batch_id: str = None,
) -> str:
    print("\n" + "=" * 60)
    print("模型评测综合分析系统 - 生成报告")
    print("=" * 60)

    data = load_and_preprocess(
        questions_excel=questions_excel,
        replies_excel=replies_excel,
        human_excel=human_excel,
        eval_batch_id=eval_batch_id,
    )

    ranking_analyzer = ModelRankingAnalyzer(data)
    expert_corrected_analyzer = ExpertCorrectedRankingAnalyzer(data)
    human_model_analyzer = HumanModelConsistencyAnalyzer(data)
    human_expert_analyzer = HumanExpertConsistencyAnalyzer(data)
    model_reliability_analyzer = ModelReliabilityAnalyzer(data)
    valuable_analyzer = ValuableQuestionAnalyzer(data)
    item_analyzer = ItemAnalyzer(data)
    constraint_analyzer = ConstraintTypeAnalyzer(data)

    print("\n▶ 分析1: 多维度排名")
    print("-" * 40)
    rankings = ranking_analyzer.generate_all_rankings()
    corrected_ranking_df = expert_corrected_analyzer.analyze_corrected_ranking()

    print("\n▶ 分析2: 人机一致性")
    print("-" * 40)
    per_question_ranking = human_model_analyzer.analyze_per_question_ranking_consistency()
    rater_model_ranking = human_model_analyzer.analyze_rater_model_ranking_consistency()

    print("\n▶ 分析3: 组内一致性")
    print("-" * 40)
    rater_vs_others = human_expert_analyzer.analyze_rater_vs_others()
    rater_vs_expert = human_expert_analyzer.analyze_rater_vs_expert()
    human_avg_vs_expert = human_expert_analyzer.analyze_human_avg_vs_expert()

    print("\n▶ 分析4: 模型打分可靠性")
    print("-" * 40)
    model_expert_overall, model_expert_detail = model_reliability_analyzer.analyze_model_vs_expert()
    model_ranking_summary, model_rank_comparison = model_reliability_analyzer.analyze_model_ranking_consistency()

    print("\n▶ 分析5: 价值题目TOP20")
    print("-" * 40)
    top20_questions = valuable_analyzer.find_top20_valuable_questions()

    print("\n▶ 分析6: 题目完整分析（信度/效度/区分度）")
    print("-" * 40)
    item_analysis_df = item_analyzer.analyze_all_items()

    print("\n▶ 分析7: 约束类型分析")
    print("-" * 40)
    constraint_type_df = constraint_analyzer.analyze_constraint_types()

    print("\n▶ 分析8: 典型案例筛选")
    print("-" * 40)
    case_selector = TypicalCaseSelector(data, item_analysis_df)
    typical_cases_df = case_selector.select_typical_cases(top_n=20)

    print("\n▶ 分析9: 人工校验分析")
    print("-" * 40)
    human_verification_results = _analyze_human_verification(data)

    print("\n▶ 生成Excel分析报告")
    print("-" * 40)

    os.makedirs(os.path.dirname(os.path.abspath(output_excel)), exist_ok=True)

    with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
        _write_ranking_sheets(writer, rankings, corrected_ranking_df)
        _write_human_model_sheets(writer, per_question_ranking, rater_model_ranking)
        _write_group_consistency_sheets(writer, rater_vs_others, rater_vs_expert, human_avg_vs_expert)
        _write_reliability_sheets(writer, model_expert_overall, model_expert_detail,
                                  model_ranking_summary, model_rank_comparison)

        if not top20_questions.empty:
            top20_questions.to_excel(writer, sheet_name='5_价值题目TOP20', index=False)
            print("  ✓ 已生成: 5_价值题目TOP20")

        if not item_analysis_df.empty:
            item_analysis_df.to_excel(writer, sheet_name='6_题目完整分析', index=False)
            print("  ✓ 已生成: 6_题目完整分析")

        if not constraint_type_df.empty:
            constraint_type_df.to_excel(writer, sheet_name='7_约束类型分析', index=False)
            print("  ✓ 已生成: 7_约束类型分析")

        if not typical_cases_df.empty:
            typical_cases_df.to_excel(writer, sheet_name='8_典型案例', index=False)
            print("  ✓ 已生成: 8_典型案例")

        _write_human_verification_sheets(writer, human_verification_results)

        metric_defs = generate_metric_definitions()
        metric_defs.to_excel(writer, sheet_name='指标定义说明', index=False)
        print("  ✓ 已生成: 指标定义说明")

        sheet_count = len(writer.sheets)

    _print_summary(rankings, corrected_ranking_df, rater_vs_others, model_ranking_summary,
                   top20_questions, item_analysis_df)

    print(f"\n✓ 分析报告生成成功!")
    print(f"✓ 输出路径: {output_excel}")
    print(f"✓ 共生成 {sheet_count} 个工作表")
    print("=" * 60)

    return output_excel


def _analyze_human_verification(data: dict) -> dict:
    """
    人工校验分析：Solo/Common 题一致性、标注员个人表现、人机对比
    依赖 rater_scores 和 replies 中的 eval_score
    """
    rater_scores = data.get('rater_scores', pd.DataFrame())
    replies = data.get('replies', pd.DataFrame())

    results = {}

    if rater_scores.empty:
        print("    ⚠️ 无人工标注数据，跳过人工校验分析")
        return results

    human_avg = (
        rater_scores.groupby(['qid', 'model'])['score']
        .agg(['mean', 'std', 'count', 'min', 'max'])
        .reset_index()
    )
    human_avg.columns = ['qid', 'model', 'human_avg', 'human_std', 'annotator_count', 'human_min', 'human_max']
    human_avg['human_range'] = human_avg['human_max'] - human_avg['human_min']
    human_avg['human_std'] = human_avg['human_std'].fillna(0)

    model_scores = replies[['qid', 'model', 'eval_score']].dropna()
    comparison_df = human_avg.merge(model_scores, on=['qid', 'model'], how='left')
    comparison_df['score_diff'] = comparison_df['human_avg'] - comparison_df['eval_score']
    comparison_df['abs_score_diff'] = comparison_df['score_diff'].abs()
    comparison_df['relative_error'] = (
        comparison_df['abs_score_diff'] / comparison_df['human_avg'].replace(0, np.nan) * 100
    ).fillna(0)

    results['human_model_comparison'] = comparison_df

    consistency_summary = _build_consistency_summary(comparison_df)
    results['consistency_summary'] = consistency_summary

    model_ranking_human = (
        comparison_df.groupby('model')
        .agg(
            人工评估均分=('human_avg', 'mean'),
            模型自动均分=('eval_score', 'mean'),
            平均绝对偏差=('abs_score_diff', 'mean'),
            样本量=('qid', 'count'),
        )
        .sort_values('人工评估均分', ascending=False)
        .reset_index()
    )
    model_ranking_human.insert(0, '排名', model_ranking_human.index + 1)
    results['model_ranking_human'] = model_ranking_human

    annotator_performance = (
        rater_scores.groupby('rater')['score']
        .agg(['count', 'mean', 'std', 'min', 'max'])
        .reset_index()
    )
    annotator_performance.columns = ['标注员', '标注数量', '平均得分', '得分标准差', '最低分', '最高分']
    annotator_performance = annotator_performance.sort_values('标注数量', ascending=False).reset_index(drop=True)
    results['annotator_performance'] = annotator_performance

    print(f"    完成: {len(comparison_df)} 条人机对比记录，{len(annotator_performance)} 位标注员")
    return results


def _build_consistency_summary(comparison_df: pd.DataFrame) -> pd.DataFrame:
    rows = []

    valid = comparison_df.dropna(subset=['human_avg', 'eval_score'])
    if len(valid) > 1:
        try:
            corr, _ = pearsonr(valid['human_avg'], valid['eval_score'])
        except Exception:
            corr = np.nan
    else:
        corr = np.nan

    rows.append({
        '分析维度': '整体人机一致性',
        '样本量': len(valid),
        '平均分差(人-机)': round(float(valid['score_diff'].mean()), 2) if len(valid) > 0 else 'N/A',
        '平均绝对偏差': round(float(valid['abs_score_diff'].mean()), 2) if len(valid) > 0 else 'N/A',
        '平均相对误差(%)': round(float(valid['relative_error'].mean()), 2) if len(valid) > 0 else 'N/A',
        '人机相关系数(Pearson)': round(float(corr), 3) if not np.isnan(corr) else 'N/A',
        '人工互评平均极差': round(float(valid['human_range'].mean()), 2) if 'human_range' in valid.columns else 'N/A',
        '人工互评平均标准差': round(float(valid['human_std'].mean()), 2) if 'human_std' in valid.columns else 'N/A',
    })

    return pd.DataFrame(rows)


def _write_ranking_sheets(writer: pd.ExcelWriter, rankings: dict, corrected_ranking_df: pd.DataFrame):
    sheet_name = '1_多维度排名'
    start_row = 0

    ordered_keys = ['overall', 'l1', 'l2', 'l3', 'source', 'difficulty', 'significance']
    labels = {
        'overall': '【整体表现排名】',
        'l1': '【L1维度排名】',
        'l2': '【L2维度排名（TOP30）】',
        'l3': '【L3维度排名（TOP30）】',
        'source': '【Source维度排名】',
        'difficulty': '【难度等级排名】',
        'significance': '【显著性检验】',
    }

    for key in ordered_keys:
        df = rankings.get(key)
        if df is None or (isinstance(df, pd.DataFrame) and df.empty):
            continue
        pd.DataFrame([[labels.get(key, key)]]).to_excel(
            writer, sheet_name=sheet_name, startrow=start_row, index=False, header=False
        )
        start_row += 1
        df.to_excel(writer, sheet_name=sheet_name, startrow=start_row, index=False)
        start_row += len(df) + 3

    print("  ✓ 已生成: 1_多维度排名")

    if not corrected_ranking_df.empty:
        corrected_ranking_df.to_excel(writer, sheet_name='1_专家纠偏模型排名', index=False)
        print("  ✓ 已生成: 1_专家纠偏模型排名")


def _write_human_model_sheets(writer: pd.ExcelWriter, per_question_ranking: pd.DataFrame,
                               rater_model_ranking: pd.DataFrame):
    if not per_question_ranking.empty:
        per_question_ranking.to_excel(writer, sheet_name='2_每道题排名一致性', index=False)
        print("  ✓ 已生成: 2_每道题排名一致性")
    if not rater_model_ranking.empty:
        rater_model_ranking.to_excel(writer, sheet_name='2_人机一致性排名', index=False)
        print("  ✓ 已生成: 2_人机一致性排名")


def _write_group_consistency_sheets(writer: pd.ExcelWriter, rater_vs_others: pd.DataFrame,
                                     rater_vs_expert: pd.DataFrame, human_avg_vs_expert: pd.DataFrame):
    if not rater_vs_others.empty:
        rater_vs_others.to_excel(writer, sheet_name='3_组内一致性成绩单', index=False)
        print("  ✓ 已生成: 3_组内一致性成绩单")
    if not rater_vs_expert.empty:
        rater_vs_expert.to_excel(writer, sheet_name='3_与专家一致性', index=False)
        print("  ✓ 已生成: 3_与专家一致性")
    if not human_avg_vs_expert.empty:
        human_avg_vs_expert.to_excel(writer, sheet_name='3_人工均分vs专家', index=False)
        print("  ✓ 已生成: 3_人工均分vs专家")


def _write_reliability_sheets(writer: pd.ExcelWriter, model_expert_overall: pd.DataFrame,
                               model_expert_detail: pd.DataFrame, model_ranking_summary: pd.DataFrame,
                               model_rank_comparison: pd.DataFrame):
    if not model_expert_overall.empty:
        model_expert_overall.to_excel(writer, sheet_name='4_模型专家一致性', index=False)
        print("  ✓ 已生成: 4_模型专家一致性")
    if not model_expert_detail.empty:
        model_expert_detail.to_excel(writer, sheet_name='4_模型与专家一致性排名', index=False)
        print("  ✓ 已生成: 4_模型与专家一致性排名")
    if not model_rank_comparison.empty:
        model_rank_comparison.to_excel(writer, sheet_name='4_模型专家排名对比', index=False)
        print("  ✓ 已生成: 4_模型专家排名对比")
    if not model_ranking_summary.empty:
        model_ranking_summary.to_excel(writer, sheet_name='4_模型排名一致性', index=False)
        print("  ✓ 已生成: 4_模型排名一致性")


def _write_human_verification_sheets(writer: pd.ExcelWriter, human_verification_results: dict):
    if not human_verification_results:
        return

    start_row = 0
    sheet_name = '9_人工校验分析'

    sections = [
        ('consistency_summary', '【人机一致性摘要】'),
        ('model_ranking_human', '【人工视角模型排名】'),
        ('annotator_performance', '【标注员个人表现】'),
        ('human_model_comparison', '【人机评分详细对照】'),
    ]

    for key, label in sections:
        df = human_verification_results.get(key)
        if df is None or df.empty:
            continue
        pd.DataFrame([[label]]).to_excel(
            writer, sheet_name=sheet_name, startrow=start_row, index=False, header=False
        )
        start_row += 1
        df.to_excel(writer, sheet_name=sheet_name, startrow=start_row, index=False)
        start_row += len(df) + 3

    print("  ✓ 已生成: 9_人工校验分析")


def _print_summary(rankings: dict, corrected_ranking_df: pd.DataFrame,
                   rater_vs_others: pd.DataFrame, model_ranking_summary: pd.DataFrame,
                   top20_questions: pd.DataFrame, item_analysis_df: pd.DataFrame):
    print("\n【核心分析结论】")
    print("-" * 40)

    overall = rankings.get('overall')
    if overall is not None and not overall.empty:
        top_model = overall.iloc[0]['模型']
        top_score = overall.iloc[0]['平均分']
        print(f"1. 最佳模型 (原始): {top_model} (均分: {top_score})")

    if not corrected_ranking_df.empty:
        top_corrected = corrected_ranking_df.iloc[0]['模型']
        top_corrected_score = corrected_ranking_df.iloc[0]['纠偏后均分']
        change = corrected_ranking_df.iloc[0].get('排名变化', 0)
        change_str = f"{change:+d}" if isinstance(change, (int, float)) and not np.isnan(float(change)) else str(change)
        print(f"2. 最佳模型 (专家纠偏): {top_corrected} (均分: {top_corrected_score}, 排名变化: {change_str})")

    if not rater_vs_others.empty:
        top_rater = rater_vs_others.iloc[0]['标注员']
        top_score = rater_vs_others.iloc[0]['综合质量得分']
        print(f"3. 最佳标注员: {top_rater} (综合质量: {top_score})")

    if not model_ranking_summary.empty:
        rank_corr = model_ranking_summary.iloc[0].get('排名一致性_斯皮尔曼', 'N/A')
        print(f"4. 模型排名一致性: 整体ρ={rank_corr}")

    if not top20_questions.empty:
        print(f"5. 高价值题目: 已筛选20道, TOP1 Q{top20_questions.iloc[0]['qid']}")

    if not item_analysis_df.empty:
        excellent_items = (item_analysis_df['题目质量等级'] == '优秀').sum()
        avg_discrimination = pd.to_numeric(item_analysis_df['区分度指数_D'], errors='coerce').mean()
        print(f"6. 题目质量: 优秀题目 {excellent_items} 道, 平均区分度 {avg_discrimination:.3f}")

    print("-" * 40)

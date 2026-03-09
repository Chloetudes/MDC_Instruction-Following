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
    ExpertHumanMachineConsistencyAnalyzer,
)
from .valuable_questions import ValuableQuestionAnalyzer
from .item_analysis import (
    ItemAnalyzer,
    ConstraintTypeAnalyzer,
    TypicalCaseSelector,
    generate_metric_definitions,
)
from .production_quality import (
    analyze_reference_quality,
    compute_expert_discrimination_stats,
    compute_expert_data_quality_ranking,
    compute_expert_diagnosis_and_suggestions,
    compute_per_question_diagnosis_and_suggestions,
    compute_qualified_flag,
)
from .inter_batch_consistency import (
    compute_inter_batch_consistency,
    compute_expert_model_consistency_per_batch,
    compute_ranking_per_batch,
    compute_expert_model_consistency_per_batch_per_expert,
)

warnings.filterwarnings('ignore')


def _build_expert_quality_consolidated_sheet(
    expert_human_machine_summary: pd.DataFrame,
    expert_data_quality_ranking: pd.DataFrame,
    ref_per_expert: pd.DataFrame,
    expert_discrimination: pd.DataFrame,
    expert_model_per_batch_df: pd.DataFrame,
    per_batch_reliability_df: pd.DataFrame,
    qualified_count_df: pd.DataFrame = None,
) -> tuple:
    """
    专家数据审核焦点：仅体现专家表现与数据质量的指标，合并为一张表内的三个区块。
    qualified_count_df: 专家合格题目数（专家, 合格题目数），用于结算依据。
    返回 (expert_block_df, batch_consistency_df, batch_reliability_df)，用于写入同一 sheet。
    """
    # 区块1：专家数据质量（排名、人机一致性、ref 质量、区分度、合格题目数）
    expert_block = pd.DataFrame()
    if not expert_data_quality_ranking.empty:
        expert_block = expert_data_quality_ranking.copy()
        # 补全 评估题目数、专家评估数、人机一致性_ICC/MAE（来自 expert_human_machine_summary）；不展示共同任务数，规则为至少1题且有 ref+2 条回复评估即应有指标
        if not expert_human_machine_summary.empty and '专家' in expert_human_machine_summary.columns:
            hm = expert_human_machine_summary.drop_duplicates('专家').copy()
            renames = {}
            if '综合人机一致性_ICC' in hm.columns:
                renames['综合人机一致性_ICC'] = '人机一致性_ICC'
            if '综合人机一致性_MAE' in hm.columns:
                renames['综合人机一致性_MAE'] = '人机一致性_MAE'
            if renames:
                hm = hm.rename(columns=renames)
            extra_cols = ['专家', '评估题目数', '专家评估数', '有效人机对数'] + [c for c in ('人机一致性_ICC', '人机一致性_MAE') if c in hm.columns]
            expert_block = expert_block.merge(hm[[c for c in extra_cols if c in hm.columns]], on='专家', how='left')
        # 合格题目数（结算依据）
        if qualified_count_df is not None and not qualified_count_df.empty and '专家' in qualified_count_df.columns:
            expert_block = expert_block.merge(qualified_count_df, on='专家', how='left')
            expert_block['合格题目数'] = expert_block['合格题目数'].fillna(0).astype(int)
        # 诊断与优化建议：基于 ref 满分率、区分度、人机一致性
        diag_df = compute_expert_diagnosis_and_suggestions(expert_block)
        if not diag_df.empty:
            expert_block = expert_block.merge(diag_df, on='专家', how='left')
        # 统计检查列：可计算ICC、数据检查。有效人机对数=同时有专家打分与模型分的条数，≥3 才算 ICC
        def _add_expert_consistency_checks(eb: pd.DataFrame) -> pd.DataFrame:
            if eb.empty:
                return eb
            eb = eb.copy()
            n_exp = pd.to_numeric(eb.get('专家评估数', 0), errors='coerce').fillna(0).astype(int)
            n_pairs = pd.to_numeric(eb.get('有效人机对数', np.nan), errors='coerce')
            icc_val = pd.to_numeric(eb.get('人机一致性_ICC', np.nan), errors='coerce')
            has_icc = icc_val.notna() & ~np.isnan(icc_val)
            # 文案简短避免 Excel 截断（如「否(有效人机对<3)」）
            def _icc_reason(i):
                if has_icc.iloc[i]:
                    return '是'
                p = n_pairs.iloc[i]
                if pd.isna(p):
                    return '否(有效人机对<3)'
                return f'否(有效人机对{int(p)}<3)'
            eb['可计算ICC'] = [_icc_reason(i) for i in range(len(eb))]
            issues = []
            for i in range(len(eb)):
                parts = []
                np_val = n_pairs.iloc[i]
                if not has_icc.iloc[i] and n_exp.iloc[i] >= 3 and (pd.isna(np_val) or np_val < 3):
                    parts.append('部分回复未参与裁判评估(ref/reply1/reply2 注入后需跑裁判，有效人机对≥3 才有 ICC)')
                if not has_icc.iloc[i] and (pd.isna(np_val) or np_val < 3):
                    parts.append('有效人机对数不足(需≥3 才计算 ICC)')
                if not parts:
                    parts.append('正常')
                issues.append('; '.join(parts))
            eb['数据检查'] = issues
            return eb

        expert_block = _add_expert_consistency_checks(expert_block)
        # 列顺序：排名、专家、题目数、专家评估数、有效人机对数、合格题目数、一致性、可计算ICC、数据检查、ref、区分度、得分/等级、有效性、诊断、优化建议
        want_cols = ['数据质量排名', '专家', '评估题目数', '专家评估数', '有效人机对数', '合格题目数', '人机一致性_斯皮尔曼', '人机一致性_ICC', '人机一致性_MAE',
                     '可计算ICC', '数据检查',
                     'ref均分', 'ref满分率(%)', '平均区分度', '高区分度题目数', '数据质量得分', '数据质量等级',
                     'Rubrics有效性指数', '诊断', '优化建议']
        expert_block = expert_block[[c for c in want_cols if c in expert_block.columns]]

    batch_consistency = expert_model_per_batch_df if expert_model_per_batch_df is not None else pd.DataFrame()
    batch_reliability = per_batch_reliability_df if per_batch_reliability_df is not None else pd.DataFrame()
    return expert_block, batch_consistency, batch_reliability


def _compute_ila_summary(replies_df: pd.DataFrame) -> dict:
    """
    计算完全通过率 ILA（全部检查点 PASS 的题目占比）及 D1–D5 各维度 ILA 通过率。
    依赖 data_loader 中从 eval_*_raw 解析出的 full_pass、D1_ila..D5_ila 列。
    """
    if replies_df.empty or 'full_pass' not in replies_df.columns:
        return {}
    valid = replies_df.dropna(subset=['full_pass'])
    if valid.empty:
        return {}
    # 确保 full_pass 为数值型，避免 object dtype 导致 round 报错
    valid = valid.copy()
    valid['_fp_num'] = pd.to_numeric(valid['full_pass'], errors='coerce').fillna(0)
    per_model = valid.groupby('model').agg(
        full_pass_count=('_fp_num', 'sum'),
        total=('_fp_num', 'count'),
    ).reset_index()
    per_model['完全通过数'] = per_model['full_pass_count'].astype(int)
    per_model['完全通过率(%)'] = (per_model['full_pass_count'] / per_model['total'].replace(0, np.nan) * 100).round(2)
    overall_pass = int(valid['_fp_num'].sum())
    overall_total = len(valid)
    out = {
        'per_model_df': per_model[['model', '完全通过数', 'total', '完全通过率(%)']].rename(
            columns={'total': '评测数', 'model': '模型'}
        ),
        'overall_pass': overall_pass,
        'overall_total': overall_total,
        'overall_rate': round(overall_pass / overall_total * 100, 2) if overall_total > 0 else 0,
    }

    # D1–D5 各维度 ILA 通过率（该维度下全部检查点 PASS 的比例，按模型统计）
    dim_cols = [c for c in ['D1_ila', 'D2_ila', 'D3_ila', 'D4_ila', 'D5_ila'] if c in replies_df.columns]
    if not dim_cols:
        return out
    rows = []
    for model in replies_df['model'].dropna().unique():
        sub = replies_df[replies_df['model'] == model]
        row = {'模型': model}
        for col in dim_cols:
            dim_valid = sub[col].dropna()
            if len(dim_valid) == 0:
                row[col.replace('_ila', '_ILA率(%)')] = np.nan
            else:
                rate = (dim_valid.astype(bool).sum() / len(dim_valid) * 100)
                row[col.replace('_ila', '_ILA率(%)')] = round(float(rate), 2)
        rows.append(row)
    dim_df = pd.DataFrame(rows)
    # 列顺序：模型, D1_ILA率(%), D2_ILA率(%), ...
    col_order = ['模型'] + [c.replace('_ila', '_ILA率(%)') for c in dim_cols]
    dim_df = dim_df[[c for c in col_order if c in dim_df.columns]]
    out['dimension_ila_df'] = dim_df
    return out


def _normalize_questions_for_difficulty(df: pd.DataFrame) -> pd.DataFrame:
    """统一列名：数据来源->source, 预设难度->difficulty_level, 难度分->difficulty_score"""
    if df is None or df.empty:
        return df
    d = df.copy()
    alias = [('数据来源', 'source'), ('预设难度', 'difficulty_level'), ('难度等级', 'difficulty_level'),
             ('diffuculty_level', 'difficulty_level'),
             ('难度分', 'difficulty_score'), ('难度分数', 'difficulty_score')]
    for old_name, new_name in alias:
        if old_name in d.columns and new_name not in d.columns:
            d[new_name] = d[old_name]
    return d


def _compute_difficulty_analysis(data: dict) -> tuple:
    """
    难度等级分析：1) source×难度等级 题目分布  2) source×难度等级 难度均分(difficulty_score)
    3) 各模型在不同难度上的均分及分差。
    difficulty_score/difficulty_level 来自指令质量评估的预先计算。
    支持列名：source/数据来源, difficulty_level/预设难度, difficulty_score/难度分。
    返回 (difficulty_dist_df, difficulty_mean_df, model_difficulty_df)
    """
    rwq_raw = data.get('replies_with_question', pd.DataFrame())
    rwq = _normalize_questions_for_difficulty(rwq_raw) if not rwq_raw.empty else rwq_raw
    questions = _normalize_questions_for_difficulty(data.get('questions', pd.DataFrame()))

    dist_df = pd.DataFrame()
    mean_df = pd.DataFrame()
    # 若 questions 缺少 source，尝试从 replies_with_question 取唯一题目
    q_base = questions
    if (questions.empty or 'source' not in questions.columns or 'difficulty_level' not in questions.columns) and not rwq.empty:
        q_cols = [c for c in ['qid', 'source', 'source_group', 'difficulty_level', 'difficulty_score'] if c in rwq.columns]
        if ('source' in q_cols or 'source_group' in q_cols) and 'difficulty_level' in rwq.columns:
            src_col = 'source' if 'source' in rwq.columns else 'source_group'
            cols = [c for c in ['qid', src_col, 'difficulty_level', 'difficulty_score'] if c in rwq.columns]
            q_base = rwq[cols].copy()
            if not q_base.empty:
                q_base = q_base.drop_duplicates(subset=['qid'])
                q_base = q_base.rename(columns={src_col: 'source'})
                print("  ✓ 难度分析使用 replies_with_question 的题目元数据（questions 缺少 source/difficulty_level）")

    if not q_base.empty and 'difficulty_level' in q_base.columns and 'source' in q_base.columns:
        q = q_base.dropna(subset=['difficulty_level', 'source'])
        if not q.empty:
            priority = {'S': 6, 'A': 5, 'B': 4, 'C': 3, 'D': 2, 'E': 1}
            # 列=source（八值），行=难度等级（S~E）
            pivot = q.groupby(['difficulty_level', 'source']).size().unstack(fill_value=0)
            pivot = pivot.reindex(
                sorted(pivot.index, key=lambda x: priority.get(str(x), 0), reverse=True)
            )
            # 列顺序：公开(to_b/nlp_*) 优先，再自建(H/R/HM/M)
            pub_order = ['to_b', 'nlp_cif', 'nlp_firefly', 'nlp_others']
            self_order = ['H', 'R', 'HM', 'M']
            col_order = [c for c in pub_order + self_order if c in pivot.columns]
            extra = [c for c in pivot.columns if c not in col_order]
            pivot = pivot[[c for c in col_order + extra if c in pivot.columns]]
            dist_df = pivot.reset_index()
            dist_df = dist_df.rename(columns={'difficulty_level': '难度等级'})
            if 'difficulty_score' in q.columns:
                avg_score = q.groupby('difficulty_level')['difficulty_score'].mean().round(2)
                dist_df['难度分均值'] = dist_df['难度等级'].map(avg_score)
            # 合计行
            total_row = {'难度等级': '合计'}
            for col in dist_df.columns:
                if col == '难度等级':
                    continue
                if col == '难度分均值':
                    total_row[col] = ''
                elif col in pivot.columns:
                    total_row[col] = int(dist_df[col].sum())
                else:
                    total_row[col] = ''
            dist_df = pd.concat([dist_df, pd.DataFrame([total_row])], ignore_index=True)
            print("  ✓ source八值×难度等级 题目分布")
            # 同结构：单元格=对应(source,难度等级)题目集的 difficulty_score 均值
            if 'difficulty_score' in q.columns:
                pivot_mean = q.groupby(['difficulty_level', 'source'])['difficulty_score'].mean().unstack()
                pivot_mean = pivot_mean.reindex(
                    sorted(pivot_mean.index, key=lambda x: priority.get(str(x), 0), reverse=True)
                )
                mean_cols = [c for c in col_order + extra if c in pivot_mean.columns]
                if mean_cols:
                    pivot_mean = pivot_mean[mean_cols]
                mean_df = pivot_mean.round(2).reset_index()
                mean_df = mean_df.rename(columns={'difficulty_level': '难度等级'})
                print("  ✓ source八值×难度等级 难度均分")
    else:
        if questions.empty and rwq.empty:
            print("  ⚠ 无题目数据，跳过 source×难度等级 统计")
        else:
            print("  ⚠ 题目表缺少 source 或 difficulty_level 列，跳过 source×难度等级 题目分布与难度均分（需列：source/数据来源, difficulty_level/预设难度, difficulty_score/难度分）")

    model_diff_df = pd.DataFrame()
    if not rwq.empty and 'difficulty_level' in rwq.columns:
        score_col = (
            'ranking_score' if 'ranking_score' in rwq.columns and rwq['ranking_score'].notna().any()
            else 'eval_score'
        )
        if score_col not in rwq.columns:
            return dist_df, mean_df, model_diff_df

        priority = {'S': 6, 'A': 5, 'B': 4, 'C': 3, 'D': 2, 'E': 1}
        levels = sorted(rwq['difficulty_level'].dropna().unique(),
                       key=lambda x: priority.get(str(x), 0), reverse=True)
        models = rwq['model'].dropna().unique()

        rows = []
        for model in models:
            sub = rwq[rwq['model'] == model]
            row = {'模型': model}
            level_scores = []
            for lev in levels:
                lev_sub = sub[sub['difficulty_level'] == lev]
                if not lev_sub.empty:
                    mu = float(lev_sub[score_col].mean())
                    row[f'{lev}均分'] = round(mu, 2)
                    level_scores.append(mu)
                else:
                    row[f'{lev}均分'] = np.nan
            if level_scores:
                row['平均分'] = round(float(np.nanmean(level_scores)), 2)
                row['分差(易-难)'] = round(
                    float(np.nanmax(level_scores) - np.nanmin(level_scores)), 2
                )
                rows.append(row)
        model_diff_df = pd.DataFrame(rows)
        if not model_diff_df.empty:
            model_diff_df = model_diff_df.sort_values('平均分', ascending=False).reset_index(drop=True)
            model_diff_df.insert(0, '排名', model_diff_df.index + 1)
            print("  ✓ 各模型×难度等级 得分及分差")

    return dist_df, mean_df, model_diff_df


# 厂商识别：使用 vendor_config 统一配置（含厂商性质、标准命名）
from .vendor_config import (
    get_model_vendor as _get_model_vendor,
    get_model_vendor_info,
    get_model_domestic,
    get_model_thinking,
    get_vendor_model_table_df,
)
from .rubric_dimension_analysis import (
    parse_rubrics_check_from_eval_raw,
    compute_main_score_lianzuo,
    compute_composite_from_rubrics_check,
)

# 梯队划分配置（可修改）：按 Main_Score 降序后的分位数划分
# (累计分位上限, 梯队名称) — 如 0.10 表示前 10% 为第一梯队
PANORAMA_TIER_CONFIG = [
    (0.10, '👑 第一梯队'),
    (0.30, '🚀 第二梯队'),
    (0.70, '⚔️ 第三梯队'),
    (1.00, '⚠️ 第四梯队'),
]
PUBLIC_SOURCES = {'nlp_firefly', 'nlp_cif', 'nlp_others', 'to_b'}
PRIVATE_SOURCES = {'H', 'HM', 'R'}  # 纯人工与人机协作，排除 M


def _compute_vendor_ranking(overall_ranking: pd.DataFrame) -> pd.DataFrame:
    """
    厂商排名：每厂商选取最强模型参与评分，按均分降序。
    列：排名、厂商、最强模型、均分、题目数（如有）
    """
    if overall_ranking.empty or '模型' not in overall_ranking.columns or '平均分' not in overall_ranking.columns:
        return pd.DataFrame()
    model_to_avg = dict(zip(overall_ranking['模型'].astype(str), overall_ranking['平均分'].astype(float)))
    model_to_cnt = {}
    cnt_col = '题目数' if '题目数' in overall_ranking.columns else ('评测数量' if '评测数量' in overall_ranking.columns else None)
    if cnt_col:
        model_to_cnt = dict(zip(overall_ranking['模型'].astype(str), overall_ranking[cnt_col].astype(int)))
    vendor_best = {}
    for model, avg in model_to_avg.items():
        v = _get_model_vendor(model)
        _, vtype, std_name = get_model_vendor_info(model)
        if v not in vendor_best or vendor_best[v][1] < avg:
            vendor_best[v] = (model, float(avg), vtype or '', std_name or '')
    rows = []
    for v, (m, s, vtype, std_name) in sorted(vendor_best.items(), key=lambda x: x[1][1], reverse=True):
        rows.append({
            '厂商': v,
            '厂商性质': vtype,
            '最强模型': m,
            '标准命名': std_name,
            '均分': round(s, 2),
            '题目数': model_to_cnt.get(m, ''),
        })
    df = pd.DataFrame(rows)
    df.insert(0, '排名', range(1, len(df) + 1))
    return df


def _compute_vendor_series_model_ranking(overall_ranking: pd.DataFrame) -> pd.DataFrame:
    """
    厂商系列模型均分排行：每行=模型，含厂商、厂商性质、标准命名，便于绘制柱状图与厂商视角统计。
    列：排名、厂商、厂商性质、模型、标准命名、均分、标准差（如有）
    """
    if overall_ranking.empty or '模型' not in overall_ranking.columns:
        return pd.DataFrame()
    df = overall_ranking.copy()
    info = df['模型'].astype(str).apply(lambda m: get_model_vendor_info(m))
    df['厂商'] = info.apply(lambda x: x[0])
    df['厂商性质'] = info.apply(lambda x: x[1] or '')
    df['标准命名'] = info.apply(lambda x: x[2] or '')
    cols = ['厂商', '厂商性质', '模型', '标准命名']
    if '平均分' in df.columns:
        cols.append('平均分')
    if '标准差' in df.columns:
        cols.append('标准差')
    if '题目数' in df.columns:
        cols.append('题目数')
    elif '评测数量' in df.columns:
        cols.append('评测数量')
    df = df[[c for c in cols if c in df.columns]]
    df = df.sort_values('平均分', ascending=False).reset_index(drop=True)
    df.insert(0, '排名', range(1, len(df) + 1))
    return df


def _compute_l1_source_mean_scores(rwq: pd.DataFrame) -> pd.DataFrame:
    """
    L1×source 均分：纵轴=L1，横轴=source_group，不区分模型，用于自建vs公开在L1层面的分数差异。
    """
    if rwq.empty or 'L1' not in rwq.columns or 'source_group' not in rwq.columns:
        return pd.DataFrame()
    score_col = 'ranking_score' if 'ranking_score' in rwq.columns and rwq['ranking_score'].notna().any() else 'eval_score'
    if score_col not in rwq.columns:
        return pd.DataFrame()
    pivot = rwq.groupby(['L1', 'source_group'])[score_col].agg(['mean', 'count', 'std']).reset_index()
    pivot['均分'] = pivot['mean'].round(2)
    pivot['题目数'] = pivot['count'].astype(int)
    pivot['标准差'] = pivot['std'].round(2)
    # 转置为 L1 为行、source 为列
    wide = pivot.pivot_table(index='L1', columns='source_group', values='均分', aggfunc='first')
    wide = wide.reset_index()
    return wide


def _compute_panorama_ranking(data: dict) -> pd.DataFrame:
    """
    大模型多维动态约束全景总榜单。
    10 字段：Rank, Provider, Model_Name, Main_Score, CLA_Score, ILA_Rate, Public_Score,
    Private_Score, Score_Gap, Tier。
    """
    rwq = data.get('replies_with_question', pd.DataFrame())
    replies = data.get('replies', pd.DataFrame())
    eval_col = data.get('eval_column', 'eval_batch_1')
    raw_col = f'{eval_col}_raw' if not eval_col.endswith('_raw') else eval_col

    if rwq.empty or raw_col not in replies.columns:
        return pd.DataFrame()

    # 计算每行 (qid, model) 的 Main_Score（连坐）
    main_scores = []
    cla_scores = []
    full_pass_list = []
    for _, row in replies.iterrows():
        raw_val = row.get(raw_col, '')
        if pd.isna(raw_val) or not str(raw_val).strip():
            main_scores.append(np.nan)
            cla_scores.append(np.nan)
            full_pass_list.append(False)
            continue
        check = parse_rubrics_check_from_eval_raw(str(raw_val))
        main_scores.append(compute_main_score_lianzuo(check))
        res = compute_composite_from_rubrics_check(check)
        cla_scores.append(res.get('cla_score', np.nan))
        full_pass_list.append(res.get('full_pass', False))
    replies = replies.copy()
    replies['_main_score'] = main_scores
    replies['_cla'] = cla_scores
    replies['_full_pass'] = full_pass_list

    # merge source from rwq (replies_with_question has qid, model, source)
    if 'source' not in replies.columns and not rwq.empty and 'source' in rwq.columns:
        src_map = rwq[['qid', 'model', 'source']].drop_duplicates()
        replies = replies.merge(src_map, on=['qid', 'model'], how='left')

    total_questions = replies['qid'].nunique()
    rows = []
    for model in replies['model'].dropna().unique():
        sub = replies[replies['model'] == model]
        main_vals = sub['_main_score'].dropna()
        main_avg = round(float(main_vals.mean()), 2) if len(main_vals) > 0 else np.nan
        cla_vals = sub['_cla'].dropna()
        cla_avg = round(float(cla_vals.mean()), 2) if len(cla_vals) > 0 else np.nan
        ila_count = int(sub['_full_pass'].sum())
        ila_rate = f'{(ila_count / total_questions * 100):.2f}%' if total_questions > 0 else 'N/A'

        # Public_Score / Private_Score
        if 'source' in sub.columns:
            pub_sub = sub[sub['source'].astype(str).str.strip().isin(PUBLIC_SOURCES)]
            priv_sub = sub[sub['source'].astype(str).str.strip().isin(PRIVATE_SOURCES)]
            pub_main = pub_sub['_main_score'].dropna()
            priv_main = priv_sub['_main_score'].dropna()
            pub_score = round(float(pub_main.mean()), 2) if len(pub_main) > 0 else np.nan
            priv_score = round(float(priv_main.mean()), 2) if len(priv_main) > 0 else np.nan
        else:
            pub_score = priv_score = np.nan

        gap = round(float(priv_score - pub_score), 2) if not (pd.isna(priv_score) or pd.isna(pub_score)) else np.nan
        vendor, _, std_name = get_model_vendor_info(model)
        rows.append({
            'Provider': vendor,
            'Model_Name': std_name if std_name else model,
            'Domestic': get_model_domestic(model),
            'Thinking': get_model_thinking(model),
            'Main_Score': main_avg,
            'CLA_Score': cla_avg,
            'ILA_Rate': ila_rate,
            'Public_Score': pub_score if not np.isnan(pub_score) else '',
            'Private_Score': priv_score if not np.isnan(priv_score) else '',
            'Score_Gap': gap if not pd.isna(gap) else '',
            '_main_for_rank': main_avg,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame()
    df = df.sort_values('_main_for_rank', ascending=False, na_position='last').reset_index(drop=True)
    df.insert(0, 'Rank', range(1, len(df) + 1))
    df = df.drop(columns=['_main_for_rank'])

    # Tier：按分位数划分
    n = len(df)
    tier_list = []
    for i in range(n):
        q = (i + 1) / n
        tier_name = PANORAMA_TIER_CONFIG[-1][1]
        for thresh, name in PANORAMA_TIER_CONFIG:
            if q <= thresh:
                tier_name = name
                break
        tier_list.append(tier_name)
    df['Tier'] = tier_list

    # 列顺序（含 Domestic、Thinking 供分组图表使用）
    col_order = [
        'Rank', 'Provider', 'Model_Name', 'Domestic', 'Thinking',
        'Main_Score', 'CLA_Score', 'ILA_Rate',
        'Public_Score', 'Private_Score', 'Score_Gap', 'Tier',
    ]
    df = df[[c for c in col_order if c in df.columns]]
    return df


def _compute_l1_score_gap_questions(item_analysis_df: pd.DataFrame, top_n: int = 10) -> dict:
    """
    L1 各维度下分差最大/最小的题目。
    分差 = 分数范围（最高分-最低分），反映模型在该题上的表现差异。
    返回 {'gap_max': {L1: df}, 'gap_min': {L1: df}, 'summary': df}
    """
    if item_analysis_df.empty or 'L1' not in item_analysis_df.columns:
        return {}
    if '分数范围' not in item_analysis_df.columns:
        return {}
    gap_col = '分数范围'
    gap_vals = pd.to_numeric(item_analysis_df[gap_col], errors='coerce')
    item_analysis_df = item_analysis_df.copy()
    item_analysis_df['_gap'] = gap_vals
    item_analysis_df = item_analysis_df.dropna(subset=['_gap'])
    gap_max_by_l1 = {}
    gap_min_by_l1 = {}
    summary_rows = []
    for l1 in item_analysis_df['L1'].dropna().unique():
        sub = item_analysis_df[item_analysis_df['L1'] == l1].copy()
        if sub.empty:
            continue
        sub = sub.sort_values('_gap', ascending=False)
        top_max = sub.head(top_n)
        top_min = sub.tail(top_n)
        gap_max_by_l1[str(l1)] = top_max.drop(columns=['_gap'], errors='ignore')
        gap_min_by_l1[str(l1)] = top_min.drop(columns=['_gap'], errors='ignore')
        summary_rows.append({
            'L1': str(l1),
            '题目数': len(sub),
            '分差最大题均分差': round(sub['_gap'].max(), 2) if not sub.empty else np.nan,
            '分差最小题均分差': round(sub['_gap'].min(), 2) if not sub.empty else np.nan,
            '平均分差': round(sub['_gap'].mean(), 2) if not sub.empty else np.nan,
            '分差最大题代表qid': sub.iloc[0]['qid'] if not sub.empty else '',
            '分差最小题代表qid': sub.iloc[-1]['qid'] if not sub.empty else '',
        })
    summary_df = pd.DataFrame(summary_rows) if summary_rows else pd.DataFrame()
    return {'gap_max': gap_max_by_l1, 'gap_min': gap_min_by_l1, 'summary': summary_df}


def _compute_l1_high_distinction_stats(item_analysis_df: pd.DataFrame) -> pd.DataFrame:
    """
    L1 级别高区分度题目统计：每个 L1 意图类型下，区分度指数_D >= 0.3（良好及以上）的题目数量。
    用于后续按 L1 总结模型能力时，明确各 L1 有多少典型高区分度题目可支撑分析。
    """
    if item_analysis_df.empty or 'L1' not in item_analysis_df.columns:
        return pd.DataFrame()
    if '区分度指数_D' not in item_analysis_df.columns:
        return pd.DataFrame()

    rows = []
    for l1 in item_analysis_df['L1'].dropna().unique():
        sub = item_analysis_df[item_analysis_df['L1'] == l1]
        total = len(sub)
        d_vals = pd.to_numeric(sub['区分度指数_D'], errors='coerce')
        high_count = int((d_vals >= 0.3).sum())
        pct = round(high_count / total * 100, 1) if total > 0 else 0
        rows.append({
            'L1': str(l1),
            '总题目数': total,
            '高区分度题目数': high_count,
            '占比(%)': pct,
        })
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).sort_values('高区分度题目数', ascending=False).reset_index(drop=True)
    print("  ✓ L1级别高区分度题目统计（区分度≥0.3为高区分度）")
    return df


def _compute_l1_loss_profiles(
    replies_with_q: pd.DataFrame,
    dimension_stats: dict,
    eval_column: str = '',
) -> pd.DataFrame:
    """
    按 L1 聚合各维度的通过率，并基于 AI 评估的 Dx_Y 检查点及失分评语(reason)汇总，形成各任务意图的失分特征总结。
    - 数据来源：dimension_stats 的 row_level_df（D2/D3/D4/D5 通过率）+ 若提供 eval_column 则解析 eval_*_raw 中每条 Dx_Y 的 PASS/FAIL 与 reason 评语。
    - 明确区分维度含义：D2=流程步骤、D3=边界范围、D4=格式形式、D5=内容质量，便于看出是「内容质量」还是「边界限制」等失分。
    返回 DataFrame：L1、各维度通过率、主要失分点、高频失分检查点(Dx_Y)、典型失分原因(来自评语)、失分特征简述。
    """
    from .rubric_dimension_analysis import (
        DIMENSION_LABELS,
        get_dimension_from_checkpoint,
        parse_rubrics_check_from_eval_raw,
    )
    row_level_df = dimension_stats.get('row_level_df', pd.DataFrame())
    if replies_with_q.empty or 'L1' not in replies_with_q.columns:
        return pd.DataFrame()
    qm_l1 = replies_with_q[['qid', 'model', 'L1']].drop_duplicates()
    qm_l1['qid'] = qm_l1['qid'].astype(str).str.strip()
    qm_l1['model'] = qm_l1['model'].astype(str).str.strip()
    merged = row_level_df.copy()
    if not merged.empty:
        merged['qid'] = merged['qid'].astype(str).str.strip()
        merged['model'] = merged['model'].astype(str).str.strip()
        merged = merged.merge(qm_l1, on=['qid', 'model'], how='inner')
    # 基于 eval_*_raw 的 Dx_Y 检查点失分与评语（按 L1 聚合）
    raw_col = ''
    if eval_column:
        raw_col = eval_column if str(eval_column).endswith('_raw') else f"{eval_column}_raw"
    if not raw_col or raw_col not in replies_with_q.columns:
        raw_col = next((c for c in replies_with_q.columns if isinstance(c, str) and c.startswith('eval_') and c.endswith('_raw')), '')
    l1_checkpoint_fails = {}  # L1 -> { checkpoint_id: count }
    l1_dim_reasons = {}       # L1 -> { dim: [reason1, reason2, ...] }
    if raw_col:
        for _, row in replies_with_q.iterrows():
            l1 = row.get('L1')
            if pd.isna(l1) or not str(l1).strip():
                continue
            l1 = str(l1).strip()
            raw_val = row.get(raw_col, '')
            if pd.isna(raw_val) or not str(raw_val).strip():
                continue
            check = parse_rubrics_check_from_eval_raw(str(raw_val))
            if not check:
                continue
            if l1 not in l1_checkpoint_fails:
                l1_checkpoint_fails[l1] = {}
                l1_dim_reasons[l1] = {}
            for cp_id, info in check.items():
                res = (info.get('result') or '').strip().upper()
                if res != 'FAIL':
                    continue
                l1_checkpoint_fails[l1][cp_id] = l1_checkpoint_fails[l1].get(cp_id, 0) + 1
                reason = (info.get('reason') or '').strip()
                if reason and len(reason) > 2:
                    dim = get_dimension_from_checkpoint(cp_id)
                    if dim:
                        if dim not in l1_dim_reasons[l1]:
                            l1_dim_reasons[l1][dim] = []
                        r_short = reason[:80] + '…' if len(reason) > 80 else reason
                        if r_short not in l1_dim_reasons[l1][dim]:
                            l1_dim_reasons[l1][dim].append(r_short)
                            if len(l1_dim_reasons[l1][dim]) > 3:
                                l1_dim_reasons[l1][dim] = l1_dim_reasons[l1][dim][:3]

    if merged.empty and not l1_checkpoint_fails:
        return pd.DataFrame()
    dims = ['D1', 'D2', 'D3', 'D4', 'D5']
    l1_set = set()
    if not merged.empty:
        l1_set = set(merged['L1'].dropna().astype(str).str.strip())
    l1_set.update(l1_checkpoint_fails.keys())
    if not l1_set:
        return pd.DataFrame()
    rows = []
    for l1 in sorted(l1_set):
        sub = merged[merged['L1'].astype(str).str.strip() == l1] if not merged.empty else pd.DataFrame()
        rec = {'L1': str(l1)}
        rates = {}
        if not sub.empty:
            for d in dims:
                pcol, tcol = f'{d}_pass', f'{d}_total'
                if pcol not in sub.columns or tcol not in sub.columns:
                    continue
                total = sub[tcol].sum()
                if total and total > 0:
                    rate = round(float(sub[pcol].sum()) / float(total) * 100, 1)
                    rec[f'{d}通过率'] = rate
                    rates[d] = rate
        if not rates:
            if l1 not in l1_checkpoint_fails:
                continue
            for d in dims:
                rec[f'{d}通过率'] = np.nan
        # 主要失分点：通过率最低的 1～2 个维度（业务理解=D1，内容质量=D5，边界限制=D3，流程=D2，格式=D4）
        sorted_dims = sorted(rates.keys(), key=lambda x: rates[x]) if rates else list(dims)
        main_loss = sorted_dims[:2] if len(sorted_dims) >= 2 else sorted_dims[:1]
        rec['主要失分点'] = '、'.join([f"{d}{DIMENSION_LABELS.get(d, d)}" for d in main_loss])
        # 高频失分检查点（来自 AI 评估 Dx_Y）
        cp_fails = l1_checkpoint_fails.get(l1, {})
        if cp_fails:
            top_cps = sorted(cp_fails.keys(), key=lambda x: cp_fails[x], reverse=True)[:6]
            rec['高频失分检查点'] = '、'.join(top_cps)
        else:
            rec['高频失分检查点'] = ''
        # 典型失分原因（来自 AI 评语 reason）
        dim_reasons = l1_dim_reasons.get(l1, {})
        reason_parts = []
        for d in dims:
            reasons = dim_reasons.get(d, [])
            if not reasons:
                continue
            label = DIMENSION_LABELS.get(d, d)
            reason_parts.append(f"{d}{label}：{'；'.join(reasons[:2])}")
        rec['典型失分原因(评语)'] = ' | '.join(reason_parts[:4]) if reason_parts else ''
        # 失分特征简述：明确是业务理解(D1)/内容质量(D5)还是边界限制(D3)等
        if rates:
            labels = [f"{d}{DIMENSION_LABELS.get(d, d)}（{rates[d]}%）" for d in sorted_dims]
            rec['失分特征简述'] = f"该意图下 {'、'.join(labels)}；主要薄弱在 {rec['主要失分点']}（可区分业务理解/D1、内容质量/D5、边界限制/D3、流程步骤/D2、格式形式/D4）。"
        else:
            rec['失分特征简述'] = f"主要失分在 {rec['主要失分点']}。" + (f" 高频检查点：{rec['高频失分检查点']}。" if rec.get('高频失分检查点') else "")
        rows.append(rec)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    col_order = ['L1'] + [f'{d}通过率' for d in dims if f'{d}通过率' in df.columns] + ['主要失分点', '高频失分检查点', '典型失分原因(评语)', '失分特征简述']
    df = df[[c for c in col_order if c in df.columns]]
    print("  ✓ L1 失分特征总结（含 Dx_Y 检查点与 AI 评语汇总，区分内容质量/边界限制等维度）")
    return df


def _compute_dimension_fail_rate_tables(dimension_stats: dict) -> dict:
    """
    基于 rubrics_check 解析结果（dimension_stats），输出：
    - overall_df: 每维度 PASS/FAIL/失分率
    - per_model_df: 每模型每维度 PASS/FAIL/失分率
    """
    from .rubric_dimension_analysis import DIMENSION_LABELS
    row_level_df = (dimension_stats or {}).get('row_level_df', pd.DataFrame())
    model_dim_df = (dimension_stats or {}).get('model_dimension_df', pd.DataFrame())
    out = {'overall_df': pd.DataFrame(), 'per_model_df': pd.DataFrame()}
    if row_level_df is None or row_level_df.empty:
        return out

    dims = ['D1', 'D2', 'D3', 'D4', 'D5']
    overall_rows = []
    for d in dims:
        pcol, tcol = f'{d}_pass', f'{d}_total'
        if pcol not in row_level_df.columns or tcol not in row_level_df.columns:
            continue
        total = pd.to_numeric(row_level_df[tcol], errors='coerce').fillna(0).sum()
        passed = pd.to_numeric(row_level_df[pcol], errors='coerce').fillna(0).sum()
        failed = max(float(total - passed), 0.0)
        if total <= 0:
            continue
        fail_rate = round(float(failed) / float(total) * 100, 2)
        overall_rows.append({
            '维度': f'{d}{DIMENSION_LABELS.get(d, d)}',
            'PASS': int(passed),
            'FAIL': int(failed),
            '失分率(%)': fail_rate,
        })
    out['overall_df'] = pd.DataFrame(overall_rows)

    if model_dim_df is not None and not model_dim_df.empty:
        per_rows = []
        for _, r in model_dim_df.iterrows():
            dim = str(r.get('dimension', '')).strip()
            if dim not in dims:
                continue
            total = float(r.get('total_count', 0) or 0)
            passed = float(r.get('pass_count', 0) or 0)
            if total <= 0:
                continue
            failed = max(total - passed, 0.0)
            fail_rate = round(float(failed) / float(total) * 100, 2)
            per_rows.append({
                '模型': str(r.get('model', '')).strip(),
                '维度': f'{dim}{DIMENSION_LABELS.get(dim, dim)}',
                'PASS': int(passed),
                'FAIL': int(failed),
                '失分率(%)': fail_rate,
            })
        out['per_model_df'] = pd.DataFrame(per_rows)
    return out


def _compute_d5_fail_by_l1(
    replies_with_q: pd.DataFrame,
    dimension_stats: dict,
) -> pd.DataFrame:
    """D5（内容质量）按 L1 聚合失分率，用于定位业务能力薄弱类型。"""
    from .rubric_dimension_analysis import DIMENSION_LABELS
    row_level_df = (dimension_stats or {}).get('row_level_df', pd.DataFrame())
    if replies_with_q is None or replies_with_q.empty or row_level_df is None or row_level_df.empty:
        return pd.DataFrame()
    if 'L1' not in replies_with_q.columns:
        return pd.DataFrame()
    qm_l1 = replies_with_q[['qid', 'model', 'L1']].drop_duplicates()
    qm_l1['qid'] = qm_l1['qid'].astype(str).str.strip()
    qm_l1['model'] = qm_l1['model'].astype(str).str.strip()
    merged = row_level_df.copy()
    merged['qid'] = merged['qid'].astype(str).str.strip()
    merged['model'] = merged['model'].astype(str).str.strip()
    merged = merged.merge(qm_l1, on=['qid', 'model'], how='inner')
    if merged.empty or 'D5_pass' not in merged.columns or 'D5_total' not in merged.columns:
        return pd.DataFrame()
    merged['D5_pass'] = pd.to_numeric(merged['D5_pass'], errors='coerce').fillna(0)
    merged['D5_total'] = pd.to_numeric(merged['D5_total'], errors='coerce').fillna(0)
    g = merged.groupby('L1').agg({'D5_pass': 'sum', 'D5_total': 'sum'}).reset_index()
    g = g[g['D5_total'] > 0].copy()
    if g.empty:
        return pd.DataFrame()
    g['D5通过率(%)'] = (g['D5_pass'] / g['D5_total'] * 100).round(2)
    g['D5失分率(%)'] = (100 - g['D5通过率(%)']).round(2)
    g['维度含义'] = f"D5{DIMENSION_LABELS.get('D5', '内容质量')}"
    g = g.sort_values('D5失分率(%)', ascending=False).reset_index(drop=True)
    return g[['L1', 'D5_pass', 'D5_total', 'D5通过率(%)', 'D5失分率(%)', '维度含义']]


def _compute_model_weakness_summary_light(
    replies_with_q: pd.DataFrame,
    dimension_stats: dict,
) -> dict:
    """
    仅基于 row_level_df + L1 汇总（不解析 eval_*_raw），得到每模型薄弱 L1 及主要失分维度。
    计算量小，适合默认「汇总统计」。
    返回 dict model -> "L1A(主要失分点)、L1B(主要失分点)"
    """
    from .rubric_dimension_analysis import DIMENSION_LABELS
    row_level_df = dimension_stats.get('row_level_df', pd.DataFrame())
    if replies_with_q.empty or row_level_df.empty or 'L1' not in replies_with_q.columns:
        return {}
    qm_l1 = replies_with_q[['qid', 'model', 'L1']].drop_duplicates()
    qm_l1['qid'] = qm_l1['qid'].astype(str).str.strip()
    qm_l1['model'] = qm_l1['model'].astype(str).str.strip()
    merged = row_level_df.copy()
    merged['qid'] = merged['qid'].astype(str).str.strip()
    merged['model'] = merged['model'].astype(str).str.strip()
    merged = merged.merge(qm_l1, on=['qid', 'model'], how='inner')
    if merged.empty:
        return {}
    dims = ['D2', 'D3', 'D4', 'D5']
    out = {}
    for m in merged['model'].dropna().unique():
        m = str(m).strip()
        sub = merged[merged['model'].astype(str).str.strip() == m]
        rows = []
        for l1 in sub['L1'].dropna().unique():
            l1 = str(l1).strip()
            s = sub[sub['L1'].astype(str).str.strip() == l1]
            rates = {}
            for d in dims:
                pcol, tcol = f'{d}_pass', f'{d}_total'
                if pcol not in s.columns or tcol not in s.columns:
                    continue
                total = s[tcol].sum()
                if total and total > 0:
                    rates[d] = float(s[pcol].sum()) / float(total) * 100
            if not rates:
                continue
            sorted_dims = sorted(rates.keys(), key=lambda x: rates[x])
            main_loss = '、'.join([f"{d}{DIMENSION_LABELS.get(d, d)}" for d in sorted_dims[:2]])
            avg = sum(rates.values()) / len(rates)
            rows.append((avg, l1, main_loss))
        rows.sort(key=lambda x: x[0])
        parts = [f"{r[1]}({r[2]})" for r in rows[:3]]
        out[m] = '；'.join(parts) if parts else '—'
    print("  ✓ 模型薄弱 L1 汇总（基于统计，未解析评语，计算量小）")
    return out


def _compute_model_l1_loss_profiles(
    replies_with_q: pd.DataFrame,
    dimension_stats: dict,
    eval_column: str = '',
    focus_models: list = None,
) -> tuple:
    """
    按 模型×L1 聚合维度通过率与 Dx_Y 失分评语，得到「具体模型在哪些 L1、哪些维度失分及原因」。
    focus_models: 若指定，仅对这些模型（及建议含第一名）解析 raw 并输出明细，大幅减少计算量。
    返回 (model_l1_df, model_weakness_summary):
    - model_l1_df: 列 model, L1, D2/D3/D4/D5通过率, 主要失分点, 高频失分检查点, 典型失分原因(评语), 失分特征简述
    - model_weakness_summary: dict model -> str "薄弱L1及维度：L1A(D5/D3)、L1B(D2)"
    """
    from .rubric_dimension_analysis import (
        DIMENSION_LABELS,
        get_dimension_from_checkpoint,
        parse_rubrics_check_from_eval_raw,
    )
    row_level_df = dimension_stats.get('row_level_df', pd.DataFrame())
    if replies_with_q.empty or 'L1' not in replies_with_q.columns:
        return pd.DataFrame(), {}
    qm_l1 = replies_with_q[['qid', 'model', 'L1']].drop_duplicates()
    qm_l1['qid'] = qm_l1['qid'].astype(str).str.strip()
    qm_l1['model'] = qm_l1['model'].astype(str).str.strip()
    merged = row_level_df.copy()
    if not merged.empty:
        merged['qid'] = merged['qid'].astype(str).str.strip()
        merged['model'] = merged['model'].astype(str).str.strip()
        merged = merged.merge(qm_l1, on=['qid', 'model'], how='inner')
    # 聚焦模式：只对 focus_models 内的模型解析 raw 并输出
    focus_set = None
    if focus_models:
        focus_set = set(str(m).strip() for m in focus_models if m)
    rwq_for_raw = replies_with_q
    if focus_set:
        rwq_for_raw = replies_with_q[replies_with_q['model'].astype(str).str.strip().isin(focus_set)]
    raw_col = ''
    if eval_column:
        raw_col = eval_column if str(eval_column).endswith('_raw') else f"{eval_column}_raw"
    if not raw_col or raw_col not in replies_with_q.columns:
        raw_col = next((c for c in replies_with_q.columns if isinstance(c, str) and c.startswith('eval_') and c.endswith('_raw')), '')
    # (model, L1) -> checkpoint_fails, dim_reasons（仅对 rwq_for_raw 解析，减少迭代）
    ml_checkpoint_fails = {}
    ml_dim_reasons = {}
    if raw_col:
        for _, row in rwq_for_raw.iterrows():
            model = row.get('model')
            l1 = row.get('L1')
            if pd.isna(model) or pd.isna(l1) or not str(l1).strip():
                continue
            key = (str(model).strip(), str(l1).strip())
            raw_val = row.get(raw_col, '')
            if pd.isna(raw_val) or not str(raw_val).strip():
                continue
            check = parse_rubrics_check_from_eval_raw(str(raw_val))
            if not check:
                continue
            if key not in ml_checkpoint_fails:
                ml_checkpoint_fails[key] = {}
                ml_dim_reasons[key] = {}
            for cp_id, info in check.items():
                res = (info.get('result') or '').strip().upper()
                if res != 'FAIL':
                    continue
                ml_checkpoint_fails[key][cp_id] = ml_checkpoint_fails[key].get(cp_id, 0) + 1
                reason = (info.get('reason') or '').strip()
                if reason and len(reason) > 2:
                    dim = get_dimension_from_checkpoint(cp_id)
                    if dim:
                        if dim not in ml_dim_reasons[key]:
                            ml_dim_reasons[key][dim] = []
                        r_short = reason[:60] + '…' if len(reason) > 60 else reason
                        if r_short not in ml_dim_reasons[key][dim]:
                            ml_dim_reasons[key][dim].append(r_short)
                            if len(ml_dim_reasons[key][dim]) > 2:
                                ml_dim_reasons[key][dim] = ml_dim_reasons[key][dim][:2]

    dims = ['D2', 'D3', 'D4', 'D5']
    if merged.empty and not ml_checkpoint_fails:
        return pd.DataFrame(), {}
    keys_done = set()
    merged_for_keys = merged
    if focus_set and not merged.empty:
        merged_for_keys = merged[merged['model'].astype(str).str.strip().isin(focus_set)]
    if not merged_for_keys.empty:
        for (model, l1) in merged_for_keys.groupby(['model', 'L1']).groups.keys():
            keys_done.add((str(model).strip(), str(l1).strip()))
    keys_done.update(ml_checkpoint_fails.keys())
    rows = []
    for (model, l1) in sorted(keys_done):
        sub = merged[(merged['model'].astype(str).str.strip() == model) & (merged['L1'].astype(str).str.strip() == l1)] if not merged.empty else pd.DataFrame()
        rec = {'model': model, 'L1': str(l1)}
        rates = {}
        if not sub.empty:
            for d in dims:
                pcol, tcol = f'{d}_pass', f'{d}_total'
                if pcol not in sub.columns or tcol not in sub.columns:
                    continue
                total = sub[tcol].sum()
                if total and total > 0:
                    rate = round(float(sub[pcol].sum()) / float(total) * 100, 1)
                    rec[f'{d}通过率'] = rate
                    rates[d] = rate
        if not rates and (model, l1) not in ml_checkpoint_fails:
            continue
        if not rates:
            for d in dims:
                rec[f'{d}通过率'] = np.nan
        sorted_dims = sorted(rates.keys(), key=lambda x: rates[x]) if rates else list(dims)
        main_loss = sorted_dims[:2] if len(sorted_dims) >= 2 else sorted_dims[:1]
        rec['主要失分点'] = '、'.join([f"{d}{DIMENSION_LABELS.get(d, d)}" for d in main_loss])
        cp_fails = ml_checkpoint_fails.get((model, l1), {})
        rec['高频失分检查点'] = '、'.join(sorted(cp_fails.keys(), key=lambda x: cp_fails[x], reverse=True)[:5]) if cp_fails else ''
        dim_reasons = ml_dim_reasons.get((model, l1), {})
        reason_parts = []
        for d in dims:
            reasons = dim_reasons.get(d, [])
            if not reasons:
                continue
            reason_parts.append(f"{d}{DIMENSION_LABELS.get(d, d)}：{'；'.join(reasons[:2])}")
        rec['典型失分原因(评语)'] = ' | '.join(reason_parts[:3]) if reason_parts else ''
        avg_rate = (sum(rates.values()) / len(rates)) if rates else 0
        rec['_avg_pass_rate'] = avg_rate
        if rates:
            labels = [f"{d}({rates[d]}%)" for d in sorted_dims[:2]]
            rec['失分特征简述'] = f"主要薄弱在 {rec['主要失分点']}；{'、'.join(labels)}。"
        else:
            rec['失分特征简述'] = f"主要失分在 {rec['主要失分点']}。" + (f" 高频检查点：{rec['高频失分检查点']}。" if rec.get('高频失分检查点') else "")
        rows.append(rec)
    if not rows:
        return pd.DataFrame(), {}
    df = pd.DataFrame(rows)
    col_order = ['model', 'L1'] + [f'{d}通过率' for d in dims if f'{d}通过率' in df.columns] + ['主要失分点', '高频失分检查点', '典型失分原因(评语)', '失分特征简述']
    df = df[[c for c in col_order if c in df.columns]]
    if '_avg_pass_rate' in df.columns:
        df = df.drop(columns=['_avg_pass_rate'], errors='ignore')
    # 每模型汇总：薄弱 L1 及维度（按该模型下平均通过率最低的 3 个 L1）
    model_weakness_summary = {}
    if not df.empty and 'model' in df.columns:
        for m in df['model'].unique():
            sub = df[df['model'] == m].copy()
            sub['_avg'] = sub[[f'{d}通过率' for d in dims if f'{d}通过率' in sub.columns]].mean(axis=1)
            sub = sub.sort_values('_avg', ascending=True).head(3)
            parts = [f"{row['L1']}({row['主要失分点']})" for _, row in sub.iterrows()]
            model_weakness_summary[str(m)] = '；'.join(parts) if parts else '—'
    if focus_set:
        print(f"  ✓ 模型×L1 失分画像（聚焦 {len(focus_set)} 个模型，含评语）")
    else:
        print("  ✓ 模型×L1 失分画像（全模型，具体维度与评语）")
    return df, model_weakness_summary


def _build_data_synthesis_suggestions(
    l1_loss_profiles: pd.DataFrame,
    model_l1_df: pd.DataFrame,
    model_weakness_summary: dict,
    dimension_stats: dict,
) -> list:
    """
    基于 L1 与 模型×L1 失分数据，生成可执行的数据合成建议（内容质量/边界限制/流程/格式等）。
    """
    from .rubric_dimension_analysis import DIMENSION_LABELS
    suggestions = []
    dim_to_suggestion = {
        'D5': '内容质量类题目与数据',
        'D3': '边界与约束类数据',
        'D2': '流程步骤与操作逻辑类数据',
        'D4': '格式与输出形式类数据',
    }
    # 1) 从 L1 整体：各意图上主要失分维度 → 建议补充对应类型数据
    if not l1_loss_profiles.empty and '主要失分点' in l1_loss_profiles.columns and 'L1' in l1_loss_profiles.columns:
        for _, row in l1_loss_profiles.iterrows():
            l1_name = str(row.get('L1', '')).strip()
            main = str(row.get('主要失分点', ''))
            if not l1_name or not main:
                continue
            for dim in ['D5', 'D3', 'D2', 'D4']:
                if dim in main and dim in DIMENSION_LABELS:
                    label = DIMENSION_LABELS[dim]
                    sug_type = dim_to_suggestion.get(dim, f'{dim}类数据')
                    suggestions.append(f"**L1={l1_name}** 上整体在 **{label}** 失分较多，建议增加该意图下的{sug_type}，以提升该维度通过率。")
                    break
    # 2) 从 模型×L1：某模型在多个 L1 上同一维度失分 → 针对该模型的数据建议
    if not model_l1_df.empty and 'model' in model_l1_df.columns and '主要失分点' in model_l1_df.columns:
        for model in model_l1_df['model'].unique():
            sub = model_l1_df[model_l1_df['model'] == model]
            dim_counts = {}
            l1_by_dim = {}
            for _, row in sub.iterrows():
                main = str(row.get('主要失分点', ''))
                l1_name = str(row.get('L1', ''))
                for dim in ['D5', 'D3', 'D2', 'D4']:
                    if dim in main:
                        dim_counts[dim] = dim_counts.get(dim, 0) + 1
                        if dim not in l1_by_dim:
                            l1_by_dim[dim] = []
                        if l1_name and l1_name not in l1_by_dim[dim]:
                            l1_by_dim[dim].append(l1_name)
            if not dim_counts:
                continue
            top_dim = max(dim_counts.keys(), key=lambda x: dim_counts[x])
            if dim_counts[top_dim] >= 2:
                label = DIMENSION_LABELS.get(top_dim, top_dim)
                sug_type = dim_to_suggestion.get(top_dim, f'{top_dim}类数据')
                l1s = l1_by_dim.get(top_dim, [])[:5]
                l1_str = '、'.join(l1s) if l1s else '多个意图'
                suggestions.append(f"**模型 {model}** 在 {l1_str} 上主要在 **{label}** 失分，建议增加{sug_type}进行针对性训练。")
    # 3) 全局维度：若某维度全模型通过率普遍偏低，补充一条
    dim_pivot = (dimension_stats or {}).get('dimension_pivot_df', pd.DataFrame())
    if not dim_pivot.empty:
        rate_cols = [c for c in dim_pivot.columns if c.endswith('通过率') and c.startswith('D')]
        if rate_cols:
            global_avg = dim_pivot[rate_cols].mean()
            for col in rate_cols:
                dim = col.replace('通过率', '')
                if global_avg[col] < 75 and dim in DIMENSION_LABELS:
                    label = DIMENSION_LABELS[dim]
                    sug_type = dim_to_suggestion.get(dim, f'{dim}类数据')
                    suggestions.append(f"各模型在 **{label}** 维度通过率整体偏低，建议加强{sug_type}的构建与合成。")
                    break
    # 去重并限制条数
    seen = set()
    out = []
    for s in suggestions:
        if s not in seen and len(out) < 12:
            seen.add(s)
            out.append(s)
    return out


def generate_analysis_report(
    questions_excel: str,
    replies_excel: str,
    output_excel: str,
    human_excel: str = None,
    eval_batch_id: str = None,
    stats_only: bool = False,
    backfill_questions_excel: str = None,
    quality_thresholds: dict = None,
) -> str:
    """
    stats_only: 两套统计方案开关。False=评测统计（所有模型、source/L1/difficulty 排名、D1–D5 ILA、厂商/全景等，附专家视角 sheet）；
    True=专家统计（仅一张 sheet「专家数据质量与一致性」，无模型排名/维度分析/价值题目/案例，不触发 HTML/MD）。
    backfill_questions_excel: 若指定路径，则根据题目分析、ref 质量、人机一致性为每题生成诊断与优化建议，
    合并回题目表并写入该路径（可与 questions_excel 相同以直接更新 questions_prof 等）。
    quality_thresholds: 合格数据阈值，如 {"discrimination_min":0.25,"consistency_min":0.4,"ref_mean_min":70}，
    用于计算每题 数据合格 与专家 合格题目数（结算依据）。
    """
    print("\n" + "=" * 60)
    if stats_only:
        print("专家数据验证 - 仅统计（无案例分析/无完整报告）")
    else:
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
    model_reliability_analyzer = ModelReliabilityAnalyzer(data)
    item_analyzer = ItemAnalyzer(data)

    # 专家验证仅统计模式不需要：人机(标注员)、组内一致性、价值题目、约束类型、典型案例、难度、厂商、全景、ILA 等
    per_question_ranking = pd.DataFrame()
    rater_model_ranking = pd.DataFrame()
    rater_vs_others = pd.DataFrame()
    rater_vs_expert = pd.DataFrame()
    human_avg_vs_expert = pd.DataFrame()
    rankings = {}
    corrected_ranking_df = pd.DataFrame()
    corrected_ranking_by_l1 = pd.DataFrame()

    if stats_only:
        print("\n▶ 专家数据审核统计: 专家质量 + 各批次人机一致性（仅一张 sheet）")
        print("-" * 40)
        rankings = {}
    else:
        human_model_analyzer = HumanModelConsistencyAnalyzer(data)
        human_expert_analyzer = HumanExpertConsistencyAnalyzer(data)
        valuable_analyzer = ValuableQuestionAnalyzer(data)
        constraint_analyzer = ConstraintTypeAnalyzer(data)
        print("\n▶ 分析1: 多维度排名")
        print("-" * 40)
        rankings = ranking_analyzer.generate_all_rankings()
        rankings['ranking_自建数据'], rankings['ranking_公开数据'] = ranking_analyzer.analyze_ranking_by_source_group()
        corrected_ranking_df = expert_corrected_analyzer.analyze_corrected_ranking()
        corrected_ranking_by_l1 = expert_corrected_analyzer.analyze_corrected_ranking_by_l1()
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

    expert_hm_analyzer = ExpertHumanMachineConsistencyAnalyzer(data)
    expert_human_machine_summary, expert_human_machine_per_question = expert_hm_analyzer.analyze()

    # 题目完整分析（含区分度）需先于生产质量检验；stats_only 时仅用于专家题目区分度
    if stats_only:
        print("\n▶ 题目区分度（供专家数据质量排名）")
        print("-" * 40)
    else:
        print("\n▶ 分析6: 题目完整分析（信度/效度/区分度）")
        print("-" * 40)
    item_analysis_df = item_analyzer.analyze_all_items()

    # 数据生产环节质量检验：参考回复 + 专家数据质量排名（人机一致性 + ref 质量 + 题目区分度）
    print("   - 数据生产质量检验:")
    ref_overall, ref_per_question, ref_per_expert = analyze_reference_quality(
        data.get('replies_all', data.get('replies', pd.DataFrame())),
        data.get('expert_scores', pd.DataFrame()),
        eval_column=data.get('eval_column', 'eval_score'),
    )
    expert_discrimination = compute_expert_discrimination_stats(
        item_analysis_df, data.get('expert_scores', pd.DataFrame()))
    if not ref_overall.empty:
        print("   - 参考回复质量: ref均分={}, ref满分率={}%".format(
            ref_overall.iloc[0]['ref均分'], ref_overall.iloc[0]['ref满分率(%)']))
    if not expert_discrimination.empty:
        print("   - 专家题目区分度: {} 位专家".format(len(expert_discrimination)))
    expert_data_quality_ranking = pd.DataFrame()
    if not expert_human_machine_summary.empty or not ref_per_expert.empty or not expert_discrimination.empty:
        expert_data_quality_ranking = compute_expert_data_quality_ranking(
            expert_human_machine_summary, ref_per_expert, expert_discrimination)
        if not expert_data_quality_ranking.empty:
            print("   - 专家数据质量排名: {} 位专家".format(len(expert_data_quality_ranking)))

    # 多批次评估一致性：表中有多列 eval_* 时，计算批次间一致性及每批次可靠性
    pairwise_batch_df = pd.DataFrame()
    per_batch_reliability_df = pd.DataFrame()
    expert_model_per_batch_df = pd.DataFrame()
    try:
        replies = data.get('replies', pd.DataFrame())
        pairwise_batch_df, per_batch_reliability_df = compute_inter_batch_consistency(replies)
        if not pairwise_batch_df.empty:
            print("   - 多批次评估一致性: {} 个批次，{} 对".format(
                len(per_batch_reliability_df), len(pairwise_batch_df)))
        # 各批次人机一致性：专家打分 vs 各 eval_*，用于观察 rubrics 优化前后一致性变化
        expert_model_per_batch_df = compute_expert_model_consistency_per_batch(
            replies, data.get('expert_scores', pd.DataFrame()))
        if not expert_model_per_batch_df.empty:
            print("   - 各批次人机一致性: {} 个批次（可引导专家迭代 rubrics 或对齐评估标准）".format(
                len(expert_model_per_batch_df)))
    except Exception as e:
        print("   ⚠️ 多批次一致性计算跳过: {}".format(e))

    # 各批次综合表现（每批次模型均分/排名）+ 每位专家在各批次的人机一致性
    ranking_per_batch_df = pd.DataFrame()
    expert_per_batch_per_expert_df = pd.DataFrame()
    try:
        replies = data.get('replies', pd.DataFrame())
        ranking_per_batch_df = compute_ranking_per_batch(replies)
        if not ranking_per_batch_df.empty:
            print("   - 各批次综合表现: {} 个批次（可对比各批次模型排名）".format(ranking_per_batch_df['批次'].nunique()))
        expert_per_batch_per_expert_df = compute_expert_model_consistency_per_batch_per_expert(
            replies, data.get('expert_scores', pd.DataFrame()))
        if not expert_per_batch_per_expert_df.empty:
            print("   - 每位专家各批次人机一致性: {} 位专家 × {} 批次".format(
                expert_per_batch_per_expert_df['专家'].nunique(),
                expert_per_batch_per_expert_df['批次'].nunique()))
    except Exception as e:
        print("   ⚠️ 各批次综合表现/专家各批次一致性 跳过: {}".format(e))

    # 每题诊断、合格标记（用于反哺与专家合格题目数）
    per_q_df = compute_per_question_diagnosis_and_suggestions(
        item_analysis_df, ref_per_question, expert_human_machine_per_question
    )
    if not per_q_df.empty:
        th = quality_thresholds or {}
        per_q_df = compute_qualified_flag(
            per_q_df,
            discrimination_min=th.get('discrimination_min', 0.25),
            consistency_min=th.get('consistency_min', 0.4),
            ref_mean_min=th.get('ref_mean_min', 70.0),
        )
    qualified_count_df = pd.DataFrame()
    if not per_q_df.empty and '数据合格' in per_q_df.columns and os.path.exists(questions_excel):
        try:
            questions_df_for_count = pd.read_excel(questions_excel)
            questions_df_for_count['qid'] = questions_df_for_count['qid'].astype(str).str.strip()
            if '专家' in questions_df_for_count.columns:
                per_q_df['qid'] = per_q_df['qid'].astype(str).str.strip()
                merged = questions_df_for_count[['qid', '专家']].merge(
                    per_q_df[['qid', '数据合格']], on='qid', how='left'
                )
                qualified_count_df = merged[merged['数据合格'] == '是'].groupby('专家').size().reset_index(name='合格题目数')
        except Exception:
            pass

    # 统计反哺题目表：题目反馈写入原始表第二个 sheet「题目反馈」，第一 sheet 保持不变
    if backfill_questions_excel and os.path.exists(questions_excel) and not per_q_df.empty:
        try:
            out_path = backfill_questions_excel
            os.makedirs(os.path.dirname(os.path.abspath(out_path)) or '.', exist_ok=True)
            with pd.ExcelFile(questions_excel) as xls:
                sheet_names = xls.sheet_names
                sheets_data = {name: pd.read_excel(xls, sheet_name=name) for name in sheet_names}
            feedback_sheet = '题目反馈'
            with pd.ExcelWriter(out_path, engine='openpyxl') as writer:
                # 第1个 sheet：原始题目表
                first_name = sheet_names[0]
                sheets_data[first_name].to_excel(writer, sheet_name=first_name[:31], index=False)
                # 第2个 sheet：题目反馈
                per_q_df.to_excel(writer, sheet_name=feedback_sheet[:31], index=False)
                # 其余 sheet 保持（跳过与第1 sheet 重名或与反馈重名）
                for name in sheet_names[1:]:
                    if name == feedback_sheet:
                        continue
                    sheets_data[name].to_excel(writer, sheet_name=name[:31], index=False)
            n_qual = (per_q_df.get('数据合格') == '是').sum() if '数据合格' in per_q_df.columns else 0
            print("   - 题目表已反哺: {}（第2 sheet「{}」{} 题诊断与优化建议，{} 题数据合格）".format(
                out_path, feedback_sheet, per_q_df['qid'].nunique(), n_qual))
        except Exception as e:
            print("   ⚠️ 题目表反哺跳过: {}".format(e))

    if not stats_only:
        print("\n▶ 分析5: 价值题目TOP20")
        print("-" * 40)
        top20_questions = valuable_analyzer.find_top20_valuable_questions()

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

        # 难度等级分析：自建/公开分布 + 各模型分难度表现
        difficulty_dist_df, difficulty_mean_df, model_difficulty_df = _compute_difficulty_analysis(data)

        # 厂商排名 + 厂商系列模型均分排行
        overall_df = rankings.get('overall', pd.DataFrame())
        vendor_ranking_df = _compute_vendor_ranking(overall_df)
        vendor_series_model_df = _compute_vendor_series_model_ranking(overall_df)

        # L1×source 均分（自建vs公开在L1层面的分数差异）
        rwq = data.get('replies_with_question', pd.DataFrame())
        l1_source_mean_df = _compute_l1_source_mean_scores(rwq)

        # L1 各维度分差最大/最小题目
        l1_gap_results = _compute_l1_score_gap_questions(item_analysis_df, top_n=10)

        # 大模型多维动态约束全景总榜单
        panorama_df = _compute_panorama_ranking(data)

        # ILA 完全通过率（依赖 eval_*_raw 解析出的 full_pass）
        ila_summary = _compute_ila_summary(data.get('replies', pd.DataFrame()))
        if ila_summary:
            print(f"  ✓ ILA 完全通过率: 整体 {ila_summary['overall_pass']}/{ila_summary['overall_total']} = {ila_summary['overall_rate']}%")

    print("\n▶ 生成Excel分析报告")
    print("-" * 40)

    os.makedirs(os.path.dirname(os.path.abspath(output_excel)), exist_ok=True)

    with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
        if stats_only:
            # 专家数据审核：仅一张 sheet 集中呈现专家质量与各批次人机一致性，不做评测相关统计
            expert_block, batch_consistency, batch_reliability = _build_expert_quality_consolidated_sheet(
                expert_human_machine_summary,
                expert_data_quality_ranking,
                ref_per_expert,
                expert_discrimination,
                expert_model_per_batch_df,
                per_batch_reliability_df,
                qualified_count_df=qualified_count_df,
            )
            _write_expert_quality_single_sheet(
                writer,
                expert_block,
                batch_consistency,
                batch_reliability,
                ranking_per_batch_df=ranking_per_batch_df,
                expert_per_batch_per_expert_df=expert_per_batch_per_expert_df,
            )
        else:
            _write_panorama_sheet(writer, panorama_df)
            _write_ranking_sheets(writer, rankings, corrected_ranking_df, corrected_ranking_by_l1)
            _write_difficulty_sheet(writer, difficulty_dist_df, difficulty_mean_df, model_difficulty_df)
            _write_ila_sheet(writer, ila_summary)
            _write_human_model_sheets(writer, per_question_ranking, rater_model_ranking)
            _write_group_consistency_sheets(writer, rater_vs_others, rater_vs_expert, human_avg_vs_expert)
            _write_reliability_sheets(writer, model_expert_overall, model_expert_detail,
                                      model_ranking_summary, model_rank_comparison,
                                      expert_human_machine_summary, expert_human_machine_per_question)
            _write_production_quality_sheets(writer, ref_overall, ref_per_question, ref_per_expert,
                                             expert_discrimination, expert_data_quality_ranking)
            _write_inter_batch_sheets(writer, pairwise_batch_df, per_batch_reliability_df, expert_model_per_batch_df)
            if not top20_questions.empty:
                top20_questions.to_excel(writer, sheet_name='5_价值题目TOP20', index=False)
                print("  ✓ 已生成: 5_价值题目TOP20")
            if not item_analysis_df.empty:
                item_analysis_df.to_excel(writer, sheet_name='6_题目完整分析', index=False)
                print("  ✓ 已生成: 6_题目完整分析")
            l1_high_distinction_df = _compute_l1_high_distinction_stats(item_analysis_df)
            if not l1_high_distinction_df.empty:
                l1_high_distinction_df.to_excel(writer, sheet_name='6_L1高区分度题目统计', index=False)
                print("  ✓ 已生成: 6_L1高区分度题目统计")
            if not constraint_type_df.empty:
                constraint_type_df.to_excel(writer, sheet_name='7_约束类型分析', index=False)
                print("  ✓ 已生成: 7_约束类型分析")
            if not typical_cases_df.empty:
                typical_cases_df.to_excel(writer, sheet_name='8_典型案例', index=False)
                print("  ✓ 已生成: 8_典型案例")
            _write_vendor_model_table_sheet(writer)
            _write_vendor_and_l1_sheets(
                writer,
                vendor_ranking_df=vendor_ranking_df,
                vendor_series_model_df=vendor_series_model_df,
                l1_source_mean_df=l1_source_mean_df,
                l1_gap_results=l1_gap_results,
            )
            _write_human_verification_sheets(writer, human_verification_results)
            metric_defs = generate_metric_definitions()
            metric_defs.to_excel(writer, sheet_name='指标定义说明', index=False)
            print("  ✓ 已生成: 指标定义说明")

        sheet_count = len(writer.sheets)

    if not stats_only:
        _print_summary(rankings, corrected_ranking_df, rater_vs_others, model_ranking_summary,
                       top20_questions, item_analysis_df)

    if stats_only:
        print(f"\n✓ 专家验证统计完成（未生成案例分析与完整报告）")
    else:
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


def _write_panorama_sheet(writer: pd.ExcelWriter, panorama_df: pd.DataFrame):
    """写入大模型多维动态约束全景总榜单，作为第一个 sheet。"""
    if panorama_df.empty:
        return
    sheet_name = '0_全景总榜单'
    pd.DataFrame([['【大模型多维动态约束全景总榜单】主分数=连坐加权分；连坐：D1/D2任一Fail则该题0分；梯队由 PANORAMA_TIER_CONFIG 配置']]).to_excel(
        writer, sheet_name=sheet_name, startrow=0, index=False, header=False
    )
    # 列名中英对照
    rename_map = {
        'Rank': '综合排名',
        'Provider': '厂商',
        'Model_Name': '模型名称',
        'Main_Score': '主分数',
        'CLA_Score': '普通约束得分(CLA)',
        'ILA_Rate': '严格完全通过率(ILA)',
        'Public_Score': '公开数据均分',
        'Private_Score': '核心自建均分',
        'Score_Gap': '公私域落差',
        'Tier': '梯队评级',
    }
    out_df = panorama_df.rename(columns={k: v for k, v in rename_map.items() if k in panorama_df.columns})
    out_df.to_excel(writer, sheet_name=sheet_name, startrow=2, index=False)
    print("  ✓ 已生成: 0_全景总榜单")


def _write_ranking_sheets(
    writer: pd.ExcelWriter,
    rankings: dict,
    corrected_ranking_df: pd.DataFrame,
    corrected_ranking_by_l1: dict = None,
):
    sheet_name = '1_多维度排名'
    start_row = 0

    ordered_keys = [
        'overall', 'ranking_自建数据', 'ranking_公开数据',
        'l1', 'l2', 'l3', 'source', 'difficulty', 'significance',
    ]
    labels = {
        'overall': '【整体表现排名】',
        'ranking_自建数据': '【自建数据排名】',
        'ranking_公开数据': '【公开数据排名】',
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

    # L1 级别专家纠偏排名：每个 L1 意图类型一组排名
    if corrected_ranking_by_l1:
        start_row = 0
        sheet_name = '1_L1专家纠偏排名'
        for l1, df in corrected_ranking_by_l1.items():
            pd.DataFrame([[f'【{l1}】']]).to_excel(
                writer, sheet_name=sheet_name, startrow=start_row, index=False, header=False
            )
            start_row += 1
            df.to_excel(writer, sheet_name=sheet_name, startrow=start_row, index=False)
            start_row += len(df) + 3
        print("  ✓ 已生成: 1_L1专家纠偏排名")

    expert_only_df = rankings.get('expert_only')
    if expert_only_df is not None and not expert_only_df.empty:
        expert_only_df.to_excel(writer, sheet_name='1_专家评测榜单', index=False)
        print("  ✓ 已生成: 1_专家评测榜单（仅统计有专家打分的题目）")


def _write_difficulty_sheet(
    writer: pd.ExcelWriter,
    difficulty_dist_df: pd.DataFrame,
    difficulty_mean_df: pd.DataFrame,
    model_difficulty_df: pd.DataFrame,
):
    """写入难度等级分析：1) source×难度 题目分布  2) source×难度 难度均分  3) 各模型分难度得分及分差"""
    if difficulty_dist_df.empty and difficulty_mean_df.empty and model_difficulty_df.empty:
        return
    sheet_name = '1_难度等级分析'
    start_row = 0
    if not difficulty_dist_df.empty:
        pd.DataFrame([['【source八值×难度等级 题目分布】列=source，行=难度等级，单元格=题目数']]).to_excel(
            writer, sheet_name=sheet_name, startrow=start_row, index=False, header=False
        )
        start_row += 1
        difficulty_dist_df.to_excel(writer, sheet_name=sheet_name, startrow=start_row, index=False)
        start_row += len(difficulty_dist_df) + 3
    if not difficulty_mean_df.empty:
        pd.DataFrame([['【source八值×难度等级 难度均分】列=source，行=难度等级，单元格=对应题目类型的difficulty_score均值']]).to_excel(
            writer, sheet_name=sheet_name, startrow=start_row, index=False, header=False
        )
        start_row += 1
        difficulty_mean_df.to_excel(writer, sheet_name=sheet_name, startrow=start_row, index=False)
        start_row += len(difficulty_mean_df) + 3
    if not model_difficulty_df.empty:
        pd.DataFrame([['【各模型×难度等级 得分及分差】分差=易题均分-难题均分，反映模型在难题上的下滑幅度']]).to_excel(
            writer, sheet_name=sheet_name, startrow=start_row, index=False, header=False
        )
        start_row += 1
        model_difficulty_df.to_excel(writer, sheet_name=sheet_name, startrow=start_row, index=False)
    print("  ✓ 已生成: 1_难度等级分析")


def _write_ila_sheet(writer: pd.ExcelWriter, ila_summary: dict):
    """写入完全通过率 ILA 表及 D1–D5 各维度 ILA 通过率（仅当有 full_pass 数据时）。"""
    if not ila_summary:
        return
    df = ila_summary.get('per_model_df')
    if df is None or df.empty:
        return
    sheet_name = '1_完全通过率ILA'
    start_row = 0
    pd.DataFrame([['【整体 ILA】各模型完全通过率（全部检查点 PASS 的题目占比）']]).to_excel(
        writer, sheet_name=sheet_name, startrow=start_row, index=False, header=False
    )
    start_row += 1
    df.to_excel(writer, sheet_name=sheet_name, startrow=start_row, index=False)
    start_row += len(df) + 2

    dim_df = ila_summary.get('dimension_ila_df')
    if dim_df is not None and not dim_df.empty:
        pd.DataFrame([['【D1–D5 各维度 ILA 通过率】该维度下全部检查点 PASS 的比例，便于分析模型在哪些维度易出问题']]).to_excel(
            writer, sheet_name=sheet_name, startrow=start_row, index=False, header=False
        )
        start_row += 1
        dim_df.to_excel(writer, sheet_name=sheet_name, startrow=start_row, index=False)
    print("  ✓ 已生成: 1_完全通过率ILA")


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
                               model_rank_comparison: pd.DataFrame,
                               expert_human_machine_summary: pd.DataFrame = None,
                               expert_human_machine_per_question: pd.DataFrame = None):
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
    # 专家人机一致性反馈：每题人机一致性 + 专家综合人机一致性（供专家 rubrics 质量参考）
    if expert_human_machine_summary is not None and not expert_human_machine_summary.empty:
        expert_human_machine_summary.to_excel(writer, sheet_name='4_专家人机一致性反馈', index=False)
        print("  ✓ 已生成: 4_专家人机一致性反馈")
    if expert_human_machine_per_question is not None and not expert_human_machine_per_question.empty:
        expert_human_machine_per_question.to_excel(writer, sheet_name='4_专家每题人机一致性', index=False)
        print("  ✓ 已生成: 4_专家每题人机一致性")


def _write_production_quality_sheets(
    writer: pd.ExcelWriter,
    ref_overall: pd.DataFrame,
    ref_per_question: pd.DataFrame,
    ref_per_expert: pd.DataFrame,
    expert_discrimination: pd.DataFrame,
    expert_data_quality_ranking: pd.DataFrame,
):
    """数据生产环节质量检验：ref 质量 + 专家数据质量排名。"""
    if not ref_overall.empty:
        ref_overall.to_excel(writer, sheet_name='4_参考回复质量', index=False)
        print("  ✓ 已生成: 4_参考回复质量")
    if not ref_per_question.empty:
        ref_per_question.to_excel(writer, sheet_name='4_每题参考回复得分', index=False)
        print("  ✓ 已生成: 4_每题参考回复得分")
    if not ref_per_expert.empty:
        ref_per_expert.to_excel(writer, sheet_name='4_专家参考回复质量', index=False)
        print("  ✓ 已生成: 4_专家参考回复质量")
    if expert_discrimination is not None and not expert_discrimination.empty:
        expert_discrimination.to_excel(writer, sheet_name='4_专家题目区分度', index=False)
        print("  ✓ 已生成: 4_专家题目区分度")
    if not expert_data_quality_ranking.empty:
        expert_data_quality_ranking.to_excel(writer, sheet_name='4_专家数据质量排名', index=False)
        print("  ✓ 已生成: 4_专家数据质量排名")


def _expert_stats_check_summary(expert_block: pd.DataFrame) -> pd.DataFrame:
    """统计检查说明：有效人机对数=同时有专家打分与模型分的条数，≥3 才计算 ICC；专家评估数>有效人机对数说明部分行未跑裁判。"""
    if expert_block.empty or '专家' not in expert_block.columns:
        return pd.DataFrame()
    n_exp = pd.to_numeric(expert_block.get('专家评估数', 0), errors='coerce').fillna(0).astype(int)
    n_pairs = pd.to_numeric(expert_block.get('有效人机对数', np.nan), errors='coerce')
    has_icc = pd.to_numeric(expert_block.get('人机一致性_ICC', np.nan), errors='coerce').notna()
    no_icc_names = expert_block.loc[~has_icc, '专家'].astype(str).tolist()
    uneval = (n_exp >= 3) & ((n_pairs.isna()) | (n_pairs < 3)) & ~has_icc
    uneval_names = expert_block.loc[uneval, '专家'].astype(str).tolist()
    lines = [['【统计检查】有效人机对数 = 同时有专家打分与模型评估分数的条数，≥3 才计算 ICC。若专家评估数>有效人机对数，说明部分回复未跑裁判。']]
    if no_icc_names:
        lines.append([f"无 ICC 的专家：{', '.join(no_icc_names)}"])
    if uneval_names:
        lines.append([f"专家评估数≥3 但有效人机对<3（请确认 ref/reply1/reply2 已注入且已跑裁判）：{', '.join(uneval_names)}"])
    if len(lines) == 1:
        lines.append(['未发现异常。'])
    return pd.DataFrame(lines)


def _write_expert_quality_single_sheet(
    writer: pd.ExcelWriter,
    expert_block: pd.DataFrame,
    batch_consistency: pd.DataFrame,
    batch_reliability: pd.DataFrame,
    ranking_per_batch_df: pd.DataFrame = None,
    expert_per_batch_per_expert_df: pd.DataFrame = None,
):
    """专家数据审核：一张 sheet 内分块呈现——统计检查、专家数据质量、各批次人机一致性、多批次评估可靠性、各批次综合表现、每位专家各批次人机一致性。"""
    sheet_name = '专家数据质量与一致性'
    row = 0
    if not expert_block.empty:
        # 先写统计检查摘要（部分人没有分数、数量对不上时可直接看出）
        stats_df = _expert_stats_check_summary(expert_block)
        if not stats_df.empty:
            stats_df.to_excel(writer, sheet_name=sheet_name, index=False, header=False, startrow=row)
            row += len(stats_df) + 1
        pd.DataFrame([['【专家数据质量】每位专家的人机一致性、ref 质量、题目区分度、综合排名及诊断与优化建议']]).to_excel(
            writer, sheet_name=sheet_name, index=False, header=False, startrow=row
        )
        row += 1
        expert_block.to_excel(writer, sheet_name=sheet_name, index=False, startrow=row)
        row += len(expert_block) + 2
    if batch_consistency is not None and not batch_consistency.empty:
        pd.DataFrame([['【各批次人机一致性】专家打分 vs 各评估批次，用于观察 rubrics 优化前后变化']]).to_excel(
            writer, sheet_name=sheet_name, index=False, header=False, startrow=row
        )
        row += 1
        batch_consistency.to_excel(writer, sheet_name=sheet_name, index=False, startrow=row)
        row += len(batch_consistency) + 2
    if batch_reliability is not None and not batch_reliability.empty:
        pd.DataFrame([['【多批次评估可靠性】各批次与其它批次平均一致性，可靠性排名越高越稳定']]).to_excel(
            writer, sheet_name=sheet_name, index=False, header=False, startrow=row
        )
        row += 1
        batch_reliability.to_excel(writer, sheet_name=sheet_name, index=False, startrow=row)
        row += len(batch_reliability) + 2
    if ranking_per_batch_df is not None and not ranking_per_batch_df.empty:
        pd.DataFrame([['【各批次综合表现】每个评估批次的模型均分与排名，便于对比各批次间模型表现变化']]).to_excel(
            writer, sheet_name=sheet_name, index=False, header=False, startrow=row
        )
        row += 1
        ranking_per_batch_df.to_excel(writer, sheet_name=sheet_name, index=False, startrow=row)
        row += len(ranking_per_batch_df) + 2
    if expert_per_batch_per_expert_df is not None and not expert_per_batch_per_expert_df.empty:
        pd.DataFrame([['【每位专家各批次人机一致性】每位专家在每个评估批次上与裁判模型的一致性，便于对比个人在各批次表现']]).to_excel(
            writer, sheet_name=sheet_name, index=False, header=False, startrow=row
        )
        row += 1
        expert_per_batch_per_expert_df.to_excel(writer, sheet_name=sheet_name, index=False, startrow=row)
    any_block = (
        not expert_block.empty
        or (batch_consistency is not None and not batch_consistency.empty)
        or (batch_reliability is not None and not batch_reliability.empty)
        or (ranking_per_batch_df is not None and not ranking_per_batch_df.empty)
        or (expert_per_batch_per_expert_df is not None and not expert_per_batch_per_expert_df.empty)
    )
    if any_block:
        print("  ✓ 已生成: 专家数据质量与一致性（专家表现 + 各批次一致性 + 可靠性 + 各批次综合表现 + 专家各批次表现）")


def _write_inter_batch_sheets(
    writer: pd.ExcelWriter,
    pairwise_batch_df: pd.DataFrame,
    per_batch_reliability_df: pd.DataFrame,
    expert_model_per_batch_df: pd.DataFrame = None,
):
    """多批次评估：两两一致性表 + 每批次可靠性排名 + 各批次人机一致性（rubrics 优化验证）。"""
    if not pairwise_batch_df.empty:
        pairwise_batch_df.to_excel(writer, sheet_name='4_多批次评估两两一致性', index=False)
        print("  ✓ 已生成: 4_多批次评估两两一致性")
    if not per_batch_reliability_df.empty:
        per_batch_reliability_df.to_excel(writer, sheet_name='4_多批次评估可靠性排名', index=False)
        print("  ✓ 已生成: 4_多批次评估可靠性排名")
    if expert_model_per_batch_df is not None and not expert_model_per_batch_df.empty:
        expert_model_per_batch_df.to_excel(writer, sheet_name='4_各批次人机一致性', index=False)
        print("  ✓ 已生成: 4_各批次人机一致性（rubrics 优化验证：可观察每批次人机一致性变化，引导迭代）")


def _write_vendor_model_table_sheet(writer: pd.ExcelWriter):
    """写入厂商模型对照表：厂商、厂商性质、标准命名、原始评测录入名"""
    df = get_vendor_model_table_df()
    if df.empty:
        return
    sheet_name = '0_厂商模型对照表'
    pd.DataFrame([['【厂商与模型对照表】用于厂商统计视角，原始评测录入名对应 replies 表中的 model 列']]).to_excel(
        writer, sheet_name=sheet_name, startrow=0, index=False, header=False
    )
    df.to_excel(writer, sheet_name=sheet_name, startrow=2, index=False)
    print("  ✓ 已生成: 0_厂商模型对照表")


def _write_vendor_and_l1_sheets(
    writer: pd.ExcelWriter,
    vendor_ranking_df: pd.DataFrame,
    vendor_series_model_df: pd.DataFrame,
    l1_source_mean_df: pd.DataFrame,
    l1_gap_results: dict,
):
    """写入厂商排名、厂商系列模型排行、L1×source均分、L1分差题目统计"""
    has_data = (
        not vendor_ranking_df.empty
        or not vendor_series_model_df.empty
        or not l1_source_mean_df.empty
        or bool(l1_gap_results and (l1_gap_results.get('summary') is not None or l1_gap_results.get('gap_max') or l1_gap_results.get('gap_min')))
    )
    if not has_data:
        return
    sheet_name = '1_厂商与L1分析'
    start_row = 0

    if not vendor_ranking_df.empty:
        pd.DataFrame([['【厂商排名】每厂商选取最强模型参与评分，按均分降序']]).to_excel(
            writer, sheet_name=sheet_name, startrow=start_row, index=False, header=False
        )
        start_row += 1
        vendor_ranking_df.to_excel(writer, sheet_name=sheet_name, startrow=start_row, index=False)
        start_row += len(vendor_ranking_df) + 3
        print("  ✓ 已生成: 1_厂商与L1分析 - 厂商排名")

    if not vendor_series_model_df.empty:
        pd.DataFrame([['【厂商系列模型均分排行】便于绘制柱状图：横轴=模型，纵轴=均分']]).to_excel(
            writer, sheet_name=sheet_name, startrow=start_row, index=False, header=False
        )
        start_row += 1
        vendor_series_model_df.to_excel(writer, sheet_name=sheet_name, startrow=start_row, index=False)
        start_row += len(vendor_series_model_df) + 3
        print("  ✓ 已生成: 1_厂商与L1分析 - 厂商系列模型排行")

    if not l1_source_mean_df.empty:
        pd.DataFrame([['【L1×数据来源 均分】纵轴=L1，横轴=source，不区分模型，自建vs公开在L1层面的分数差异']]).to_excel(
            writer, sheet_name=sheet_name, startrow=start_row, index=False, header=False
        )
        start_row += 1
        l1_source_mean_df.to_excel(writer, sheet_name=sheet_name, startrow=start_row, index=False)
        start_row += len(l1_source_mean_df) + 3
        print("  ✓ 已生成: 1_厂商与L1分析 - L1×source均分")

    if l1_gap_results:
        summary = l1_gap_results.get('summary')
        if summary is not None and not summary.empty:
            pd.DataFrame([['【L1各维度分差概览】分差=该题最高分-最低分，反映模型表现差异；各L1下分差最大/最小题目见后续块']]).to_excel(
                writer, sheet_name=sheet_name, startrow=start_row, index=False, header=False
            )
            start_row += 1
            summary.to_excel(writer, sheet_name=sheet_name, startrow=start_row, index=False)
            start_row += len(summary) + 2
        gap_max = l1_gap_results.get('gap_max') or {}
        gap_min = l1_gap_results.get('gap_min') or {}
        for l1 in sorted(set(list(gap_max.keys()) + list(gap_min.keys()))):
            if l1 in gap_max and not gap_max[l1].empty:
                pd.DataFrame([[f'【{l1} 分差最大题目 TOP10】']]).to_excel(
                    writer, sheet_name=sheet_name, startrow=start_row, index=False, header=False
                )
                start_row += 1
                gap_max[l1].to_excel(writer, sheet_name=sheet_name, startrow=start_row, index=False)
                start_row += len(gap_max[l1]) + 2
            if l1 in gap_min and not gap_min[l1].empty:
                pd.DataFrame([[f'【{l1} 分差最小题目 TOP10】']]).to_excel(
                    writer, sheet_name=sheet_name, startrow=start_row, index=False, header=False
                )
                start_row += 1
                gap_min[l1].to_excel(writer, sheet_name=sheet_name, startrow=start_row, index=False)
                start_row += len(gap_min[l1]) + 2
        if gap_max or gap_min:
            print("  ✓ 已生成: 1_厂商与L1分析 - L1分差最大/最小题目")


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

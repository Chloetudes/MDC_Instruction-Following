# -*- coding: utf-8 -*-
"""
数据生产环节质量检验：参考回复得分、专家数据质量排名。
用于 prof 等专家出题批次的专家反馈，评估 rubrics 自洽性与数据合格度。
"""
import numpy as np
import pandas as pd


REF_MODEL_PATTERN = 'ref'


def _is_ref_model(model_val) -> bool:
    return str(model_val).strip().lower() == REF_MODEL_PATTERN


def analyze_reference_quality(
    replies: pd.DataFrame,
    expert_scores: pd.DataFrame,
    eval_column: str = 'eval_score',
) -> tuple:
    """
    参考回复（model='ref'）质量分析：用专家 rubrics 评估参考回复，理想应接近满分。
    Returns:
        ref_overall: 整体统计（ref数量、均分、满分率）
        ref_per_question: 每题 ref 得分
        ref_per_expert: 每位专家的 ref 均分、满分率（需能从 qid 映射到专家）
    """
    if replies.empty or eval_column not in replies.columns:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    ref_mask = replies['model'].astype(str).str.strip().str.lower() == REF_MODEL_PATTERN
    ref_df = replies.loc[ref_mask].dropna(subset=[eval_column]).copy()

    if ref_df.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    ref_df['eval_score'] = pd.to_numeric(ref_df[eval_column], errors='coerce')
    ref_df = ref_df[ref_df['eval_score'].notna()]
    if ref_df.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    # 整体
    n = len(ref_df)
    mean_score = float(ref_df['eval_score'].mean())
    full_mark_count = int((ref_df['eval_score'] >= 100).sum())
    full_mark_rate = round(full_mark_count / n * 100, 1) if n > 0 else 0
    ref_overall = pd.DataFrame([{
        'ref数量': n,
        'ref均分': round(mean_score, 2),
        'ref满分数': full_mark_count,
        'ref满分率(%)': full_mark_rate,
    }])

    # 每题
    per_q = ref_df.groupby('qid').agg(
        ref均分=('eval_score', lambda x: round(float(x.mean()), 2)),
        ref数=('eval_score', 'count'),
        ref满分=('eval_score', lambda x: (x >= 100).all()),
    ).reset_index()
    ref_per_question = per_q

    # 按专家（qid -> expert 来自 expert_scores，每 qid 对应一个专家）
    ref_per_expert = pd.DataFrame()
    if not expert_scores.empty and 'rater' in expert_scores.columns:
        qid_to_expert = expert_scores.drop_duplicates('qid').set_index('qid')['rater'].to_dict()
        ref_df = ref_df.copy()
        ref_df['专家'] = ref_df['qid'].astype(str).map(qid_to_expert)
        ref_df = ref_df[ref_df['专家'].notna()]
        if not ref_df.empty:
            agg = ref_df.groupby('专家').agg(
                题目数=('qid', 'nunique'),
                ref均分=('eval_score', lambda x: round(float(x.mean()), 2)),
                ref满分数=('eval_score', lambda x: int((x >= 100).sum())),
                ref总数=('eval_score', 'count'),
            ).reset_index()
            agg['ref满分率(%)'] = (agg['ref满分数'] / agg['ref总数'] * 100).round(1)
            ref_per_expert = agg[['专家', '题目数', 'ref均分', 'ref满分数', 'ref总数', 'ref满分率(%)']]

    return ref_overall, ref_per_question, ref_per_expert


def compute_expert_discrimination_stats(
    item_analysis_df: pd.DataFrame,
    expert_scores: pd.DataFrame,
) -> pd.DataFrame:
    """
    按专家聚合题目区分度：分数区间越大、区分度指数越高，说明专家出题能有效区分模型能力。
    """
    if item_analysis_df.empty or expert_scores.empty or 'rater' not in expert_scores.columns:
        return pd.DataFrame()
    disc_col = '区分度指数_D'
    if disc_col not in item_analysis_df.columns:
        return pd.DataFrame()
    qid_to_expert = expert_scores.drop_duplicates('qid').set_index('qid')['rater'].to_dict()
    items = item_analysis_df.copy()
    items['专家'] = items['qid'].astype(str).map(qid_to_expert)
    items = items[items['专家'].notna()]
    if items.empty:
        return pd.DataFrame()
    disc_num = pd.to_numeric(items[disc_col], errors='coerce').fillna(0)
    items['_disc'] = disc_num
    agg = items.groupby('专家').agg(
        题目数=('qid', 'nunique'),
        平均区分度=('_disc', lambda x: round(float(x.mean()), 3)),
        分数范围均值=('分数范围', lambda x: round(float(pd.to_numeric(x, errors='coerce').mean()), 1)),
        高区分度题目数=('_disc', lambda x: int((x >= 0.3).sum())),
    ).reset_index()
    agg['高区分度占比(%)'] = (agg['高区分度题目数'] / agg['题目数'] * 100).round(1)
    return agg


def compute_expert_data_quality_ranking(
    expert_human_machine_summary: pd.DataFrame,
    ref_per_expert: pd.DataFrame,
    expert_discrimination: pd.DataFrame = None,
    weight_consistency: float = 0.4,
    weight_ref_mean: float = 0.2,
    weight_ref_full_rate: float = 0.2,
    weight_discrimination: float = 0.2,
) -> pd.DataFrame:
    """
    综合专家数据质量排名：人机一致性 + ref 质量 + 题目区分度。
    人机一致性高=rubrics可执行，ref质量好=自洽，区分度高=出题能区分模型能力。
    """
    if expert_human_machine_summary.empty and ref_per_expert.empty and (expert_discrimination is None or expert_discrimination.empty):
        return pd.DataFrame()

    # 以专家为 key 合并
    merged = pd.DataFrame()
    if not expert_human_machine_summary.empty:
        hm = expert_human_machine_summary.copy()
        hm['专家'] = hm['专家'].astype(str)
        consistency_col = '每题人机一致性_斯皮尔曼均值'
        if consistency_col not in hm.columns:
            consistency_col = '综合人机一致性_斯皮尔曼'
        hm['_consistency'] = pd.to_numeric(hm[consistency_col], errors='coerce').fillna(0)
        merged = hm[['专家', '_consistency']].drop_duplicates('专家')
    if merged.empty:
        if not ref_per_expert.empty:
            merged = ref_per_expert.copy()
            merged['_consistency'] = 0.0
            merged['_ref_mean_norm'] = merged['ref均分'].clip(0, 100) / 100
            merged['_ref_full_rate_norm'] = merged['ref满分率(%)'].clip(0, 100) / 100
        elif expert_discrimination is not None and not expert_discrimination.empty:
            merged = expert_discrimination[['专家']].drop_duplicates().copy()
            merged['_consistency'] = 0.0
            merged['_ref_mean_norm'] = 0.0
            merged['_ref_full_rate_norm'] = 0.0
            merged['ref均分'] = np.nan
            merged['ref满分率(%)'] = np.nan
    elif not ref_per_expert.empty and not merged.empty:
        ref = ref_per_expert.copy()
        ref['专家'] = ref['专家'].astype(str)
        ref['_ref_mean_norm'] = ref['ref均分'].clip(0, 100) / 100
        ref['_ref_full_rate_norm'] = ref['ref满分率(%)'].clip(0, 100) / 100
        merged = merged.merge(
            ref[['专家', '_ref_mean_norm', '_ref_full_rate_norm', 'ref均分', 'ref满分率(%)']],
            on='专家', how='outer'
        )
    if merged.empty:
        return pd.DataFrame()
    if '_ref_mean_norm' not in merged.columns:
        merged['_ref_mean_norm'] = 0.0
    if '_ref_full_rate_norm' not in merged.columns:
        merged['_ref_full_rate_norm'] = 0.0
    if 'ref均分' not in merged.columns:
        merged['ref均分'] = np.nan
    if 'ref满分率(%)' not in merged.columns:
        merged['ref满分率(%)'] = np.nan
    merged['_ref_mean_norm'] = merged['_ref_mean_norm'].fillna(0)
    merged['_ref_full_rate_norm'] = merged['_ref_full_rate_norm'].fillna(0)
    merged['_consistency'] = merged['_consistency'].fillna(0) if '_consistency' in merged.columns else 0.0
    if expert_discrimination is not None and not expert_discrimination.empty:
        disc = expert_discrimination.copy()
        disc['专家'] = disc['专家'].astype(str)
        disc['_disc_norm'] = disc['平均区分度'].clip(0, 1)
        merged = merged.merge(disc[['专家', '_disc_norm', '平均区分度', '高区分度题目数']], on='专家', how='outer')
    merged['_disc_norm'] = merged['_disc_norm'].fillna(0) if '_disc_norm' in merged.columns else 0.0
    if '平均区分度' not in merged.columns:
        merged['平均区分度'] = np.nan
    merged['高区分度题目数'] = merged['高区分度题目数'].fillna(0) if '高区分度题目数' in merged.columns else 0
    merged = merged.drop_duplicates(subset=['专家'], keep='first')
    w_c, w_m, w_f, w_d = weight_consistency, weight_ref_mean, weight_ref_full_rate, weight_discrimination
    merged['数据质量得分'] = (
        merged['_consistency'] * w_c +
        merged['_ref_mean_norm'] * w_m +
        merged['_ref_full_rate_norm'] * w_f +
        merged['_disc_norm'] * w_d
    ).round(3)
    merged = merged.sort_values('数据质量得分', ascending=False).reset_index(drop=True)
    merged.insert(0, '数据质量排名', merged.index + 1)
    merged['数据质量等级'] = pd.cut(
        merged['数据质量得分'],
        bins=[0, 0.4, 0.6, 0.8, 1.0],
        labels=['待提升', '合格', '良好', '优秀'],
        include_lowest=True
    )
    out_cols = ['数据质量排名', '专家', '数据质量得分', '数据质量等级',
                '_consistency', 'ref均分', 'ref满分率(%)', '平均区分度', '高区分度题目数']
    out_cols = [c for c in out_cols if c in merged.columns]
    out = merged[out_cols].copy()
    out = out.rename(columns={'_consistency': '人机一致性_斯皮尔曼'})
    return out


# 区分度/ref满分率 阈值：用于诊断 rubrics 宽松 vs 有效
DISC_HIGH = 0.30
DISC_LOW = 0.25
REF_FULL_RATE_HIGH = 50.0
REF_FULL_RATE_LOOSE = 40.0
REF_MEAN_LOW = 70.0
REF_MEAN_STRICT_OK = 85.0
CONSISTENCY_MIN_GOOD = 0.4
EFFECTIVENESS_EPS = 0.05


def compute_expert_diagnosis_and_suggestions(expert_ranking_df: pd.DataFrame) -> pd.DataFrame:
    """
    基于专家数据质量表，计算 Rubrics 有效性指数，并给出诊断与可执行的优化建议。
    用于检测每人数据质量并引导修改题目/rubrics/评估标准。

    输入表需含列：专家, ref均分, ref满分率(%), 平均区分度, 人机一致性_斯皮尔曼；
    若有 评估题目数 则用于判断「无评估数据」。

    Returns:
        DataFrame: 专家, Rubrics有效性指数, 诊断, 优化建议
    """
    if expert_ranking_df is None or expert_ranking_df.empty or '专家' not in expert_ranking_df.columns:
        return pd.DataFrame()

    need = ['ref均分', 'ref满分率(%)', '平均区分度', '人机一致性_斯皮尔曼']
    missing = [c for c in need if c not in expert_ranking_df.columns]
    if missing:
        return pd.DataFrame()

    df = expert_ranking_df.copy()
    df['专家'] = df['专家'].astype(str)
    ref_mean = pd.to_numeric(df['ref均分'], errors='coerce')
    ref_rate = pd.to_numeric(df['ref满分率(%)'], errors='coerce').fillna(0)
    disc = pd.to_numeric(df['平均区分度'], errors='coerce').fillna(0)
    consistency = pd.to_numeric(df['人机一致性_斯皮尔曼'], errors='coerce').fillna(-1)
    n_tasks = df.get('评估题目数')
    if n_tasks is not None:
        n_tasks = pd.to_numeric(n_tasks, errors='coerce').fillna(0)
    else:
        n_tasks = pd.Series(1, index=df.index)

    # Rubrics 有效性指数 = 区分度 / (ref满分率/100 + ε)；ref满分率=0 时用 — 或按区分度体现“严”
    eff_raw = disc / (ref_rate / 100.0 + EFFECTIVENESS_EPS)
    eff_cap = eff_raw.clip(upper=2.0).round(3)
    effectiveness = eff_cap.where(ref_rate > 0, np.nan)
    df['Rubrics有效性指数'] = effectiveness.apply(lambda x: round(x, 3) if not np.isnan(x) else '—')

    diagnosis = []
    suggestions = []

    for i in range(len(df)):
        r_mean = ref_mean.iloc[i] if i < len(ref_mean) else np.nan
        r_rate = ref_rate.iloc[i] if i < len(ref_rate) else 0.0
        d = disc.iloc[i] if i < len(disc) else 0.0
        c = consistency.iloc[i] if i < len(consistency) else -1.0
        n = n_tasks.iloc[i] if i < len(n_tasks) else 1

        diag = ''
        sug = ''

        # 1. 无评估数据
        if n == 0 and (pd.isna(r_mean) or (r_mean == 0 and r_rate == 0)):
            diag = '无评估数据'
            sug = '请补充题目的人机评估数据后再查看质量报告。'
        # 2. 人机严重偏离
        elif c < 0:
            diag = '人机严重偏离'
            sug = '专家打分与模型打分呈负相关，请检查评分标准是否与模型理解一致，或补充校准题训练。'
        # 3. 优质：ref 高 + 区分度高 + 人机好
        elif r_rate >= REF_FULL_RATE_HIGH and d >= DISC_HIGH and c >= CONSISTENCY_MIN_GOOD:
            diag = '优质'
            sug = '当前 rubrics 与 reference 质量良好，区分度与自洽性兼顾，可作标杆。'
        # 4. 宽松放水：ref 满分率高但区分度低
        elif r_rate >= REF_FULL_RATE_LOOSE and d < DISC_LOW:
            diag = 'rubrics偏宽松'
            sug = 'ref 得分高但题目区分度低。建议：①在 rubrics 中增加至少2条「一票否决」项（触发则不超过60分）；②每个维度描述高/中/低三档，明确「差回复」的给分标准；③用明显差回复自测，若得分>70需收紧标准。'
        # 5. reference 质量差
        elif not pd.isna(r_mean) and r_mean < REF_MEAN_LOW:
            diag = 'reference或标准需检查'
            sug = 'reference 得分偏低。建议：①检查 reference 是否真正满足 rubrics 满分描述；②若标准过严，补充中档与低档描述；③必要时重写 reference 或重对 rubrics。'
        # 6. ref 满分率为 0：过严或 ref 与标准不符
        elif r_rate == 0 and not pd.isna(r_mean) and r_mean >= REF_MEAN_STRICT_OK and d >= DISC_LOW:
            diag = '标准过严或ref与标准不符'
            sug = 'ref 均分高但满分率为0。建议：①核对 ref 与 rubrics 满分条款逐条对照；②适当补充「何种情况给满分」的正面描述。'
        elif r_rate == 0 and (pd.isna(r_mean) or r_mean < REF_MEAN_STRICT_OK):
            diag = 'reference或标准需检查'
            sug = 'ref 满分率为0且均分不高。建议：检查 reference 质量与 rubrics 的匹配度，必要时重写 ref 或细化标准。'
        # 7. 可优化
        else:
            diag = '可优化'
            sug = '建议：提升人机一致性（细化 rubrics 可执行描述）、保证 ref 自洽、并提高题目区分度（增加分档与否决项）。'

        diagnosis.append(diag)
        suggestions.append(sug)

    df['诊断'] = diagnosis
    df['优化建议'] = suggestions
    return df[['专家', 'Rubrics有效性指数', '诊断', '优化建议']]


# 每题诊断阈值（题目级别）
ITEM_DISC_HIGH = 0.30
ITEM_DISC_LOW = 0.20
ITEM_REF_MEAN_LOW = 70.0
ITEM_REF_MEAN_GOOD = 85.0
ITEM_CONSISTENCY_GOOD = 0.5
ITEM_CONSISTENCY_MIN = 0.2


def compute_per_question_diagnosis_and_suggestions(
    item_analysis_df: pd.DataFrame,
    ref_per_question: pd.DataFrame,
    expert_human_machine_per_question: pd.DataFrame,
) -> pd.DataFrame:
    """
    基于题目分析、每题 ref 质量、每题人机一致性，为每道题生成诊断与优化建议，
    用于反哺到 questions 表（如 questions_prof.xlsx），引导专家检查 rubrics、细化考点、检查 reference。

    Returns:
        DataFrame: qid, 题目诊断, 题目优化建议 [, 区分度指数_D, ref均分, 人机一致性_斯皮尔曼, 人机一致性_ICC ]
    """
    all_qids = set()
    if not item_analysis_df.empty and 'qid' in item_analysis_df.columns:
        all_qids.update(item_analysis_df['qid'].astype(str).str.strip().tolist())
    if not ref_per_question.empty and 'qid' in ref_per_question.columns:
        all_qids.update(ref_per_question['qid'].astype(str).str.strip().tolist())
    if not expert_human_machine_per_question.empty and 'qid' in expert_human_machine_per_question.columns:
        all_qids.update(expert_human_machine_per_question['qid'].astype(str).str.strip().tolist())
    if not all_qids:
        return pd.DataFrame()

    # 按 qid 聚合人机一致性（多专家时取均值）：斯皮尔曼与 ICC 均写入题目反馈
    qid_consistency = pd.DataFrame()
    qid_icc = pd.DataFrame()
    if not expert_human_machine_per_question.empty:
        exp = expert_human_machine_per_question.copy()
        exp['qid'] = exp['qid'].astype(str).str.strip()
        if '人机一致性_斯皮尔曼' in exp.columns:
            exp['_c'] = pd.to_numeric(exp['人机一致性_斯皮尔曼'], errors='coerce')
            qid_consistency = exp.groupby('qid')['_c'].mean().reset_index()
            qid_consistency.columns = ['qid', '人机一致性_斯皮尔曼']
        if '人机一致性_ICC' in exp.columns:
            exp['_icc'] = pd.to_numeric(exp['人机一致性_ICC'], errors='coerce')
            qid_icc = exp.groupby('qid')['_icc'].mean().reset_index()
            qid_icc.columns = ['qid', '人机一致性_ICC']

    # 题目指标：区分度、ref、人机一致性
    rows = []
    for qid in sorted(all_qids, key=lambda x: (len(x), x)):
        ref_mean = np.nan
        ref_full = False
        if not ref_per_question.empty:
            r = ref_per_question[ref_per_question['qid'].astype(str).str.strip() == qid]
            if not r.empty:
                ref_mean = float(r['ref均分'].iloc[0]) if 'ref均分' in r.columns else np.nan
                ref_full = bool(r['ref满分'].iloc[0]) if 'ref满分' in r.columns else False
        disc = np.nan
        if not item_analysis_df.empty and '区分度指数_D' in item_analysis_df.columns:
            it = item_analysis_df[item_analysis_df['qid'].astype(str).str.strip() == qid]
            if not it.empty:
                disc = float(pd.to_numeric(it['区分度指数_D'].iloc[0], errors='coerce')) if len(it) > 0 else np.nan
        consistency = np.nan
        consistency_icc = np.nan
        if not qid_consistency.empty:
            c = qid_consistency[qid_consistency['qid'] == qid]
            if not c.empty:
                consistency = float(c['人机一致性_斯皮尔曼'].iloc[0])
        if not qid_icc.empty:
            ci = qid_icc[qid_icc['qid'] == qid]
            if not ci.empty:
                consistency_icc = float(ci['人机一致性_ICC'].iloc[0])

        diag = ''
        sug = ''

        # 无有效数据
        if np.isnan(disc) and np.isnan(ref_mean) and np.isnan(consistency):
            diag = '无评估数据'
            sug = '该题暂无评估或 ref 数据，完成评估后可查看优化建议。'
        # 人机一致性差
        elif not np.isnan(consistency) and consistency < 0:
            diag = '人机一致性差'
            sug = '专家打分与模型打分相关性差或负相关。建议：①检查 rubrics 表述是否清晰、可执行；②补充评分要点与档次描述；③核对 reference 是否与 rubrics 满分标准一致。'
        # 优质
        elif (np.isnan(disc) or disc >= ITEM_DISC_HIGH) and (np.isnan(ref_mean) or ref_mean >= ITEM_REF_MEAN_GOOD) and (np.isnan(consistency) or consistency >= ITEM_CONSISTENCY_GOOD):
            diag = '质量良好'
            sug = '区分度、reference 质量与评分一致性较好，可保持；可适当补充考点说明便于后续复用。'
        # 区分度低
        elif not np.isnan(disc) and disc < ITEM_DISC_LOW:
            diag = '区分度偏低'
            sug = '题目对模型得分区分不足。建议：①在 rubrics 中增加明确的高/中/低分档描述与否决项；②细化考点，避免“写满即高分”；③检查 reference 是否过于宽松导致多数回复也拿高分。'
        # ref 质量差
        elif not np.isnan(ref_mean) and ref_mean < ITEM_REF_MEAN_LOW:
            diag = 'reference 需检查'
            sug = '参考回复得分偏低。建议：①核对 reference 是否满足 rubrics 满分要求；②若 rubrics 过严，补充中低档描述；③必要时重写 reference 或调整评分标准。'
        # 人机一致性一般
        elif not np.isnan(consistency) and consistency < ITEM_CONSISTENCY_MIN and consistency >= 0:
            diag = '评分一致性待提升'
            sug = '专家与模型评分一致性较弱。建议：①细化 rubrics 考点与给分细则；②统一“好/中/差”的判定标准；③检查 reference 与 rubrics 的对应关系。'
        else:
            diag = '可优化'
            sug = '建议：检查 rubrics 与考点是否完整、reference 是否达标、评分标准是否便于人机一致执行。'

        row = {'qid': qid, '题目诊断': diag, '题目优化建议': sug}
        if not np.isnan(disc):
            row['区分度指数_D'] = round(disc, 3)
        if not np.isnan(ref_mean):
            row['ref均分'] = round(ref_mean, 2)
        if not np.isnan(consistency):
            row['人机一致性_斯皮尔曼'] = round(consistency, 3)
        if not np.isnan(consistency_icc):
            row['人机一致性_ICC'] = round(consistency_icc, 3)
        rows.append(row)

    out = pd.DataFrame(rows)
    return out


# 合格数据阈值（用于「一条合格数据」判定，可被 analysis.quality_thresholds 覆盖）
QUALIFIED_DIAGNOSIS_OK = ('质量良好', '可优化')
QUALIFIED_DIAGNOSIS_FAIL = ('无评估数据', '人机一致性差')
QUALIFIED_DISC_MIN = 0.25
QUALIFIED_CONSISTENCY_MIN = 0.4
QUALIFIED_REF_MEAN_MIN = 70.0


def compute_qualified_flag(
    per_question_df: pd.DataFrame,
    discrimination_min: float = QUALIFIED_DISC_MIN,
    consistency_min: float = QUALIFIED_CONSISTENCY_MIN,
    ref_mean_min: float = QUALIFIED_REF_MEAN_MIN,
    diagnosis_ok: tuple = QUALIFIED_DIAGNOSIS_OK,
    diagnosis_fail: tuple = QUALIFIED_DIAGNOSIS_FAIL,
) -> pd.DataFrame:
    """
    为每题计算「数据合格」与「合格依据」，用于反哺题目表及专家合格题目数统计。
    合格定义：题目诊断在合格名单内、且区分度/人机一致性/ref均分不低于阈值（缺项不卡）。
    用于：减少审核工作量、专家结算依据（合格题目数 = 该专家下数据合格=是的题目数）。
    """
    if per_question_df is None or per_question_df.empty:
        return per_question_df
    df = per_question_df.copy()
    diag = df.get('题目诊断', pd.Series(dtype=object))
    disc = pd.to_numeric(df.get('区分度指数_D'), errors='coerce')
    cons = pd.to_numeric(df.get('人机一致性_斯皮尔曼'), errors='coerce')
    # 若缺少 ref均分 列，get 返回标量 NaN；统一转成与 df 同长度的 Series，避免 len(np.float64) 报错
    if 'ref均分' in df.columns:
        ref = pd.to_numeric(df['ref均分'], errors='coerce')
    else:
        ref = pd.Series(np.nan, index=df.index)

    qualified = []
    reason = []
    for i in range(len(df)):
        d = diag.iloc[i] if i < len(diag) else ''
        dc = disc.iloc[i] if i < len(disc) else np.nan
        cc = cons.iloc[i] if i < len(cons) else np.nan
        rc = ref.iloc[i] if i < len(ref) else np.nan

        if d in diagnosis_fail:
            qualified.append('否')
            reason.append('诊断未通过')
            continue
        if d not in diagnosis_ok:
            qualified.append('否')
            reason.append('诊断待优化')
            continue
        # 诊断在合格名单，再卡阈值（有数值则必须达标，缺值不卡）
        if not np.isnan(dc) and dc < discrimination_min:
            qualified.append('否')
            reason.append('区分度<{}'.format(discrimination_min))
            continue
        if not np.isnan(cc) and cc < consistency_min:
            qualified.append('否')
            reason.append('人机一致性<{}'.format(consistency_min))
            continue
        if not np.isnan(rc) and rc < ref_mean_min:
            qualified.append('否')
            reason.append('ref均分<{}'.format(ref_mean_min))
            continue
        qualified.append('是')
        parts = []
        if not np.isnan(dc):
            parts.append('D={}'.format(round(dc, 2)))
        if not np.isnan(cc):
            parts.append('ρ={}'.format(round(cc, 2)))
        if not np.isnan(rc):
            parts.append('ref={}'.format(round(rc, 1)))
        reason.append(';'.join(parts) if parts else '达标')

    df['数据合格'] = qualified
    df['合格依据'] = reason
    return df

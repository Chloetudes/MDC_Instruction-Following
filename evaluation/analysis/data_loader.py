# -*- coding: utf-8 -*-
import os
import warnings
import numpy as np
import pandas as pd
from tqdm import tqdm

warnings.filterwarnings('ignore')


def _normalize_qid(val):
    """统一 qid 格式为字符串，避免 int/float/str 合并报错。如 123.0 -> '123'。"""
    s = str(val).strip()
    try:
        f = float(s)
        if not pd.isna(f) and f == int(f):
            return str(int(f))
    except (ValueError, TypeError):
        pass
    return s


def load_and_preprocess(
    questions_excel: str,
    replies_excel: str,
    human_excel: str = None,
    eval_batch_id: str = None,
) -> dict:
    print("\n" + "=" * 60)
    print("模型评测综合分析系统 - 数据加载")
    print("=" * 60)

    for path in [questions_excel, replies_excel]:
        if not os.path.exists(path):
            raise FileNotFoundError(f"文件不存在: {path}")

    questions_df = pd.read_excel(questions_excel)
    replies_df, expert_df = _load_replies_and_expert(replies_excel)

    print(f"✓ 题目表: {questions_df.shape[0]} 题")
    print(f"✓ 结果表: {replies_df.shape[0]} 条回复, {replies_df['model'].nunique()} 个模型")

    # 若第二个 sheet 有专家评估（qid, model, 专家打分/专家理由），合并到 replies 供后续使用
    if not expert_df.empty:
        replies_df = _merge_expert_into_replies(replies_df, expert_df)
        print(f"✓ 专家评估: 从第2个 sheet 加载 {len(expert_df)} 条，已与回复表对齐")

    _preprocess_questions(questions_df)
    eval_column = _resolve_eval_column(replies_df, eval_batch_id)
    _preprocess_replies(replies_df, eval_column)
    # 出题人：用于人机一致统计的「谁评估了这条回复」。有冲突时以回复表评估专家为准，缺则用题目表专家补全。
    # 1) 回复表 sheet2 合并的「专家」= 实际给该条回复打分的人，优先写入出题人
    if '专家' in replies_df.columns:
        from_sheet2 = replies_df['专家'].fillna('').astype(str).str.strip().replace('nan', '').replace('None', '').replace('NaN', '')
        mask = from_sheet2 != ''
        if mask.any():
            if '出题人' not in replies_df.columns:
                replies_df['出题人'] = ''
            replies_df.loc[mask, '出题人'] = replies_df.loc[mask, '专家'].astype(str).str.strip()
            print(f"✓ 已用回复表 sheet2「专家」填充出题人 {mask.sum()} 条（回复评估专家优先）")
    # 2) 题目表「专家」= 题目的 rubrics 分析者；仅对出题人仍为空的行按 qid 补全
    expert_source_col = next((c for c in ['专家', '出题人', '专家名'] if c in questions_df.columns), None)
    if expert_source_col:
        q_uniq = questions_df.drop_duplicates('qid').copy()
        q_uniq['_qid_norm'] = q_uniq['qid'].astype(str).str.strip().map(_normalize_qid)
        qid_to_expert = q_uniq.set_index('_qid_norm')[expert_source_col]
        qid_to_expert = qid_to_expert.fillna('').astype(str).str.strip().replace('nan', '').replace('None', '').replace('NaN', '')
        if '出题人' not in replies_df.columns:
            replies_df['出题人'] = replies_df['qid'].map(qid_to_expert)
        else:
            empty = replies_df['出题人'].isna() | (replies_df['出题人'].astype(str).str.strip().isin(['', 'nan', 'None', 'NaN']))
            if empty.any():
                replies_df.loc[empty, '出题人'] = replies_df.loc[empty, 'qid'].map(qid_to_expert)
        replies_df['出题人'] = replies_df['出题人'].fillna('').astype(str).str.strip().replace('nan', '').replace('None', '').replace('NaN', '')
        n_filled = (replies_df['出题人'].astype(str).str.strip() != '').sum()
        if n_filled > 0:
            print(f"✓ 出题人列已补全，有效 {n_filled} 条（含题目表补全）")
        qid_to_expert_dict = qid_to_expert.to_dict()
    else:
        qid_to_expert_dict = None
        if '出题人' not in replies_df.columns:
            replies_df['出题人'] = ''
        print(f"⚠️  题目表无「专家」或「出题人」列，无法按 qid 补全出题人；专家统计可能为空")
    if '专家打分' in replies_df.columns or '出题人' in replies_df.columns:
        print(f"✓ 专家相关统计仅基于回复表（qid、reply、专家打分、出题人）")

    human_df = pd.DataFrame()
    rater_scores_df = pd.DataFrame()
    expert_scores_df = pd.DataFrame()

    if human_excel and os.path.exists(human_excel):
        human_df = pd.read_excel(human_excel)
        if 'QID' in human_df.columns:
            human_df = human_df.rename(columns={'QID': 'qid'})
        _preprocess_human(human_df)
        rater_scores_df = _build_rater_scores(human_df)
        expert_scores_df = _build_expert_scores(replies_df, qid_to_expert=qid_to_expert_dict)
        print(f"✓ 人工标注表: {human_df.shape[0]} 条标注")
        print(f"✓ 标注员数量: {rater_scores_df['rater'].nunique() if not rater_scores_df.empty else 0}")
    else:
        expert_scores_df = _build_expert_scores(replies_df, qid_to_expert=qid_to_expert_dict)
        if human_excel:
            print(f"⚠️  人工标注文件不存在，跳过人机一致性分析: {human_excel}")

    replies_with_question = replies_df.merge(
        questions_df[[c for c in [
            'qid', 'L1', 'L2', 'L3', 'source', 'source_group', 'source_group_3',
            'difficulty_level', 'difficulty_code', 'difficulty_score',
            'query', 'reference', 'reference_type', '专家洞察', '专家'
        ] if c in questions_df.columns]],
        on='qid',
        how='left'
    )

    print(f"✓ 使用评估列: {eval_column}")
    if 'ranking_score' in replies_df.columns and replies_df['ranking_score'].notna().any():
        print(f"✓ 主分数（维度加权）: 已从 rubrics_check 计算，用于排名")
    # model='ref' 为参考回复，只参与参考回复质量分析，不参与模型排名与综合统计
    ref_model_name = 'ref'
    ref_mask = replies_df['model'].astype(str).str.strip().str.lower() == ref_model_name
    n_ref = int(ref_mask.sum())
    if n_ref > 0:
        replies_for_ranking = replies_df[~ref_mask].copy()
        rwq_for_ranking = replies_with_question[~replies_with_question['model'].astype(str).str.strip().str.lower().eq(ref_model_name)].copy()
        print(f"✓ 已排除 model=ref 共 {n_ref} 条，不参与排名与统计（仅用于参考回复质量分析）")
    else:
        replies_for_ranking = replies_df
        rwq_for_ranking = replies_with_question
    valid_scores = replies_for_ranking['eval_score'].notna().sum()
    models_with_scores = replies_for_ranking.dropna(subset=['eval_score'])['model'].nunique() if valid_scores > 0 else 0
    print(f"✓ 有效分数: {valid_scores}/{len(replies_for_ranking)} 条（不含ref）, 参与排名模型数: {models_with_scores}/{replies_for_ranking['model'].nunique()}")
    if valid_scores > 0 and models_with_scores < 2:
        print(f"  ⚠️ 仅 {models_with_scores} 个模型有分数，排名/报告可能异常；可运行 backfill 从 raw 补分")
    if not expert_scores_df.empty:
        print(f"✓ 专家评分覆盖: {expert_scores_df['qid'].nunique()} 题")

    return {
        'questions': questions_df,
        'replies': replies_for_ranking,
        'replies_all': replies_df,
        'human': human_df,
        'rater_scores': rater_scores_df,
        'expert_scores': expert_scores_df,
        'replies_with_question': rwq_for_ranking,
        'replies_with_question_all': replies_with_question,
        'eval_column': eval_column,
    }


def _load_replies(replies_excel: str) -> pd.DataFrame:
    """仅加载第一个 sheet（模型评估结果），兼容旧调用。"""
    repl, _ = _load_replies_and_expert(replies_excel)
    return repl


def _load_replies_and_expert(replies_excel: str) -> tuple:
    """
    第一个 sheet：模型评估结果（qid, model, reply, eval_*）。
    第二个 sheet（若存在且含 qid, model, 专家打分）：专家评估，单独加载并与第一表对齐。
    """
    xls = pd.ExcelFile(replies_excel)
    repl_sheet = next(
        (s for s in ('Sheet1', 'replies') if s in xls.sheet_names),
        xls.sheet_names[0]
    )
    replies_df = pd.read_excel(replies_excel, sheet_name=repl_sheet)

    expert_df = pd.DataFrame()
    # 第二个 sheet 或名称含「专家」的 sheet 作为专家评估；支持 专家打分、专家1打分、专家2打分 等
    score_cols = lambda c: '专家打分' in str(c) or (isinstance(c, str) and '专家' in c and '打分' in c)
    other_sheets = [s for s in xls.sheet_names if s not in (repl_sheet, 'batch_log', 'Batch_log')]
    for name in other_sheets:
        df = pd.read_excel(replies_excel, sheet_name=name)
        if 'qid' in df.columns and 'model' in df.columns:
            if any(score_cols(c) for c in df.columns):
                expert_df = df
                break
    # 若无匹配，用第二个 sheet（索引 1）
    if expert_df.empty and len(xls.sheet_names) >= 2:
        cand = xls.sheet_names[1]
        if cand not in ('batch_log', 'Batch_log'):
            df = pd.read_excel(replies_excel, sheet_name=cand)
            if 'qid' in df.columns and 'model' in df.columns:
                expert_df = df
    return replies_df, expert_df


def _detect_expert_score_columns(expert_df: pd.DataFrame) -> list:
    """检测专家打分列：专家打分、专家1打分、专家2打分、专家A打分 等。"""
    out = []
    for c in expert_df.columns:
        if not isinstance(c, str):
            continue
        if c == '专家打分':
            out.append(c)
        elif '专家' in c and '打分' in c:
            out.append(c)
    return sorted(out)


def _merge_expert_into_replies(replies_df: pd.DataFrame, expert_df: pd.DataFrame) -> pd.DataFrame:
    """将专家评估表按 (qid, model) 左合并到回复表，不改变 replies 行数。合并列：专家打分、专家理由、专家（出题人）。"""
    if expert_df.empty or 'qid' not in expert_df.columns or 'model' not in expert_df.columns:
        return replies_df
    score_cols = _detect_expert_score_columns(expert_df)
    reason_cols = [c for c in expert_df.columns if isinstance(c, str) and '专家' in c and ('理由' in c or '意见' in c)]
    expert_cols = score_cols + [c for c in reason_cols if c not in score_cols]
    # sheet2 中的「专家」列一并合并，用于后续填充出题人、人机一致统计
    name_cols = [c for c in ['专家', '出题人'] if c in expert_df.columns]
    if not expert_cols and not name_cols:
        return replies_df
    replies_df = replies_df.copy()
    expert_df = expert_df.copy()
    replies_df['qid'] = replies_df['qid'].astype(str).str.strip().map(_normalize_qid)
    replies_df['model'] = replies_df['model'].astype(str).str.strip()
    expert_df['qid'] = expert_df['qid'].astype(str).str.strip().map(_normalize_qid)
    expert_df['model'] = expert_df['model'].astype(str).str.strip()
    merge_cols = ['qid', 'model']
    take_cols = merge_cols + expert_cols + [c for c in name_cols if c not in merge_cols]
    expert_sub = expert_df[take_cols].drop_duplicates(subset=merge_cols, keep='first')
    for c in expert_cols + name_cols:
        if c in replies_df.columns and c not in merge_cols:
            replies_df = replies_df.drop(columns=[c])
    merged = replies_df.merge(expert_sub, on=merge_cols, how='left')
    return merged


def _resolve_eval_column(replies_df: pd.DataFrame, eval_batch_id: str = None) -> str:
    eval_cols = [c for c in replies_df.columns if isinstance(c, str) and c.startswith('eval_') and not c.endswith('_raw')]

    if eval_batch_id:
        candidate = f"eval_{eval_batch_id}"
        if candidate in replies_df.columns:
            return candidate
        # 兼容列名：eval_batch_1 与 eval_batch1 互认，便于补齐与分析使用同一列
        alt = eval_batch_id.replace('_', '')
        alt2 = eval_batch_id.replace('batch', 'batch_') if 'batch' in eval_batch_id else eval_batch_id
        for c in [f"eval_{alt}", f"eval_{alt2}"]:
            if c in replies_df.columns:
                return c

    if eval_cols:
        return eval_cols[-1]

    raise ValueError(f"结果表中未找到评估列（eval_*），已有列: {list(replies_df.columns)}")


def _preprocess_questions(questions_df: pd.DataFrame):
    if 'qid' in questions_df.columns:
        questions_df['qid'] = questions_df['qid'].astype(str).str.strip().map(_normalize_qid)
    # 统一列名，便于后续 merge 与难度分析（含 diffuculty_level 拼写容错）
    for old_name, new_name in [
        ('数据来源', 'source'), ('预设难度', 'difficulty_level'), ('难度等级', 'difficulty_level'),
        ('diffuculty_level', 'difficulty_level'),
        ('难度分', 'difficulty_score'), ('难度分数', 'difficulty_score'),
    ]:
        if old_name in questions_df.columns and new_name not in questions_df.columns:
            questions_df[new_name] = questions_df[old_name]
    # source 八值：公开=to_b,nlp_cif,nlp_firefly,nlp_others(主要CFBench)；自建=H(人工),R(真实来源),HM(人机协作),M(模型合成)
    if 'source' in questions_df.columns:
        _self_built = {'H', 'R', 'HM', 'M'}
        _human_built = {'H', 'R', 'HM'}  # 纯人工自建，不含 M 合成
        def _sg3(x):
            s = str(x).strip()
            if s == 'M':
                return 'M合成'
            if s in _human_built:
                return '纯人工自建'
            return '公开数据'
        questions_df['source_group'] = questions_df['source'].apply(
            lambda x: '自建数据' if str(x).strip() in _self_built else '公开数据'
        )
        questions_df['source_group_3'] = questions_df['source'].apply(_sg3)

    difficulty_map = {'E': 1, 'D': 2, 'C': 3, 'B': 4, 'A': 5, 'S': 6}
    if 'difficulty_level' in questions_df.columns:
        questions_df['difficulty_code'] = questions_df['difficulty_level'].map(difficulty_map)


def _parse_eval_score(val, eval_column: str) -> float:
    """解析评估分数：支持数值、或字符串如 '60% (18/30)'、FINAL_SCORE JSON 等。"""
    if pd.isna(val):
        return np.nan
    num = pd.to_numeric(val, errors='coerce')
    if not np.isnan(num):
        return float(num)
    s = str(val).strip()
    if not s or s.lower() in ('nan', 'none', ''):
        return np.nan
    # 尝试从 "60% (18/30)" 或 JSON FINAL_SCORE 解析
    try:
        from ..stages.stage4_evaluate import extract_scores_from_evaluation
        scores = extract_scores_from_evaluation(s)
        v = scores.get('total_score') if scores else None
        return float(v) if v is not None and not (isinstance(v, float) and np.isnan(v)) else np.nan
    except Exception:
        return np.nan


def _preprocess_replies(replies_df: pd.DataFrame, eval_column: str):
    replies_df['qid'] = replies_df['qid'].astype(str).str.strip().map(_normalize_qid)
    replies_df['model'] = replies_df['model'].astype(str).str.strip()
    # 支持数值或字符串（如 "60% (18/30)"）格式的评估分
    replies_df['eval_score'] = replies_df[eval_column].apply(lambda x: _parse_eval_score(x, eval_column))

    # 若有 eval_*_raw，从 rubrics_check 计算主分数（维度加权通过率）、CLA、ILA
    _augment_composite_from_raw(replies_df, eval_column)

    if '专家打分' in replies_df.columns:
        replies_df['expert_score'] = pd.to_numeric(replies_df['专家打分'], errors='coerce')


def _augment_composite_from_raw(replies_df: pd.DataFrame, eval_column: str):
    """从 eval_*_raw 解析 rubrics_check，计算 full_pass、eval_composite，并设置 ranking_score。"""
    raw_col = f"{eval_column}_raw" if not eval_column.endswith('_raw') else eval_column
    if raw_col not in replies_df.columns:
        print(f"  ⚠️ 未找到 {raw_col} 列，跳过维度加权计算，使用原始 eval_score")
        return
    from .rubric_dimension_analysis import parse_rubrics_check_from_eval_raw, compute_composite_from_rubrics_check

    full_pass_list = []
    eval_composite_list = []
    cla_list = []
    dim_ila_lists = {'D1_ila': [], 'D2_ila': [], 'D3_ila': [], 'D4_ila': [], 'D5_ila': []}
    ok_count = 0
    for _, row in replies_df.iterrows():
        raw_val = row.get(raw_col, '')
        if pd.isna(raw_val) or not str(raw_val).strip():
            full_pass_list.append(np.nan)
            eval_composite_list.append(np.nan)
            cla_list.append(np.nan)
            for k in dim_ila_lists:
                dim_ila_lists[k].append(np.nan)
            continue
        check = parse_rubrics_check_from_eval_raw(str(raw_val))
        res = compute_composite_from_rubrics_check(check)
        full_pass_list.append(res['full_pass'] if res['total'] > 0 else np.nan)
        eval_composite_list.append(res['composite_score'])
        cla_list.append(res['cla_score'])
        dim_ila = res.get('dimension_ila') or {}
        for dim in ('D1', 'D2', 'D3', 'D4', 'D5'):
            dim_ila_lists[f'{dim}_ila'].append(dim_ila.get(dim, np.nan))
        if res['total'] > 0 and not np.isnan(res.get('composite_score')):
            ok_count += 1
    replies_df['full_pass'] = full_pass_list
    replies_df['eval_composite'] = eval_composite_list
    replies_df['eval_score_cla'] = cla_list
    for k, v in dim_ila_lists.items():
        replies_df[k] = v
    # ranking_score：优先使用综合分，无 raw 时用 eval_score
    replies_df['ranking_score'] = replies_df['eval_composite'].fillna(replies_df['eval_score'])

    raw_vals = replies_df[raw_col]
    total_with_raw = int((raw_vals.notna() & (raw_vals.astype(str).str.strip() != '')).sum())
    if total_with_raw > 0:
        print(f"  维度加权解析: {ok_count}/{total_with_raw} 条成功（未成功则用原 eval_score）")
        if ok_count == 0 and total_with_raw > 0:
            print(f"  💡 若需维度加权分，请确认 {raw_col} 为 JSON 且含 rubrics_check；可运行: python scripts/diagnose_rubrics_parse.py --replies <回复表路径> --batch <批次>")


def _detect_annotators(human_df: pd.DataFrame) -> list:
    """
    自动检测人工标注表中的标注员列，支持任意数量的标注员。
    识别规则：列名以 ann 开头且包含 score 的列（如 ann1_score, ann3_score_m2）。
    """
    annotators = set()
    for col in human_df.columns:
        if isinstance(col, str) and col.startswith('ann') and 'score' in col:
            parts = col.split('_')
            if parts:
                annotators.add(parts[0])
    return sorted(annotators)


def _preprocess_human(human_df: pd.DataFrame):
    human_df['qid'] = human_df['qid'].astype(str).str.strip()

    annotators = _detect_annotators(human_df)
    if not annotators:
        return

    for ann_idx, ann in enumerate(annotators, 1):
        multi_model_score_cols = [c for c in human_df.columns if isinstance(c, str) and c.startswith(f'{ann}_score_m')]
        if multi_model_score_cols:
            human_df[f'{ann}_avg_score'] = pd.to_numeric(
                human_df[multi_model_score_cols].mean(axis=1), errors='coerce'
            )
        elif f'{ann}_score' in human_df.columns:
            human_df[f'{ann}_avg_score'] = pd.to_numeric(human_df[f'{ann}_score'], errors='coerce')

    avg_cols = [f'{ann}_avg_score' for ann in annotators if f'{ann}_avg_score' in human_df.columns]
    if avg_cols:
        human_df['human_avg_score'] = human_df[avg_cols].mean(axis=1)


def _build_rater_scores(human_df: pd.DataFrame) -> pd.DataFrame:
    records = []
    annotators = _detect_annotators(human_df)

    for ann_idx, ann in enumerate(annotators, 1):
        score_col = f'{ann}_avg_score'
        name_col = f'{ann}_name'
        raw_col = f'{ann}_raw_eval'

        if score_col not in human_df.columns:
            continue

        for _, row in human_df.iterrows():
            if pd.isna(row[score_col]):
                continue
            rater_name = (
                str(row[name_col])
                if name_col in human_df.columns and pd.notna(row.get(name_col))
                else f'标注员{ann_idx}'
            )
            records.append({
                'qid': row['qid'],
                'model': row.get('model', None),
                'rater': rater_name,
                'score': float(row[score_col]),
                'raw_eval': str(row[raw_col]) if raw_col in human_df.columns and pd.notna(row.get(raw_col)) else '',
                'task_id': f"{row['qid']}_{row.get('model', '')}",
            })

    return pd.DataFrame(records) if records else pd.DataFrame()


def _build_expert_scores(replies_df: pd.DataFrame, qid_to_expert: dict = None) -> pd.DataFrame:
    """构建专家评分表。rater 优先用回复表「出题人」；若为空则用 qid_to_expert（题目表 qid→专家），保证每人都有统计。"""
    if '专家打分' not in replies_df.columns:
        return pd.DataFrame()

    expert_data = replies_df[replies_df['专家打分'].notna()].copy()
    use_rater_col = '出题人' if '出题人' in expert_data.columns else '专家'
    qid_to_expert = qid_to_expert or {}
    records = []
    for _, row in expert_data.iterrows():
        rater = str(row.get(use_rater_col) or row.get('专家') or '').strip()
        if rater in ('nan', 'None', 'NaN', ''):
            qid_norm = _normalize_qid(str(row['qid']))
            rater = (qid_to_expert.get(qid_norm) or '').strip()
        if rater in ('nan', 'None', 'NaN', ''):
            rater = '专家'
        records.append({
            'qid': str(row['qid']),
            'model': str(row['model']),
            'rater': rater,
            'score': float(row['专家打分']),
            'reason': str(row.get('专家理由', '')) if pd.notna(row.get('专家理由', '')) else '',
            'task_id': f"{row['qid']}_{row['model']}",
        })

    return pd.DataFrame(records) if records else pd.DataFrame()

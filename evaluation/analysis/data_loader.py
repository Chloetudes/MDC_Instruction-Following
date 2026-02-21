# -*- coding: utf-8 -*-
import os
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')


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
    replies_df = _load_replies(replies_excel)

    print(f"✓ 题目表: {questions_df.shape[0]} 题")
    print(f"✓ 结果表: {replies_df.shape[0]} 条回复, {replies_df['model'].nunique()} 个模型")

    _preprocess_questions(questions_df)
    eval_column = _resolve_eval_column(replies_df, eval_batch_id)
    _preprocess_replies(replies_df, eval_column)

    human_df = pd.DataFrame()
    rater_scores_df = pd.DataFrame()
    expert_scores_df = pd.DataFrame()

    if human_excel and os.path.exists(human_excel):
        human_df = pd.read_excel(human_excel)
        if 'QID' in human_df.columns:
            human_df = human_df.rename(columns={'QID': 'qid'})
        _preprocess_human(human_df)
        rater_scores_df = _build_rater_scores(human_df)
        expert_scores_df = _build_expert_scores(replies_df)
        print(f"✓ 人工标注表: {human_df.shape[0]} 条标注")
        print(f"✓ 标注员数量: {rater_scores_df['rater'].nunique() if not rater_scores_df.empty else 0}")
    else:
        expert_scores_df = _build_expert_scores(replies_df)
        if human_excel:
            print(f"⚠️  人工标注文件不存在，跳过人机一致性分析: {human_excel}")

    replies_with_question = replies_df.merge(
        questions_df[[c for c in [
            'qid', 'L1', 'L2', 'L3', 'source', 'source_group',
            'difficulty_level', 'difficulty_code', 'difficulty_score',
            'query', 'reference', 'reference_type'
        ] if c in questions_df.columns]],
        on='qid',
        how='left'
    )

    print(f"✓ 使用评估列: {eval_column}")
    if not expert_scores_df.empty:
        print(f"✓ 专家评分覆盖: {expert_scores_df['qid'].nunique()} 题")

    return {
        'questions': questions_df,
        'replies': replies_df,
        'human': human_df,
        'rater_scores': rater_scores_df,
        'expert_scores': expert_scores_df,
        'replies_with_question': replies_with_question,
        'eval_column': eval_column,
    }


def _load_replies(replies_excel: str) -> pd.DataFrame:
    xls = pd.ExcelFile(replies_excel)
    target_sheet = next(
        (s for s in ('Sheet1', 'replies') if s in xls.sheet_names),
        xls.sheet_names[0]
    )
    return pd.read_excel(replies_excel, sheet_name=target_sheet)


def _resolve_eval_column(replies_df: pd.DataFrame, eval_batch_id: str = None) -> str:
    eval_cols = [c for c in replies_df.columns if c.startswith('eval_') and not c.endswith('_raw')]

    if eval_batch_id:
        candidate = f"eval_{eval_batch_id}"
        if candidate in replies_df.columns:
            return candidate

    if eval_cols:
        return eval_cols[-1]

    raise ValueError(f"结果表中未找到评估列（eval_*），已有列: {list(replies_df.columns)}")


def _preprocess_questions(questions_df: pd.DataFrame):
    if 'source' in questions_df.columns:
        questions_df['source_group'] = questions_df['source'].apply(
            lambda x: '自建数据' if x in ['H', 'R', 'HM', 'M'] else '公开数据'
        )

    difficulty_map = {'E': 1, 'D': 2, 'C': 3, 'B': 4, 'A': 5, 'S': 6}
    if 'difficulty_level' in questions_df.columns:
        questions_df['difficulty_code'] = questions_df['difficulty_level'].map(difficulty_map)


def _preprocess_replies(replies_df: pd.DataFrame, eval_column: str):
    replies_df['qid'] = replies_df['qid'].astype(str).str.strip()
    replies_df['model'] = replies_df['model'].astype(str).str.strip()
    replies_df['eval_score'] = pd.to_numeric(replies_df[eval_column], errors='coerce')

    if '专家打分' in replies_df.columns:
        replies_df['expert_score'] = pd.to_numeric(replies_df['专家打分'], errors='coerce')


def _preprocess_human(human_df: pd.DataFrame):
    human_df['qid'] = human_df['qid'].astype(str).str.strip()

    for ann in ['ann1', 'ann2']:
        score_cols = [f'{ann}_score_m1', f'{ann}_score_m2', f'{ann}_score_m3']
        existing_cols = [c for c in score_cols if c in human_df.columns]
        if existing_cols:
            human_df[f'{ann}_avg_score'] = pd.to_numeric(
                human_df[existing_cols].mean(axis=1), errors='coerce'
            )
        elif f'{ann}_score' in human_df.columns:
            human_df[f'{ann}_avg_score'] = pd.to_numeric(human_df[f'{ann}_score'], errors='coerce')

    avg_cols = [c for c in ['ann1_avg_score', 'ann2_avg_score'] if c in human_df.columns]
    if avg_cols:
        human_df['human_avg_score'] = human_df[avg_cols].mean(axis=1)


def _build_rater_scores(human_df: pd.DataFrame) -> pd.DataFrame:
    records = []

    for ann_idx, ann in enumerate(['ann1', 'ann2'], 1):
        score_col = f'{ann}_avg_score'
        name_col = f'{ann}_name'
        raw_col = f'{ann}_raw_eval'

        if score_col not in human_df.columns:
            continue

        for _, row in human_df.iterrows():
            if pd.isna(row[score_col]):
                continue
            rater_name = str(row[name_col]) if name_col in human_df.columns and pd.notna(row.get(name_col)) else f'标注员{ann_idx}'
            records.append({
                'qid': row['qid'],
                'model': row.get('model', None),
                'rater': rater_name,
                'score': float(row[score_col]),
                'raw_eval': str(row[raw_col]) if raw_col in human_df.columns and pd.notna(row.get(raw_col)) else '',
                'task_id': f"{row['qid']}_{row.get('model', '')}",
            })

    return pd.DataFrame(records) if records else pd.DataFrame()


def _build_expert_scores(replies_df: pd.DataFrame) -> pd.DataFrame:
    if '专家打分' not in replies_df.columns:
        return pd.DataFrame()

    expert_data = replies_df[replies_df['专家打分'].notna()]
    records = []
    for _, row in expert_data.iterrows():
        records.append({
            'qid': str(row['qid']),
            'model': str(row['model']),
            'rater': '专家',
            'score': float(row['专家打分']),
            'reason': str(row.get('专家理由', '')) if pd.notna(row.get('专家理由', '')) else '',
            'task_id': f"{row['qid']}_{row['model']}",
        })

    return pd.DataFrame(records) if records else pd.DataFrame()

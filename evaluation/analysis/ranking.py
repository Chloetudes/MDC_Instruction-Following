# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd
from scipy.stats import f_oneway, ttest_ind

from .metrics import ScientificMetrics


class ModelRankingAnalyzer:

    def __init__(self, data: dict):
        self.replies = data['replies_with_question']
        self.models = self.replies['model'].unique() if 'model' in self.replies.columns else []
        # 优先用综合分（含完全通过加成），无 raw 时用 eval_score
        self._score_col = (
            'ranking_score'
            if 'ranking_score' in self.replies.columns and self.replies['ranking_score'].notna().any()
            else 'eval_score'
        )

    def analyze_overall_performance(self) -> pd.DataFrame:
        print("   - 生成模型整体表现排名...")
        use_composite = self._score_col == 'ranking_score'
        results = []
        for model in self.models:
            sub = self.replies[self.replies['model'] == model]
            scores = sub[self._score_col].dropna()
            if len(scores) == 0:
                continue
            row = {
                '模型': model,
                '评测数量': len(scores),
                '平均分': round(float(scores.mean()), 2),
                '标准差': round(float(scores.std()), 2),
                '最高分': round(float(scores.max()), 2),
                '最低分': round(float(scores.min()), 2),
                '中位数': round(float(scores.median()), 2),
                '>=90分数量': int((scores >= 90).sum()),
                '>=80分数量': int((scores >= 80).sum()),
                '>=70分数量': int((scores >= 70).sum()),
                '>=60分数量': int((scores >= 60).sum()),
            }
            # 原均分(CLA)：约束通过率 passed/total，优先用从 rubrics_check 算出的 eval_score_cla
            if use_composite:
                cla_scores = sub.get('eval_score_cla')
                if cla_scores is not None and cla_scores.notna().any():
                    orig = cla_scores.dropna()
                    row['原均分(CLA)'] = round(float(orig.mean()), 2) if len(orig) > 0 else np.nan
                elif 'eval_score' in sub.columns:
                    orig = sub['eval_score'].dropna()
                    row['原均分(CLA)'] = round(float(orig.mean()), 2) if len(orig) > 0 else np.nan
            results.append(row)
        if not results:
            return pd.DataFrame()
        df = pd.DataFrame(results).sort_values('平均分', ascending=False).reset_index(drop=True)
        df.insert(0, '排名', df.index + 1)
        if use_composite and '原均分(CLA)' in df.columns:
            cols = list(df.columns)
            cols.remove('原均分(CLA)')
            idx = cols.index('平均分') + 1
            df = df[cols[:idx] + ['原均分(CLA)'] + cols[idx:]]
        return df

    def _build_overall_style_ranking(self, subset: pd.DataFrame) -> pd.DataFrame:
        """对给定子集（如按 source_group 筛选）生成与整体表现同结构的排名表。"""
        if subset.empty or self._score_col not in subset.columns:
            return pd.DataFrame()
        use_composite = self._score_col == 'ranking_score'
        models_in_subset = subset['model'].dropna().unique()
        results = []
        for model in models_in_subset:
            sub = subset[subset['model'] == model]
            scores = sub[self._score_col].dropna()
            if len(scores) == 0:
                continue
            row = {
                '模型': model,
                '评测数量': len(scores),
                '平均分': round(float(scores.mean()), 2),
                '标准差': round(float(scores.std()), 2),
                '最高分': round(float(scores.max()), 2),
                '最低分': round(float(scores.min()), 2),
                '中位数': round(float(scores.median()), 2),
                '>=90分数量': int((scores >= 90).sum()),
                '>=80分数量': int((scores >= 80).sum()),
                '>=70分数量': int((scores >= 70).sum()),
                '>=60分数量': int((scores >= 60).sum()),
            }
            if use_composite and 'eval_score_cla' in sub.columns and sub['eval_score_cla'].notna().any():
                orig = sub['eval_score_cla'].dropna()
                row['原均分(CLA)'] = round(float(orig.mean()), 2) if len(orig) > 0 else np.nan
            elif use_composite and 'eval_score' in sub.columns:
                orig = sub['eval_score'].dropna()
                row['原均分(CLA)'] = round(float(orig.mean()), 2) if len(orig) > 0 else np.nan
            results.append(row)
        if not results:
            return pd.DataFrame()
        df = pd.DataFrame(results).sort_values('平均分', ascending=False).reset_index(drop=True)
        df.insert(0, '排名', df.index + 1)
        if use_composite and '原均分(CLA)' in df.columns:
            cols = list(df.columns)
            cols.remove('原均分(CLA)')
            idx = cols.index('平均分') + 1
            df = df[cols[:idx] + ['原均分(CLA)'] + cols[idx:]]
        return df

    def analyze_ranking_by_source_group(self) -> tuple:
        """
        按数据来源（自建数据 / 公开数据）分别计算模型排名，与整体表现表结构一致。
        返回 (自建数据排名_df, 公开数据排名_df)；无 source_group 或某类无数据时对应为空 DataFrame。
        """
        if 'source_group' not in self.replies.columns:
            return pd.DataFrame(), pd.DataFrame()
        self_built = self.replies[self.replies['source_group'] == '自建数据']
        public = self.replies[self.replies['source_group'] == '公开数据']
        df_self = self._build_overall_style_ranking(self_built)
        df_pub = self._build_overall_style_ranking(public)
        if not df_self.empty:
            print("   - 生成自建数据排名表...")
        if not df_pub.empty:
            print("   - 生成公开数据排名表...")
        return df_self, df_pub

    def _build_dimension_ranking(self, dimension_col: str, categories: list, label: str) -> pd.DataFrame:
        results = []
        for model in self.models:
            model_data = self.replies[self.replies['model'] == model]
            row = {'模型': model}
            dim_scores = []
            for cat in categories:
                cat_data = model_data[model_data[dimension_col] == cat]
                if not cat_data.empty:
                    score = float(cat_data[self._score_col].mean())
                    row[str(cat)] = round(score, 2)
                    dim_scores.append(score)
                else:
                    row[str(cat)] = 'N/A'
            valid = [s for s in dim_scores if not np.isnan(s)]
            row['平均分'] = round(float(np.mean(valid)), 2) if valid else 0
            results.append(row)
        if not results:
            return pd.DataFrame()
        df = pd.DataFrame(results).sort_values('平均分', ascending=False).reset_index(drop=True)
        df.insert(0, '排名', df.index + 1)
        return df

    def analyze_l1_dimension(self) -> tuple:
        print("   - 生成L1维度排名...")
        if 'L1' not in self.replies.columns:
            return pd.DataFrame(), []
        cats = sorted([str(c) for c in self.replies['L1'].dropna().unique()])
        return self._build_dimension_ranking('L1', cats, 'L1'), cats

    def analyze_l2_dimension(self, top_n: int = 30) -> tuple:
        print(f"   - 生成L2维度排名 (TOP{top_n})...")
        if 'L2' not in self.replies.columns:
            return pd.DataFrame(), []
        cats = sorted([str(c) for c in self.replies['L2'].value_counts().head(top_n).index])
        return self._build_dimension_ranking('L2', cats, 'L2'), cats

    def analyze_l3_dimension(self, top_n: int = 30) -> tuple:
        print(f"   - 生成L3维度排名 (TOP{top_n})...")
        if 'L3' not in self.replies.columns:
            return pd.DataFrame(), []
        cats = sorted([str(c) for c in self.replies['L3'].value_counts().head(top_n).index])
        return self._build_dimension_ranking('L3', cats, 'L3'), cats

    def analyze_source_dimension(self) -> tuple:
        print("   - 生成Source维度排名...")
        if 'source' not in self.replies.columns:
            return pd.DataFrame(), []
        channels = sorted([str(c) for c in self.replies['source'].dropna().unique()])
        return self._build_dimension_ranking('source', channels, 'source'), channels

    def analyze_difficulty_dimension(self) -> tuple:
        print("   - 生成难度等级排名...")
        if 'difficulty_level' not in self.replies.columns:
            return pd.DataFrame(), []
        actual_levels = self.replies['difficulty_level'].dropna().unique()
        if len(actual_levels) == 0:
            return pd.DataFrame(), []
        priority = {'S': 6, 'A': 5, 'B': 4, 'C': 3, 'D': 2, 'E': 1}
        sorted_levels = sorted(actual_levels, key=lambda x: priority.get(x, 0), reverse=True)
        return self._build_dimension_ranking('difficulty_level', sorted_levels, 'difficulty'), sorted_levels

    def analyze_significance_test(self) -> pd.DataFrame:
        print("   - 生成显著性检验...")
        top_models = self.models[:10] if len(self.models) > 10 else self.models
        model_scores = []
        model_names = []
        for model in top_models:
            scores = self.replies[self.replies['model'] == model][self._score_col].dropna().values
            if len(scores) > 0:
                model_scores.append(scores)
                model_names.append(model)

        if len(model_scores) < 2:
            return pd.DataFrame()

        results = []
        try:
            f_stat, p_val = f_oneway(*model_scores)
            results.append({
                '检验类型': '模型间整体差异（ANOVA）',
                '统计量': round(float(f_stat), 4),
                'p值': round(float(p_val), 4),
                '显著性': '显著' if p_val < 0.05 else '不显著',
                '效应量_d': '-'
            })
        except Exception:
            pass

        for i in range(min(5, len(model_names))):
            for j in range(i + 1, min(5, len(model_names))):
                s1 = self.replies[self.replies['model'] == model_names[i]][self._score_col].dropna().values
                s2 = self.replies[self.replies['model'] == model_names[j]][self._score_col].dropna().values
                if len(s1) > 0 and len(s2) > 0:
                    try:
                        t_stat, p_val = ttest_ind(s1, s2)
                        d = ScientificMetrics.cohens_d(s1, s2)
                        results.append({
                            '检验类型': f'{model_names[i][:20]} vs {model_names[j][:20]}',
                            '统计量': round(float(t_stat), 4),
                            'p值': round(float(p_val), 4),
                            '显著性': '显著' if p_val < 0.05 else '不显著',
                            '效应量_d': d if not np.isnan(d) else 'N/A'
                        })
                    except Exception:
                        pass

        return pd.DataFrame(results)

    def analyze_expert_only_ranking(self) -> pd.DataFrame:
        """
        仅专家评测过的题目榜单：只统计「有专家打分」的 (qid, model) 行，
        按专家打分算各模型均分并排名；同时给出同一子集上模型打分的均分，便于对比。
        """
        if 'expert_score' not in self.replies.columns or self.replies['expert_score'].notna().sum() == 0:
            return pd.DataFrame()
        sub = self.replies[self.replies['expert_score'].notna()]
        if sub.empty:
            return pd.DataFrame()
        results = []
        for model in self.models:
            model_sub = sub[sub['model'] == model]
            if model_sub.empty:
                continue
            exp_scores = model_sub['expert_score'].dropna()
            if len(exp_scores) == 0:
                continue
            model_scores_same = model_sub[self._score_col].dropna()
            row = {
                '模型': model,
                '专家题数量': len(exp_scores),
                '专家均分': round(float(exp_scores.mean()), 2),
                '专家标准差': round(float(exp_scores.std()), 2) if len(exp_scores) > 1 else 0,
                '最高分': round(float(exp_scores.max()), 2),
                '最低分': round(float(exp_scores.min()), 2),
            }
            if len(model_scores_same) > 0:
                row['模型均分(专家题上)'] = round(float(model_scores_same.mean()), 2)
            results.append(row)
        if not results:
            return pd.DataFrame()
        df = pd.DataFrame(results).sort_values('专家均分', ascending=False).reset_index(drop=True)
        df.insert(0, '排名', df.index + 1)
        print(f"   - 生成专家评测榜单: {len(df)} 个模型（仅统计有专家打分的题目）")
        return df

    def generate_all_rankings(self) -> dict:
        print("\n▶ 正在生成多维度排名表...")
        rankings = {
            'overall': self.analyze_overall_performance(),
        }
        rankings['expert_only'] = self.analyze_expert_only_ranking()
        rankings['l1'], rankings['l1_cats'] = self.analyze_l1_dimension()
        rankings['l2'], rankings['l2_cats'] = self.analyze_l2_dimension()
        rankings['l3'], rankings['l3_cats'] = self.analyze_l3_dimension()
        rankings['source'], rankings['source_cats'] = self.analyze_source_dimension()
        rankings['difficulty'], rankings['difficulty_cats'] = self.analyze_difficulty_dimension()
        rankings['significance'] = self.analyze_significance_test()
        print("  ✓ 排名表生成完成")
        return rankings


class ExpertCorrectedRankingAnalyzer:

    def __init__(self, data: dict):
        self.replies = data['replies']
        self.expert_scores = data['expert_scores']
        self.replies_with_question = data.get('replies_with_question', pd.DataFrame())
        self.models = self.replies['model'].unique() if 'model' in self.replies.columns else []
        self._score_col = (
            'ranking_score'
            if 'ranking_score' in self.replies.columns and self.replies['ranking_score'].notna().any()
            else 'eval_score'
        )

    def analyze_corrected_ranking(self) -> pd.DataFrame:
        print("\n▶ 正在生成专家纠偏模型性能排行榜...")
        if self.expert_scores.empty:
            print("  ⚠️ 无专家评分数据，跳过")
            return pd.DataFrame()

        expert_dict = {
            (str(row['qid']), str(row['model'])): row['score']
            for _, row in self.expert_scores.iterrows()
        }
        print(f"  ✓ 加载专家评分: {len(expert_dict)} 条")

        results = []
        for model in self.models:
            model_data = self.replies[self.replies['model'] == model]
            total_score = 0
            valid_count = 0
            expert_used = 0

            for _, row in model_data.iterrows():
                key = (str(row['qid']), str(model))
                score = expert_dict.get(key, row[self._score_col])
                if key in expert_dict:
                    expert_used += 1
                if pd.notna(score):
                    total_score += score
                    valid_count += 1

            if valid_count == 0:
                continue

            corrected_mean = total_score / valid_count
            original_mean = model_data[self._score_col].mean()
            results.append({
                '模型': model,
                '纠偏后均分': round(corrected_mean, 2),
                '原始均分': round(original_mean, 2) if pd.notna(original_mean) else 'N/A',
                '差异': round(corrected_mean - original_mean, 2) if pd.notna(original_mean) else 'N/A',
                '专家题目数': expert_used,
                '总题目数': valid_count,
                '专家覆盖率': f"{expert_used}/{valid_count} ({round(expert_used / valid_count * 100, 1)}%)"
            })

        if not results:
            return pd.DataFrame()

        df = pd.DataFrame(results).sort_values('纠偏后均分', ascending=False).reset_index(drop=True)
        df.insert(0, '排名', df.index + 1)

        original_ranking = self.replies.groupby('model')[self._score_col].mean().sort_values(ascending=False)
        rank_map = {m: idx + 1 for idx, m in enumerate(original_ranking.index)}
        df['原始排名'] = df['模型'].map(rank_map)
        df['排名变化'] = df['原始排名'] - df['排名']

        print(f"  ✓ 专家纠偏排行榜生成完成: {len(df)} 个模型")
        return df

    def analyze_corrected_ranking_by_l1(self) -> dict:
        """
        L1 级别专家纠偏排名：按 L1 意图类型分组，每组内用专家分（有则用）替换模型分后计算均分并排名。
        返回 {l1: DataFrame}，每个 DataFrame 含 排名、模型、纠偏后均分、原始均分、专家题目数、总题目数 等。
        """
        if self.expert_scores.empty or self.replies_with_question.empty:
            return {}
        if 'L1' not in self.replies_with_question.columns:
            return {}

        expert_dict = {
            (str(row['qid']), str(row['model'])): row['score']
            for _, row in self.expert_scores.iterrows()
        }

        l1_cats = sorted([str(c) for c in self.replies_with_question['L1'].dropna().unique()])
        result = {}

        for l1 in l1_cats:
            subset = self.replies_with_question[self.replies_with_question['L1'] == l1]
            if subset.empty:
                continue

            rows = []
            for model in self.models:
                model_data = subset[subset['model'] == model]
                if model_data.empty:
                    continue
                total_score = 0
                valid_count = 0
                expert_used = 0
                for _, row in model_data.iterrows():
                    key = (str(row['qid']), str(model))
                    score = expert_dict.get(key, row[self._score_col])
                    if key in expert_dict:
                        expert_used += 1
                    if pd.notna(score):
                        total_score += score
                        valid_count += 1
                if valid_count == 0:
                    continue
                corrected_mean = total_score / valid_count
                orig_mean = model_data[self._score_col].mean()
                rows.append({
                    '模型': model,
                    '纠偏后均分': round(corrected_mean, 2),
                    '原始均分': round(float(orig_mean), 2) if pd.notna(orig_mean) else np.nan,
                    '专家题目数': expert_used,
                    '总题目数': valid_count,
                    '专家覆盖率': f"{expert_used}/{valid_count} ({round(expert_used / valid_count * 100, 1)}%)",
                })

            if not rows:
                continue
            df = pd.DataFrame(rows).sort_values('纠偏后均分', ascending=False).reset_index(drop=True)
            df.insert(0, '排名', df.index + 1)
            result[l1] = df

        if result:
            print(f"  ✓ L1级别专家纠偏排名: {len(result)} 个 L1 意图类型")
        return result

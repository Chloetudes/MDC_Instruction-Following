# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd
from scipy.stats import f_oneway, ttest_ind

from .metrics import ScientificMetrics


class ModelRankingAnalyzer:

    def __init__(self, data: dict):
        self.replies = data['replies_with_question']
        self.models = self.replies['model'].unique() if 'model' in self.replies.columns else []

    def analyze_overall_performance(self) -> pd.DataFrame:
        print("   - 生成模型整体表现排名...")
        results = []
        for model in self.models:
            scores = self.replies[self.replies['model'] == model]['eval_score'].dropna()
            if len(scores) == 0:
                continue
            results.append({
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
            })
        if not results:
            return pd.DataFrame()
        df = pd.DataFrame(results).sort_values('平均分', ascending=False).reset_index(drop=True)
        df.insert(0, '排名', df.index + 1)
        return df

    def _build_dimension_ranking(self, dimension_col: str, categories: list, label: str) -> pd.DataFrame:
        results = []
        for model in self.models:
            model_data = self.replies[self.replies['model'] == model]
            row = {'模型': model}
            dim_scores = []
            for cat in categories:
                cat_data = model_data[model_data[dimension_col] == cat]
                if not cat_data.empty:
                    score = float(cat_data['eval_score'].mean())
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
            scores = self.replies[self.replies['model'] == model]['eval_score'].dropna().values
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
                s1 = self.replies[self.replies['model'] == model_names[i]]['eval_score'].dropna().values
                s2 = self.replies[self.replies['model'] == model_names[j]]['eval_score'].dropna().values
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

    def generate_all_rankings(self) -> dict:
        print("\n▶ 正在生成多维度排名表...")
        rankings = {
            'overall': self.analyze_overall_performance(),
        }
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
        self.models = self.replies['model'].unique() if 'model' in self.replies.columns else []

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
                score = expert_dict.get(key, row['eval_score'])
                if key in expert_dict:
                    expert_used += 1
                if pd.notna(score):
                    total_score += score
                    valid_count += 1

            if valid_count == 0:
                continue

            corrected_mean = total_score / valid_count
            original_mean = model_data['eval_score'].mean()
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

        original_ranking = self.replies.groupby('model')['eval_score'].mean().sort_values(ascending=False)
        rank_map = {m: idx + 1 for idx, m in enumerate(original_ranking.index)}
        df['原始排名'] = df['模型'].map(rank_map)
        df['排名变化'] = df['原始排名'] - df['排名']

        print(f"  ✓ 专家纠偏排行榜生成完成: {len(df)} 个模型")
        return df

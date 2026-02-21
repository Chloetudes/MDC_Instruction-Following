# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd
from scipy.stats import spearmanr, kendalltau, pearsonr

from .metrics import ScientificMetrics

MIN_SAMPLE_FOR_CORRELATION = 3
MIN_MODELS_PER_QUESTION = 2


class HumanModelConsistencyAnalyzer:

    def __init__(self, data: dict):
        self.rater_scores = data['rater_scores']
        self.replies = data['replies']

    def analyze_per_question_ranking_consistency(self) -> pd.DataFrame:
        if self.rater_scores.empty or self.replies.empty:
            return pd.DataFrame()

        print("   - 计算每道题排名一致性...")
        human_avg = (
            self.rater_scores.groupby(['qid', 'model'])['score']
            .mean()
            .reset_index()
            .rename(columns={'score': 'human_score'})
        )
        model_scores = self.replies[['qid', 'model', 'eval_score']].dropna()
        merged = human_avg.merge(model_scores, on=['qid', 'model'], how='inner')

        results = []
        for qid in merged['qid'].unique():
            q_data = merged[merged['qid'] == qid]
            if len(q_data) < MIN_MODELS_PER_QUESTION:
                continue

            human_rank = q_data.groupby('model')['human_score'].mean().rank(ascending=False, method='dense')
            model_rank = q_data.groupby('model')['eval_score'].mean().rank(ascending=False, method='dense')
            common_models = set(human_rank.index) & set(model_rank.index)
            if len(common_models) < MIN_MODELS_PER_QUESTION:
                continue

            h_list = [human_rank[m] for m in common_models]
            m_list = [model_rank[m] for m in common_models]

            rank_corr = np.nan
            kendall_corr = np.nan
            if len(h_list) >= MIN_SAMPLE_FOR_CORRELATION:
                try:
                    rank_corr, _ = spearmanr(h_list, m_list)
                except Exception:
                    pass
                try:
                    kendall_corr, _ = kendalltau(h_list, m_list)
                except Exception:
                    pass

            rank_diff = np.array(h_list) - np.array(m_list)
            top3_human = set(human_rank.nsmallest(3).index) if len(human_rank) >= 3 else set()
            top3_model = set(model_rank.nsmallest(3).index) if len(model_rank) >= 3 else set()
            top3_overlap = len(top3_human & top3_model) / 3 if top3_human and top3_model else 0

            results.append({
                'qid': str(qid),
                '模型总数': len(q_data['model'].unique()),
                '共同模型数': len(common_models),
                '排名一致性_斯皮尔曼': round(rank_corr, 3) if not np.isnan(rank_corr) else 'N/A',
                '排名一致性_肯德尔': round(kendall_corr, 3) if not np.isnan(kendall_corr) else 'N/A',
                '平均排名偏差': round(float(np.abs(rank_diff).mean()), 2),
                '最大排名偏差': int(np.abs(rank_diff).max()),
                '完全一致比例': round(float(np.mean(rank_diff == 0)), 3),
                'TOP3重合度': round(float(top3_overlap), 3),
            })

        df = pd.DataFrame(results)
        print(f"    完成: {len(df)} 道题")
        return df

    def analyze_rater_model_ranking_consistency(self) -> pd.DataFrame:
        if self.rater_scores.empty:
            return pd.DataFrame()

        print("   - 计算标注员人机一致性...")
        results = []

        for rater in self.rater_scores['rater'].unique():
            rater_data = self.rater_scores[self.rater_scores['rater'] == rater]
            rater_avg = rater_data.groupby(['qid', 'model'])['score'].mean().reset_index()
            model_scores = self.replies[['qid', 'model', 'eval_score']].dropna()
            merged = rater_avg.merge(model_scores, on=['qid', 'model'], how='inner')

            if len(merged) < MIN_SAMPLE_FOR_CORRELATION:
                continue

            rank_corrs, top1_consistents, top3_overlaps = [], [], []
            for qid in merged['qid'].unique():
                q_data = merged[merged['qid'] == qid]
                if len(q_data) < MIN_MODELS_PER_QUESTION:
                    continue

                human_rank = q_data['score'].rank(ascending=False, method='dense')
                model_rank = q_data['eval_score'].rank(ascending=False, method='dense')
                if len(q_data) >= MIN_SAMPLE_FOR_CORRELATION:
                    try:
                        r_corr, _ = spearmanr(human_rank, model_rank)
                        if not np.isnan(r_corr):
                            rank_corrs.append(r_corr)
                    except Exception:
                        pass

                top1_h = q_data.loc[q_data['score'].idxmax(), 'model'] if not q_data.empty else None
                top1_m = q_data.loc[q_data['eval_score'].idxmax(), 'model'] if not q_data.empty else None
                if top1_h and top1_m:
                    top1_consistents.append(top1_h == top1_m)

                top3_h = set(q_data.nlargest(3, 'score')['model']) if len(q_data) >= 3 else set()
                top3_m = set(q_data.nlargest(3, 'eval_score')['model']) if len(q_data) >= 3 else set()
                if top3_h and top3_m:
                    top3_overlaps.append(len(top3_h & top3_m) / 3)

            icc = ScientificMetrics.icc_2_1(merged['score'].values, merged['eval_score'].values)
            kappa = ScientificMetrics.cohens_kappa_weighted(merged['score'].values, merged['eval_score'].values)
            nmae = ScientificMetrics.normalized_mae(merged['score'].values, merged['eval_score'].values)
            try:
                spearman_corr = spearmanr(merged['score'], merged['eval_score'])[0]
            except Exception:
                spearman_corr = np.nan
            mae = float(np.abs(merged['score'] - merged['eval_score']).mean())

            results.append({
                '标注员': str(rater),
                '共同任务数': len(merged),
                '共同题目数': merged['qid'].nunique(),
                '平均排名一致性': round(float(np.mean(rank_corrs)), 3) if rank_corrs else 'N/A',
                'TOP1一致率': round(float(np.mean(top1_consistents)), 3) if top1_consistents else 'N/A',
                'TOP3平均重合度': round(float(np.mean(top3_overlaps)), 3) if top3_overlaps else 'N/A',
                'ICC(2,1)': round(icc, 3) if not np.isnan(icc) else 'N/A',
                '加权Kappa': round(kappa, 3) if not np.isnan(kappa) else 'N/A',
                '打分一致性_斯皮尔曼': round(spearman_corr, 3) if not np.isnan(spearman_corr) else 'N/A',
                'MAE': round(mae, 2),
                '归一化MAE': round(nmae, 3) if not np.isnan(nmae) else 'N/A',
            })

        df = pd.DataFrame(results)
        if not df.empty:
            df['_sort_key'] = pd.to_numeric(df['平均排名一致性'], errors='coerce')
            df = df.sort_values('_sort_key', ascending=False).drop('_sort_key', axis=1).reset_index(drop=True)
            df.insert(0, '人机排名一致性排名', df.index + 1)
        print(f"    完成: {len(df)} 位标注员")
        return df


class HumanExpertConsistencyAnalyzer:

    def __init__(self, data: dict):
        self.rater_scores = data['rater_scores']
        self.expert_scores = data['expert_scores']

    def analyze_rater_vs_others(self) -> pd.DataFrame:
        if self.rater_scores.empty:
            return pd.DataFrame()

        print("   - 计算组内一致性排名...")
        raters = self.rater_scores['rater'].unique()
        if len(raters) < 2:
            return pd.DataFrame()

        rater_quality = []
        for target_rater in raters:
            target_data = self.rater_scores[self.rater_scores['rater'] == target_rater]
            target_avg = target_data.groupby(['qid', 'model'])['score'].mean().reset_index()
            target_avg['task_id'] = target_avg['qid'].astype(str) + '_' + target_avg['model'].astype(str)

            all_spearmans, all_iccs, all_kappas, all_nmaes = [], [], [], []
            for other_rater in [r for r in raters if r != target_rater]:
                other_data = self.rater_scores[self.rater_scores['rater'] == other_rater]
                other_avg = other_data.groupby(['qid', 'model'])['score'].mean().reset_index()
                other_avg['task_id'] = other_avg['qid'].astype(str) + '_' + other_avg['model'].astype(str)
                merged = target_avg.merge(other_avg[['task_id', 'score']], on='task_id', suffixes=('_t', '_o'))

                if len(merged) < MIN_SAMPLE_FOR_CORRELATION:
                    continue
                try:
                    r, _ = spearmanr(merged['score_t'], merged['score_o'])
                    if not np.isnan(r):
                        all_spearmans.append(r)
                except Exception:
                    pass
                icc = ScientificMetrics.icc_2_1(merged['score_t'].values, merged['score_o'].values)
                if not np.isnan(icc):
                    all_iccs.append(icc)
                kappa = ScientificMetrics.cohens_kappa_weighted(merged['score_t'].values, merged['score_o'].values)
                if not np.isnan(kappa):
                    all_kappas.append(kappa)
                nmae = ScientificMetrics.normalized_mae(merged['score_t'].values, merged['score_o'].values)
                if not np.isnan(nmae):
                    all_nmaes.append(nmae)

            if not all_spearmans:
                continue

            avg_spearman = float(np.mean(all_spearmans))
            avg_icc = float(np.mean(all_iccs)) if all_iccs else 0.0
            avg_kappa = float(np.mean(all_kappas)) if all_kappas else 0.0
            avg_nmae = float(np.mean(all_nmaes)) if all_nmaes else 1.0

            composite = (
                avg_spearman * 0.4
                + avg_icc * 0.3
                + avg_kappa * 0.2
                + (1.0 - avg_nmae) * 0.1
            )

            rater_quality.append({
                '标注员': str(target_rater),
                '有效对比数': len(all_spearmans),
                '平均斯皮尔曼_ρ': round(avg_spearman, 3),
                '平均ICC(2,1)': round(avg_icc, 3),
                '平均加权Kappa': round(avg_kappa, 3),
                '平均归一化MAE': round(avg_nmae, 3),
                '综合质量得分': round(composite, 3),
            })

        df = pd.DataFrame(rater_quality)
        if not df.empty:
            df = df.sort_values('综合质量得分', ascending=False).reset_index(drop=True)
            df.insert(0, '组内一致性排名', df.index + 1)
            df['成绩等级'] = pd.cut(
                df['综合质量得分'],
                bins=[0, 0.4, 0.6, 0.8, 1.0],
                labels=['待提升', '合格', '良好', '优秀'],
                include_lowest=True
            )
        print(f"    完成: {len(df)} 位标注员")
        return df

    def analyze_rater_vs_expert(self) -> pd.DataFrame:
        if self.expert_scores.empty or self.rater_scores.empty:
            return pd.DataFrame()

        print("   - 计算标注员与专家一致性...")
        expert = self.expert_scores.copy()
        expert['task_id'] = expert['qid'].astype(str) + '_' + expert['model'].astype(str)
        results = []

        for rater in self.rater_scores['rater'].unique():
            rater_data = self.rater_scores[self.rater_scores['rater'] == rater]
            rater_avg = rater_data.groupby(['qid', 'model'])['score'].mean().reset_index()
            rater_avg['task_id'] = rater_avg['qid'].astype(str) + '_' + rater_avg['model'].astype(str)
            merged = rater_avg.merge(expert[['task_id', 'score']], on='task_id', suffixes=('_rater', '_expert'))

            if len(merged) < MIN_SAMPLE_FOR_CORRELATION:
                continue
            try:
                spearman_r = spearmanr(merged['score_rater'], merged['score_expert'])[0]
            except Exception:
                spearman_r = np.nan
            icc = ScientificMetrics.icc_2_1(merged['score_rater'].values, merged['score_expert'].values)
            kappa = ScientificMetrics.cohens_kappa_weighted(merged['score_rater'].values, merged['score_expert'].values)
            mae = float(np.abs(merged['score_rater'] - merged['score_expert']).mean())
            nmae = ScientificMetrics.normalized_mae(merged['score_rater'].values, merged['score_expert'].values)

            results.append({
                '标注员': str(rater),
                '共同任务数': len(merged),
                '与专家一致性_斯皮尔曼': round(spearman_r, 3) if not np.isnan(spearman_r) else 'N/A',
                '与专家_ICC': round(icc, 3) if not np.isnan(icc) else 'N/A',
                '与专家_加权Kappa': round(kappa, 3) if not np.isnan(kappa) else 'N/A',
                '与专家_MAE': round(mae, 2),
                '与专家_归一化MAE': round(nmae, 3) if not np.isnan(nmae) else 'N/A',
            })

        df = pd.DataFrame(results)
        if not df.empty:
            df['_sort'] = pd.to_numeric(df['与专家一致性_斯皮尔曼'], errors='coerce')
            df = df.sort_values('_sort', ascending=False).drop('_sort', axis=1).reset_index(drop=True)
            df.insert(0, '与专家一致性排名', df.index + 1)
        print(f"    完成: {len(df)} 位标注员")
        return df

    def analyze_human_avg_vs_expert(self) -> pd.DataFrame:
        if self.expert_scores.empty or self.rater_scores.empty:
            return pd.DataFrame()

        human_avg = (
            self.rater_scores.groupby(['qid', 'model'])['score']
            .mean()
            .reset_index()
            .rename(columns={'score': 'human_avg_score'})
        )
        human_avg['task_id'] = human_avg['qid'].astype(str) + '_' + human_avg['model'].astype(str)
        expert = self.expert_scores.copy()
        expert['task_id'] = expert['qid'].astype(str) + '_' + expert['model'].astype(str)
        merged = human_avg.merge(expert[['task_id', 'score']], on='task_id')

        if len(merged) < MIN_SAMPLE_FOR_CORRELATION:
            return pd.DataFrame()

        icc = ScientificMetrics.icc_2_1(merged['human_avg_score'].values, merged['score'].values)
        nmae = ScientificMetrics.normalized_mae(merged['human_avg_score'].values, merged['score'].values)
        try:
            spearman_r = spearmanr(merged['human_avg_score'], merged['score'])[0]
        except Exception:
            spearman_r = np.nan
        mae = float(np.abs(merged['human_avg_score'] - merged['score']).mean())

        return pd.DataFrame([{
            '对比对象': '人工均分 vs 专家',
            '共同任务数': len(merged),
            '共同题目数': merged['qid'].nunique(),
            '斯皮尔曼_ρ': round(spearman_r, 3) if not np.isnan(spearman_r) else 'N/A',
            'ICC(2,1)': round(icc, 3) if not np.isnan(icc) else 'N/A',
            'MAE': round(mae, 2),
            '归一化MAE': round(nmae, 3) if not np.isnan(nmae) else 'N/A',
        }])


class ModelReliabilityAnalyzer:

    def __init__(self, data: dict):
        self.replies = data['replies']
        self.expert_scores = data['expert_scores']

    def analyze_model_vs_expert(self) -> tuple:
        if self.expert_scores.empty:
            return pd.DataFrame(), pd.DataFrame()

        print("   - 计算模型与专家一致性...")
        expert = self.expert_scores.rename(columns={'score': 'expert_score'})
        model = self.replies[['qid', 'model', 'eval_score']].dropna().rename(columns={'eval_score': 'model_score'})
        merged = model.merge(expert, on=['qid', 'model'], how='inner')

        if len(merged) < MIN_SAMPLE_FOR_CORRELATION:
            return pd.DataFrame(), pd.DataFrame()

        try:
            pearson_r = pearsonr(merged['model_score'], merged['expert_score'])[0]
            spearman_r = spearmanr(merged['model_score'], merged['expert_score'])[0]
        except Exception:
            pearson_r, spearman_r = np.nan, np.nan

        icc = ScientificMetrics.icc_2_1(merged['model_score'].values, merged['expert_score'].values)
        mae = float(np.abs(merged['model_score'] - merged['expert_score']).mean())
        rmse = float(np.sqrt(((merged['model_score'] - merged['expert_score']) ** 2).mean()))
        nmae = ScientificMetrics.normalized_mae(merged['model_score'].values, merged['expert_score'].values)

        overall_df = pd.DataFrame([{
            '对比维度': '整体',
            '样本量': len(merged),
            '题目数': merged['qid'].nunique(),
            '模型数': merged['model'].nunique(),
            '皮尔逊_r': round(pearson_r, 3) if not np.isnan(pearson_r) else 'N/A',
            '斯皮尔曼_ρ': round(spearman_r, 3) if not np.isnan(spearman_r) else 'N/A',
            'ICC(2,1)': round(icc, 3) if not np.isnan(icc) else 'N/A',
            'MAE': round(mae, 2),
            'RMSE': round(rmse, 2),
            '归一化MAE': round(nmae, 3) if not np.isnan(nmae) else 'N/A',
        }])

        model_results = []
        for model_name in merged['model'].unique():
            m_data = merged[merged['model'] == model_name]
            if len(m_data) < MIN_SAMPLE_FOR_CORRELATION:
                continue
            try:
                spearman_m = spearmanr(m_data['model_score'], m_data['expert_score'])[0]
            except Exception:
                spearman_m = np.nan
            m_icc = ScientificMetrics.icc_2_1(m_data['model_score'].values, m_data['expert_score'].values)
            m_mae = float(np.abs(m_data['model_score'] - m_data['expert_score']).mean())
            m_nmae = ScientificMetrics.normalized_mae(m_data['model_score'].values, m_data['expert_score'].values)
            model_results.append({
                '模型': model_name,
                '样本量': len(m_data),
                '斯皮尔曼_ρ': round(spearman_m, 3) if not np.isnan(spearman_m) else 'N/A',
                'ICC(2,1)': round(m_icc, 3) if not np.isnan(m_icc) else 'N/A',
                'MAE': round(m_mae, 2),
                '归一化MAE': round(m_nmae, 3) if not np.isnan(m_nmae) else 'N/A',
                '模型均分': round(float(m_data['model_score'].mean()), 2),
                '专家均分': round(float(m_data['expert_score'].mean()), 2),
                '均分差': round(float(m_data['model_score'].mean() - m_data['expert_score'].mean()), 2),
            })

        model_df = pd.DataFrame(model_results)
        if not model_df.empty:
            model_df['_sort'] = pd.to_numeric(model_df['斯皮尔曼_ρ'], errors='coerce')
            model_df = model_df.sort_values('_sort', ascending=False).drop('_sort', axis=1).reset_index(drop=True)
            model_df.insert(0, '与专家一致性排名', model_df.index + 1)

        print(f"    完成: {len(model_df)} 个模型")
        return overall_df, model_df

    def analyze_model_ranking_consistency(self) -> tuple:
        if self.expert_scores.empty:
            return pd.DataFrame(), pd.DataFrame()

        print("   - 计算模型排名一致性...")
        expert = self.expert_scores.rename(columns={'score': 'expert_score'})
        model = self.replies[['qid', 'model', 'eval_score']].dropna().rename(columns={'eval_score': 'model_score'})
        merged = model.merge(expert, on=['qid', 'model'], how='inner')

        if len(merged) < MIN_SAMPLE_FOR_CORRELATION:
            return pd.DataFrame(), pd.DataFrame()

        model_rank = merged.groupby('model')['model_score'].mean().rank(ascending=False, method='dense')
        expert_rank = merged.groupby('model')['expert_score'].mean().rank(ascending=False, method='dense')
        common_models = set(model_rank.index) & set(expert_rank.index)

        if len(common_models) < MIN_MODELS_PER_QUESTION:
            return pd.DataFrame(), pd.DataFrame()

        m_list = [model_rank[m] for m in common_models]
        e_list = [expert_rank[m] for m in common_models]
        rank_corr = np.nan
        if len(m_list) >= MIN_SAMPLE_FOR_CORRELATION:
            try:
                rank_corr = spearmanr(m_list, e_list)[0]
            except Exception:
                pass

        comparison = []
        for m in common_models:
            comparison.append({
                '模型': m,
                '模型排名': int(model_rank[m]),
                '专家排名': int(expert_rank[m]),
                '排名偏差': int(model_rank[m] - expert_rank[m]),
            })
        comparison_df = pd.DataFrame(comparison).sort_values('专家排名').reset_index(drop=True)

        summary_df = pd.DataFrame([{
            '分析维度': '整体排名',
            '模型数量': len(common_models),
            '排名一致性_斯皮尔曼': round(rank_corr, 3) if not np.isnan(rank_corr) else 'N/A',
            '完全一致模型数': int((comparison_df['排名偏差'] == 0).sum()),
            '完全一致比例': round(float((comparison_df['排名偏差'] == 0).mean()), 3),
            '平均绝对偏差': round(float(comparison_df['排名偏差'].abs().mean()), 2),
            '最大偏差': int(comparison_df['排名偏差'].abs().max()),
        }])

        print(f"    完成: 整体ρ={round(rank_corr, 3) if not np.isnan(rank_corr) else 'N/A'}")
        return summary_df, comparison_df

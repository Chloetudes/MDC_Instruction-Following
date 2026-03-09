# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd
from scipy.stats import spearmanr, kendalltau, pearsonr

from .metrics import ScientificMetrics

MIN_SAMPLE_FOR_CORRELATION = 3   # 至少 3 条回复同时有专家分与模型分即算一致性（含 ICC）；例如 1 道题下 ref+reply1+reply2 共 3 条即可
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

    def _rater_scores_on_expert_tasks(self) -> pd.DataFrame:
        """仅保留专家评估过的 (qid, model) 上的标注员打分，用于组内一致性与专家一致性。"""
        if self.rater_scores.empty:
            return self.rater_scores
        if self.expert_scores.empty:
            return self.rater_scores
        expert_tasks = set(
            zip(self.expert_scores['qid'].astype(str), self.expert_scores['model'].astype(str))
        )
        keys = list(zip(self.rater_scores['qid'].astype(str), self.rater_scores['model'].astype(str)))
        mask = pd.Series(keys).isin(expert_tasks)
        return self.rater_scores.loc[mask].copy()

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
            avg_icc = float(np.mean(all_iccs)) if all_iccs else None
            avg_kappa = float(np.mean(all_kappas)) if all_kappas else None
            avg_nmae = float(np.mean(all_nmaes)) if all_nmaes else None

            weight_map = {'spearman': (avg_spearman, 0.4)}
            if avg_icc is not None:
                weight_map['icc'] = (avg_icc, 0.3)
            if avg_kappa is not None:
                weight_map['kappa'] = (avg_kappa, 0.2)
            if avg_nmae is not None:
                weight_map['nmae'] = (1.0 - avg_nmae, 0.1)

            total_weight = sum(w for _, w in weight_map.values())
            composite = sum(v * w for v, w in weight_map.values()) / total_weight if total_weight > 0 else 0.0

            rater_quality.append({
                '标注员': str(target_rater),
                '有效对比数': len(all_spearmans),
                '平均斯皮尔曼_ρ': round(avg_spearman, 3),
                '平均ICC(2,1)': round(avg_icc, 3) if avg_icc is not None else np.nan,
                '平均加权Kappa': round(avg_kappa, 3) if avg_kappa is not None else np.nan,
                '平均归一化MAE': round(avg_nmae, 3) if avg_nmae is not None else np.nan,
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

        # 仅在专家评估过的 (qid, model) 上计算
        rater_scores_scope = self._rater_scores_on_expert_tasks()
        if rater_scores_scope.empty:
            return pd.DataFrame()

        print("   - 计算标注员与专家一致性（仅专家评估过的题目×模型）...")
        expert = self.expert_scores.copy()
        expert['task_id'] = expert['qid'].astype(str) + '_' + expert['model'].astype(str)
        results = []

        for rater in rater_scores_scope['rater'].unique():
            rater_data = rater_scores_scope[rater_scores_scope['rater'] == rater]
            rater_avg = rater_data.groupby(['qid', 'model'])['score'].mean().reset_index()
            rater_avg['task_id'] = rater_avg['qid'].astype(str) + '_' + rater_avg['model'].astype(str)
            merged = rater_avg.merge(expert[['task_id', 'score']], on='task_id', suffixes=('_rater', '_expert'))

            if len(merged) < MIN_SAMPLE_FOR_CORRELATION:
                continue
            try:
                spearman_r = spearmanr(merged['score_rater'], merged['score_expert'])[0]
            except Exception:
                spearman_r = np.nan
            try:
                pearson_r = pearsonr(merged['score_rater'], merged['score_expert'])[0]
            except Exception:
                pearson_r = np.nan
            icc = ScientificMetrics.icc_2_1(merged['score_rater'].values, merged['score_expert'].values)
            kappa = ScientificMetrics.cohens_kappa_weighted(merged['score_rater'].values, merged['score_expert'].values)
            mae = float(np.abs(merged['score_rater'] - merged['score_expert']).mean())
            nmae = ScientificMetrics.normalized_mae(merged['score_rater'].values, merged['score_expert'].values)

            results.append({
                '标注员': str(rater),
                '共同任务数': len(merged),
                '与专家_斯皮尔曼': round(spearman_r, 3) if not np.isnan(spearman_r) else 'N/A',
                '与专家_Pearson': round(pearson_r, 3) if not np.isnan(pearson_r) else 'N/A',
                '与专家_ICC': round(icc, 3) if not np.isnan(icc) else 'N/A',
                '与专家_加权Kappa': round(kappa, 3) if not np.isnan(kappa) else 'N/A',
                '与专家_MAE': round(mae, 2),
                '与专家_归一化MAE': round(nmae, 3) if not np.isnan(nmae) else 'N/A',
            })

        df = pd.DataFrame(results)
        if not df.empty:
            df['_sort'] = pd.to_numeric(df['与专家_斯皮尔曼'], errors='coerce')
            df = df.sort_values('_sort', ascending=False).drop('_sort', axis=1).reset_index(drop=True)
            df.insert(0, '与专家一致性排名', df.index + 1)
        print(f"    完成: {len(df)} 位标注员")
        return df

    def analyze_human_avg_vs_expert(self) -> pd.DataFrame:
        if self.expert_scores.empty or self.rater_scores.empty:
            return pd.DataFrame()

        # 仅在专家评估过的 (qid, model) 上计算人工均分 vs 专家
        rater_scores_scope = self._rater_scores_on_expert_tasks()
        if rater_scores_scope.empty:
            return pd.DataFrame()

        human_avg = (
            rater_scores_scope.groupby(['qid', 'model'])['score']
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
        try:
            pearson_r = pearsonr(merged['human_avg_score'], merged['score'])[0]
        except Exception:
            pearson_r = np.nan
        mae = float(np.abs(merged['human_avg_score'] - merged['score']).mean())

        return pd.DataFrame([{
            '对比对象': '人工均分 vs 专家',
            '共同任务数': len(merged),
            '共同题目数': merged['qid'].nunique(),
            '斯皮尔曼_ρ': round(spearman_r, 3) if not np.isnan(spearman_r) else 'N/A',
            'Pearson_r': round(pearson_r, 3) if not np.isnan(pearson_r) else 'N/A',
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
                pearson_m = pearsonr(m_data['model_score'], m_data['expert_score'])[0]
            except Exception:
                spearman_m, pearson_m = np.nan, np.nan
            m_icc = ScientificMetrics.icc_2_1(m_data['model_score'].values, m_data['expert_score'].values)
            m_mae = float(np.abs(m_data['model_score'] - m_data['expert_score']).mean())
            m_nmae = ScientificMetrics.normalized_mae(m_data['model_score'].values, m_data['expert_score'].values)
            m_diff = np.abs(m_data['model_score'].values - m_data['expert_score'].values)
            m_exact_pct = round(float(np.mean(m_diff == 0)) * 100, 1)
            m_within05_pct = round(float(np.mean(m_diff <= 0.5)) * 100, 1)
            model_results.append({
                '模型': model_name,
                '样本量': len(m_data),
                '皮尔逊_r': round(pearson_m, 3) if not np.isnan(pearson_m) else 'N/A',
                '斯皮尔曼_ρ': round(spearman_m, 3) if not np.isnan(spearman_m) else 'N/A',
                'ICC(2,1)': round(m_icc, 3) if not np.isnan(m_icc) else 'N/A',
                '准确率(%)': m_exact_pct,
                '容差准确率_±0.5分(%)': m_within05_pct,
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


class ExpertHumanMachineConsistencyAnalyzer:
    """
    专家人机一致性分析：按专家（专家列）统计每题人机一致性及专家综合人机一致性。
    用于检验专家 rubrics 质量：若 rubrics 细致、覆盖多种模型回复，则人机打分一致性高。
    """

    def __init__(self, data: dict):
        self.replies = data['replies']
        self.expert_scores = data['expert_scores']

    def analyze(self) -> tuple:
        """
        按专家统计人机一致性。
        Returns:
            expert_summary: 每位专家的综合人机一致性。
                专家评估数 = 该专家在回复表中有「专家打分」的条数。只要专家打分非空且该行有模型评估分数即参与统计；部分题目无 ref/reply 不影响已评估数据，AI 会评估所有回复。
            expert_per_question: 每位专家每道题的人机一致性明细
        """
        if self.expert_scores.empty or self.replies.empty:
            return pd.DataFrame(), pd.DataFrame()

        model_scores = self.replies[['qid', 'model', 'eval_score']].dropna()
        experts = self.expert_scores['rater'].unique()

        # 单专家时无需按人拆分，但仍可输出整体一致性供参考
        expert_summary_rows = []
        expert_per_question_rows = []

        for expert in experts:
            exp_data = self.expert_scores[self.expert_scores['rater'] == expert].copy()
            merged = exp_data.merge(model_scores, on=['qid', 'model'], how='inner')

            # 每题人机一致性：一题有 ref+reply1+reply2 即 3 对人机分，每题都算斯皮尔曼与 ICC，写入题目反馈
            per_q_corrs = []
            for qid in merged['qid'].unique():
                q_data = merged[merged['qid'] == qid]
                if len(q_data) < MIN_MODELS_PER_QUESTION:
                    continue
                r_val = np.nan
                try:
                    r_val, _ = spearmanr(q_data['score'], q_data['eval_score'])
                except Exception:
                    pass
                if not np.isnan(r_val):
                    per_q_corrs.append(r_val)
                icc_q = np.nan
                try:
                    icc_q = ScientificMetrics.icc_2_1(q_data['score'].values, q_data['eval_score'].values)
                except Exception:
                    pass
                expert_per_question_rows.append({
                    '专家': str(expert),
                    'qid': str(qid),
                    '共同模型数': len(q_data),
                    '人机一致性_斯皮尔曼': round(r_val, 3) if not np.isnan(r_val) else np.nan,
                    '人机一致性_ICC': round(icc_q, 3) if not np.isnan(icc_q) else np.nan,
                })

            n_pairs = len(merged)
            if n_pairs < MIN_SAMPLE_FOR_CORRELATION:
                expert_summary_rows.append({
                    '专家': str(expert),
                    '评估题目数': merged['qid'].nunique() if not merged.empty else 0,
                    '专家评估数': len(exp_data),
                    '有效人机对数': n_pairs,
                    '每题人机一致性_斯皮尔曼均值': 'N/A',
                    '综合人机一致性_斯皮尔曼': 'N/A',
                    '综合人机一致性_ICC': 'N/A',
                    '综合人机一致性_MAE': 'N/A',
                })
                continue

            try:
                spearman_overall = spearmanr(merged['score'], merged['eval_score'])[0]
            except Exception:
                spearman_overall = np.nan
            icc = ScientificMetrics.icc_2_1(merged['score'].values, merged['eval_score'].values)
            mae = float(np.abs(merged['score'] - merged['eval_score']).mean())

            # 有效人机对数 = 同时有专家打分与模型评估分数的条数，≥3 才计算 ICC
            expert_summary_rows.append({
                '专家': str(expert),
                '评估题目数': merged['qid'].nunique(),
                '专家评估数': len(exp_data),
                '有效人机对数': len(merged),
                '每题人机一致性_斯皮尔曼均值': round(float(np.mean(per_q_corrs)), 3) if per_q_corrs else 'N/A',
                '综合人机一致性_斯皮尔曼': round(spearman_overall, 3) if not np.isnan(spearman_overall) else 'N/A',
                '综合人机一致性_ICC': round(icc, 3) if not np.isnan(icc) else 'N/A',
                '综合人机一致性_MAE': round(mae, 2),
            })

        summary_df = pd.DataFrame(expert_summary_rows)
        if not summary_df.empty:
            summary_df['_sort'] = pd.to_numeric(summary_df['每题人机一致性_斯皮尔曼均值'], errors='coerce')
            summary_df = summary_df.sort_values('_sort', ascending=False).drop('_sort', axis=1).reset_index(drop=True)
            summary_df.insert(0, '人机一致性排名', summary_df.index + 1)

        per_q_df = pd.DataFrame(expert_per_question_rows)
        print(f"   - 专家人机一致性: {len(summary_df)} 位专家")
        return summary_df, per_q_df

# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd

from .metrics import ScientificMetrics


class ValuableQuestionAnalyzer:

    def __init__(self, data: dict):
        self.replies = data['replies_with_question']
        self.questions = data['questions']
        self.expert_scores = data.get('expert_scores', pd.DataFrame())
        self.rater_scores = data.get('rater_scores', pd.DataFrame())

    @staticmethod
    def _safe_str(value, max_len: int = 200) -> str:
        if value is None:
            return ''
        try:
            s = str(value)
            return s[:max_len] + '...' if len(s) > max_len else s
        except Exception:
            return ''

    @staticmethod
    def _safe_float(value, default=np.nan) -> float:
        try:
            return float(value)
        except Exception:
            return default

    def find_top20_valuable_questions(self) -> pd.DataFrame:
        print("   - 计算价值题目TOP20...")
        results = []

        for qid in self.replies['qid'].unique():
            q_data = self.replies[self.replies['qid'] == qid]
            scores = q_data['eval_score'].dropna()
            if len(scores) < 5:
                continue

            mean_score = self._safe_float(scores.mean())
            std_score = self._safe_float(scores.std())
            discrimination = self._safe_float(ScientificMetrics.discrimination_index(scores))

            expert_mean = np.nan
            expert_comment = ''
            if not self.expert_scores.empty:
                expert_data = self.expert_scores[self.expert_scores['qid'] == str(qid)]
                if not expert_data.empty:
                    expert_mean = self._safe_float(expert_data['score'].mean())
                    comments = expert_data['reason'].dropna()
                    if len(comments) > 0:
                        expert_comment = self._safe_str(comments.iloc[0], 200)

            model_avg = q_data.groupby('model')['eval_score'].mean()
            model_diff = self._safe_float(model_avg.max() - model_avg.min()) if len(model_avg) >= 2 else np.nan

            cv = std_score / mean_score if mean_score > 0 else 0
            difficulty_p = mean_score / 100
            difficulty_suitability = 1 - abs(difficulty_p - 0.5) * 2
            expert_bias = abs(mean_score - expert_mean) if not np.isnan(expert_mean) else 50
            expert_bias_norm = 1 - (expert_bias / 100)

            value_score = (
                discrimination * 0.35
                + (std_score / 100) * 0.25
                + cv * 0.15
                + difficulty_suitability * 0.15
                + expert_bias_norm * 0.10
            )

            q_info = self.questions[self.questions['qid'] == qid]

            human_comment = ''
            if not self.rater_scores.empty:
                q_rater = self.rater_scores[self.rater_scores['qid'] == str(qid)]
                comments = []
                for _, row in q_rater.iterrows():
                    raw = row.get('raw_eval', '')
                    if pd.notna(raw) and str(raw):
                        comments.append(f"{self._safe_str(row['rater'])}: {self._safe_str(raw, 100)}")
                human_comment = ' | '.join(comments[:2])

            best_model = self._safe_str(model_avg.idxmax()) if len(model_avg) > 0 else 'N/A'
            best_score = self._safe_float(model_avg.max()) if len(model_avg) > 0 else np.nan
            worst_model = self._safe_str(model_avg.idxmin()) if len(model_avg) > 0 else 'N/A'
            worst_score = self._safe_float(model_avg.min()) if len(model_avg) > 0 else np.nan

            def _get_q_field(field):
                return self._safe_str(q_info[field].iloc[0]) if not q_info.empty and field in q_info.columns else ''

            results.append({
                'qid': str(qid),
                'L1': _get_q_field('L1'),
                'L2': _get_q_field('L2'),
                'L3': _get_q_field('L3'),
                '数据来源': _get_q_field('source'),
                '预设难度': _get_q_field('difficulty_level'),
                '模型均分': round(mean_score, 2) if not np.isnan(mean_score) else 'N/A',
                '标准差': round(std_score, 2) if not np.isnan(std_score) else 'N/A',
                '区分度_D值': round(discrimination, 3) if not np.isnan(discrimination) else 'N/A',
                '变异系数': round(cv, 3) if not np.isnan(cv) else 'N/A',
                '专家均分': round(expert_mean, 2) if not np.isnan(expert_mean) else 'N/A',
                '模型专家偏差': round(expert_bias, 2) if not np.isnan(expert_bias) else 'N/A',
                '模型分差': round(model_diff, 2) if not np.isnan(model_diff) else 'N/A',
                '综合价值分': round(value_score, 4) if not np.isnan(value_score) else 'N/A',
                '最佳模型': best_model,
                '最佳得分': round(best_score, 2) if not np.isnan(best_score) else 'N/A',
                '最差模型': worst_model,
                '最差得分': round(worst_score, 2) if not np.isnan(worst_score) else 'N/A',
                '专家核心意见': expert_comment,
                '人工标注意见': human_comment,
            })

        df = pd.DataFrame(results)
        if not df.empty:
            df['_sort'] = pd.to_numeric(df['综合价值分'], errors='coerce')
            df = df.nlargest(20, '_sort').drop('_sort', axis=1).reset_index(drop=True)
            df.insert(0, '排名', range(1, len(df) + 1))

        print(f"    完成: {len(df)} 道价值题目")
        return df

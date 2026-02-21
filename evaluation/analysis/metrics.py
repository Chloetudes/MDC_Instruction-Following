# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import confusion_matrix


class ScientificMetrics:

    @staticmethod
    def cronbach_alpha(df: pd.DataFrame) -> float:
        if df is None or df.empty or len(df.columns) < 2:
            return np.nan
        try:
            items = df.values.T
            n_items = items.shape[0]
            item_variances = np.var(items, axis=1, ddof=1)
            total_variance = np.var(np.sum(items, axis=0), ddof=1)
            if total_variance == 0:
                return np.nan
            alpha = (n_items / (n_items - 1)) * (1 - np.sum(item_variances) / total_variance)
            return round(alpha, 3)
        except Exception:
            return np.nan

    @staticmethod
    def icc_2_1(scores1: np.ndarray, scores2: np.ndarray) -> float:
        """
        ICC(2,1) — 双因素随机效应模型，单次测量绝对一致性。
        适用于两位评分者对同一批对象独立评分的场景。

        公式：ICC = (MS_between - MS_error) / (MS_between + (k-1)*MS_error + k*(MS_rater - MS_error)/n)
        其中 k=2（评分者数），n=样本量。
        """
        if scores1 is None or scores2 is None:
            return np.nan
        n = len(scores1)
        if n < 2 or len(scores2) != n:
            return np.nan
        try:
            scores_matrix = np.column_stack([scores1, scores2])
            grand_mean = np.mean(scores_matrix)
            subject_means = np.mean(scores_matrix, axis=1)
            rater_means = np.mean(scores_matrix, axis=0)

            k = 2
            ss_between_subjects = k * np.sum((subject_means - grand_mean) ** 2)
            ss_between_raters = n * np.sum((rater_means - grand_mean) ** 2)
            ss_total = np.sum((scores_matrix - grand_mean) ** 2)
            ss_error = ss_total - ss_between_subjects - ss_between_raters

            df_between_subjects = n - 1
            df_between_raters = k - 1
            df_error = (n - 1) * (k - 1)

            if df_between_subjects == 0 or df_error == 0:
                return np.nan

            ms_between = ss_between_subjects / df_between_subjects
            ms_rater = ss_between_raters / df_between_raters
            ms_error = ss_error / df_error

            denominator = ms_between + (k - 1) * ms_error + k * (ms_rater - ms_error) / n
            if denominator <= 0:
                return np.nan

            icc = (ms_between - ms_error) / denominator
            return round(float(np.clip(icc, -1.0, 1.0)), 3)
        except Exception:
            return np.nan

    @staticmethod
    def discrimination_index(scores: pd.Series) -> float:
        if scores is None or len(scores) < 10:
            return 0
        try:
            sorted_scores = scores.sort_values()
            n_27 = max(1, int(len(scores) * 0.27))
            high_group = sorted_scores.tail(n_27).mean()
            low_group = sorted_scores.head(n_27).mean()
            score_range = scores.max() - scores.min()
            if score_range > 0:
                return round((high_group - low_group) / score_range, 3)
            return 0
        except Exception:
            return 0

    @staticmethod
    def cohens_kappa_weighted(y1: np.ndarray, y2: np.ndarray) -> float:
        """
        加权 Kappa（线性权重）。
        使用基于实际数据范围的分箱，避免空 bin 导致的计算不稳定。
        """
        if y1 is None or y2 is None or len(y1) < 5 or len(y2) < 5:
            return np.nan
        try:
            y1 = np.asarray(y1, dtype=float)
            y2 = np.asarray(y2, dtype=float)
            combined = np.concatenate([y1, y2])
            score_min = combined.min()
            score_max = combined.max()

            if score_max == score_min:
                return np.nan

            n_bins = 5
            bin_edges = np.linspace(score_min, score_max + 1e-9, n_bins + 1)
            y1_bin = np.digitize(y1, bin_edges[1:-1])
            y2_bin = np.digitize(y2, bin_edges[1:-1])

            cm = confusion_matrix(y1_bin, y2_bin, labels=range(n_bins))
            row_marg = cm.sum(axis=1)
            col_marg = cm.sum(axis=0)
            total = cm.sum()
            if total == 0:
                return np.nan

            expected = np.outer(row_marg, col_marg) / total
            weights_matrix = 1 - np.abs(
                np.subtract.outer(range(n_bins), range(n_bins))
            ) / (n_bins - 1)

            observed_weighted = np.sum(weights_matrix * cm) / total
            expected_weighted = np.sum(weights_matrix * expected) / total

            if 1 - expected_weighted == 0:
                return 1.0 if observed_weighted == expected_weighted else np.nan

            kappa = (observed_weighted - expected_weighted) / (1 - expected_weighted)
            return round(float(kappa), 3)
        except Exception:
            return np.nan

    @staticmethod
    def cohens_d(scores1: np.ndarray, scores2: np.ndarray) -> float:
        if scores1 is None or scores2 is None:
            return np.nan
        n1, n2 = len(scores1), len(scores2)
        if n1 < 2 or n2 < 2:
            return np.nan
        try:
            mean1, mean2 = np.mean(scores1), np.mean(scores2)
            var1, var2 = np.var(scores1, ddof=1), np.var(scores2, ddof=1)
            pooled_std = np.sqrt(((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2))
            if pooled_std == 0:
                return 0
            return round((mean1 - mean2) / pooled_std, 3)
        except Exception:
            return np.nan

    @staticmethod
    def kendall_w(ranks_df: pd.DataFrame) -> float:
        if ranks_df is None or ranks_df.empty or len(ranks_df.columns) < 2:
            return np.nan
        try:
            n_items = len(ranks_df)
            n_judges = len(ranks_df.columns)
            row_sums = ranks_df.sum(axis=1)
            mean_sum = row_sums.mean()
            S = np.sum((row_sums - mean_sum) ** 2)
            max_S = (n_judges ** 2 * (n_items ** 3 - n_items)) / 12
            if max_S > 0:
                return round(S / max_S, 3)
            return 0
        except Exception:
            return np.nan

    @staticmethod
    def normalized_mae(scores1: np.ndarray, scores2: np.ndarray, score_range: float = None) -> float:
        """
        归一化 MAE（相对于评分范围），范围 [0, 1]，越小越好。
        score_range 为 None 时自动从数据推断。
        """
        if scores1 is None or scores2 is None or len(scores1) < 2:
            return np.nan
        try:
            mae = float(np.abs(np.asarray(scores1) - np.asarray(scores2)).mean())
            if score_range is None:
                combined = np.concatenate([scores1, scores2])
                score_range = combined.max() - combined.min()
            if score_range <= 0:
                return 0.0
            return round(mae / score_range, 3)
        except Exception:
            return np.nan

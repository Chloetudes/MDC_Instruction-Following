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
        if scores1 is None or scores2 is None:
            return np.nan
        n = len(scores1)
        if n < 2 or len(scores2) < 2:
            return np.nan
        try:
            target_means = (scores1 + scores2) / 2
            grand_mean = np.mean(np.concatenate([scores1, scores2]))
            ms_between = np.sum((target_means - grand_mean) ** 2) * 2 / (n - 1) if n > 1 else 0
            diff = scores1 - scores2
            ss_residual = np.sum(diff ** 2) / 2
            ms_residual = ss_residual / (n - 1) if n > 1 else 0
            if ms_between + ms_residual > 0:
                return round((ms_between - ms_residual) / (ms_between + ms_residual), 3)
            return 0
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
        if y1 is None or y2 is None or len(y1) < 5 or len(y2) < 5:
            return np.nan
        try:
            n_bins = 5
            y1_bin = pd.cut(y1, bins=n_bins, labels=False)
            y2_bin = pd.cut(y2, bins=n_bins, labels=False)
            cm = confusion_matrix(y1_bin, y2_bin, labels=range(n_bins))
            row_marg = cm.sum(axis=1)
            col_marg = cm.sum(axis=0)
            n = cm.sum()
            if n == 0:
                return np.nan
            expected = np.outer(row_marg, col_marg) / n
            weights_matrix = 1 - np.abs(np.subtract.outer(range(n_bins), range(n_bins))) / (n_bins - 1)
            observed = np.sum(weights_matrix * cm) / n
            expected_weighted = np.sum(weights_matrix * expected) / n
            if expected_weighted == 1:
                return 1
            if 1 - expected_weighted == 0:
                return 0
            return round((observed - expected_weighted) / (1 - expected_weighted), 3)
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

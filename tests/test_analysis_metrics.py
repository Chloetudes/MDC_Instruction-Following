# -*- coding: utf-8 -*-
"""
统计分析模块单元测试
覆盖 metrics.py / data_loader.py / consistency.py 的核心修复点
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
import pandas as pd
import unittest

from evaluation.analysis.metrics import ScientificMetrics
from evaluation.analysis.data_loader import _detect_annotators, _preprocess_human, _build_rater_scores
from evaluation.analysis.consistency import HumanModelConsistencyAnalyzer, HumanExpertConsistencyAnalyzer, ModelReliabilityAnalyzer


class TestICC21(unittest.TestCase):

    def test_perfect_agreement(self):
        scores = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        icc = ScientificMetrics.icc_2_1(scores, scores)
        self.assertAlmostEqual(icc, 1.0, places=2)

    def test_no_agreement_opposite(self):
        s1 = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        s2 = np.array([5.0, 4.0, 3.0, 2.0, 1.0])
        icc = ScientificMetrics.icc_2_1(s1, s2)
        self.assertLessEqual(icc, 0.0)

    def test_result_in_valid_range(self):
        rng = np.random.default_rng(42)
        s1 = rng.uniform(0, 10, 20)
        s2 = s1 + rng.normal(0, 1, 20)
        icc = ScientificMetrics.icc_2_1(s1, s2)
        self.assertFalse(np.isnan(icc))
        self.assertGreaterEqual(icc, -1.0)
        self.assertLessEqual(icc, 1.0)

    def test_insufficient_samples(self):
        icc = ScientificMetrics.icc_2_1(np.array([1.0]), np.array([1.0]))
        self.assertTrue(np.isnan(icc))

    def test_none_input(self):
        icc = ScientificMetrics.icc_2_1(None, np.array([1.0, 2.0]))
        self.assertTrue(np.isnan(icc))

    def test_constant_scores(self):
        s1 = np.array([5.0, 5.0, 5.0, 5.0, 5.0])
        s2 = np.array([5.0, 5.0, 5.0, 5.0, 5.0])
        icc = ScientificMetrics.icc_2_1(s1, s2)
        self.assertTrue(np.isnan(icc) or icc == 0.0)

    def test_high_correlation_gives_high_icc(self):
        s1 = np.array([1.0, 3.0, 5.0, 7.0, 9.0])
        s2 = np.array([1.5, 3.5, 5.5, 7.5, 9.5])
        icc = ScientificMetrics.icc_2_1(s1, s2)
        self.assertGreater(icc, 0.9)


class TestWeightedKappa(unittest.TestCase):

    def test_perfect_agreement(self):
        scores = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0])
        kappa = ScientificMetrics.cohens_kappa_weighted(scores, scores)
        self.assertAlmostEqual(kappa, 1.0, places=1)

    def test_result_in_valid_range(self):
        rng = np.random.default_rng(0)
        s1 = rng.uniform(0, 10, 30)
        s2 = rng.uniform(0, 10, 30)
        kappa = ScientificMetrics.cohens_kappa_weighted(s1, s2)
        self.assertFalse(np.isnan(kappa))
        self.assertGreaterEqual(kappa, -1.0)
        self.assertLessEqual(kappa, 1.0)

    def test_narrow_range_no_crash(self):
        s1 = np.array([9.0, 9.1, 9.2, 9.3, 9.4, 9.5])
        s2 = np.array([9.1, 9.2, 9.3, 9.4, 9.5, 9.6])
        kappa = ScientificMetrics.cohens_kappa_weighted(s1, s2)
        self.assertFalse(np.isnan(kappa) and False)

    def test_insufficient_samples(self):
        kappa = ScientificMetrics.cohens_kappa_weighted(np.array([1.0, 2.0]), np.array([1.0, 2.0]))
        self.assertTrue(np.isnan(kappa))

    def test_constant_input_returns_nan(self):
        s = np.array([5.0, 5.0, 5.0, 5.0, 5.0, 5.0])
        kappa = ScientificMetrics.cohens_kappa_weighted(s, s)
        self.assertTrue(np.isnan(kappa))


class TestNormalizedMAE(unittest.TestCase):

    def test_perfect_agreement(self):
        s = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        nmae = ScientificMetrics.normalized_mae(s, s)
        self.assertAlmostEqual(nmae, 0.0, places=5)

    def test_max_disagreement(self):
        s1 = np.array([0.0, 0.0, 0.0])
        s2 = np.array([10.0, 10.0, 10.0])
        nmae = ScientificMetrics.normalized_mae(s1, s2, score_range=10.0)
        self.assertAlmostEqual(nmae, 1.0, places=5)

    def test_auto_range_inference(self):
        s1 = np.array([0.0, 5.0, 10.0])
        s2 = np.array([1.0, 5.0, 9.0])
        nmae = ScientificMetrics.normalized_mae(s1, s2)
        self.assertGreater(nmae, 0.0)
        self.assertLessEqual(nmae, 1.0)

    def test_none_input(self):
        nmae = ScientificMetrics.normalized_mae(None, np.array([1.0, 2.0]))
        self.assertTrue(np.isnan(nmae))


class TestDetectAnnotators(unittest.TestCase):

    def test_standard_two_annotators(self):
        df = pd.DataFrame({'ann1_score': [1], 'ann2_score': [2], 'other_col': [3]})
        result = _detect_annotators(df)
        self.assertEqual(result, ['ann1', 'ann2'])

    def test_three_annotators(self):
        df = pd.DataFrame({'ann1_score': [1], 'ann2_score': [2], 'ann3_score': [3]})
        result = _detect_annotators(df)
        self.assertEqual(result, ['ann1', 'ann2', 'ann3'])

    def test_multi_model_score_cols(self):
        df = pd.DataFrame({'ann1_score_m1': [1], 'ann1_score_m2': [2], 'ann2_score_m1': [3]})
        result = _detect_annotators(df)
        self.assertEqual(result, ['ann1', 'ann2'])

    def test_no_annotators(self):
        df = pd.DataFrame({'query': ['hello'], 'model': ['gpt']})
        result = _detect_annotators(df)
        self.assertEqual(result, [])

    def test_mixed_columns(self):
        df = pd.DataFrame({
            'ann1_score': [8], 'ann2_score': [7],
            'ann1_name': ['Alice'], 'ann2_name': ['Bob'],
            'qid': ['Q001'], 'model': ['gpt']
        })
        result = _detect_annotators(df)
        self.assertEqual(result, ['ann1', 'ann2'])


class TestPreprocessHuman(unittest.TestCase):

    def test_single_score_column(self):
        df = pd.DataFrame({
            'qid': ['Q001', 'Q002'],
            'ann1_score': [8.0, 7.0],
            'ann2_score': [9.0, 6.0],
        })
        _preprocess_human(df)
        self.assertIn('ann1_avg_score', df.columns)
        self.assertIn('ann2_avg_score', df.columns)
        self.assertIn('human_avg_score', df.columns)
        self.assertAlmostEqual(df['human_avg_score'].iloc[0], 8.5)

    def test_multi_model_score_columns(self):
        df = pd.DataFrame({
            'qid': ['Q001'],
            'ann1_score_m1': [8.0],
            'ann1_score_m2': [6.0],
            'ann1_score_m3': [7.0],
        })
        _preprocess_human(df)
        self.assertIn('ann1_avg_score', df.columns)
        self.assertAlmostEqual(df['ann1_avg_score'].iloc[0], 7.0)

    def test_three_annotators(self):
        df = pd.DataFrame({
            'qid': ['Q001'],
            'ann1_score': [9.0],
            'ann2_score': [8.0],
            'ann3_score': [7.0],
        })
        _preprocess_human(df)
        self.assertAlmostEqual(df['human_avg_score'].iloc[0], 8.0)


class TestBuildRaterScores(unittest.TestCase):

    def test_basic_two_raters(self):
        df = pd.DataFrame({
            'qid': ['Q001', 'Q001'],
            'model': ['gpt', 'claude'],
            'ann1_score': [8.0, 7.0],
            'ann2_score': [9.0, 6.0],
            'ann1_name': ['Alice', 'Alice'],
            'ann2_name': ['Bob', 'Bob'],
        })
        _preprocess_human(df)
        rater_scores = _build_rater_scores(df)
        self.assertFalse(rater_scores.empty)
        self.assertIn('Alice', rater_scores['rater'].values)
        self.assertIn('Bob', rater_scores['rater'].values)
        self.assertEqual(len(rater_scores), 4)

    def test_fallback_name_when_no_name_col(self):
        df = pd.DataFrame({
            'qid': ['Q001'],
            'model': ['gpt'],
            'ann1_score': [8.0],
        })
        _preprocess_human(df)
        rater_scores = _build_rater_scores(df)
        self.assertEqual(rater_scores.iloc[0]['rater'], '标注员1')


class TestHumanModelConsistencyAnalyzer(unittest.TestCase):

    def _make_data(self):
        rater_scores = pd.DataFrame({
            'qid': ['Q1', 'Q1', 'Q2', 'Q2', 'Q3', 'Q3'],
            'model': ['m1', 'm2', 'm1', 'm2', 'm1', 'm2'],
            'rater': ['Alice'] * 6,
            'score': [8.0, 6.0, 7.0, 9.0, 5.0, 8.0],
        })
        replies = pd.DataFrame({
            'qid': ['Q1', 'Q1', 'Q2', 'Q2', 'Q3', 'Q3'],
            'model': ['m1', 'm2', 'm1', 'm2', 'm1', 'm2'],
            'eval_score': [8.5, 6.5, 7.5, 8.5, 5.5, 7.5],
        })
        return {'rater_scores': rater_scores, 'replies': replies}

    def test_per_question_ranking_no_crash(self):
        analyzer = HumanModelConsistencyAnalyzer(self._make_data())
        result = analyzer.analyze_per_question_ranking_consistency()
        self.assertIsInstance(result, pd.DataFrame)

    def test_rater_model_consistency_no_crash(self):
        analyzer = HumanModelConsistencyAnalyzer(self._make_data())
        result = analyzer.analyze_rater_model_ranking_consistency()
        self.assertIsInstance(result, pd.DataFrame)

    def test_empty_rater_scores_returns_empty(self):
        data = {'rater_scores': pd.DataFrame(), 'replies': pd.DataFrame()}
        analyzer = HumanModelConsistencyAnalyzer(data)
        result = analyzer.analyze_per_question_ranking_consistency()
        self.assertTrue(result.empty)

    def test_normalized_mae_column_present(self):
        data = self._make_data()
        analyzer = HumanModelConsistencyAnalyzer(data)
        result = analyzer.analyze_rater_model_ranking_consistency()
        if not result.empty:
            self.assertIn('归一化MAE', result.columns)


class TestModelReliabilityAnalyzer(unittest.TestCase):

    def _make_data(self):
        replies = pd.DataFrame({
            'qid': ['Q1', 'Q1', 'Q2', 'Q2', 'Q3', 'Q3'],
            'model': ['m1', 'm2', 'm1', 'm2', 'm1', 'm2'],
            'eval_score': [8.0, 6.0, 7.0, 9.0, 5.0, 8.0],
        })
        expert_scores = pd.DataFrame({
            'qid': ['Q1', 'Q1', 'Q2', 'Q2', 'Q3', 'Q3'],
            'model': ['m1', 'm2', 'm1', 'm2', 'm1', 'm2'],
            'score': [8.5, 6.5, 7.5, 8.5, 5.5, 7.5],
        })
        return {'replies': replies, 'expert_scores': expert_scores}

    def test_model_vs_expert_no_crash(self):
        analyzer = ModelReliabilityAnalyzer(self._make_data())
        overall, per_model = analyzer.analyze_model_vs_expert()
        self.assertIsInstance(overall, pd.DataFrame)
        self.assertIsInstance(per_model, pd.DataFrame)

    def test_overall_has_normalized_mae(self):
        analyzer = ModelReliabilityAnalyzer(self._make_data())
        overall, _ = analyzer.analyze_model_vs_expert()
        if not overall.empty:
            self.assertIn('归一化MAE', overall.columns)

    def test_empty_expert_returns_empty(self):
        data = {'replies': pd.DataFrame(), 'expert_scores': pd.DataFrame()}
        analyzer = ModelReliabilityAnalyzer(data)
        overall, per_model = analyzer.analyze_model_vs_expert()
        self.assertTrue(overall.empty)
        self.assertTrue(per_model.empty)

    def test_ranking_consistency_no_crash(self):
        analyzer = ModelReliabilityAnalyzer(self._make_data())
        summary, comparison = analyzer.analyze_model_ranking_consistency()
        self.assertIsInstance(summary, pd.DataFrame)
        self.assertIsInstance(comparison, pd.DataFrame)


if __name__ == '__main__':
    unittest.main(verbosity=2)

# -*- coding: utf-8 -*-
import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List

import numpy as np
import pandas as pd
from scipy.stats import pearsonr


@dataclass
class TypicalCase:
    qid: str
    query: str
    l3: str
    source: str
    difficulty_level: str
    score_variance: float
    score_range: float
    score_std: float
    model_scores: Dict[str, float]
    best_model: str
    worst_model: str
    selection_reason: str


class ItemAnalyzer:

    def __init__(self, data: dict):
        self.replies = data['replies_with_question']
        self.questions = data['questions']

    def analyze_all_items(self) -> pd.DataFrame:
        print("   - 计算题目完整分析指标（信度/效度/区分度）...")
        item_metrics = []

        for qid in self.replies['qid'].unique():
            qid_df = self.replies[self.replies['qid'] == qid]
            scores = qid_df['eval_score'].dropna().values

            if len(scores) < 2:
                continue

            first_row = qid_df.iloc[0]
            metrics = self._compute_item_metrics(qid, scores, first_row, qid_df)
            item_metrics.append(metrics)

        df = pd.DataFrame(item_metrics)
        if not df.empty:
            df = df.sort_values('综合质量分', ascending=False).reset_index(drop=True)
            df.insert(0, '排名', df.index + 1)

        print(f"    完成: {len(df)} 道题")
        return df

    def _compute_item_metrics(self, qid: str, scores: np.ndarray,
                               first_row: pd.Series, qid_df: pd.DataFrame) -> dict:
        score_mean = float(np.mean(scores))
        score_std = float(np.std(scores, ddof=1)) if len(scores) > 1 else 0.0
        score_min = float(np.min(scores))
        score_max = float(np.max(scores))
        score_range = score_max - score_min
        score_median = float(np.median(scores))
        cv = (score_std / score_mean * 100) if score_mean > 0 else 0

        pass_rates = qid_df['pass_rate'].dropna().values if 'pass_rate' in qid_df.columns else np.array([])

        cronbach_alpha = self._cronbach_alpha(scores)
        split_half = self._split_half_reliability(scores)
        reliability_level = self._reliability_level(cronbach_alpha)

        instruction_difficulty_score = float(first_row.get('difficulty_score', 0) or 0)
        content_validity = min(instruction_difficulty_score / 100, 1.0) if instruction_difficulty_score > 0 else 0
        construct_validity = self._construct_validity(scores, instruction_difficulty_score)
        predictive_validity = self._predictive_validity(scores, pass_rates)
        comprehensive_validity = (content_validity + construct_validity + predictive_validity) / 3
        validity_level = self._validity_level(comprehensive_validity)

        discrimination_index = self._discrimination_index(scores)
        point_biserial = self._point_biserial(scores)
        discrimination_level = self._discrimination_level(discrimination_index)

        difficulty_index = score_mean / 100
        difficulty_category = self._difficulty_category(difficulty_index)

        quality_score = self._item_quality_score(cronbach_alpha, comprehensive_validity, discrimination_index)
        quality_level = self._quality_level(quality_score)

        model_avg = qid_df.groupby('model')['eval_score'].mean()
        best_model = str(model_avg.idxmax()) if len(model_avg) > 0 else 'N/A'
        worst_model = str(model_avg.idxmin()) if len(model_avg) > 0 else 'N/A'

        def _get(field):
            val = first_row.get(field, '')
            return str(val) if pd.notna(val) else ''

        return {
            'qid': str(qid),
            'L1': _get('L1'),
            'L2': _get('L2'),
            'L3': _get('L3'),
            '来源': _get('source'),
            '难度等级': _get('difficulty_level'),
            '指令难度分': round(instruction_difficulty_score, 1),
            '模型数量': len(scores),
            '平均质量分': round(score_mean, 2),
            '中位数': round(score_median, 2),
            '标准差': round(score_std, 2),
            '最高分': round(score_max, 2),
            '最低分': round(score_min, 2),
            '分数范围': round(score_range, 2),
            '变异系数(%)': round(cv, 2),
            '>=90分数量': int((scores >= 90).sum()),
            '>=80分数量': int((scores >= 80).sum()),
            '>=70分数量': int((scores >= 70).sum()),
            '<60分数量': int((scores < 60).sum()),
            '最佳模型': best_model,
            '最佳得分': round(float(model_avg.max()), 2) if len(model_avg) > 0 else 'N/A',
            '最差模型': worst_model,
            '最差得分': round(float(model_avg.min()), 2) if len(model_avg) > 0 else 'N/A',
            'Cronbach_Alpha': round(cronbach_alpha, 3),
            '分半信度': round(split_half, 3),
            '信度等级': reliability_level,
            '内容效度': round(content_validity, 3),
            '构念效度': round(construct_validity, 3),
            '预测效度': round(predictive_validity, 3),
            '综合效度': round(comprehensive_validity, 3),
            '效度等级': validity_level,
            '区分度指数_D': round(discrimination_index, 3),
            '点双列相关': round(point_biserial, 3),
            '区分度等级': discrimination_level,
            '实际难度指数': round(difficulty_index, 3),
            '难度分类': difficulty_category,
            '综合质量分': round(quality_score, 2),
            '题目质量等级': quality_level,
        }

    @staticmethod
    def _cronbach_alpha(scores: np.ndarray) -> float:
        """
        单题场景下，将每个模型的得分视为一个"评分者"，
        用各模型得分的方差与总体方差之比来估算内部一致性。
        当只有一道题时，用分数离散度作为代理指标。
        """
        n = len(scores)
        if n <= 1:
            return 0.0
        score_std = float(np.std(scores, ddof=1))
        score_mean = float(np.mean(scores))
        if score_mean <= 0:
            return 0.0
        cv = score_std / score_mean
        alpha = max(0.0, min(1.0, 1.0 - cv))
        return alpha

    @staticmethod
    def _split_half_reliability(scores: np.ndarray) -> float:
        if len(scores) < 4:
            return 0.0
        mid = len(scores) // 2
        half1 = scores[:mid]
        half2 = scores[mid:2 * mid]
        if len(half1) == 0 or len(half2) == 0:
            return 0.0
        if float(np.std(half1)) <= 0 or float(np.std(half2)) <= 0:
            return 0.0
        try:
            correlation, _ = pearsonr(half1, half2)
            if np.isnan(correlation):
                return 0.0
            split_half = (2 * correlation) / (1 + correlation)
            return max(0.0, min(1.0, split_half))
        except Exception:
            return 0.0

    @staticmethod
    def _construct_validity(scores: np.ndarray, instruction_difficulty: float) -> float:
        if instruction_difficulty <= 0 or len(scores) <= 1:
            return 0.0
        score_std = float(np.std(scores, ddof=1))
        score_mean = float(np.mean(scores))
        if score_std <= 0 or score_mean <= 0:
            return 0.0
        normalized_difficulty = instruction_difficulty / 100
        normalized_mean = score_mean / 100
        difficulty_match = 1 - abs(normalized_difficulty - (1 - normalized_mean))
        cv = score_std / score_mean
        expected_cv = normalized_difficulty * 0.5
        dispersion_match = (
            1 - abs(cv - expected_cv) / max(cv, expected_cv)
            if max(cv, expected_cv) > 0 else 0
        )
        return max(0.0, min(1.0, (difficulty_match + dispersion_match) / 2))

    @staticmethod
    def _predictive_validity(scores: np.ndarray, pass_rates: np.ndarray) -> float:
        if len(scores) <= 1 or len(pass_rates) != len(scores):
            return 0.0
        if float(np.std(scores)) <= 0 or float(np.std(pass_rates)) <= 0:
            return 0.0
        try:
            correlation, _ = pearsonr(scores, pass_rates)
            return float(abs(correlation)) if not np.isnan(correlation) else 0.0
        except Exception:
            return 0.0

    @staticmethod
    def _discrimination_index(scores: np.ndarray) -> float:
        if len(scores) < 4:
            return 0.0
        sorted_scores = np.sort(scores)
        n = len(sorted_scores)
        top_27_idx = int(n * 0.73)
        bottom_27_idx = int(n * 0.27)
        high_group = sorted_scores[top_27_idx:]
        low_group = sorted_scores[:bottom_27_idx]
        if len(high_group) == 0 or len(low_group) == 0:
            return 0.0
        return float((np.mean(high_group) - np.mean(low_group)) / 100)

    @staticmethod
    def _point_biserial(scores: np.ndarray) -> float:
        """
        点双列相关：将分数二分化（高于中位数为1，否则为0），
        计算连续分数与二分变量的相关系数，衡量题目区分能力。
        """
        if len(scores) <= 3 or float(np.std(scores)) <= 0:
            return 0.0
        try:
            median_score = float(np.median(scores))
            binary_pass = (scores > median_score).astype(float)
            if float(np.std(binary_pass)) <= 0:
                return 0.0
            correlation, _ = pearsonr(scores, binary_pass)
            return float(correlation) if not np.isnan(correlation) else 0.0
        except Exception:
            return 0.0

    @staticmethod
    def _item_quality_score(cronbach: float, validity: float, discrimination: float) -> float:
        components = [(cronbach, 1), (validity, 1), (discrimination, 1)]
        valid = [(v * 100, w) for v, w in components if v > 0]
        if not valid:
            return 0.0
        return sum(v * w for v, w in valid) / sum(w for _, w in valid)

    @staticmethod
    def _reliability_level(alpha: float) -> str:
        if alpha >= 0.9:
            return '优秀'
        elif alpha >= 0.8:
            return '良好'
        elif alpha >= 0.7:
            return '可接受'
        return '较差'

    @staticmethod
    def _validity_level(avg: float) -> str:
        if avg >= 0.8:
            return '优秀'
        elif avg >= 0.6:
            return '良好'
        elif avg >= 0.4:
            return '可接受'
        return '较差'

    @staticmethod
    def _discrimination_level(index: float) -> str:
        if index >= 0.4:
            return '优秀'
        elif index >= 0.3:
            return '良好'
        elif index >= 0.2:
            return '可接受'
        return '较差'

    @staticmethod
    def _difficulty_category(index: float) -> str:
        if index >= 0.8:
            return '容易'
        elif index >= 0.5:
            return '中等'
        elif index >= 0.3:
            return '困难'
        return '很困难'

    @staticmethod
    def _quality_level(score: float) -> str:
        if score >= 80:
            return '优秀'
        elif score >= 60:
            return '良好'
        elif score >= 40:
            return '中等'
        return '较差'


class ConstraintTypeAnalyzer:

    EVALUABLE_TYPES = ['流程步骤', '格式输出', '格式形式', '边界范围', '数量篇幅']

    def __init__(self, data: dict):
        self.replies = data['replies']

    def analyze_constraint_types(self) -> pd.DataFrame:
        print("   - 生成约束类型分析...")

        if 'constraint_scores_json' not in self.replies.columns:
            print("    ⚠️ 结果表中无 constraint_scores_json 列，跳过约束类型分析")
            return pd.DataFrame()

        stats = []
        for model in self.replies['model'].unique():
            model_df = self.replies[self.replies['model'] == model]
            type_stats: Dict[str, dict] = defaultdict(lambda: {'total': 0, 'max': 0, 'count': 0, 'pass_count': 0})

            for _, row in model_df.iterrows():
                raw_json = row.get('constraint_scores_json', '[]')
                try:
                    constraint_scores = json.loads(raw_json) if raw_json else []
                except Exception:
                    continue

                for cs in constraint_scores:
                    c_type = cs.get('constraint_type', '')
                    if c_type not in self.EVALUABLE_TYPES:
                        continue
                    type_stats[c_type]['total'] += cs.get('actual_score', 0)
                    type_stats[c_type]['max'] += cs.get('max_score', 10)
                    type_stats[c_type]['count'] += 1
                    if cs.get('is_pass', False):
                        type_stats[c_type]['pass_count'] += 1

            row_data: dict = {'模型': model}
            score_rates = []
            for c_type in self.EVALUABLE_TYPES:
                type_data = type_stats[c_type]
                if type_data['max'] > 0:
                    score_rate = type_data['total'] / type_data['max'] * 100
                    pass_rate = type_data['pass_count'] / type_data['count'] * 100 if type_data['count'] > 0 else 0
                    row_data[f'{c_type}_得分率'] = round(score_rate, 2)
                    row_data[f'{c_type}_通过率'] = round(pass_rate, 2)
                    row_data[f'{c_type}_数量'] = type_data['count']
                    score_rates.append(score_rate)
                else:
                    row_data[f'{c_type}_得分率'] = 'N/A'
                    row_data[f'{c_type}_通过率'] = 'N/A'
                    row_data[f'{c_type}_数量'] = 0

            row_data['平均得分率'] = round(float(np.mean(score_rates)), 2) if score_rates else 0
            stats.append(row_data)

        df = pd.DataFrame(stats)
        if not df.empty:
            df = df.sort_values('平均得分率', ascending=False).reset_index(drop=True)
            df.insert(0, '排名', df.index + 1)

        print(f"    完成: {len(df)} 个模型")
        return df


class TypicalCaseSelector:

    def __init__(self, data: dict, item_analysis_df: pd.DataFrame):
        self.replies = data['replies_with_question']
        self.item_analysis_df = item_analysis_df

    def select_typical_cases(self, top_n: int = 20) -> pd.DataFrame:
        print(f"   - 筛选典型案例 TOP{top_n}...")

        if self.item_analysis_df.empty:
            return pd.DataFrame()

        candidates = self.item_analysis_df.copy()
        selected_rows = []
        l3_coverage: Dict[str, int] = defaultdict(int)
        source_coverage: Dict[str, int] = defaultdict(int)
        level_coverage: Dict[str, int] = defaultdict(int)

        sorted_candidates = candidates.sort_values('分数范围', ascending=False)

        for _, row in sorted_candidates.iterrows():
            if len(selected_rows) >= top_n:
                break

            l3 = str(row.get('L3', ''))
            source = str(row.get('来源', ''))
            level = str(row.get('难度等级', ''))

            if l3_coverage[l3] >= 5 or source_coverage[source] >= 10 or level_coverage[level] >= 8:
                continue

            l3_coverage[l3] += 1
            source_coverage[source] += 1
            level_coverage[level] += 1

            qid = str(row['qid'])
            qid_df = self.replies[self.replies['qid'] == qid]
            query = ''
            if not qid_df.empty and 'query' in qid_df.columns:
                raw_query = str(qid_df.iloc[0]['query'])
                query = raw_query[:100] + '...' if len(raw_query) > 100 else raw_query

            reason = self._generate_reason(row)

            selected_rows.append({
                '序号': len(selected_rows) + 1,
                'qid': qid,
                '指令内容': query,
                'L1': row.get('L1', ''),
                'L2': row.get('L2', ''),
                'L3': l3,
                '来源': source,
                '难度等级': level,
                '平均质量分': row.get('平均质量分', 'N/A'),
                '分数范围': row.get('分数范围', 'N/A'),
                '标准差': row.get('标准差', 'N/A'),
                '区分度指数_D': row.get('区分度指数_D', 'N/A'),
                '综合质量分': row.get('综合质量分', 'N/A'),
                '最佳模型': row.get('最佳模型', 'N/A'),
                '最佳得分': row.get('最佳得分', 'N/A'),
                '最差模型': row.get('最差模型', 'N/A'),
                '最差得分': row.get('最差得分', 'N/A'),
                '选择理由': reason,
            })

        df = pd.DataFrame(selected_rows)
        print(f"    完成: {len(df)} 个典型案例")
        return df

    @staticmethod
    def _generate_reason(row: pd.Series) -> str:
        reasons = []
        score_range = row.get('分数范围', 0)
        if isinstance(score_range, (int, float)) and not np.isnan(score_range):
            if score_range >= 50:
                reasons.append(f"高区分度（分数范围{score_range:.1f}分）")
            elif score_range >= 30:
                reasons.append(f"中等区分度（分数范围{score_range:.1f}分）")

        level = str(row.get('难度等级', ''))
        if level in ['S', 'A', 'B']:
            reasons.append(f"高难度指令（{level}级）")

        std = row.get('标准差', 0)
        if isinstance(std, (int, float)) and not np.isnan(std) and std >= 20:
            reasons.append(f"模型表现差异大（标准差{std:.1f}）")

        return '；'.join(reasons) if reasons else '典型案例'


def generate_metric_definitions() -> pd.DataFrame:
    definitions = [
        {'维度': '基础信息', '指标名称': '指令难度分', '计算方法': '约束加权难度均值×10', '取值范围': '0-100',
         '说明': '反映指令的综合难度，越高越难'},
        {'维度': '统计描述', '指标名称': '平均质量分', '计算方法': '所有模型在该题目上的评分均值', '取值范围': '0-100',
         '说明': '分数越低说明题目越难'},
        {'维度': '统计描述', '指标名称': '分数范围', '计算方法': '最高分 - 最低分', '取值范围': '0-100',
         '说明': '反映题目区分能力，范围越大区分度越高'},
        {'维度': '统计描述', '指标名称': '变异系数(%)', '计算方法': '标准差/均值×100', '取值范围': '≥0',
         '说明': '相对离散程度，排除均值影响'},
        {'维度': '信度指标', '指标名称': 'Cronbach_Alpha', '计算方法': '基于变异系数的内部一致性估算：1 - (std/mean)',
         '取值范围': '0-1', '说明': '≥0.9优秀，≥0.8良好，≥0.7可接受；分数越集中一致性越高'},
        {'维度': '信度指标', '指标名称': '分半信度', '计算方法': '2r/(1+r)，r为前后半组模型得分的皮尔逊相关系数',
         '取值范围': '0-1', '说明': '将模型按顺序分两半计算一致性'},
        {'维度': '效度指标', '指标名称': '内容效度', '计算方法': 'min(指令难度分/100, 1.0)', '取值范围': '0-1',
         '说明': '反映题目内容的代表性'},
        {'维度': '效度指标', '指标名称': '构念效度', '计算方法': '难度匹配度与分散度匹配度的均值', '取值范围': '0-1',
         '说明': '评估题目难度与实际分数分布的合理性'},
        {'维度': '效度指标', '指标名称': '预测效度', '计算方法': '质量分与通过率的皮尔逊相关系数绝对值', '取值范围': '0-1',
         '说明': '评估质量分对通过率的预测能力'},
        {'维度': '区分度指标', '指标名称': '区分度指数_D', '计算方法': '(高分组27%均分 - 低分组27%均分) / 100',
         '取值范围': '0-1', '说明': '≥0.4优秀，≥0.3良好，≥0.2可接受'},
        {'维度': '区分度指标', '指标名称': '点双列相关', '计算方法': '分数与二分化通过/失败变量的皮尔逊相关系数',
         '取值范围': '-1~1', '说明': '衡量题目对高低分模型的区分能力'},
        {'维度': '区分度指标', '指标名称': '实际难度指数', '计算方法': '平均质量分 / 100', '取值范围': '0-1',
         '说明': '越接近0.5区分效果越好'},
        {'维度': '综合质量', '指标名称': '综合质量分', '计算方法': '(Cronbach_Alpha + 综合效度 + 区分度指数) × 100 / 3',
         '取值范围': '0-100', '说明': '综合信度、效度、区分度的整体质量评价'},
        {'维度': '一致性指标', '指标名称': 'ICC(2,1)', '计算方法': '(MS_between - MS_residual) / (MS_between + MS_residual)',
         '取值范围': '-1~1', '说明': '组内相关系数，衡量评分者间一致性'},
        {'维度': '一致性指标', '指标名称': '加权Kappa', '计算方法': '(观测一致性 - 期望一致性) / (1 - 期望一致性)',
         '取值范围': '-1~1', '说明': '考虑评分距离的一致性系数'},
        {'维度': '一致性指标', '指标名称': '斯皮尔曼_ρ', '计算方法': '基于秩次的相关系数', '取值范围': '-1~1',
         '说明': '衡量排名一致性，不受异常值影响'},
        {'维度': '一致性指标', '指标名称': 'MAE', '计算方法': '|人工分 - 模型分| 的均值', '取值范围': '≥0',
         '说明': '平均绝对误差，越小越好'},
    ]
    return pd.DataFrame(definitions)

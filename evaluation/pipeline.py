# -*- coding: utf-8 -*-
from typing import Dict, List, Optional

import pandas as pd

from evaluation.managers.directory import DirectoryManager
from evaluation.managers.sysprompt import SyspromptManager
from evaluation.managers.constraint_library import ConstraintLibraryManager
from evaluation.testing.model_tester import ModelAvailabilityTester, select_best_judge_model
from evaluation.core.utils import safe_save_excel
from evaluation.stages import (
    generate_instructions,
    extract_structured_instructions,
    expand_to_multiturn,
    batch_evaluate_instruction_quality,
    batch_generate_criteria,
    batch_generate_references,
    batch_generate_replies,
    batch_evaluate_responses_with_cache,
    generate_evaluation_report,
)
from evaluation.analysis import generate_analysis_report, generate_all_series_reports


class PipelineManager:
    STAGE_DEFINITIONS = {
        'generate_instructions': {
            'name': '指令生成',
            'input_files': [],
            'output_files': ['stage0_generation/generated_responses.xlsx']
        },
        'extract_instructions': {
            'name': '指令提取',
            'input_files': ['stage0_generation/generated_responses.xlsx'],
            'output_files': ['stage0.5_extraction/extracted_instructions.xlsx']
        },
        'evaluate_instructions': {
            'name': '指令质量评估（可选）',
            'input_files': ['stage0.5_extraction/extracted_instructions.xlsx'],
            'output_files': ['stage1_quality/evaluated_instructions.xlsx']
        },
        'expand_multiturn': {
            'name': '多轮对话扩展（可选）',
            'input_files': ['stage0.5_extraction/extracted_instructions.xlsx'],
            'output_files': ['stage0.7_multiturn/multiturn_instructions.xlsx']
        },
        'promote_to_questions': {
            'name': '数据提升为评测题目',
            'input_files': [],
            'output_files': ['questions/questions.xlsx']
        },
        'generate_criteria': {
            'name': '评估标准生成',
            'input_files': ['questions/questions.xlsx'],
            'output_files': ['questions/questions_with_criteria.xlsx']
        },
        'generate_references': {
            'name': '参考答案生成',
            'input_files': ['questions/questions_with_criteria.xlsx'],
            'output_files': ['questions/questions_complete.xlsx']
        },
        'generate_replies': {
            'name': '回复生成',
            'input_files': ['questions/questions_complete.xlsx'],
            'output_files': ['replies/replies.xlsx']
        },
        'evaluate_replies': {
            'name': '回复评估',
            'input_files': ['questions/questions_complete.xlsx', 'replies/replies.xlsx'],
            'output_files': ['evaluations/evaluation_results.xlsx']
        },
        'test_models': {
            'name': '模型可用性测试',
            'input_files': [],
            'output_files': ['library/model_availability_test.xlsx']
        },
        'analyze_results': {
            'name': '评测结果综合分析',
            'input_files': ['questions/questions_complete.xlsx', 'replies/replies.xlsx'],
            'output_files': ['reports/analysis_report.xlsx']
        },
        'generate_report': {
            'name': '可视化报告生成',
            'input_files': ['questions/questions_complete.xlsx', 'replies/replies.xlsx'],
            'output_files': ['reports/evaluation_report_*.html', 'reports/evaluation_report_*.md']
        },
    }

    def __init__(self, config: dict):
        self.config = config
        self.dir_manager = DirectoryManager(config['output_base_dir'])
        self.sysprompt_manager = SyspromptManager(config['sysprompt_excel'])
        self.constraint_library = ConstraintLibraryManager(
            self.dir_manager.get_path("library", "constraint_library.xlsx")
        )

    def _get_sorted_stages(self, stages: List[str]) -> List[str]:
        all_stages = list(self.STAGE_DEFINITIONS.keys())
        for stage in stages:
            if stage not in all_stages:
                raise ValueError(f"未知的阶段: {stage}，可用阶段: {all_stages}")
        return [s for s in all_stages if s in stages]

    def _resolve_replies_excel(self) -> str:
        custom_path = self.config.get('replies_excel')
        if custom_path:
            return custom_path
        return self.dir_manager.get_path("replies", "replies.xlsx")

    def _resolve_promote_source(self) -> tuple:
        """
        按优先级选择 promote_to_questions 的数据源。
        优先级：用户显式指定 > stage1_quality > stage0.7_multiturn > stage0.5_extraction
        返回 (source_path, source_label)
        """
        import os
        dm = self.dir_manager
        cfg = self.config

        explicit_source = cfg.get('promote_source_excel')
        if explicit_source and os.path.exists(explicit_source):
            return explicit_source, f'用户指定（{explicit_source}）'

        quality_path = dm.get_path("stage1_quality", "evaluated_instructions.xlsx")
        multiturn_path = dm.get_path("stage0.7_multiturn", "multiturn_instructions.xlsx")
        extracted_path = dm.get_path("stage0.5_extraction", "extracted_instructions.xlsx")

        if os.path.exists(quality_path):
            return quality_path, 'stage1_quality（已过滤）'
        if os.path.exists(multiturn_path):
            return multiturn_path, 'stage0.7_multiturn（多轮）'
        if os.path.exists(extracted_path):
            return extracted_path, 'stage0.5_extraction（单轮）'

        return None, None

    def test_models(self, model_configs: List[Dict[str, str]],
                    output_excel: Optional[str] = None) -> pd.DataFrame:
        tester = ModelAvailabilityTester(timeout=self.config.get('test_timeout', 30))
        results = tester.test_all_models(model_configs, max_workers=3)
        if output_excel and safe_save_excel(results, output_excel):
            print(f"✅ 测试结果已保存: {output_excel}")
        return results

    def auto_select_judge_model(self, test_results: pd.DataFrame) -> bool:
        judge_config = select_best_judge_model(test_results)
        if judge_config:
            self.config['provider'] = judge_config['provider']
            self.config['model'] = judge_config['model']
            print(f"✅ 已自动配置裁判模型")
            return True
        print(f"❌ 无法自动选择裁判模型")
        return False

    def _execute_promote_to_questions(self):
        source_path, source_label = self._resolve_promote_source()

        if not source_path:
            raise RuntimeError(
                "promote_to_questions: 找不到可用的输入文件。\n"
                "请先运行 extract_instructions，或在 CONFIG 中设置 'promote_source_excel' 指定自定义路径。"
            )

        print(f"  📖 数据来源: {source_label}")
        df = pd.read_excel(source_path)

        if 'status' in df.columns:
            before_count = len(df)
            df = df[df['status'] == 'ok']
            print(f"  📌 按 status=ok 过滤: {before_count} → {len(df)} 条")

        output_path = self.dir_manager.get_path("questions", "questions.xlsx")
        if safe_save_excel(df, output_path):
            print(f"  ✅ 题目已写入: {output_path}  共 {len(df)} 条")

    def execute_stage(self, stage: str):
        stage_def = self.STAGE_DEFINITIONS[stage]
        print(f"\n{'=' * 60}")
        print(f"🚀 执行阶段: {stage_def['name']}")
        print(f"{'=' * 60}\n")

        cfg = self.config
        dm = self.dir_manager
        sp = self.sysprompt_manager

        if stage == 'generate_instructions':
            generation_cfg = cfg.get('generation', {})
            generate_instructions(
                output_excel=dm.get_path("stage0_generation", "generated_responses.xlsx"),
                provider=cfg['provider'], model=cfg['model'],
                sysprompt_manager=sp,
                num_batches=generation_cfg.get('num_batches', cfg.get('num_instruction_batches', 15)),
                items_per_batch=generation_cfg.get('items_per_batch', 3),
                temperature=cfg.get('instruction_temperature', 0.8),
                timeout=cfg['timeout'],
                schema_excel=generation_cfg.get('schema_excel'),
                see_excel=generation_cfg.get('see_excel'),
            )

        elif stage == 'extract_instructions':
            extract_structured_instructions(
                input_excel=dm.get_path("stage0_generation", "generated_responses.xlsx"),
                output_excel=dm.get_path("stage0.5_extraction", "extracted_instructions.xlsx")
            )

        elif stage == 'evaluate_instructions':
            batch_evaluate_instruction_quality(
                input_excel=dm.get_path("stage0.5_extraction", "extracted_instructions.xlsx"),
                output_excel=dm.get_path("stage1_quality", "evaluated_instructions.xlsx"),
                provider=cfg['provider'], model=cfg['model'],
                sysprompt_manager=sp,
                constraint_library=self.constraint_library,
                temperature=cfg.get('evaluation_temperature', 0.3),
                max_workers=cfg.get('max_workers', 4),
                checkpoint_interval=cfg.get('checkpoint_interval', 10),
                timeout=cfg['timeout']
            )

        elif stage == 'expand_multiturn':
            multiturn_cfg = cfg.get('multiturn', {})
            expand_to_multiturn(
                input_excel=dm.get_path("stage0.5_extraction", "extracted_instructions.xlsx"),
                output_excel=dm.get_path("stage0.7_multiturn", "multiturn_instructions.xlsx"),
                provider=cfg['provider'], model=cfg['model'],
                sysprompt_manager=sp,
                min_turns=multiturn_cfg.get('min_turns', 3),
                max_turns=multiturn_cfg.get('max_turns', 8),
                temperature=multiturn_cfg.get('temperature', 0.8),
                max_workers=multiturn_cfg.get('max_workers', cfg.get('max_workers', 3)),
                checkpoint_interval=cfg.get('checkpoint_interval', 10),
                timeout=cfg['timeout'],
            )

        elif stage == 'promote_to_questions':
            self._execute_promote_to_questions()

        elif stage == 'generate_criteria':
            batch_generate_criteria(
                input_excel=dm.get_path("questions", "questions.xlsx"),
                output_excel=dm.get_path("questions", "questions_with_criteria.xlsx"),
                provider=cfg['provider'], model=cfg['model'],
                sysprompt_manager=sp,
                temperature=cfg.get('criteria_temperature', 0.3),
                max_workers=1,
                checkpoint_interval=cfg.get('checkpoint_interval', 10),
                timeout=cfg['timeout']
            )

        elif stage == 'generate_references':
            batch_generate_references(
                input_excel=dm.get_path("questions", "questions_with_criteria.xlsx"),
                output_excel=dm.get_path("questions", "questions_complete.xlsx"),
                provider=cfg['provider'], model=cfg['model'],
                sysprompt_manager=sp,
                temperature=cfg.get('reference_temperature', 0.7),
                max_workers=1,
                checkpoint_interval=cfg.get('checkpoint_interval', 10),
                timeout=cfg['timeout']
            )

        elif stage == 'generate_replies':
            batch_generate_replies(
                questions_excel=dm.get_path("questions", "questions_complete.xlsx"),
                model_configs=cfg['reply_model_configs'],
                output_excel=self._resolve_replies_excel(),
                temperature=cfg.get('reply_temperature', 0.6),
                max_workers=cfg.get('max_workers', 5),
                checkpoint_interval=cfg.get('checkpoint_interval', 10),
                timeout=cfg['timeout']
            )

        elif stage == 'evaluate_replies':
            replies_file = self._resolve_replies_excel()
            batch_evaluate_responses_with_cache(
                questions_excel=dm.get_path("questions", "questions_complete.xlsx"),
                replies_excel=replies_file,
                output_excel=replies_file,
                provider=cfg['provider'], model=cfg['model'],
                sysprompt_manager=sp,
                batch_id=cfg.get('batch_id'),
                data_filters=cfg.get('data_filters'),
                temperature=cfg.get('evaluation_temperature', 0.3),
                max_workers=cfg.get('max_workers', 5),
                checkpoint_interval=cfg.get('checkpoint_interval', 10),
                timeout=cfg['timeout'],
                overwrite_mode=cfg.get('overwrite_mode', 'skip'),
            )

        elif stage == 'analyze_results':
            analysis_cfg = cfg.get('analysis', {})
            replies_file = analysis_cfg.get('replies_excel') or self._resolve_replies_excel()
            generate_analysis_report(
                questions_excel=dm.get_path("questions", "questions_complete.xlsx"),
                replies_excel=replies_file,
                output_excel=dm.get_path("reports", "analysis_report.xlsx"),
                human_excel=analysis_cfg.get('human_excel'),
                eval_batch_id=analysis_cfg.get('eval_batch_id', cfg.get('batch_id')),
            )

            model_series_config = analysis_cfg.get('model_series')
            if model_series_config:
                import pandas as pd
                from evaluation.analysis.data_loader import _load_replies, _resolve_eval_column, _preprocess_replies
                questions_df = pd.read_excel(dm.get_path("questions", "questions_complete.xlsx"))
                replies_df = _load_replies(replies_file)
                eval_col = _resolve_eval_column(replies_df, analysis_cfg.get('eval_batch_id', cfg.get('batch_id')))
                _preprocess_replies(replies_df, eval_col)
                generate_all_series_reports(
                    replies_df=replies_df,
                    questions_df=questions_df,
                    model_series_config=model_series_config,
                    output_dir=dm.get_path("reports", ""),
                )

        elif stage == 'generate_report':
            report_cfg = cfg.get('report', {})
            replies_file = report_cfg.get('replies_excel') or self._resolve_replies_excel()
            generate_evaluation_report(
                questions_excel=dm.get_path("questions", "questions_complete.xlsx"),
                replies_excel=replies_file,
                output_dir=dm.get_path("reports", ""),
                provider=cfg['provider'],
                model=cfg['model'],
                sysprompt_manager=sp,
                human_excel=report_cfg.get('human_excel'),
                eval_batch_id=report_cfg.get('eval_batch_id', cfg.get('batch_id')),
                top_n_cases=report_cfg.get('top_n_cases', 20),
                max_workers=report_cfg.get('max_workers', cfg.get('max_workers', 3)),
                timeout=report_cfg.get('timeout', cfg.get('timeout', 120)),
                temperature=report_cfg.get('temperature', 0.3),
                report_title=report_cfg.get('report_title', '多模型能力评测报告'),
            )

    def run(self, stages: List[str]):
        sorted_stages = self._get_sorted_stages(stages)

        print(f"\n{'=' * 60}")
        print(f"🎯 执行流程  阶段数量: {len(sorted_stages)}")
        print(f"{'=' * 60}")
        for i, stage in enumerate(sorted_stages, 1):
            print(f"  {i}. {self.STAGE_DEFINITIONS[stage]['name']} ({stage})")
        print(f"{'=' * 60}\n")

        try:
            for stage in sorted_stages:
                self.execute_stage(stage)
            print(f"\n{'=' * 60}")
            print(f"✅ 流程执行完毕！")
            print(f"{'=' * 60}\n")
        except RuntimeError as e:
            print(f"\n❌ 流程终止: {e}")
        except Exception as e:
            print(f"\n❌ 执行失败: {e}")
            import traceback
            traceback.print_exc()

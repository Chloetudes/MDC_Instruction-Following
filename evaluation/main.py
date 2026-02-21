# -*- coding: utf-8 -*-
"""
main.py - 评估系统入口
基于约束的完整评估系统 v9.0 (灵活化重构版)

使用模式：
  【全链路模式】数据合成 → 评测
    stages: ['generate_instructions', 'extract_instructions',
             'evaluate_instructions',   # 可选，质量把控
             'expand_multiturn',        # 可选，多轮扩展
             'promote_to_questions',
             'generate_criteria', 'generate_references',
             'generate_replies', 'evaluate_replies',
             'analyze_results', 'generate_report']

  【自定义评测模式】已有 questions.xlsx，直接从评测开始
    stages: ['generate_criteria', 'generate_references',
             'generate_replies', 'evaluate_replies',
             'analyze_results', 'generate_report']
"""
from evaluation.pipeline import PipelineManager


CONFIG = {
    # ========== 执行阶段 ==========
    'stages': [
        'generate_criteria',
    ],

    # ========== 基础配置 ==========
    'sysprompt_excel': "data/evaluation/sysprompts.xlsx",
    'output_base_dir': "outputs/evaluation",

    # ========== 裁判模型配置 ==========
    'provider': "idealab",
    'model': "claude_sonnet4_5",
    'timeout': 300,

    # ========== 温度配置 ==========
    'instruction_temperature': 0.9,
    'criteria_temperature': 0.3,
    'reference_temperature': 0.7,
    'reply_temperature': 0.6,
    'evaluation_temperature': 0.3,

    # ========== 数据合成配置（Stage 0）==========
    'generation': {
        'num_batches': 15,
        'items_per_batch': 3,
        'schema_excel': None,
        'see_excel': None,
    },

    # ========== 多轮扩展配置（Stage 0.7，可选）==========
    'multiturn': {
        'min_turns': 3,
        'max_turns': 8,
        'temperature': 0.8,
    },

    # ========== 评估批次ID ==========
    'batch_id': "batch_1",

    # ========== 评估覆盖策略 ==========
    # 'skip'      - 跳过已有评估，只评估空白数据（默认）
    # 'overwrite' - 清空已有评估列，全部重新评估
    # 'new_batch' - 自动生成新 batch_id（时间戳），保留历史评估
    'overwrite_mode': 'skip',

    # ========== 回复文件路径（三个阶段共用）==========
    # None 时使用默认 replies/replies.xlsx
    'replies_excel': None,

    # ========== 待测试模型配置 ==========
    'reply_model_configs': [
        {"model": "qwen3-max-2026-01-23", "enable_thinking": True},
        {"model": "gpt-5.2-chat-latest", "enable_thinking": False},
    ],

    # ========== 并发配置 ==========
    'max_workers': 5,
    'checkpoint_interval': 10,
    'test_timeout': 300,

    # ========== 数据筛选配置 ==========
    'data_filters': {
        'qid_list': None,
        'model_list': None,
        'reference_type': None,
        'batch_size': None,
    },

    # ========== 分析/报告配置 ==========
    'analysis': {
        'human_excel': None,
        'eval_batch_id': None,
        'replies_excel': None,
    },
    'report': {
        'human_excel': None,
        'eval_batch_id': None,
        'top_n_cases': 20,
        'report_title': '多模型能力评测报告',
        'replies_excel': None,
    },
}


def main():
    print(f"\n{'=' * 60}")
    print(f"🚀 基于约束的完整评估系统 v9.0 (灵活化重构版)")
    print(f"{'=' * 60}\n")

    pipeline = PipelineManager(CONFIG)

    if 'test_models' in CONFIG['stages']:
        print(f"\n{'=' * 60}")
        print(f"🧪 步骤1: 测试所有模型可用性")
        print(f"{'=' * 60}\n")

        test_results = pipeline.test_models(
            CONFIG['reply_model_configs'],
            output_excel=pipeline.dir_manager.get_path("library", "model_availability_test.xlsx")
        )

        if test_results['available'].sum() == 0:
            print("❌ 所有模型都不可用，请检查配置")
            return

        if not CONFIG.get('provider') or not CONFIG.get('model'):
            if not pipeline.auto_select_judge_model(test_results):
                print("❌ 无法自动选择裁判模型")
                return

        available_models = test_results[test_results['available']]
        CONFIG['reply_model_configs'] = [{'model': row['model']} for _, row in available_models.iterrows()]

        print(f"\n{'=' * 60}")
        print(f"✅ 模型筛选完成")
        print(f"{'=' * 60}")
        print(f"  原始模型数: {len(test_results)}  可用模型数: {len(CONFIG['reply_model_configs'])}")
        print(f"  裁判模型: {CONFIG['provider']} / {CONFIG['model']}")
        print(f"{'=' * 60}\n")

    remaining_stages = [s for s in CONFIG['stages'] if s != 'test_models']
    if remaining_stages:
        pipeline.run(remaining_stages)


if __name__ == "__main__":
    main()

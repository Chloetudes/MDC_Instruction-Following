# -*- coding: utf-8 -*-
"""
main.py - 评估系统入口
基于约束的完整评估系统 v9.0 (灵活化重构版)

========== 使用模式说明 ==========

【模式A：全链路数据合成 + 评测】
  stages: [
    'generate_instructions',   # Stage 0: 生成原始指令批次（JSON格式）
    'extract_instructions',    # Stage 0.5: 解析JSON，提取每条query
    'evaluate_instructions',   # Stage 1: 可选，质量过滤（status=ok才进入后续）
    'expand_multiturn',        # Stage 0.7: 可选，单轮→多轮对话扩展
    'promote_to_questions',    # 将合成数据转为评测题目格式
    'generate_criteria',       # Stage 1.5: 生成评分标准
    'generate_references',     # Stage 2: 生成参考答案
    'generate_replies',        # Stage 3: 多模型生成回复
    'evaluate_replies',        # Stage 4: 裁判模型评分
    'analyze_results',         # Stage 5a: 统计分析
    'generate_report',         # Stage 5b: 可视化报告
  ]

【模式B：自定义评测（已有 questions.xlsx）】
  stages: [
    'generate_criteria',
    'generate_references',
    'generate_replies',
    'evaluate_replies',
    'analyze_results',
    'generate_report',
  ]

【模式C：仅数据合成（不评测）】
  stages: [
    'generate_instructions',
    'extract_instructions',
    'evaluate_instructions',   # 可选
    'expand_multiturn',        # 可选
    'promote_to_questions',
  ]

========== 数据流说明 ==========

  generated_responses.xlsx  (id, response, L1, L2, L3)
    ↓ extract_instructions
  extracted_instructions.xlsx  (qid, original_id, item_num, task_type, query)
    ↓ evaluate_instructions [可选，过滤低质量]
  evaluated_instructions.xlsx  (qid, query, raw_response, status, ...)
    ↓ expand_multiturn [可选，多轮扩展]
  multiturn_instructions.xlsx  (session_id, turn_id, qid, query, history_context, ...)
    ↓ promote_to_questions [自动选择最优数据源]
  questions.xlsx  (qid, query, task_type, ...)
    ↓ generate_criteria
  questions_with_criteria.xlsx  (qid, query, evaluation_criteria, ...)
    ↓ generate_references
  questions_complete.xlsx  (qid, query, evaluation_criteria, reference, reference_type, ...)
    ↓ generate_replies
  replies.xlsx  (qid, model, reply, ...)
    ↓ evaluate_replies
  replies.xlsx  (新增 eval_{batch_id} 列)
    ↓ analyze_results / generate_report
  analysis_report.xlsx / evaluation_report.html
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

    # ========== promote_to_questions 数据源（可选）==========
    # None 时按优先级自动选择：stage1_quality > stage0.7_multiturn > stage0.5_extraction
    # 设置后直接使用指定文件，忽略自动选择逻辑
    'promote_source_excel': None,

    # ========== 评估批次ID ==========
    'batch_id': "batch_1",

    # ========== 评估覆盖策略 ==========
    # 'skip'      - 跳过已有评估，只评估空白数据（默认）
    # 'overwrite' - 清空已有评估列，全部重新评估
    # 'new_batch' - 自动生成新 batch_id（时间戳），保留历史评估
    'overwrite_mode': 'skip',

    # ========== 回复文件路径（generate_replies/evaluate_replies/analyze/report 共用）==========
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
                print("❌ 无法自动选择裁判模型，请在 CONFIG 中手动配置 provider 和 model")
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

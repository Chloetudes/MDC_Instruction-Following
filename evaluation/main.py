# -*- coding: utf-8 -*-
"""
main.py - 评估系统入口
基于约束的完整评估系统 v8.0 (数据流重构版)
"""
from evaluation.pipeline import PipelineManager


CONFIG = {
    # ========== 执行阶段 ==========
    'stages': [
        # 'test_models',           # 1 测试模型可用性
        # 'generate_instructions', # 2 生成指令
        # 'extract_instructions',  # 3 提取指令
        # 'evaluate_instructions', # 4 指令质量评估
        'generate_criteria',       # 5 生成评分标准
        # 'generate_references',   # 6 生成参考答案（基于评分标准）
        # 'generate_replies',      # 7 生成回复
        # 'evaluate_replies'       # 8 评估回复（支持增量评估）
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

    'num_instruction_batches': 15,
    'test_timeout': 300,

    # ========== 数据筛选配置 ==========
    'data_filters': {
        'qid_list': None,
        'model_list': None,
        'reference_type': None,
        'batch_size': None,
    },

    # ========== 评估批次ID ==========
    'batch_id': "batch_1",

    # ========== 待测试模型配置 ==========
    'reply_model_configs': [
        {"model": "qwen3-max-2026-01-23", "enable_thinking": True},
        {"model": "gpt-5.2-chat-latest", "enable_thinking": False},
    ],

    # ========== 并发配置 ==========
    'max_workers': 5,
    'checkpoint_interval': 10,
}


def main():
    print(f"\n{'=' * 60}")
    print(f"🚀 基于约束的完整评估系统 v8.0 (数据流重构版)")
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
            available_models = test_results[test_results['available']].sort_values('response_time')
            print("可用模型列表：")
            for idx, (_, row) in enumerate(available_models.iterrows(), 1):
                print(f"  {idx}. {row['provider']:20s} / {row['model']:35s} ({row['response_time']:.2f}秒)")

            print("\n请选择裁判模型编号（直接回车使用推荐模型）：", end='')
            choice = input().strip()

            if choice:
                try:
                    selected = available_models.iloc[int(choice) - 1]
                    CONFIG['provider'] = selected['provider']
                    CONFIG['model'] = selected['model']
                    print(f"\n✅ 已选择: {CONFIG['provider']} / {CONFIG['model']}")
                except Exception:
                    print("❌ 无效选择，使用推荐模型")
                    if not pipeline.auto_select_judge_model(test_results):
                        print("❌ 无法自动选择裁判模型")
                        return
            else:
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

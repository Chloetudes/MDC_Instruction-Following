# -*- coding: utf-8 -*-
"""
agent_runner.py - Agent 自主运行入口

【给 Agent 的任务说明】
======================
你是一个负责运行"多模型能力评测系统"的自主 Agent。
你的目标是：从零开始，完成一次完整的评测流程，最终产出可供人类查阅的评测报告。

【系统目标】
本系统通过以下流程评测多个 AI 模型的中文指令跟随能力：
  1. 合成高质量的测试指令（带约束的复杂中文指令）
  2. 为每条指令生成评分标准（Rubric）和参考答案
  3. 让多个被测模型回答这些指令
  4. 用裁判模型（judge）按 Rubric 逐条评分
  5. 生成统计分析报告和可视化 HTML 报告

【你的工作流程】
Step 1: 运行自检（check_prerequisites），确认环境就绪
Step 2: 生成最小测试数据（3条指令），验证全流程可通
Step 3: 全流程跑通后，扩大规模运行正式评测
Step 4: 如遇报错，读取对应代码文件，定位 bug，修复后重跑

【关键文件路径】
- 配置文件:       config.py（API key、模型列表）
- 主入口:         evaluation/main.py（修改 CONFIG 字典来控制运行参数）
- 系统提示词:     data/sysprompts/（各阶段 .txt 文件）
- 输出目录:       outputs/evaluation/（所有中间文件和最终报告）
- 系统说明书:     AGENT_GUIDE.md（详细的阶段说明和报错处理指引）

【运行方式】
  python agent_runner.py --mode check      # 仅自检
  python agent_runner.py --mode test       # 生成测试数据 + 跑最小流程
  python agent_runner.py --mode full       # 完整评测流程
  python agent_runner.py --mode resume     # 从上次中断处继续
"""

import sys
import os
import argparse
import json
import traceback
from datetime import datetime
from pathlib import Path

_project_root = os.path.dirname(os.path.abspath(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


# ==================== 自检模块 ====================

def check_prerequisites() -> dict:
    """
    检查运行前提条件，返回检查结果字典。
    Agent 应在运行任何阶段前先调用此函数。
    """
    results = {
        "passed": True,
        "warnings": [],
        "errors": [],
        "config_summary": {}
    }

    print("\n" + "=" * 60)
    print("🔍 系统自检")
    print("=" * 60)

    # 1. 检查 Python 依赖
    required_packages = ["pandas", "openpyxl", "tqdm", "requests"]
    missing_packages = []
    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            missing_packages.append(package)

    if missing_packages:
        results["errors"].append(f"缺少 Python 依赖: {', '.join(missing_packages)}")
        results["passed"] = False
        print(f"  ❌ 缺少依赖: {missing_packages}")
        print(f"     修复: pip install {' '.join(missing_packages)}")
    else:
        print(f"  ✅ Python 依赖完整")

    # 2. 检查 config.py 中的 API key
    try:
        from config import ALL_CONFIGS, MODEL_PROVIDER_MAPPING
        unconfigured_providers = []
        for provider_name, provider_cfg in ALL_CONFIGS.items():
            if provider_cfg.api_key == "YOUR_API_KEY_HERE":
                unconfigured_providers.append(provider_name)

        if unconfigured_providers:
            results["warnings"].append(
                f"以下 provider 的 API key 未配置: {unconfigured_providers}\n"
                f"  → 请在 config.py 中将 'YOUR_API_KEY_HERE' 替换为真实 key"
            )
            print(f"  ⚠️  未配置 API key 的 provider: {unconfigured_providers}")
        else:
            print(f"  ✅ 所有 provider API key 已配置")

        results["config_summary"]["total_providers"] = len(ALL_CONFIGS)
        results["config_summary"]["total_models"] = len(MODEL_PROVIDER_MAPPING)
        print(f"  📊 已配置 {len(ALL_CONFIGS)} 个 provider，{len(MODEL_PROVIDER_MAPPING)} 个模型")

    except Exception as e:
        results["errors"].append(f"config.py 加载失败: {e}")
        results["passed"] = False
        print(f"  ❌ config.py 加载失败: {e}")

    # 3. 检查 sysprompts 文件
    sysprompts_dir = Path(_project_root) / "data" / "sysprompts"
    required_sysprompts = [
        "instruction_generation.txt",
        "instruction_quality_evaluation.txt",
        "criteria_generation.txt",
        "reference_generation.txt",
        "reply_evaluation.txt",
        "report_analysis.txt",
        "multiturn_expansion.txt",
    ]
    missing_sysprompts = []
    empty_sysprompts = []

    for filename in required_sysprompts:
        filepath = sysprompts_dir / filename
        if not filepath.exists():
            missing_sysprompts.append(filename)
        elif filepath.stat().st_size < 50:
            empty_sysprompts.append(filename)

    if missing_sysprompts:
        results["errors"].append(f"缺少 sysprompt 文件: {missing_sysprompts}")
        results["passed"] = False
        print(f"  ❌ 缺少 sysprompt 文件: {missing_sysprompts}")
    elif empty_sysprompts:
        results["warnings"].append(f"以下 sysprompt 文件内容过短（可能未填写）: {empty_sysprompts}")
        print(f"  ⚠️  sysprompt 文件内容过短: {empty_sysprompts}")
    else:
        print(f"  ✅ 所有 sysprompt 文件存在且有内容")

    # 4. 检查 SyspromptManager 是否能正确加载 txt 文件
    try:
        from evaluation.managers.sysprompt import SyspromptManager
        sp_manager = SyspromptManager("data/sysprompts.xlsx")
        test_key = "instruction_generation"
        content = sp_manager.get(test_key, "")
        if content:
            print(f"  ✅ SyspromptManager 加载正常（{test_key}: {len(content)} 字符）")
        else:
            results["warnings"].append(
                f"SyspromptManager 无法读取 '{test_key}'，请检查 data/sysprompts/ 目录"
            )
            print(f"  ⚠️  SyspromptManager 读取 '{test_key}' 为空")
    except Exception as e:
        results["errors"].append(f"SyspromptManager 初始化失败: {e}")
        results["passed"] = False
        print(f"  ❌ SyspromptManager 失败: {e}")

    # 5. 检查输出目录
    output_dir = Path(_project_root) / "outputs" / "evaluation"
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"  ✅ 输出目录就绪: {output_dir}")

    # 汇总
    print("\n" + "-" * 40)
    if results["passed"] and not results["warnings"]:
        print("✅ 自检通过，系统就绪")
    elif results["passed"]:
        print(f"⚠️  自检通过（有 {len(results['warnings'])} 个警告）")
        for warning in results["warnings"]:
            print(f"   - {warning}")
    else:
        print(f"❌ 自检失败（{len(results['errors'])} 个错误）")
        for error in results["errors"]:
            print(f"   - {error}")

    return results


# ==================== 测试数据生成 ====================

def generate_minimal_test_data():
    """
    生成最小测试数据集（3条指令），用于验证全流程可通。
    直接写入 outputs/evaluation/questions/questions.xlsx，跳过 stage0-1。
    """
    import pandas as pd
    from evaluation.managers.directory import DirectoryManager

    print("\n" + "=" * 60)
    print("📝 生成最小测试数据（3条指令）")
    print("=" * 60)

    test_questions = [
        {
            "qid": "test_Q1",
            "task_type": "信息抽取",
            "query": (
                "请从以下客服对话记录中抽取关键信息，并按指定格式输出。\n\n"
                "【对话记录】\n"
                "客户：你好，我在2024年3月15日购买了一台型号为XR-2000的空调，"
                "订单号是ORD-20240315-8821，但是安装师傅说需要额外收取500元的安装费，"
                "这个费用在购买时没有提到，我想投诉并申请退款。\n"
                "客服：您好，感谢您的反馈。我查询到您的订单，确认安装费属于额外服务费用，"
                "购买页面第三条款有说明。但考虑到您的情况，我们可以为您申请50%的安装费减免。\n\n"
                "【抽取要求】\n"
                "1. 抽取以下字段：客户姓名（无则填'未知'）、购买日期、产品型号、订单号、"
                "投诉金额、客服处理结果\n"
                "2. 判断客户诉求是否被完全满足（是/否），并说明理由（1句话）\n"
                "3. 按以下格式输出：\n"
                "字段名: 值\n"
                "（每个字段占一行，最后一行输出诉求满足情况）"
            ),
            "history_context": "",
            "session_id": "",
            "turn_id": "",
        },
        {
            "qid": "test_Q2",
            "task_type": "标签分类",
            "query": (
                "你是一名内容审核专员，需要对以下5条用户评论进行多维度分类标注。\n\n"
                "【评论列表】\n"
                "1. 「这个产品真的太棒了！用了一周，效果超出预期，强烈推荐给所有人！」\n"
                "2. 「客服态度很差，等了半小时才回复，问题还没解决，太让人失望了。」\n"
                "3. 「价格还可以，质量一般，和描述基本符合，没什么特别的。」\n"
                "4. 「收到货发现包装破损，里面的东西也有划痕，要求退货被拒绝，非常气愤！」\n"
                "5. 「第二次购买了，上次用完觉得不错就回购了，希望这次也一样好用。」\n\n"
                "【标注维度】\n"
                "- 情感极性：正面/负面/中性\n"
                "- 评价对象：产品质量/客服服务/物流包装/价格/综合\n"
                "- 是否包含投诉意图：是/否\n"
                "- 是否有复购行为或意向：是/否\n\n"
                "【输出格式】用表格输出，列为：编号|情感极性|评价对象|投诉意图|复购意向"
            ),
            "history_context": "",
            "session_id": "",
            "turn_id": "",
        },
        {
            "qid": "test_Q3",
            "task_type": "阅读理解",
            "query": (
                "阅读以下段落，回答后面的问题。\n\n"
                "【材料】\n"
                "某公司规定：员工请假需提前3个工作日申请，病假除外。"
                "年假每年15天，入职不满1年按比例折算。"
                "小王于2024年6月1日入职，计划在2024年12月20日至2024年12月31日请年假。\n\n"
                "【问题】\n"
                "1. 小王截至12月20日，共工作了多少个月？（精确到月）\n"
                "2. 小王可以使用的年假天数是多少天？（按比例折算，向下取整）\n"
                "3. 小王计划请假的时间段（12月20日至31日）共有多少个工作日？"
                "（假设该时间段内无法定节假日）\n"
                "4. 小王的年假是否足够覆盖这段请假？请给出明确的是/否判断和计算过程。"
            ),
            "history_context": "",
            "session_id": "",
            "turn_id": "",
        },
    ]

    df = pd.DataFrame(test_questions)

    dm = DirectoryManager("outputs/evaluation")
    output_path = dm.get_path("questions", "questions.xlsx")

    df.to_excel(output_path, index=False)
    print(f"  ✅ 测试数据已写入: {output_path}")
    print(f"  📊 共 {len(df)} 条测试指令")
    for _, row in df.iterrows():
        print(f"     - {row['qid']}: {row['task_type']} ({len(row['query'])} 字)")

    return output_path


# ==================== 流程运行器 ====================

def run_pipeline(stages: list, config_overrides: dict = None):
    """
    运行指定阶段的 pipeline。
    config_overrides 可以覆盖 main.py 中的 CONFIG 默认值。
    """
    from evaluation.main import CONFIG
    from evaluation.pipeline import PipelineManager

    if config_overrides:
        CONFIG.update(config_overrides)

    CONFIG['stages'] = stages

    print(f"\n{'=' * 60}")
    print(f"🚀 启动 Pipeline")
    print(f"   阶段: {stages}")
    print(f"   裁判模型: {CONFIG.get('provider')} / {CONFIG.get('model')}")
    print(f"{'=' * 60}\n")

    pipeline = PipelineManager(CONFIG)

    if 'test_models' in stages:
        test_results = pipeline.test_models(
            CONFIG['reply_model_configs'],
            output_excel=pipeline.dir_manager.get_path("library", "model_availability_test.xlsx")
        )
        if test_results['available'].sum() == 0:
            raise RuntimeError("所有模型都不可用，请检查 config.py 中的 API key 配置")

        available_models = test_results[test_results['available']]
        CONFIG['reply_model_configs'] = [{'model': row['model']} for _, row in available_models.iterrows()]
        print(f"  ✅ 可用模型: {[m['model'] for m in CONFIG['reply_model_configs']]}")

    remaining_stages = [s for s in stages if s != 'test_models']
    if remaining_stages:
        pipeline.run(remaining_stages)


# ==================== 主流程 ====================

def run_test_mode():
    """
    测试模式：生成最小数据集，跑 generate_criteria → generate_references → generate_replies → evaluate_replies
    用于验证全流程代码无 bug。
    """
    print("\n" + "=" * 60)
    print("🧪 测试模式：验证全流程可通")
    print("=" * 60)

    generate_minimal_test_data()

    run_pipeline(
        stages=[
            'generate_criteria',
            'generate_references',
            'generate_replies',
            'evaluate_replies',
        ],
        config_overrides={
            'max_workers': 2,
            'checkpoint_interval': 3,
        }
    )

    print("\n✅ 测试模式完成！请检查 outputs/evaluation/ 目录下的输出文件。")


def run_full_mode():
    """
    完整模式：从指令生成开始，跑完整流程。
    """
    print("\n" + "=" * 60)
    print("🚀 完整模式：全流程评测")
    print("=" * 60)

    run_pipeline(
        stages=[
            'test_models',
            'generate_instructions',
            'extract_instructions',
            'evaluate_instructions',
            'promote_to_questions',
            'generate_criteria',
            'generate_references',
            'generate_replies',
            'evaluate_replies',
            'analyze_results',
            'generate_report',
        ]
    )

    print("\n✅ 完整评测流程完成！报告位于 outputs/evaluation/reports/")


def run_resume_mode():
    """
    续跑模式：检测已有输出文件，从上次中断处继续。
    """
    import pandas as pd
    from pathlib import Path

    print("\n" + "=" * 60)
    print("🔄 续跑模式：从上次中断处继续")
    print("=" * 60)

    output_base = Path("outputs/evaluation")

    stage_file_map = {
        'generate_instructions': output_base / "stage0_generation" / "generated_responses.xlsx",
        'extract_instructions': output_base / "stage0.5_extraction" / "extracted_instructions.xlsx",
        'evaluate_instructions': output_base / "stage1_quality" / "evaluated_instructions.xlsx",
        'promote_to_questions': output_base / "questions" / "questions.xlsx",
        'generate_criteria': output_base / "questions" / "questions_with_criteria.xlsx",
        'generate_references': output_base / "questions" / "questions_complete.xlsx",
        'generate_replies': output_base / "replies" / "replies.xlsx",
        'evaluate_replies': output_base / "replies" / "replies.xlsx",
        'analyze_results': output_base / "reports" / "analysis_report.xlsx",
    }

    completed_stages = []
    pending_stages = []

    all_stages_ordered = [
        'generate_instructions', 'extract_instructions', 'evaluate_instructions',
        'promote_to_questions', 'generate_criteria', 'generate_references',
        'generate_replies', 'evaluate_replies', 'analyze_results', 'generate_report',
    ]

    for stage in all_stages_ordered:
        output_file = stage_file_map.get(stage)
        if output_file and output_file.exists():
            try:
                df = pd.read_excel(output_file)
                completed_stages.append(stage)
                print(f"  ✅ {stage}: 已完成（{len(df)} 行）")
            except Exception:
                pending_stages.append(stage)
                print(f"  ⚠️  {stage}: 文件存在但无法读取，将重跑")
        else:
            pending_stages.append(stage)
            print(f"  ⏳ {stage}: 待执行")

    if not pending_stages:
        print("\n✅ 所有阶段已完成！")
        return

    print(f"\n📋 待执行阶段: {pending_stages}")
    run_pipeline(stages=pending_stages)


def main():
    parser = argparse.ArgumentParser(
        description="评测系统 Agent 自主运行入口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
运行模式说明:
  check   - 仅执行系统自检，不运行任何评测阶段
  test    - 生成3条测试指令，验证全流程代码无 bug
  full    - 完整评测流程（从指令生成到报告输出）
  resume  - 检测已有输出，从上次中断处继续
        """
    )
    parser.add_argument(
        '--mode',
        choices=['check', 'test', 'full', 'resume'],
        default='check',
        help='运行模式（默认: check）'
    )
    args = parser.parse_args()

    print(f"\n{'=' * 60}")
    print(f"🤖 评测系统 Agent Runner")
    print(f"   时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   模式: {args.mode}")
    print(f"{'=' * 60}")

    check_result = check_prerequisites()

    if not check_result["passed"]:
        print("\n❌ 自检失败，请修复上述错误后重试")
        sys.exit(1)

    if args.mode == 'check':
        print("\n✅ 自检完成（仅检查模式，未运行评测）")
        return

    try:
        if args.mode == 'test':
            run_test_mode()
        elif args.mode == 'full':
            run_full_mode()
        elif args.mode == 'resume':
            run_resume_mode()
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断，进度已通过 checkpoint 保存，可用 --mode resume 继续")
    except Exception as e:
        print(f"\n❌ 运行失败: {e}")
        print("\n📋 错误详情:")
        traceback.print_exc()
        print("\n💡 Agent 修复建议:")
        print("  1. 阅读上方错误堆栈，定位出错的文件和行号")
        print("  2. 阅读 AGENT_GUIDE.md 中对应阶段的'常见报错'部分")
        print("  3. 修复代码后，用 --mode resume 从中断处继续")
        sys.exit(1)


if __name__ == "__main__":
    main()

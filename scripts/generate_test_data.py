# -*- coding: utf-8 -*-
"""
scripts/generate_test_data.py - 最小测试数据生成脚本

用途：
  生成覆盖全流程所需格式的最小测试 Excel 文件，
  无需调用任何 LLM API，直接写入 outputs/evaluation/questions/questions.xlsx。

使用方式：
  python scripts/generate_test_data.py
  python scripts/generate_test_data.py --count 5   # 生成5条
  python scripts/generate_test_data.py --stage all  # 同时生成各阶段测试文件
"""

import sys
import os
import argparse
import pandas as pd
from pathlib import Path
from datetime import datetime

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from evaluation.managers.directory import DirectoryManager


SAMPLE_QUESTIONS = [
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
    {
        "qid": "test_Q4",
        "task_type": "关系推理",
        "query": (
            "根据以下描述，推断各人物之间的关系，并回答问题。\n\n"
            "【描述】\n"
            "张明是李华的父亲。李华和王芳是夫妻。王芳的母亲叫陈秀。"
            "张明有一个兄弟叫张强。张强的儿子叫张小龙。\n\n"
            "【问题】\n"
            "1. 王芳和张明是什么关系？\n"
            "2. 张小龙和李华是什么关系？\n"
            "3. 陈秀和张明是什么关系？\n"
            "4. 张小龙叫陈秀什么？\n\n"
            "请逐题回答，每题格式为：第N题：[关系称谓]（理由：...）"
        ),
        "history_context": "",
        "session_id": "",
        "turn_id": "",
    },
    {
        "qid": "test_Q5",
        "task_type": "编辑校对",
        "query": (
            "请对以下文本进行校对，找出所有错误并改正，最后输出修改后的完整文本。\n\n"
            "【原文】\n"
            "根据最新统计数据显示，2023年全国居民人均可支配收入为36883元，"
            "比上年增长6.3%，扣除价格因素，实际增长6.1%。其中，城镇居民人均可支配收入"
            "51821元，增长5.1%；农村居民人均可支配收入21691元，增长7.7%。"
            "城乡居民收入比为2.39，比上年缩小0.04。\n\n"
            "【校对要求】\n"
            "1. 找出所有语法错误（如句式不通、成分缺失）\n"
            "2. 找出所有标点符号错误\n"
            "3. 找出数字逻辑错误（如比例计算不一致）\n"
            "4. 输出格式：先列出错误清单（编号+错误描述+修改建议），再输出修改后的完整文本"
        ),
        "history_context": "",
        "session_id": "",
        "turn_id": "",
    },
]


def generate_questions_excel(count: int = 3, output_path: str = None) -> str:
    """生成 questions.xlsx 测试文件"""
    dm = DirectoryManager("outputs/evaluation")
    if output_path is None:
        output_path = dm.get_path("questions", "questions.xlsx")

    selected = SAMPLE_QUESTIONS[:min(count, len(SAMPLE_QUESTIONS))]
    df = pd.DataFrame(selected)
    df.to_excel(output_path, index=False)

    print(f"✅ questions.xlsx 已生成: {output_path}")
    print(f"   共 {len(df)} 条指令")
    return output_path


def generate_stage0_excel(output_path: str = None) -> str:
    """
    生成 stage0 格式的 generated_responses.xlsx（模拟 LLM 生成的 JSON 批次）
    用于测试 extract_instructions 阶段。
    """
    import json
    dm = DirectoryManager("outputs/evaluation")
    if output_path is None:
        output_path = dm.get_path("stage0_generation", "generated_responses.xlsx")

    batch_responses = []
    for i in range(1, 4):
        questions_in_batch = SAMPLE_QUESTIONS[(i-1)*1:i*1]
        json_items = [
            {"task_type": q["task_type"], "query": q["query"]}
            for q in questions_in_batch
        ]
        batch_responses.append({
            "id": f"batch_{i:03d}",
            "response": json.dumps(json_items, ensure_ascii=False),
            "L1": "NLP",
            "L2": questions_in_batch[0]["task_type"] if questions_in_batch else "",
            "L3": "",
            "timestamp": datetime.now().isoformat(),
        })

    df = pd.DataFrame(batch_responses)
    df.to_excel(output_path, index=False)
    print(f"✅ generated_responses.xlsx 已生成: {output_path}")
    return output_path


def generate_all_stage_fixtures():
    """生成所有阶段的测试 fixture 文件"""
    print("\n生成所有阶段测试数据...")
    generate_stage0_excel()
    generate_questions_excel(count=3)
    print("\n✅ 所有测试数据已生成")


def main():
    parser = argparse.ArgumentParser(description="生成评测系统测试数据")
    parser.add_argument('--count', type=int, default=3, help='生成指令数量（默认3条）')
    parser.add_argument(
        '--stage',
        choices=['questions', 'stage0', 'all'],
        default='questions',
        help='生成哪个阶段的测试数据（默认: questions）'
    )
    args = parser.parse_args()

    print(f"\n{'=' * 50}")
    print(f"📝 测试数据生成器")
    print(f"{'=' * 50}\n")

    if args.stage == 'questions':
        generate_questions_excel(count=args.count)
    elif args.stage == 'stage0':
        generate_stage0_excel()
    elif args.stage == 'all':
        generate_all_stage_fixtures()


if __name__ == "__main__":
    main()

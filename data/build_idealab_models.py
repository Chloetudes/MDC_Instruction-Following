# -*- coding: utf-8 -*-
"""生成 data/idealab_models.xlsx：所有来源的模型清单（idealab + config 中其他 provider），便于通过表格配置 API。
每行含「来源」列（idealab / routify_claude / aiarena 等），接口信息 idealab 的可从站点复制。
"""
import os
import sys
import pandas as pd

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
from config import MODEL_PROVIDER_MAPPING

# 列：展示名, api_model_id, 供应商, 部署, 上下文, 最大输出, Thinking, Tool_Call, 简介（共9列，main 中加 来源=idealab）
ROWS_IDEALAB = [
    ("claude-opus-4-6", "claude-opus-4-6", "Anthropic", "外部部署", "200000", "32000", "是", "是", ""),
    ("kimi-k2.5", "bailian/kimi-k2.5", "Moonshot", "阿里云部署", "256000", "16000", "是", "否", ""),
    ("GLM-4.7", "glm-4.7", "Z.AI", "内部部署", "200000", "128000", "否", "否", "Advanced agentic, reasoning and coding."),
    ("kimi-k2-thinking", "kimi-k2-thinking", "Moonshot", "阿里云部署", "256000", "16000", "是", "否", ""),
    ("GPT-5.2", "gpt-5.2-1211-global", "Azure Openai", "外部部署", "400000", "128000", "否", "是", "GPT-5.2"),
    ("GPT-5.1", "gpt-51-1113-global", "Azure Openai", "外部部署", "400000", "128000", "否", "是", "自适应推理"),
    ("GPT-5.1-chat", "gpt-51-chat-1113-global", "Azure Openai", "外部部署", "128000", "16384", "否", "是", "Chat 场景"),
    ("GPT-5.1-codex", "gpt-51-codex-1113-global", "Azure Openai", "外部部署", "400000", "128000", "否", "是", "Agentic Coding"),
    ("GPT-5.1-codex-mini", "gpt-51-codex-mini-1113-global", "Azure Openai", "外部部署", "400000", "128000", "否", "是", "Agentic Coding 轻量"),
    ("GLM-4.6", "glm-4.6", "Z.AI", "内部部署", "200000", "128000", "否", "否", "Advanced agentic, reasoning and coding."),
    ("GPT-5-pro", "gpt-5-pro-1006-global", "Azure Openai", "外部部署", "400000", "272000", "否", "是", "更强推理"),
    ("GPT-5-Codex", "gpt-5-codex-0915-global", "Azure Openai", "外部部署", "400000", "128000", "否", "是", "Agentic Coding"),
    ("GPT-5", "gpt-5-0807-global", "Azure Openai", "外部部署", "400000", "128000", "否", "是", "全推理模型"),
    ("GPT-5 mini", "gpt-5-mini-0807-global", "Azure Openai", "外部部署", "400000", "128000", "否", "是", "实时推理"),
    ("GPT-5 nano", "gpt-5-nano-0807-global", "Azure Openai", "外部部署", "400000", "128000", "否", "是", "超低延迟"),
    ("GPT-5 chat", "gpt-5-chat-0807-global", "Azure Openai", "外部部署", "128000", "16384", "否", "是", "多轮对话"),
    ("o1-preview-0912", "o1-preview-0912", "Azure Openai", "外部部署", "128000", "32768", "是", "否", "强化学习推理"),
    ("o1-preview-0912-global", "o1-preview-0912-global", "Azure Openai", "外部部署", "128000", "32768", "是", "否", ""),
    ("o1-mini-0912", "o1-mini-0912", "Azure Openai", "外部部署", "128000", "65536", "否", "否", ""),
    ("o1-mini-0912-global", "o1-mini-0912-global", "Azure Openai", "外部部署", "128000", "65536", "否", "否", ""),
    ("o3-0416-global", "o3-0416-global", "Azure Openai", "外部部署", "200000", "100000", "是", "是", ""),
    ("o3-mini-0131-global", "o3-mini-0131-global", "Azure Openai", "外部部署", "200000", "100000", "是", "否", ""),
    ("o4-mini-0416-global", "o4-mini-0416-global", "Azure Openai", "外部部署", "200000", "100000", "是", "是", ""),
    ("gpt-image-1-0415-global", "gpt-image-1-0415-global", "Azure Openai", "外部部署", "-", "-", "否", "否", "图像生成"),
    ("gpt-4o-mini-0718", "gpt-4o-mini-0718", "Azure Openai", "外部部署", "128000", "16384", "否", "是", "轻量智能"),
    ("gpt-4o-mini-0718-global", "gpt-4o-mini-0718-global", "Azure Openai", "外部部署", "128000", "16384", "否", "是", ""),
    ("gpt-4o-0806-global", "gpt-4o-0806-global", "Azure Openai", "外部部署", "128000", "16384", "否", "是", ""),
    ("gpt-4o-0806", "gpt-4o-0806", "Azure Openai", "外部部署", "128000", "16384", "否", "是", ""),
    ("gpt-4o-0513-global", "gpt-4o-0513-global", "Azure Openai", "外部部署", "128000", "4096", "否", "是", ""),
    ("gpt-4o-0513", "gpt-4o-0513", "Azure Openai", "外部部署", "128000", "4096", "否", "是", ""),
    ("gpt-4.5-preview", "gpt-45-0227-global", "Azure Openai", "外部部署", "128000", "16384", "否", "是", ""),
    ("gpt-4.1-0414-global", "gpt-41-0414-global", "Azure Openai", "外部部署", "1047576", "32768", "否", "是", ""),
    ("gpt-4.1-mini-0414-global", "gpt-41-mini-0414-global", "Azure Openai", "外部部署", "1047576", "32768", "否", "是", ""),
    ("gpt-4.1-nano-0414-global", "gpt-41-nano-0414-global", "Azure Openai", "外部部署", "1047576", "32768", "否", "是", ""),
    ("gpt-4-0409", "gpt-4-0409", "Azure Openai", "外部部署", "128000", "4096", "否", "是", "GPT-4 Turbo GA"),
    ("gpt-4-turbo-128k", "gpt-4-turbo-128k", "Azure Openai", "外部部署", "128000", "4096", "否", "是", "128K 上下文"),
    ("gpt-4-vision-preview", "gpt-4-vision-preview", "Azure Openai", "外部部署", "128000", "4096", "否", "是", "多模态"),
    ("gpt-4-8K", "gpt-4 8K", "Azure Openai", "外部部署", "8192", "-", "否", "是", "8K 版本"),
    ("gpt-4-32K", "gpt-4 32K", "Azure Openai", "外部部署", "32768", "-", "否", "是", "32K 版本"),
    ("gpt-3.5-turbo", "gpt-3.5-turbo", "Azure Openai", "外部部署", "4096", "-", "否", "是", ""),
    ("gpt-3.5-16K", "gpt-3.5-16K", "Azure Openai", "外部部署", "16384", "-", "否", "是", ""),
    ("gpt-35-turbo-0125", "gpt-35-turbo-0125", "Azure Openai", "外部部署", "16385", "4096", "否", "是", ""),
    ("gemini-3-flash-preview", "gemini-3-flash-preview", "Google", "外部部署", "1048576", "65536", "否", "是", ""),
    ("gemini-3-pro-preview", "gemini-3-pro-preview", "Google", "外部部署", "1048576", "65536", "是", "是", "最强推理"),
    ("gemini-2.5-flash-image", "gemini-2.5-flash-image", "Google", "外部部署", "32768", "32768", "否", "否", "图像生成 Nano Banana"),
    ("gemini-2.5-flash-image-preview", "gemini-2.5-flash-image-preview", "Google", "外部部署", "32768", "32768", "否", "否", ""),
    ("gemini-2.5-pro-06-17", "gemini-2.5-pro-06-17", "Google", "外部部署", "1048576", "65536", "是", "是", "思考型"),
    ("gemini-2.5-flash-06-17", "gemini-2.5-flash-06-17", "Google", "外部部署", "1048576", "65536", "否", "是", "Flash 思考"),
    ("gemini-2.0-flash", "gemini-2.0-flash", "Google", "外部部署", "1000000", "8192", "否", "是", ""),
    ("gemini-2.5-flash-lite-07-22", "gemini-2.5-flash-lite-07-22", "Google", "外部部署", "1048576", "65536", "否", "否", "低延迟"),
    ("gemini-2.5-flash-lite-preview-06-17", "gemini-2.5-flash-lite-preview-06-17", "Google", "外部部署", "1048576", "65536", "否", "否", ""),
    ("gemini-1.5-pro", "gemini-1.5-pro", "Google", "外部部署", "1000000", "8192", "否", "是", ""),
    ("gemini-1.5-pro-flash", "gemini-1.5-pro-flash", "Google", "外部部署", "1000000", "8192", "否", "是", ""),
    ("gemini-pro-vision", "gemini-pro-vision", "Google", "外部部署", "16384", "2048", "否", "否", "多模态"),
    ("Qwen3-Max", "qwen3-max", "Alibaba", "阿里云部署", "262144", "32768", "是", "是", "通义千问3 Max"),
    ("Qwen3-Max-Preview", "qwen3-max-preview", "Alibaba", "阿里云部署", "262144", "32768", "是", "是", ""),
    ("qwen3-next-80b-a3b-instruct", "qwen3-next-80b-a3b-instruct", "Alibaba", "阿里云部署", "131072", "16384", "是", "是", "非思考模式"),
    ("qwen3-next-80b-a3b-thinking", "qwen3-next-80b-a3b-thinking", "Alibaba", "阿里云部署", "131072", "16384", "是", "是", "思考模式"),
    ("Qwen3-8B", "qwen3-8b", "Alibaba", "阿里云部署", "131072", "16384", "是", "是", ""),
    ("Qwen3-4B", "qwen3-4b", "Alibaba", "阿里云部署", "131072", "16384", "是", "是", ""),
    ("Qwen3-Coder-Flash", "qwen3-coder-flash", "Alibaba", "内部部署", "1048576", "65536", "否", "是", ""),
    ("Qwen3-Coder-Plus", "qwen3-coder-plus", "Alibaba", "阿里云部署", "1048576", "65536", "否", "是", ""),
    ("Qwen-Long", "qwen-long", "Alibaba", "阿里云部署", "10000000", "8192", "否", "否", "长文档"),
    ("Qwen-Flash", "qwen-flash", "Alibaba", "阿里云部署", "10000000", "8192", "否", "否", "1M 上下文"),
    ("Qwen-Doc-Turbo", "qwen-doc-turbo", "Alibaba", "阿里云部署", "131072", "8192", "否", "否", "文档抽取"),
    ("Qwen3-235B-a22B-Instruct-2507", "qwen3-235b-a22b-instruct-2507", "Alibaba", "阿里云部署", "131072", "8192", "否", "是", ""),
    ("Qwen3-235B-A22B", "Qwen3-235B-A22B", "Alibaba", "阿里云部署", "131072", "8192", "是", "是", ""),
    ("Qwen3-30B-A3B", "Qwen3-30B-A3B", "Alibaba", "阿里云部署", "131072", "8192", "是", "是", ""),
    ("Qwen3-32B", "Qwen3-32B", "Alibaba", "阿里云部署", "131072", "8192", "是", "是", ""),
    ("qwen-max-latest", "qwen-max-latest", "Alibaba", "阿里云部署", "131072", "8192", "否", "是", ""),
    ("qwen-plus-latest", "qwen-plus-latest", "Alibaba", "阿里云部署", "131072", "8192", "是", "是", ""),
    ("qwen-plus-latest-inc", "qwen-plus-latest-inc", "Alibaba", "内部部署", "131072", "8192", "是", "是", ""),
    ("qwen-turbo-inc", "qwen-turbo-inc", "Alibaba", "内部部署", "131072", "8192", "是", "否", ""),
    ("qwen-turbo-latest", "qwen-turbo-latest", "Alibaba", "阿里云部署", "131072", "8192", "是", "否", ""),
    ("qwen-turbo-latest-inc", "qwen-turbo-latest-inc", "Alibaba", "内部部署", "131072", "8192", "是", "否", ""),
    ("qvq-max", "qvq-max", "Alibaba", "阿里云部署", "122880", "8192", "否", "否", "约72B"),
    ("qwq-32b", "qwq-32b", "Alibaba", "阿里云部署", "131072", "8192", "是", "否", "约32B"),
    ("qwen_max", "qwen_max", "Alibaba", "阿里云部署", "32768", "8192", "否", "是", "千亿级"),
    ("qwen-max-inc", "qwen-max-inc", "Alibaba", "内部部署", "32768", "8192", "否", "是", ""),
    ("qwen2.5-max", "qwen2.5-max", "Alibaba", "阿里云部署", "131072", "8192", "否", "是", ""),
    ("qwen-plus", "qwen-plus", "Alibaba", "阿里云部署", "131072", "8192", "否", "是", "约72B"),
    ("qwen-plus-inc", "qwen-plus-inc", "Alibaba", "内部部署", "131072", "8192", "否", "否", ""),
    ("qwen2.5-plus", "qwen2.5-plus", "Alibaba", "阿里云部署", "131072", "8192", "否", "否", ""),
    ("qwen3-vl-235b-a22b-instruct", "qwen3-vl-235b-a22b-instruct", "Alibaba", "阿里云部署", "131072", "32768", "否", "是", "视觉理解"),
    ("qwen3-vl-235b-a22b-thinking", "qwen3-vl-235b-a22b-thinking", "Alibaba", "阿里云部署", "131072", "32768", "否", "是", ""),
    ("qwen-vl-max", "qwen-vl-max", "Alibaba", "阿里云部署", "32768", "2048", "否", "是", "多模态"),
    ("qwen-vl-max-inc", "qwen-vl-max-inc", "Alibaba", "内部部署", "32768", "2048", "否", "是", ""),
    ("qwen-vl-plus-inc", "qwen-vl-plus-inc", "Alibaba", "内部部署", "131072", "8192", "否", "是", ""),
    ("qwen2.5-vl-72b-instruct", "qwen2.5-vl-72b-instruct", "Alibaba", "阿里云部署", "8000", "2000", "否", "否", ""),
    ("qwen-72b-chat", "Qwen_32K_72B", "Alibaba", "阿里云部署", "32000", "2000", "否", "否", "建议用 qwen2.5-72b-instruct"),
    ("qwen-turbo-poly", "qwen-turbo-poly", "Alibaba", "阿里云部署", "8000", "2000", "否", "否", "多语言"),
    ("qwen2-7b-instruct", "qwen2-7b-instruct", "Alibaba", "阿里云部署", "131072", "6144", "否", "是", ""),
    ("qwen2-72b-instruct", "qwen2-72b-instruct", "Alibaba", "阿里云部署", "131072", "6144", "否", "是", ""),
    ("qwen2.5-72b-instruct", "qwen2.5-72b-instruct", "Alibaba", "阿里云部署", "131072", "8192", "否", "否", ""),
    ("qwen2.5-32b-instruct", "qwen2.5-32b-instruct", "Alibaba", "阿里云部署", "131072", "8192", "否", "是", ""),
    ("qwen2.5-14b-instruct", "qwen2.5-14b-instruct", "Alibaba", "阿里云部署", "131072", "8192", "否", "是", ""),
    ("qwen2.5-7b-instruct", "qwen2.5-7b-instruct", "Alibaba", "阿里云部署", "131072", "8192", "否", "是", ""),
    ("qwen2.5-3b-instruct", "qwen2.5-3b-instruct", "Alibaba", "阿里云部署", "32768", "8192", "否", "是", ""),
    ("qwen2.5-1.5b-instruct", "qwen2.5-1.5b-instruct", "Alibaba", "阿里云部署", "32768", "8192", "否", "是", ""),
    ("qwen2.5-0.5b-instruct", "qwen2.5-0.5b-instruct", "Alibaba", "阿里云部署", "32768", "8192", "否", "是", ""),
    ("qwen2.5-coder-7b-instruct", "qwen2.5-coder-7b-instruct", "Alibaba", "阿里云部署", "131072", "8192", "否", "是", ""),
    ("qwen2.5-coder-32b-instruct", "qwen2.5-coder-32b-instruct", "Alibaba", "阿里云部署", "131072", "8192", "否", "是", ""),
    ("claude-haiku-4_5", "claude-haiku-4_5", "Anthropic", "外部部署", "200000", "64000", "是", "是", ""),
    ("claude_sonnet4_5", "claude_sonnet4_5", "Anthropic", "外部部署", "200000", "64000", "是", "是", ""),
    ("claude-opus-4-5", "claude-opus-4-5", "Anthropic", "外部部署", "200000", "32000", "是", "是", ""),
    ("claude_opus4_1", "claude_opus4_1", "Anthropic", "外部部署", "200000", "32000", "是", "是", ""),
    ("claude_sonnet4", "claude_sonnet4", "Anthropic", "外部部署", "200000", "64000", "是", "是", ""),
    ("claude_opus4", "claude_opus4", "Anthropic", "外部部署", "200000", "32000", "是", "是", ""),
    ("Claude-3.7-sonnet", "claude37_sonnet", "Anthropic", "外部部署", "200000", "128000", "是", "是", ""),
    ("claude3_sonnet", "claude3_sonnet", "Anthropic", "外部部署", "200000", "4096", "否", "否", ""),
    ("claude3_opus", "claude3_opus", "Anthropic", "外部部署", "200000", "4096", "否", "是", ""),
    ("claude35_sonnet", "claude35_sonnet", "Anthropic", "外部部署", "200000", "8192", "否", "是", ""),
    ("claude35_sonnet2", "claude35_sonnet2", "Anthropic", "外部部署", "200000", "8192", "否", "是", "v2"),
    ("claude35_haiku", "claude35_haiku", "Anthropic", "外部部署", "200000", "8192", "否", "是", "最快"),
    ("llama3", "llama3", "Meta", "内部部署", "8192", "2048", "否", "否", "Meta-Llama-3-70B-Instruct"),
    ("DeepSeek-R1-0528", "DeepSeek-R1-0528", "DeepSeek", "内部部署", "32768", "-", "否", "否", ""),
    ("DeepSeek-R1-671B", "DeepSeek-R1-671B", "DeepSeek", "内部部署", "65792", "32768", "否", "否", "建议 stream"),
    ("DeepSeek-V3-671B", "DeepSeek-V3-671B", "DeepSeek", "内部部署", "65792", "8192", "否", "否", ""),
    ("DeepSeek-R1-Distill-Qwen-32B", "DeepSeek-R1-Distill-Qwen-32B", "DeepSeek", "内部部署", "32768", "16384", "否", "否", ""),
    ("DeepSeek-R1-Distill-Qwen-14B", "DeepSeek-R1-Distill-Qwen-14B", "DeepSeek", "内部部署", "32768", "16384", "否", "否", ""),
    ("kimi-k2", "kimi-k2", "Moonshot", "阿里云部署", "131072", "-", "否", "否", "Moonshot-Kimi-K2-Instruct"),
]

# 已知的接口信息（与 idealab 模型详情页一致）：展示名 -> (协议, 端点, 调用方式)
KNOWN_API_INFO = {
    "GPT-5.1-codex": ("openai", "/v1/responses", "Responses"),
    "GPT-5.1": ("openai", "/v1/chat/completions", "Chat"),  # 常见
    "GPT-5": ("openai", "/v1/responses", "Responses"),
    "claude_sonnet4_5": ("openai", "/v1/chat/completions", "Chat"),
}

def main():
    # idealab 详细清单：每行插入 来源=idealab
    rows = [
        (r[0], r[1], "idealab", r[2], r[3], r[4], r[5], r[6], r[7], r[8])
        for r in ROWS_IDEALAB
    ]
    idealab_api_ids = {r[1] for r in ROWS_IDEALAB}

    # 合并 config 中其他来源：同一模型可有多行（不同 来源）
    for model_name, provider in MODEL_PROVIDER_MAPPING.items():
        if provider == "idealab":
            if model_name not in idealab_api_ids:
                rows.append((model_name, model_name, "idealab", "", "", "", "", "", "", ""))
        else:
            rows.append((model_name, model_name, provider, "", "", "", "", "", "", ""))

    df = pd.DataFrame(
        rows,
        columns=[
            "展示名称",
            "api_model_id",
            "来源",
            "供应商",
            "部署方式",
            "上下文窗口",
            "最大输出",
            "Thinking",
            "Tool_Call",
            "简介",
        ],
    )
    # 插入「协议」「端点」「调用方式」三列（紧接 来源 后），便于与 idealab 站点对照
    df.insert(3, "协议", "")
    df.insert(4, "端点", "")
    df.insert(5, "调用方式", "")
    for name, (protocol, endpoint, call_type) in KNOWN_API_INFO.items():
        mask = (df["展示名称"] == name) & (df["来源"] == "idealab")
        if mask.any():
            df.loc[mask, "协议"] = protocol
            df.loc[mask, "端点"] = endpoint
            df.loc[mask, "调用方式"] = call_type

    # 可用状态、最后测试时间（批量回复前测试后由程序写入）
    df["可用状态"] = ""
    df["最后测试时间"] = ""

    # 填写说明 sheet
    help_rows = [
        ("列名", "说明", "如何填写"),
        ("展示名称", "页面上显示的模型名", "与 idealab/各站点列表一致"),
        ("api_model_id", "接口请求时使用的模型名（请求体 model 参数）", "从模型详情页 Default 或 API 文档复制"),
        ("来源", "API 来源（provider）", "idealab / routify_claude / aiarena / openrouter / bailian 等，与 config 一致"),
        ("协议", "API 协议", "如 openai，以实际环境为准"),
        ("端点", "请求路径", "如 /v1/responses 或 /v1/chat/completions，从详情页 Endpoints 复制"),
        ("调用方式", "接口类型", "Responses 或 Chat Completions，与端点对应"),
        ("供应商", "模型供应商", "如 Azure Openai, Anthropic, Alibaba"),
        ("部署方式", "部署类型", "外部部署 / 阿里云部署 / 内部部署"),
        ("上下文窗口", "context window", "单位 token"),
        ("最大输出", "max output tokens", "单位 token"),
        ("Thinking", "是否支持思考模式", "是/否"),
        ("Tool_Call", "是否支持 function calling", "是/否"),
        ("简介", "备注", "可选"),
        ("可用状态", "程序测试后写入：是/否/空(待测)", "批量回复前运行测试会更新本列"),
        ("最后测试时间", "最近一次可用性测试时间", "程序写入"),
        ("", "", ""),
        ("批量填写建议", "", "在 idealab 模型详情页：Default 即 api_model_id；Endpoints 下有端点与调用方式；按展示名称匹配后复制到本表。"),
    ]
    df_help = pd.DataFrame(help_rows[1:], columns=help_rows[0])

    out_path = os.path.join(_THIS_DIR, "idealab_models.xlsx")
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="idealab_models")
        df_help.to_excel(writer, index=False, sheet_name="填写说明")
    by_source = df.groupby("来源").size()
    print(f"已生成: {out_path}  共 {len(df)} 条")
    print("  按来源: " + ", ".join(f"{k}={v}" for k, v in by_source.items()))

if __name__ == "__main__":
    main()

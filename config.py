# -*- coding: utf-8 -*-
"""
config.py - 配置文件
支持 Routify 统一调用入口和多种协议
"""

import os
from dataclasses import dataclass
from typing import Optional, Dict, List


@dataclass
class ProviderConfig:
    """Provider配置"""
    name: str
    base_url: str
    api_key: str
    protocol: str = "openai"  # openai, vertex, openai_responses
    auth_header: str = "Authorization"
    auth_prefix: str = "Bearer"
    extra_headers: Optional[Dict[str, str]] = None
    timeout: int = 120


# ==================== Routify 配置 ====================

ROUTIFY_CONFIGS = {
    "routify_claude": ProviderConfig(
        name="routify_claude",
        base_url="https://routify.alibaba-inc.com/protocol/openai/v1",
        api_key="sk-d68fe0f6d9ce4fb788571d9c65bf6e63",
        protocol="openai",
        auth_header="Authorization",
        auth_prefix="Bearer"
    ),

    "routify_gemini": ProviderConfig(
        name="routify_gemini",
        base_url="https://routify.alibaba-inc.com/protocol/vertex/v1beta",
        api_key="sk-d68fe0f6d9ce4fb788571d9c65bf6e63",
        protocol="vertex",
        auth_header="x-goog-api-key",
        auth_prefix="Bearer"
    ),

    "routify_gpt_responses": ProviderConfig(
        name="routify_gpt_responses",
        base_url="https://routify.alibaba-inc.com/protocol/openai/v1/responses",
        api_key="sk-9eba1adb38fa4cb1af5dca05f58f8472",
        protocol="openai_responses",
        auth_header="Authorization",
        auth_prefix="Bearer"
    ),

    "routify_gpt": ProviderConfig(
        name="routify_gpt",
        base_url="https://routify.alibaba-inc.com/protocol/openai/v1",
        api_key="sk-9eba1adb38fa4cb1af5dca05f58f8472",
        protocol="openai",
        auth_header="Authorization",
        auth_prefix="Bearer"
    ),
}

# ==================== 其他 Provider 配置 ====================

OTHER_CONFIGS = {
    "idealab": ProviderConfig(
        name="idealab",
        base_url="https://idealab.alibaba-inc.com/api/openai/v1",
        api_key="e086b5a947c3c2651165617b22318df5",
        protocol="openai"
    ),

    "aiarena": ProviderConfig(
        name="aiarena",
        base_url="https://aiarena.alibaba-inc.com/api/openai/v1",
        api_key="intern-c9e16118-3b3e-41ff-9650-7251de404042",
        protocol="openai"
    ),

    "openrouter": ProviderConfig(
        name="openrouter",
        base_url="https://openrouter.alibaba-inc.com/api/openapi/v1",
        api_key="sk-db9e0e8e2cff4922a25b613d3aa2a722",
        protocol="openai",
        extra_headers={"bizCode": "dt_softwareengcoding"}
    ),

    "bailian": ProviderConfig(
        name="bailian",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="sk-ff46d6acc52a4192be3e927a1c578b30",
        protocol="openai"
    ),

    "bailian_thinking": ProviderConfig(
        name="bailian_thinking",
        base_url="https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
        api_key="sk-ff46d6acc52a4192be3e927a1c578b30",
        protocol="dashscope",
        auth_header="Authorization",
        auth_prefix="Bearer",  # 不需要 Bearer
        #extra_headers={"x-dashscope-sse": "enable"}
    ),

    "zhipu": ProviderConfig(
        name="zhipu",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        api_key="3c031872401a41389006c05c7c01018b.5iaQSsiIB5FVWYVX",
        protocol="openai"
    ),
}

ALL_CONFIGS = {**ROUTIFY_CONFIGS, **OTHER_CONFIGS}

# ==================== 模型映射配置 ====================

MODEL_PROVIDER_MAPPING = {
    # Claude 系列
    "claude-sonnet-4-5-20250929": "routify_claude",
    "claude-sonnet-4-20250514": "routify_claude",
    "claude-opus-4-5-20251101": "openrouter",
    "claude-opus-4-5":"idealab",
    "claude-opus-4-6":"routify_claude",  # idealab 常报「模型不存在」，走 Routify
    "claude-haiku-4_5":"idealab",
    "claude_sonnet4_5":"idealab",
    "nova-lite-v1":"idealab",

    "claude-opus-4-5-thinking": "openrouter",  # Thinking版本

    # Gemini 系列
    "gemini-3-pro-preview": "routify_gemini",
    "gemini-2.0-flash-exp": "idealab",
    "gemini-3-flash-preview": "idealab", #vlm video u
    "gemini-3-pro-preview": "idealab",
    "gemini-3-pro-image-preview": "idealab", #vlm video u

    "gemini-3-pro-thinking": "routify_gemini",  # Thinking版本
    "gemini-3-pro-thinking":"openrouter",



    # GPT 系列
    "gpt-5.2-chat-latest": "routify_gpt_responses",
    "gpt-5.1-codex": "routify_gpt_responses",
    "gpt-4o": "routify_gpt",
    "gpt-4o-mini-0718": "aiarena",
    "gpt-5.2-codex-0114-global": "idealab",
    "gpt-5.2-pro": "idealab",

    # DeepSeek 系列
    "deepseek-v3.2-exp": "aiarena",
    "deepseek-v3-1-think-250821": "aiarena",
    "DeepSeek-R1-0528": "idealab",
    "DeepSeek-V3-671B": "idealab",
    "DeepSeek-V3.2-think": "idealab",

    # Qwen 系列
    "qwen3-max": "idealab",
    "qwen3-max-preview": "aiarena",
    "qwen3-coder-30b-a3b-instruct": "bailian",
    "qwen3-coder-480b-a35b-instruct": "bailian",
    "qwen3-max-preview": "idealab",

    # Qwen3 Thinking 系列（新增）2026年1月26日
    "qwen3-max-2026-01-23": "bailian_thinking",
    "qwen3-max-thinking": "bailian_thinking",
    #"pre-qwen3-max-thinking-test-chat": "bailian_thinking",

    # Kimi 系列
    "kimi-k2-thinking": "idealab",
    "kimi-k2-0905-preview": "idealab",

    # GLM 系列
    "glm-4.6": "zhipu",
    "glm-4.6": "idealab",
    "glm-4.7": "idealab",
    "glm-4.7": "zhipu",

    # Grok 系列
    "grok-4-fast-reasoning": "aiarena",
    "grok-4-0709": "aiarena",
    "grok-4-1-fast": "openrouter",
    "grok-4-1-fast-reasoning": "idealab",

    # Doubao 系列
    "doubao-seed-1-6-251015": "aiarena",
    "doubao-seedance-1-5-pro-251215": "idealab",#video

    "doubao-seed-1.8-1228": "idealab",



    "kling-v2-6":"idealab", #video
    "MiniMax-M2.1": "idealab",
    "gemini-2.5-flash-lite-07-22": "idealab",

}

# 裁判模型候选：仅 Claude / Gemini / GPT-5.2 系列（优先 Claude），用于「先测可用性、再交互选择」
JUDGE_CANDIDATE_MODELS = [
    # Claude 优先
    "claude-opus-4-6", "claude-sonnet-4-5-20250929", "claude-opus-4-5-20251101",
    "claude_sonnet4_5", "claude-opus-4-5", "claude-haiku-4_5",
    # Gemini
    "gemini-3-pro-preview", "gemini-3-flash-preview", "gemini-2.0-flash-exp",
    "gemini-2.5-flash-lite-07-22", "gemini-3-pro-thinking",
    # GPT-5.2
    "gpt-5.2-chat-latest", "gpt-5.2-pro", "gpt-5.2-codex-0114-global",
]

DEFAULT_TIMEOUT = 120


def get_provider(provider_name: str) -> ProviderConfig:
    """获取provider配置"""
    if provider_name not in ALL_CONFIGS:
        raise ValueError(f"未知的provider: {provider_name}")
    return ALL_CONFIGS[provider_name]


def get_provider_for_model(model_name: str) -> ProviderConfig:
    """根据模型名称自动获取对应的provider配置"""
    if model_name not in MODEL_PROVIDER_MAPPING:
        raise ValueError(f"未配置模型 {model_name} 的provider映射")

    provider_name = MODEL_PROVIDER_MAPPING[model_name]
    return get_provider(provider_name)



'''
# ==================== Provider 和 Model 配置选项 ====================

# 【Claude 系列 - 通过 Routify】
'provider': "routify_claude",
'model': "claude-sonnet-4-5-20250929",  # Claude Sonnet 4.5（推荐）

'provider': "routify_claude",
'model': "claude-sonnet-4-20250514",  # Claude Sonnet 4

'provider': "openrouter",
'model': "claude-opus-4-5-20251101",  # Claude Opus 4.5（最强推理）

# 【GPT 系列 - 通过 Routify】
'provider': "routify_gpt_responses",
'model': "gpt-5.2-chat-latest",  # GPT-5.2（最新版本）

'provider': "routify_gpt_responses",
'model': "gpt-5.1-codex",  # GPT-5.1 Codex（代码专用）

'provider': "routify_gpt",
'model': "gpt-4o",  # GPT-4o

'provider': "aiarena",
'model': "gpt-4o-mini-0718",  # GPT-4o Mini（轻量版）

# 【Gemini 系列】
'provider': "routify_gemini",
'model': "gemini-3-pro-preview",  # Gemini 3 Pro（通过 Routify）

'provider': "idealab",
'model': "gemini-2.0-flash-exp",  # Gemini 2.0 Flash（快速版）

# 【DeepSeek 系列】
'provider': "aiarena",
'model': "deepseek-v3.2-exp",  # DeepSeek V3.2

'provider': "aiarena",
'model': "deepseek-v3-1-think-250821",  # DeepSeek V3.1 Think

'provider': "idealab",
'model': "DeepSeek-R1-0528",  # DeepSeek R1

# 【Qwen 系列】
'provider': "idealab",
'model': "qwen3-max",  # Qwen3 Max

'provider': "aiarena",
'model': "qwen3-max-preview",  # Qwen3 Max Preview

'provider': "bailian",
'model': "qwen3-coder-30b-a3b-instruct",  # Qwen3 Coder 30B

'provider': "bailian",
'model': "qwen3-coder-480b-a35b-instruct",  # Qwen3 Coder 480B

# 【Kimi 系列】
'provider': "idealab",
'model': "kimi-k2-thinking",  # Kimi K2 Thinking

# 【GLM 系列】
'provider': "zhipu",
'model': "glm-4.6",  # GLM-4.6

# 【Grok 系列】
'provider': "aiarena",
'model': "grok-4-fast-reasoning",  # Grok 4 Fast Reasoning

'provider': "aiarena",
'model': "grok-4-0709",  # Grok 4

'provider': "openrouter",
'model': "grok-4-1-fast",  # Grok 4.1 Fast

# 【Doubao 系列】
'provider': "aiarena",
'model': "doubao-seed-1-6-251015",  # Doubao Seed 1.6
'''
# ==================== 完整模型列表（用于测试） ====================



def get_all_model_configs() -> List[Dict[str, str]]:
    """获取所有已配置模型的列表"""
    return [{"model": model_name} for model_name in MODEL_PROVIDER_MAPPING.keys()]
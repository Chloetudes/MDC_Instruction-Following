# -*- coding: utf-8 -*-
"""
config.py - 配置文件
支持 Routify 统一调用入口和多种协议

【使用说明】
将所有 "YOUR_API_KEY_HERE" 替换为你的真实 API Key。
下载完整代码后直接替换此文件即可。

【最少配置要求】
至少需要配置以下 provider 之一（用于裁判模型）：
  - idealab       → 内部服务，推荐优先使用
  - routify_claude → Claude 系列，稳定可靠

被测模型所用的 provider 也需要配置对应的 API Key。
例如：被测模型为 qwen3-max，其 provider 为 bailian，需配置 bailian 的 key。

【快速上手】
1. 配置好 API Key 后，运行：python agent_runner.py --mode check
2. 自检通过后，运行：python agent_runner.py --mode test
3. 正式评测：python agent_runner.py --mode full
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
    protocol: str = "openai"
    auth_header: str = "Authorization"
    auth_prefix: str = "Bearer"
    extra_headers: Optional[Dict[str, str]] = None
    timeout: int = 120


# ==================== Routify 配置 ====================

ROUTIFY_CONFIGS = {
    "routify_claude": ProviderConfig(
        name="routify_claude",
        base_url="https://routify.alibaba-inc.com/protocol/openai/v1",
        api_key="YOUR_API_KEY_HERE",
        protocol="openai",
        auth_header="Authorization",
        auth_prefix="Bearer"
    ),

    "routify_gemini": ProviderConfig(
        name="routify_gemini",
        base_url="https://routify.alibaba-inc.com/protocol/vertex/v1beta",
        api_key="YOUR_API_KEY_HERE",
        protocol="vertex",
        auth_header="x-goog-api-key",
        auth_prefix="Bearer"
    ),

    "routify_gpt_responses": ProviderConfig(
        name="routify_gpt_responses",
        base_url="https://routify.alibaba-inc.com/protocol/openai/v1/responses",
        api_key="YOUR_API_KEY_HERE",
        protocol="openai_responses",
        auth_header="Authorization",
        auth_prefix="Bearer"
    ),

    "routify_gpt": ProviderConfig(
        name="routify_gpt",
        base_url="https://routify.alibaba-inc.com/protocol/openai/v1",
        api_key="YOUR_API_KEY_HERE",
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
        api_key="YOUR_API_KEY_HERE",
        protocol="openai"
    ),

    "aiarena": ProviderConfig(
        name="aiarena",
        base_url="https://aiarena.alibaba-inc.com/api/openai/v1",
        api_key="YOUR_API_KEY_HERE",
        protocol="openai"
    ),

    "openrouter": ProviderConfig(
        name="openrouter",
        base_url="https://openrouter.alibaba-inc.com/api/openapi/v1",
        api_key="YOUR_API_KEY_HERE",
        protocol="openai",
        extra_headers={"bizCode": "dt_softwareengcoding"}
    ),

    "bailian": ProviderConfig(
        name="bailian",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="YOUR_API_KEY_HERE",
        protocol="openai"
    ),

    "bailian_thinking": ProviderConfig(
        name="bailian_thinking",
        base_url="https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
        api_key="YOUR_API_KEY_HERE",
        protocol="dashscope",
        auth_header="Authorization",
        auth_prefix="Bearer"
    ),

    "zhipu": ProviderConfig(
        name="zhipu",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        api_key="YOUR_API_KEY_HERE",
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
    "claude-opus-4-5": "idealab",
    "claude-haiku-4_5": "idealab",
    "claude_sonnet4_5": "idealab",
    "nova-lite-v1": "idealab",
    "claude-opus-4-5-thinking": "openrouter",

    # Gemini 系列
    "gemini-2.0-flash-exp": "idealab",
    "gemini-3-flash-preview": "idealab",
    "gemini-3-pro-preview": "idealab",
    "gemini-3-pro-image-preview": "idealab",
    "gemini-3-pro-thinking": "openrouter",

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
    "qwen3-max-preview": "idealab",
    "qwen3-coder-30b-a3b-instruct": "bailian",
    "qwen3-coder-480b-a35b-instruct": "bailian",
    "qwen3-max-2026-01-23": "bailian_thinking",
    "qwen3-max-thinking": "bailian_thinking",

    # Kimi 系列
    "kimi-k2-thinking": "idealab",
    "kimi-k2-0905-preview": "idealab",

    # GLM 系列
    "glm-4.6": "idealab",
    "glm-4.7": "idealab",

    # Grok 系列
    "grok-4-fast-reasoning": "aiarena",
    "grok-4-0709": "aiarena",
    "grok-4-1-fast": "openrouter",
    "grok-4-1-fast-reasoning": "idealab",

    # Doubao 系列
    "doubao-seed-1-6-251015": "aiarena",
    "doubao-seedance-1-5-pro-251215": "idealab",
    "doubao-seed-1.8-1228": "idealab",

    # 其他
    "kling-v2-6": "idealab",
    "MiniMax-M2.1": "idealab",
    "gemini-2.5-flash-lite-07-22": "idealab",
}

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


def get_all_model_configs() -> List[Dict[str, str]]:
    """获取所有已配置模型的列表"""
    return [{"model": model_name} for model_name in MODEL_PROVIDER_MAPPING.keys()]

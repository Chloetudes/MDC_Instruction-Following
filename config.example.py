# -*- coding: utf-8 -*-
"""
config.example.py - 配置模板（公开仓库用）
使用前请复制为 config.py 并填入真实 API Key 与 endpoint，勿将 config.py 提交到仓库。
"""

import os
from dataclasses import dataclass
from typing import Optional, Dict, List


@dataclass
class ProviderConfig:
    """Provider 配置"""
    name: str
    base_url: str
    api_key: str
    protocol: str = "openai"
    auth_header: str = "Authorization"
    auth_prefix: str = "Bearer"
    extra_headers: Optional[Dict[str, str]] = None
    timeout: int = 120


# ==================== 从环境变量读取（推荐） ====================
# 可设置环境变量，例如：OPENAI_API_KEY、DASHSCOPE_API_KEY 等
def _env(key: str, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()


# ==================== Provider 配置示例 ====================
# 请复制本文件为 config.py，将 YOUR_API_KEY_HERE 替换为真实 key，或使用环境变量

OTHER_CONFIGS = {
    "openai": ProviderConfig(
        name="openai",
        base_url="https://api.openai.com/v1",
        api_key=_env("OPENAI_API_KEY", "YOUR_OPENAI_API_KEY_HERE"),
        protocol="openai",
    ),
    "dashscope": ProviderConfig(
        name="dashscope",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key=_env("DASHSCOPE_API_KEY", "YOUR_DASHSCOPE_API_KEY_HERE"),
        protocol="openai",
    ),
    "openrouter": ProviderConfig(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key=_env("OPENROUTER_API_KEY", "YOUR_OPENROUTER_API_KEY_HERE"),
        protocol="openai",
    ),
}

# 若使用内部 Routify 等，在 config.py 中追加 ROUTIFY_CONFIGS 并合并进 ALL_CONFIGS
ROUTIFY_CONFIGS = {}
ALL_CONFIGS = {**ROUTIFY_CONFIGS, **OTHER_CONFIGS}

# ==================== 模型 → Provider 映射示例 ====================
MODEL_PROVIDER_MAPPING = {
    "gpt-4o": "openai",
    "gpt-4o-mini": "openai",
    "qwen-plus": "dashscope",
    "qwen-max": "dashscope",
    "claude-3-5-sonnet": "openrouter",
}

# 裁判模型候选（用于报告阶段 LLM 分析）
JUDGE_CANDIDATE_MODELS = list(MODEL_PROVIDER_MAPPING.keys())[:5]

DEFAULT_TIMEOUT = 120


def get_provider(provider_name: str) -> ProviderConfig:
    if provider_name not in ALL_CONFIGS:
        raise ValueError(f"未知的 provider: {provider_name}。请先在 config.py 中配置。")
    return ALL_CONFIGS[provider_name]


def get_provider_for_model(model_name: str) -> ProviderConfig:
    if model_name not in MODEL_PROVIDER_MAPPING:
        raise ValueError(f"未配置模型 {model_name} 的 provider 映射。请在 config.py 的 MODEL_PROVIDER_MAPPING 中添加。")
    return get_provider(MODEL_PROVIDER_MAPPING[model_name])


def get_all_model_configs() -> List[Dict[str, str]]:
    return [{"model": m} for m in MODEL_PROVIDER_MAPPING.keys()]

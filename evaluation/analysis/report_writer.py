# -*- coding: utf-8 -*-
import os
import json
import warnings
import textwrap
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')

MODEL_ICONS = {
    'claude': 'https://www.anthropic.com/_next/image?url=%2Fimages%2Ficons%2Fclaude-app-icon.png&w=96&q=75',
    'gpt': 'https://cdn.oaistatic.com/_next/static/media/apple-touch-icon.59f2e898.png',
    'gemini': 'https://www.gstatic.com/lamda/images/gemini_sparkle_v002_d4735304ff6292a690345.svg',
    'qwen': 'https://img.alicdn.com/imgextra/i3/O1CN01YPqjHT1hbfBhJmPMH_!!6000000004295-2-tps-500-500.png',
    'deepseek': 'https://avatars.githubusercontent.com/u/130298873?s=200&v=4',
    'glm': 'https://open.bigmodel.cn/static/zhipuai/favicon.ico',
    'moonshot': 'https://platform.moonshot.cn/favicon.ico',
    'kimi': 'https://platform.moonshot.cn/favicon.ico',
    'doubao': 'https://lf-cdn.coze.cn/obj/coze-web-cn/obric/coze/favicon.png',
    'ernie': 'https://yiyan.baidu.com/favicon.ico',
    'spark': 'https://xinghuo.xfyun.cn/favicon.ico',
    'minimax': 'https://platform.minimaxi.com/favicon.ico',
    'yi': 'https://www.01.ai/favicon.ico',
    'baichuan': 'https://platform.baichuan-ai.com/favicon.ico',
}


def _get_model_icon(model_name: str) -> str:
    model_lower = model_name.lower()
    for key, url in MODEL_ICONS.items():
        if key in model_lower:
            return url
    return 'https://via.placeholder.com/40/667eea/ffffff?text=AI'


def _escape_html(text: str) -> str:
    if not text:
        return ''
    return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _nl2br(text: str) -> str:
    if not text:
        return ''
    return _escape_html(text).replace('\n', '<br>')


def _safe_float(value, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if not np.isnan(result) else default
    except Exception:
        return default


def _safe_str(value, max_len: int = 0) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ''
    text = str(value)
    if max_len > 0 and len(text) > max_len:
        return text[:max_len] + '...'
    return text

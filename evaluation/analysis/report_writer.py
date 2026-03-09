# -*- coding: utf-8 -*-
import os
import json
import re
import warnings
import textwrap
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')

MODEL_ICONS = {
    'claude': 'https://www.anthropic.com/_next/image?url=%2Fimages%2Ficons%2Fclaude-app-icon.png&w=96&q=75',
    'cladue': 'https://www.anthropic.com/_next/image?url=%2Fimages%2Ficons%2Fclaude-app-icon.png&w=96&q=75',
    'gpt': 'https://cdn.oaistatic.com/_next/static/media/apple-touch-icon.59f2e898.png',
    'gemini': 'https://www.gstatic.com/lamda/images/gemini_sparkle_v002_d4735304ff6292a690345.svg',
    'qwen': 'https://img.alicdn.com/imgextra/i3/O1CN01YPqjHT1hbfBhJmPMH_!!6000000004295-2-tps-500-500.png',
    'deepseek': 'https://avatars.githubusercontent.com/u/130298873?s=200&v=4',
    'glm': 'https://open.bigmodel.cn/static/zhipuai/favicon.ico',
    'moonshot': 'https://platform.moonshot.cn/favicon.ico',
    'kimi': 'https://platform.moonshot.cn/favicon.ico',
    'doubao': 'https://lf-cdn.coze.cn/obj/coze-web-cn/obric/coze/favicon.png',
    'ernie': 'https://yiyan.baidu.com/favicon.ico',
    'erine': 'https://yiyan.baidu.com/favicon.ico',
    'spark': 'https://xinghuo.xfyun.cn/favicon.ico',
    'minimax': 'https://platform.minimaxi.com/favicon.ico',
    'yi': 'https://www.01.ai/favicon.ico',
    'baichuan': 'https://platform.baichuan-ai.com/favicon.ico',
    'grok': 'https://x.com/favicon.ico',
    'longcat': 'https://avatars.githubusercontent.com/u/130298873?s=200&v=4',
    'hunyuan': 'https://hunyuan.tencent.com/favicon.ico',
    'mimo': 'https://www.minimaxi.com/favicon.ico',
    'step': 'https://stepfun.ai/favicon.ico',
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


def _sanitize_excel_text(text: str) -> str:
    """清理 Excel 导出的转义标记（如 _x000D_、_x000A_ 等），转为正常换行。"""
    if not text:
        return ''
    s = str(text)
    # _x000D_ = CR, _x000A_ = LF, _x0009_ = Tab；可能带数字如 _x000D_、_x000B_
    s = re.sub(r'_x([0-9a-fA-F]{4})_', lambda m: _excel_unicode_to_char(m.group(1)), s)
    return s


def _excel_unicode_to_char(hex_str: str) -> str:
    try:
        code = int(hex_str, 16)
        if code == 0x000D or code == 0x000A:  # CR/LF -> \n
            return '\n'
        if code == 0x0009:  # Tab -> \t
            return '\t'
        return chr(code) if code < 0x110000 else ''
    except Exception:
        return ''


def _nl2br(text: str) -> str:
    if not text:
        return ''
    sanitized = _sanitize_excel_text(text)
    return _escape_html(sanitized).replace('\n', '<br>')


def _safe_float(value, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if not np.isnan(result) else default
    except Exception:
        return default


def _task_count(questions) -> int:
    """题目数量：优先用 qid 去重后的数量（与题目表实际题目数一致）。"""
    if questions is None or questions.empty:
        return 0
    if 'qid' in questions.columns:
        return int(questions['qid'].dropna().nunique())
    return questions.shape[0]


def _source_counts(questions) -> tuple:
    """(公开数据题数, 自建数据题数)，按 source 分组统计 unique qid。"""
    public_cnt = self_cnt = 0
    if questions is None or questions.empty or 'source' not in questions.columns or 'qid' not in questions.columns:
        return 0, 0
    _self = {'H', 'R', 'HM', 'M'}
    for src, grp in questions.groupby('source', dropna=False):
        cnt = grp['qid'].dropna().nunique()
        if str(src).strip() in _self:
            self_cnt += cnt
        else:
            public_cnt += cnt
    return int(public_cnt), int(self_cnt)


def _source_counts_3(questions) -> tuple:
    """(公开题数, 纯人工自建题数, M合成题数)。纯人工=H/R/HM，更能反映真实业务难度。"""
    pub = human = m_cnt = 0
    if questions is None or questions.empty or 'source' not in questions.columns or 'qid' not in questions.columns:
        return 0, 0, 0
    _human = {'H', 'R', 'HM'}
    for src, grp in questions.groupby('source', dropna=False):
        cnt = int(grp['qid'].dropna().nunique())
        s = str(src).strip()
        if s == 'M':
            m_cnt += cnt
        elif s in _human:
            human += cnt
        else:
            pub += cnt
    return pub, human, m_cnt


def _safe_str(value, max_len: int = 0) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ''
    text = str(value)
    if max_len > 0 and len(text) > max_len:
        return text[:max_len] + '...'
    return text

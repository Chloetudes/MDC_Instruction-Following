# -*- coding: utf-8 -*-
"""
厂商与模型对照配置

结构：厂商、厂商性质、标准命名、原始评测录入名
用于：厂商排名、厂商系列排行、厂商模型对照表
"""
import pandas as pd

# 厂商模型对照表：(厂商, 厂商性质, 标准命名, 原始评测录入名)
MODEL_VENDOR_TABLE = [
    # OpenAI
    ('OpenAI', '国外大厂', 'GPT-5.2 Pro (2025-11-21)', 'GPT-5.2-pro-2025-21-11'),
    ('OpenAI', '国外大厂', 'GPT-5.2 (2025-12-11)', 'GPT-5.2-2025-12-11'),
    ('OpenAI', '国外大厂', 'GPT-5.1', 'gpt-5.1'),
    # Anthropic
    ('Anthropic', '国外大厂', 'Claude 4.6 Opus Thinking', 'cladue-opus-4-6-thinking'),
    ('Anthropic', '国外大厂', 'Claude 4.5 Opus', 'Claude-Opus-4.5'),
    ('Anthropic', '国外大厂', 'Claude 4.5 Sonnet Thinking', 'Claude-Sonnet-4.5-Thinking'),
    # Google
    ('Google', '国外大厂', 'Gemini 3.1 Pro', 'gemini-3.1-pro'),
    ('Google', '国外大厂', 'Gemini 3 Pro Preview', 'gemini-3-pro-preview'),
    ('Google', '国外大厂', 'Gemini 3 Flash Preview', 'Gemini-3-Flash-preview'),
    # xAI
    ('xAI', '国外大厂', 'Grok 4.1', 'Grok-4.1'),
    ('xAI', '国外大厂', 'Grok 4 Fast Reasoning', 'Grok-4-Fast-Reasoning'),
    # 阿里巴巴
    ('阿里巴巴', '国内大厂', 'Qwen 3.5 Plus', 'qwen3.5-plus'),
    ('阿里巴巴', '国内大厂', 'Qwen 3 Max Thinking', 'Qwen3-Max-Thinking'),
    ('阿里巴巴', '国内大厂', 'Qwen 3 Max Thinking (2026-01-23)', 'qwen-3-max-thinking'),
    ('阿里巴巴', '国内大厂', 'Qwen 3 Max', 'Qwen3-Max'),
    ('阿里巴巴', '国内大厂', 'Qwen Plus Thinking (2025-12-01)', 'Qwen-Plus-Think-20251201'),
    ('阿里巴巴', '国内大厂', 'Qwen Plus (2025-12-01)', 'Qwen-Plus-2025-12-01'),
    # 字节跳动
    ('字节跳动', '国内大厂', 'Doubao Seed 2.0 Pro', 'doubao-seed-2.0-pro'),
    ('字节跳动', '国内大厂', 'Doubao Seed 1.8 (251215)', 'doubao-seed-1-8-251215'),
    ('字节跳动', '国内大厂', 'Doubao Seed 1.6 Thinking (251015)', 'Doubao-seed-1.6-Thinking-251015'),
    # 腾讯
    ('腾讯', '国内大厂', 'Hunyuan 2.0 Thinking (2025-11-09)', 'Hunyuan-2.0-Thinking-20251109'),
    ('腾讯', '国内大厂', 'Hunyuan T1 (2025-08-22)', 'Hunyuan-T1-20250822'),
    # 百度
    ('百度', '国内大厂', 'ERNIE 5.0', 'erine5.0'),
    # 小米
    ('小米', '国内大厂', 'MiMo V2 Flash Thinking', 'MiMo-V2-Flash-Think'),
    ('小米', '国内大厂', 'MiMo V2 Flash', 'MiMo-V2-Flash'),
    # 美团
    ('美团', '国内大厂', 'LongCat', 'LongCat'),
    # 智谱AI
    ('智谱AI', '国内独角兽', 'GLM-5', 'glm-5'),
    ('智谱AI', '国内独角兽', 'GLM-4.7', 'GLM-4.7'),
    ('智谱AI', '国内独角兽', 'GLM-4.7 Flash', 'GLM-4.7-flash'),
    ('智谱AI', '国内独角兽', 'GLM-4.6 Reasoning', 'GLM-4.6（Reasoning）'),
    # 深度求索
    ('深度求索', '国内独角兽', 'DeepSeek V3.2 Thinking', 'DeepSeek-V3.2-Thinking'),
    ('深度求索', '国内独角兽', 'DeepSeek V3.2', 'DeepSeek-V3.2'),
    # 月之暗面
    ('月之暗面', '国内独角兽', 'Kimi k2.5', 'kimi-k2.5'),
    ('月之暗面', '国内独角兽', 'Kimi k2 Thinking', 'kimi-k2-thinking'),
    ('月之暗面', '国内独角兽', 'Kimi k2 (0905)', 'Kimi-K2-0905'),
    # 稀宇科技
    ('稀宇科技', '国内独角兽', 'MiniMax M2.5', 'minimax-m2.5'),
    ('稀宇科技', '国内独角兽', 'MiniMax M2.1', 'minimax-m2.1'),
    ('稀宇科技', '国内独角兽', 'MiniMax M2', 'MiniMax-M2'),
    # 阶跃星辰
    ('阶跃星辰', '国内独角兽', 'Step 3.5 Flash', 'step-3.5-flash'),
]


def _norm(s: str) -> str:
    return str(s).strip().lower() if s is not None else ''


def _build_lookup():
    """构建 原始名 -> (厂商, 厂商性质, 标准命名) 的精确匹配表"""
    lookup = {}
    for vendor, vtype, std_name, orig_name in MODEL_VENDOR_TABLE:
        key = _norm(orig_name)
        if key and key not in lookup:
            lookup[key] = (vendor, vtype, std_name)
    return lookup


# 原始名（归一化）-> (厂商, 厂商性质, 标准命名)
_ORIGINAL_TO_VENDOR = _build_lookup()

# 国内厂商（用于 国内/国外 二元变量）
_DOMESTIC_VENDORS = {
    '阿里巴巴', '字节跳动', '腾讯', '百度', '小米', '美团',
    '智谱AI', '深度求索', '月之暗面', '稀宇科技', '阶跃星辰',
}
# 开源模型（可下载或 API 开源）；其余默认闭源
_OPEN_SOURCE_MODELS = {'deepseek', 'qwen', 'glm', 'yi', 'baichuan', 'minimax', 'mimo', 'step', 'longcat'}

# 厂商名 -> 匹配 pattern 列表（用于未在精确表中的模型回退）
_VENDOR_PATTERNS = [
    ('OpenAI', ['gpt-5', 'gpt-4', 'gpt']),
    ('Anthropic', ['claude', 'cladue']),
    ('Google', ['gemini']),
    ('xAI', ['grok']),
    ('阿里巴巴', ['qwen']),
    ('字节跳动', ['doubao']),
    ('腾讯', ['hunyuan']),
    ('百度', ['ernie', 'erine']),
    ('小米', ['mimo']),
    ('美团', ['longcat']),
    ('智谱AI', ['glm']),
    ('深度求索', ['deepseek']),
    ('月之暗面', ['kimi', 'moonshot']),
    ('稀宇科技', ['minimax']),
    ('阶跃星辰', ['step']),
]


def get_model_vendor(model_name: str) -> str:
    """根据模型名返回厂商。优先精确匹配，否则用 pattern 回退。"""
    key = _norm(model_name)
    if key and key in _ORIGINAL_TO_VENDOR:
        return _ORIGINAL_TO_VENDOR[key][0]
    m = key
    for vendor, patterns in _VENDOR_PATTERNS:
        for p in patterns:
            if p.lower() in m:
                return vendor
    return '其他'


def get_model_vendor_info(model_name: str) -> tuple:
    """返回 (厂商, 厂商性质, 标准命名)。未在表中则厂商性质、标准命名为空。"""
    key = _norm(model_name)
    if key and key in _ORIGINAL_TO_VENDOR:
        return _ORIGINAL_TO_VENDOR[key]
    vendor = get_model_vendor(model_name)
    return (vendor, '', '')


def get_model_domestic(model_name: str) -> str:
    """国内/国外。"""
    v = get_model_vendor(model_name)
    return '国内' if v in _DOMESTIC_VENDORS else '国外'


def get_model_thinking(model_name: str) -> str:
    """深度思考/非深度思考。模型名含 thinking、reasoning 等判为深度思考。"""
    m = _norm(model_name)
    for kw in ('thinking', 'reasoning'):
        if kw in m:
            return '深度思考'
    return '非深度思考'


def get_model_open_source(model_name: str) -> str:
    """开源/闭源。"""
    m = _norm(model_name)
    for prefix in _OPEN_SOURCE_MODELS:
        if prefix in m:
            return '开源'
    return '闭源'


def get_model_metadata(model_name: str) -> dict:
    """返回 {厂商, 厂商性质, 标准命名, 国内/国外, 深度思考, 开源/闭源}。"""
    vendor, vtype, std_name = get_model_vendor_info(model_name)
    return {
        '厂商': vendor,
        '厂商性质': vtype,
        '标准命名': std_name or model_name,
        '国内/国外': get_model_domestic(model_name),
        '深度思考': get_model_thinking(model_name),
        '开源/闭源': get_model_open_source(model_name),
    }


def get_vendor_model_table_df():
    """返回厂商模型对照表 DataFrame，列：厂商、厂商性质、标准命名、原始评测录入名"""
    rows = [{'厂商': v, '厂商性质': t, '标准命名': s, '原始评测录入名': o}
            for v, t, s, o in MODEL_VENDOR_TABLE]
    return pd.DataFrame(rows)


# 兼容 report.py / report_writer_html 的旧接口
def _get_model_vendor(model_name: str) -> str:
    return get_model_vendor(model_name)

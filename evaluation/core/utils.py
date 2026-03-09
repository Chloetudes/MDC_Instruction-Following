# -*- coding: utf-8 -*-
import hashlib
import os
import re
import math
import time

import pandas as pd


def safe_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return '\n'.join(str(item) for item in value if item is not None)
    if isinstance(value, float):
        try:
            if math.isnan(value):
                return ""
        except Exception:
            pass
    return str(value)


def _norm_for_fingerprint(value) -> str:
    """Normalize value for fingerprint: strip, treat NaN/None as empty."""
    s = safe_str(value)
    return s.replace("\r\n", "\n").replace("\r", "\n").strip()


def compute_input_fingerprint(row: dict, columns: list) -> str:
    """
    根据指定列计算行的输入指纹，用于增量更新：仅当指纹变化时才重新生成/覆盖。
    row: 字典或可下标对象；columns: 列名列表（顺序固定）。
    """
    parts = []
    for col in columns:
        val = row.get(col) if isinstance(row, dict) else getattr(row, col, None)
        parts.append(f"{col}={_norm_for_fingerprint(val)}")
    text = "|".join(parts)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sanitize_text(text: str) -> str:
    if text is None:
        return ""
    text = str(text)
    text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", " ", text)
    text = text.replace("\u200B", "").replace("\u200C", "").replace("\u200D", "").replace("\uFEFF", "")
    text = text.replace("\u00A0", " ").replace("\u3000", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def safe_save_excel(df: pd.DataFrame, output_path: str, max_retries: int = 3) -> bool:
    for attempt in range(max_retries):
        try:
            os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
            temp_path = output_path + '.tmp.xlsx'
            df.to_excel(temp_path, index=False, engine='openpyxl')
            pd.read_excel(temp_path, nrows=1)

            if os.path.exists(output_path):
                os.replace(temp_path, output_path)
            else:
                os.rename(temp_path, output_path)
            return True
        except Exception as e:
            print(f"⚠️  保存失败 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(1.0)
            else:
                temp_path = output_path + '.tmp.xlsx'
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass
                return False
    return False

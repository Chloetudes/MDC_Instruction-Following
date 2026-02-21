# -*- coding: utf-8 -*-
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

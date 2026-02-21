# -*- coding: utf-8 -*-
import os
import pandas as pd
from evaluation.core.utils import safe_str, sanitize_text


class SyspromptManager:
    def __init__(self, sysprompt_excel: str):
        self.sysprompts = self._load(sysprompt_excel)

    def _load(self, excel_path: str) -> dict:
        print(f"📖 读取Sysprompt配置: {excel_path}")

        if not os.path.exists(excel_path):
            print(f"⚠️  Sysprompt文件不存在，将使用空配置")
            return {}

        try:
            df = pd.read_excel(excel_path)
        except Exception as e:
            print(f"⚠️  无法读取Sysprompt文件: {e}")
            return {}

        if 'stage' not in df.columns or 'sysprompt' not in df.columns:
            print(f"⚠️  Sysprompt表必须包含 stage 和 sysprompt 列")
            return {}

        sysprompts = {}
        for _, row in df.iterrows():
            stage = safe_str(row['stage']).strip()
            sysprompt = safe_str(row['sysprompt']).strip()
            if stage:
                sysprompts[stage] = sanitize_text(sysprompt) if sysprompt and sysprompt.lower() != 'nan' else ""

        print(f"✅ 加载 {len(sysprompts)} 个Sysprompt:")
        for stage, content in sysprompts.items():
            print(f"  - {stage}: {'已配置' if content else '空'}")
        print()

        return sysprompts

    def get(self, stage: str, default: str = "") -> str:
        return self.sysprompts.get(stage, default)

import os
from typing import List, Dict, Optional, Tuple

import pandas as pd
from datetime import datetime, timedelta


def _load_idealab_models_sheet(path: str) -> pd.DataFrame:
    """读取 idealab_models.xlsx 的主数据 sheet（idealab_models）。"""
    if not os.path.exists(path):
        raise FileNotFoundError(f"模型清单不存在: {path}")

    xls = pd.ExcelFile(path)
    sheet = "idealab_models" if "idealab_models" in xls.sheet_names else xls.sheet_names[0]
    df = pd.read_excel(path, sheet_name=sheet)
    required_cols = {"展示名称", "api_model_id", "来源"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"模型表缺少必要列: {missing}，请检查 {path}")
    return df


def _str_to_bool(val) -> bool:
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    return s in ("是", "yes", "y", "true", "1")


def load_models_from_excel(path: str,
                           provider: Optional[str] = None,
                           only_available: bool = False) -> List[Dict]:
    """
    从 idealab_models.xlsx 加载待测模型列表。

    返回的每项为：
      { "provider": 来源, "model": api_model_id, "enable_thinking": bool, "展示名称": 展示名称 }

    参数：
    - provider: 若指定，仅加载该「来源」的行（如 'idealab'）；None 时不过滤。
    - only_available: 为 True 时，仅加载「可用状态」为“是”的行（用于批量回复前只用已测可用模型）。
    """
    df = _load_idealab_models_sheet(path)

    if provider:
        df = df[df["来源"] == provider]

    if only_available and "可用状态" in df.columns:
        mask = df["可用状态"].astype(str).str.strip()
        df = df[mask == "是"]

    if df.empty:
        return []

    configs: List[Dict] = []
    has_thinking = "Thinking" in df.columns

    for _, row in df.iterrows():
        model_name = str(row["api_model_id"]).strip()
        if not model_name:
            continue
        cfg: Dict = {
            "provider": str(row["来源"]).strip(),
            "model": model_name,
            "enable_thinking": _str_to_bool(row["Thinking"]) if has_thinking else False,
        }
        display_name = str(row.get("展示名称", "")).strip()
        if display_name:
            cfg["展示名称"] = display_name
        configs.append(cfg)

    return configs


def try_use_cached_availability(
    path: str,
    model_configs: List[Dict],
    max_age_days: int = 14,
    provider: Optional[str] = None,
) -> Tuple[bool, Optional[pd.DataFrame]]:
    """
    若表格中所有待测模型的「最后测试时间」距当前不足 max_age_days 天，则返回 (True, cached_df)，
    可直接用表格记录的可用状态，跳过 API 检测。否则返回 (False, None) 表示需要重新跑可用性测试。

    cached_df 格式与 test_all_models 返回的 DataFrame 一致（provider, model, available, response_time 等），
    便于下游复用交互选择逻辑。response_time 为 None（无近期实测数据）。
    """
    if not model_configs or not os.path.exists(path):
        return False, None
    df = _load_idealab_models_sheet(path)
    if "可用状态" not in df.columns or "最后测试时间" not in df.columns:
        return False, None

    now = datetime.now()
    max_age = timedelta(days=max_age_days)
    rows_out = []

    for cfg in model_configs:
        prov = str(cfg.get("provider", "")).strip()
        model_id = str(cfg.get("model", "")).strip()
        if provider and prov != provider:
            continue
        mask = (df["来源"].astype(str).str.strip() == prov) & (df["api_model_id"].astype(str).str.strip() == model_id)
        matched = df[mask]
        if matched.empty:
            return False, None
        row = matched.iloc[0]
        last_str = row.get("最后测试时间")
        if pd.isna(last_str) or not str(last_str).strip():
            return False, None
        try:
            if isinstance(last_str, datetime):
                last_dt = last_str
            else:
                last_dt = pd.to_datetime(last_str)
            if now - last_dt.to_pydatetime() > max_age:
                return False, None
        except Exception:
            return False, None
        avail_str = str(row.get("可用状态", "")).strip()
        available = avail_str == "是"
        rows_out.append({
            "provider": prov,
            "model": model_id,
            "available": available,
            "response_time": None,
            "error": None if available else "（使用表格缓存状态）",
            "展示名称": str(row.get("展示名称", "")).strip(),
            "enable_thinking": _str_to_bool(row.get("Thinking", False)) if "Thinking" in df.columns else False,
        })

    if not rows_out:
        return False, None
    return True, pd.DataFrame(rows_out)


def update_availability_in_excel(path: str,
                                 test_results: pd.DataFrame,
                                 provider: Optional[str] = None) -> None:
    """
    将模型可用性测试结果写回 idealab_models.xlsx。

    匹配键：(来源, api_model_id) == (provider, model)。
    - provider 参数不为空时，仅更新该 provider 的行。
    - 写回列：「可用状态」「最后测试时间」。
    """
    if test_results is None or test_results.empty:
        return

    df = _load_idealab_models_sheet(path)

    # 构建 (provider, model) -> available 映射；provider 做大小写不敏感匹配
    results = test_results.copy()
    results["provider"] = results["provider"].astype(str).str.strip()
    results["model"] = results["model"].astype(str).str.strip()
    if provider:
        results = results[results["provider"].str.lower() == provider.lower()]

    availability_map = {
        (row["provider"].lower(), row["model"]): bool(row["available"])
        for _, row in results.iterrows()
    }
    if not availability_map:
        return

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 确保列存在
    if "可用状态" not in df.columns:
        df["可用状态"] = ""
    if "最后测试时间" not in df.columns:
        df["最后测试时间"] = ""

    for idx, row in df.iterrows():
        src = str(row["来源"]).strip()
        mid = str(row["api_model_id"]).strip()
        key = (src.lower(), mid)
        if key in availability_map:
            available = availability_map[key]
            df.at[idx, "可用状态"] = "是" if available else "否"
            df.at[idx, "最后测试时间"] = now_str

    # 如存在说明 sheet，则一并保留
    xls = pd.ExcelFile(path)
    help_df = None
    help_sheet = None
    for name in xls.sheet_names:
        if name != "idealab_models":
            help_sheet = name
            break
    if help_sheet:
        help_df = pd.read_excel(path, sheet_name=help_sheet)

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="idealab_models")
        if help_df is not None and help_sheet is not None:
            help_df.to_excel(writer, index=False, sheet_name=help_sheet)


def mark_single_model_unavailable(models_excel_path: str, provider: str, model: str) -> bool:
    """
    立即将单个模型在表格中标记为不可用。用于首次失败时即时更新，即使用户中断运行也能生效。
    返回是否成功写入。
    """
    if not models_excel_path or not os.path.exists(models_excel_path):
        return False
    df_fail = pd.DataFrame([{"provider": str(provider).strip(), "model": str(model).strip(), "available": False}])
    update_availability_in_excel(models_excel_path, df_fail, provider=None)
    return True


def mark_failed_models_from_replies(
    models_excel_path: str,
    replies_df: Optional[pd.DataFrame] = None,
    provider: Optional[str] = None,
    blacklisted_models: Optional[list] = None,
) -> int:
    """
    将调用失败的模型在表格中标记为不可用（可用状态=否）。
    来源：(1) 回复表中 status=='error' 的记录；(2) 本次运行被黑名单跳过的模型（连接/权限等首次失败即跳过）。
    下次加载 only_available=True 时，这些模型将不再出现在可选清单中。
    返回被标记为不可用的模型数量。
    """
    if not os.path.exists(models_excel_path):
        return 0
    to_mark = []
    # 1. 从回复表提取 status=='error' 的 (provider, model)
    if replies_df is not None and not replies_df.empty and "status" in replies_df.columns and "provider" in replies_df.columns:
        failed = replies_df[replies_df["status"] == "error"]
        failed_with_provider = failed[failed["provider"].notna() & (failed["provider"].astype(str).str.strip() != "")]
        if not failed_with_provider.empty:
            for _, row in failed_with_provider[["provider", "model"]].drop_duplicates().iterrows():
                to_mark.append({"provider": str(row["provider"]).strip(), "model": str(row["model"]).strip()})
    # 2. 从黑名单提取（首次调用即失败被跳过的模型，无回复表记录）
    if blacklisted_models:
        for item in blacklisted_models:
            p = str(item.get("provider", "")).strip()
            m = str(item.get("model", "")).strip()
            if p and m:
                to_mark.append({"provider": p, "model": m})
    if not to_mark:
        return 0
    df_fail = pd.DataFrame(to_mark).drop_duplicates(subset=["provider", "model"])
    if provider:
        df_fail = df_fail[df_fail["provider"] == provider]
    if df_fail.empty:
        return 0
    df_fail["available"] = False
    update_availability_in_excel(models_excel_path, df_fail, provider=provider)
    return len(df_fail)


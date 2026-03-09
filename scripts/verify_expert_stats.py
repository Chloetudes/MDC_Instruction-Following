#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
验证：19 位专家每人都有完整统计（通过 qid 与题目表专家对应，不依赖回复表回填）。
运行：在项目根目录执行  python scripts/verify_expert_stats.py
"""
import os
import sys
import tempfile
import pandas as pd

# 项目根 = Evaluation_xr
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from evaluation.analysis.data_loader import load_and_preprocess, _normalize_qid


def main():
    n_experts = 19
    expert_names = [f"专家{i}" for i in range(1, n_experts + 1)]
    n_questions = n_experts * 2  # 每人 2 题
    qids = list(range(1, n_questions + 1))
    # 题目表：qid -> 专家（前两题专家1，接下来两题专家2，...）
    question_experts = []
    for i in range(n_questions):
        question_experts.append(expert_names[i // 2])
    models = ["model_a", "model_b"]

    with tempfile.TemporaryDirectory() as tmp:
        questions_path = os.path.join(tmp, "questions.xlsx")
        replies_path = os.path.join(tmp, "replies.xlsx")

        # 题目表：含 专家 列，无 出题人 列
        questions_df = pd.DataFrame({
            "qid": qids,
            "专家": question_experts,
            "query": [f"query_{q}" for q in qids],
            "evaluation_criteria": ["criteria"] * n_questions,
        })
        questions_df.to_excel(questions_path, index=False)

        # 回复表：有 专家打分，故意 无 出题人 列（或全空），验证仅靠 qid→题目表 也能得到 19 人
        rows = []
        for qid in qids:
            for model in models:
                rows.append({
                    "qid": qid,
                    "model": model,
                    "reply": "r",
                    "专家打分": 70.0,
                    "eval_batch_2": 72.0,
                })
        replies_df = pd.DataFrame(rows)
        replies_df.to_excel(replies_path, index=False)

        # 运行加载与预处理
        data = load_and_preprocess(
            questions_excel=questions_path,
            replies_excel=replies_path,
            human_excel=None,
            eval_batch_id="batch_2",
        )

        expert_scores = data["expert_scores"]
        assert not expert_scores.empty, "expert_scores 不应为空"
        unique_raters = set(expert_scores["rater"].dropna().astype(str))
        expert_names_set = set(expert_names)
        found = expert_names_set & unique_raters
        missing = expert_names_set - found
        has_nan = expert_scores["rater"].isna().any() or (
            expert_scores["rater"].astype(str).str.strip().isin(["nan", "None", "NaN"]).any()
        )

        print("\n" + "=" * 60)
        print("专家统计验证结果")
        print("=" * 60)
        print(f"  题目表专家数: {n_experts}")
        print(f"  expert_scores 中唯一 rater 数: {len(unique_raters)}")
        print(f"  唯一 rater 列表: {sorted(unique_raters)}")
        print(f"  与题目表专家名匹配数: {len(found)}/{n_experts}")
        if missing:
            print(f"  ❌ 缺失专家: {missing}")
        else:
            print(f"  ✓ 19 位专家均在 expert_scores 中出现")
        if has_nan:
            print(f"  ❌ 仍存在 nan/None 作为 rater")
        else:
            print(f"  ✓ 无 nan 作为 rater")
        print("=" * 60)

        assert not missing, f"缺失专家: {missing}"
        assert not has_nan, "rater 列存在 nan"
        assert len(found) == n_experts, f"应有 {n_experts} 位专家，实际 {len(found)}"
        print("\n✅ 验证通过：每位专家都有统计，且无 nan。\n")


if __name__ == "__main__":
    main()

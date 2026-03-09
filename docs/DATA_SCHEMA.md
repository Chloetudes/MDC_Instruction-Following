# 数据表结构与字段说明

本框架依赖题目表、回复表及（可选）人工标注表。以下为最小必要列与推荐列，便于自建数据接入。

---

## 1. 题目表（questions）

通常路径：`outputs/<project_id>/questions/questions_<data_batch>.xlsx`，或通过配置 `questions_excel` 指定。

| 列名 | 必填 | 说明 |
|------|------|------|
| qid | 是 | 题目唯一标识，字符串 |
| query | 是 | 用户指令/问题正文 |
| L1 | 推荐 | 一级意图（如 问答、规划建议、语言理解、文本生成、角色扮演） |
| L2 | 可选 | 二级分类 |
| L3 | 可选 | 三级分类 |
| source | 推荐 | 数据来源，如 H/R/HM/M（自建）、to_b/nlp_*（公开） |
| difficulty_level | 可选 | 难度等级 E/D/C/B/A/S |
| difficulty_score | 可选 | 难度分数 |
| evaluation_criteria | 自动/可选 | 评分标准（可由 generate_criteria 生成） |
| reference | 可选 | 参考答案（可由 generate_references 生成） |
| reference_type | 可选 | 参考类型 |
| 专家 / 出题人 | 可选 | 用于专家统计与一致性分析 |

说明：`source` 用于统计口径切换（公开/自建/混合）；系统会派生 `source_group`、`source_group_3`。

---

## 2. 回复表（replies）

通常路径：`outputs/<project_id>/replies/replies_<data_batch>.xlsx`。

| 列名 | 必填 | 说明 |
|------|------|------|
| qid | 是 | 与题目表一致 |
| model | 是 | 模型名称 |
| reply | 是 | 模型回复正文 |
| eval_<batch_id> | 评测后 | 数值分数（如 85.5） |
| eval_<batch_id>_raw | 评测后 | 裁判完整输出（含 rubrics_check 等 JSON） |

可选：`专家打分`、`专家理由`（用于专家纠偏与人机一致性）。多轮场景可有 `session_id`、`turn_id`、`history_context`。

---

## 3. 评测输出中的 rubrics_check（eval_*_raw）

裁判模型输出中可解析的检查点结构：每个检查点 id（如 D2_1、D5_3）对应 `result`（PASS/FAIL）与 `reason`。  
维度含义：D1 业务理解，D2 流程步骤，D3 边界范围，D4 格式形式，D5 内容质量。  
主分数为 D2–D5 维度加权通过率（权重可配置）。

---

## 4. 项目配置与路径

- 项目目录：`outputs/<project_id>/`，其下可有 `config.json` 覆盖全局配置。
- 题目/回复未显式指定时，默认使用 `questions_<data_batch>.xlsx`、`replies_<data_batch>.xlsx`。
- 完整配置说明见 `docs/CONFIG_PLAYBOOK.md` 与 `docs/STAGES_REFERENCE.md`。

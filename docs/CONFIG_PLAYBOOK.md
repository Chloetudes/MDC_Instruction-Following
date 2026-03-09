# 配置与流程速查（新同学必读）

本文档回答三个问题：
- **流程有哪些环节（stage）**、叫什么名字？
- **以后跑评测/统计/报告到底改哪里？**
- **如何按数据来源（公开/自建/混合）切换统计口径？**

> 阶段完整列表与 preset 代号见：`docs/STAGES_REFERENCE.md`（本仓库已包含）。

---

## 一、只改一个地方：项目配置 `outputs/<project_id>/config.json`

推荐做法：
- **不要改** `evaluation/main.py`（它是默认模板/兜底配置，更多用于第一次初始化或开发调试）。
- 每个项目在 `outputs/<project_id>/config.json` 里配置即可。

示例：`outputs/my_project/config.json`。

---

## 二、两种常用模式怎么配？

### 1) 评测模式（评估/统计/出报告）

最常见（有评分列时可以不跑 evaluate，只跑统计+报告）：

```json
{
  "stages": ["analyze_results", "generate_report"],
  "data_batch": "eval",
  "eval_batch_id": "batch_2",
  "report": {
    "report_title": "指令遵循评测报告",
    "top_n_cases": 20,
    "use_report_cache": true,
    "force_refresh": false
  }
}
```

如果要重新评估回复（写入 `eval_{batch_id}`）：

```json
{
  "stages": ["evaluate_replies", "analyze_results", "generate_report"],
  "data_batch": "eval",
  "batch_id": "batch_2",
  "eval_batch_id": "batch_2"
}
```

> **重要**：`batch_id`（写入列）和 `eval_batch_id`（读取列）表达同一件事。系统已做归一化：只写一个也能自动对齐，推荐只写 `eval_batch_id`。

### 2) 专家统计模式（只看数据质量/一致性，不出综合报告）

```json
{
  "stages": ["analyze_results"],
  "data_batch": "eval",
  "eval_batch_id": "batch_2",
  "analysis": {
    "stats_only": true
  }
}
```

---

## 三、阶段（stage）是什么？怎么记名字？

你只需要记两件事：
- `stages` 支持 **preset 代号**（最省事），例如 `"stages": "eval_only"`、`"stages": "analyze"`。
- 也支持显式列表，例如 `["evaluate_replies", "analyze_results", "generate_report"]`。

完整对照表见：`docs/STAGES_REFERENCE.md`。

---

## 四、评测模式下：如何按数据来源切换统计口径？

题目表里有 `source`（以及由系统派生的 `source_group/source_group_3`）：
- 自建：`H / R / HM / M`（**自建包含 R**）
- 公开：其他 source（如 to_b / nlp_* 等）

在 `config.json` 的 `report` 中配置三类口径（只影响统计口径，**不改变统计逻辑**）：

### 1) 全量（默认）：公开 + 自建混合

```json
"report": {
  "stats_source_scope": "all"
}
```

### 2) 只统计公开数据

```json
"report": {
  "stats_source_scope": "public_only"
}
```

### 3) 只统计自建数据（含 R）

```json
"report": {
  "stats_source_scope": "self_built_only"
}
```

### 4) 自定义：按 source 精确 include / exclude

```json
"report": {
  "stats_source_scope": "custom",
  "stats_include_sources": ["H", "R", "HM", "M"],
  "stats_exclude_sources": []
}
```

报告中会显示“本次统计口径”，便于确认当前跑的是公开/自建/全量。

---

## 五、案例分析（LLM 典型案例）与统计口径的关系

- **统计口径**（榜单/全景/L1 汇总）由 `report.stats_source_scope` 决定。
- **典型案例分析**默认仍**排除 `source=R`**（避免 R 类型题进入案例分析），不影响统计。

---

## 六、常见问题

### Q1：为什么配置里有 `data_batch` 和 `eval_batch_id`？
- `data_batch`：文件/目录批次（决定读取 `questions_{batch}.xlsx`、`replies_{batch}.xlsx`）。
- `eval_batch_id`：评分列批次（决定用哪一列 `eval_{id}` 作为分数列进行统计/报告）。

两者不是一回事，建议都保留。


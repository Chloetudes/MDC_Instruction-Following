# 阶段预设与单阶段参考

> 在 config.json 中可用 `"stages": "预设代号"` 或 `"stages": ["预设", "单阶段"]` 简化配置。JSON 不支持注释，阶段列表见下文。

## 预设代号

| 代号 | 说明 | 包含阶段 |
|------|------|----------|
| **full** | 全链路数据合成+评测 | 指令生成→提取→质量评估→多轮扩展→题目提升→标准→参考→回复→评估→分析→报告 |
| **criteria** | 仅生成评分标准 | generate_criteria |
| **references** | 仅生成参考答案 | generate_references |
| **criteria_ref** | 标准+参考 | generate_criteria, generate_references |
| **criteria_ref_reply** | 标准+参考+回复 | generate_criteria, generate_references, generate_replies |
| **reply** | 仅回复生成 | generate_replies |
| **eval** | 仅回复评估 | evaluate_replies |
| **eval_only** | 评估+分析+报告 | evaluate_replies, analyze_results, generate_report |
| **reply_eval** | 回复+评估+分析+报告 | generate_replies, evaluate_replies, analyze_results, generate_report |
| **analyze** | 分析+报告 | analyze_results, generate_report |

## 单阶段列表（可组合）

| 阶段 id | 说明 |
|---------|------|
| test_models | 模型可用性测试 |
| test_judge_models | 裁判模型可用性测试 |
| generate_instructions | 指令生成 |
| extract_instructions | 指令提取 |
| evaluate_instructions | 指令质量评估 |
| expand_multiturn | 多轮对话扩展 |
| promote_to_questions | 数据提升为题目 |
| generate_criteria | 评分标准生成 |
| generate_references | 参考答案生成 |
| generate_replies | 模型回复生成 |
| summarize_expert_assessments | 专家评估归纳 |
| evaluate_replies | 回复评估 |
| analyze_multiturn | 多轮分析 |
| analyze_results | 统计分析 |
| generate_report | 综合报告 |
| generate_series_reports | 厂商专项报告 |

## 配置示例

```json
{
  "stages": "criteria",
  "data_batch": "prof"
}
```

```json
{
  "stages": ["criteria", "references"],
  "data_batch": "prof"
}
```

```json
{
  "stages": "eval_only",
  "data_batch": "prof"
}
```

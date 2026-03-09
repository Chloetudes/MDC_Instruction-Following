# 评估系统配置文件目录

将以下两个基础配置表格放入本目录，系统即可直接读取，无需修改代码路径。

## 必须放入的文件

| 文件名 | 说明 |
|--------|------|
| `sysprompts.xlsx` | 各阶段系统提示词配置表（可选，优先使用 sysprompts/ 目录下的 txt 文件） |
| `schema.xlsx` | 指令生成的任务类型 Schema 表（可选） |

## sysprompts/ 目录（推荐方式）

系统优先从 `data/sysprompts/` 目录下读取 `.txt` 文件，文件名即为 stage key。

**本仓库不包含真实系统提示词。** 使用前请复制占位示例并自行填写：

```bash
cp -r data/sysprompts.example data/sysprompts
# 然后编辑 data/sysprompts/*.txt 填入各阶段提示词
```

| 文件名 | 对应 stage key | 说明 |
|--------|---------------|------|
| `instruction_generation.txt` | `instruction_generation` | 指令生成阶段的系统提示词（可含变量 `{{TASK_INTENT_TABLE}}`，由 schema 按批注入） |
| `instruction_quality_evaluation.txt` | `instruction_quality_evaluation` | 质量评估阶段的系统提示词 |
| `criteria_generation.txt` | `criteria_generation` | 评分标准生成阶段的系统提示词 |
| `reference_generation.txt` | `reference_generation` | 参考答案生成阶段的系统提示词 |
| `reply_evaluation.txt` | `reply_evaluation` | 回复评估阶段的系统提示词 |
| `report_analysis.txt` | `report_analysis` | 报告分析阶段的系统提示词 |
| `multiturn_expansion.txt` | `multiturn_expansion` | 多轮扩展阶段的系统提示词 |

`data/sysprompts/` 已在 `.gitignore` 中，你的真实提示词不会被提交。

## sysprompts.xlsx 格式（备用方式）

如果需要通过 Excel 配置，`stage` 列的值必须与上表中的 stage key 完全一致：

| stage | sysprompt |
|-------|-----------|
| instruction_generation | （指令生成阶段的系统提示词） |
| instruction_quality_evaluation | （质量评估阶段的系统提示词） |
| criteria_generation | （评分标准生成阶段的系统提示词） |
| reference_generation | （参考答案生成阶段的系统提示词） |
| reply_evaluation | （回复评估阶段的系统提示词） |
| report_analysis | （报告分析阶段的系统提示词） |
| multiturn_expansion | （多轮扩展阶段的系统提示词） |

## schema.xlsx 格式（可选）

用于控制指令生成的任务类型分布与**按类型遍历、按数量合成**。Sheet1 为任务类型表，列说明如下：

| 列名 | 必需 | 说明 |
|------|------|------|
| `L1` | 是 | 一级任务类型 |
| `L2` | 是 | 二级任务类型 |
| `L3` | 是 | 三级任务类型 |
| `count` 或 `合成数量` | 是 | 该类型目标合成数量（每类按此数量生成若干批） |
| `difficulty` | 否 | 难度等级，会注入到任务意图表 |
| `description` | 否 | 特征描述，会注入到任务意图表 |
| `example` | 否 | 该类型示范案例，会注入到任务意图表与用户提示 |

- 程序按 schema 行 × 合成数量 展开为多批，每批只聚焦**当前行**的任务类型：`instruction_generation` 的系统提示中的 **`{{TASK_INTENT_TABLE}}`** 会被替换为当前类型的单行表格（来自 schema 的 L1/L2/L3/难度/特征描述/示范案例），从而每次生成更聚焦。
- Sheet2 由程序维护：记录 `target_count` 与 `synthesized_count`，用于统计已合成条数。

## 使用方式

在 `evaluation/main.py` 的 CONFIG 中已默认配置：

```python
'sysprompt_excel': "data/sysprompts.xlsx",
```

系统会先扫描 `data/sysprompts/` 目录下的 txt 文件，再读取 xlsx 文件（xlsx 中的配置会覆盖同名 txt 文件）。

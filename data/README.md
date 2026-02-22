# 评估系统配置文件目录

将以下两个基础配置表格放入本目录，系统即可直接读取，无需修改代码路径。

## 必须放入的文件

| 文件名 | 说明 |
|--------|------|
| `sysprompts.xlsx` | 各阶段系统提示词配置表（可选，优先使用 sysprompts/ 目录下的 txt 文件） |
| `schema.xlsx` | 指令生成的任务类型 Schema 表（可选） |

## sysprompts/ 目录（推荐方式）

系统优先从 `data/sysprompts/` 目录下读取 `.txt` 文件，文件名即为 stage key：

| 文件名 | 对应 stage key | 说明 |
|--------|---------------|------|
| `instruction_generation.txt` | `instruction_generation` | 指令生成阶段的系统提示词 |
| `instruction_quality_evaluation.txt` | `instruction_quality_evaluation` | 质量评估阶段的系统提示词 |
| `criteria_generation.txt` | `criteria_generation` | 评分标准生成阶段的系统提示词 |
| `reference_generation.txt` | `reference_generation` | 参考答案生成阶段的系统提示词 |
| `reply_evaluation.txt` | `reply_evaluation` | 回复评估阶段的系统提示词 |
| `report_analysis.txt` | `report_analysis` | 报告分析阶段的系统提示词 |
| `multiturn_expansion.txt` | `multiturn_expansion` | 多轮扩展阶段的系统提示词 |

以上文件已内置在 `data/sysprompts/` 目录中，可直接使用。

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

用于控制指令生成的任务类型分布，包含以下列：
- `L1`：一级任务类型
- `L2`：二级任务类型
- `L3`：三级任务类型（可选）
- `count`：目标生成数量
- `difficulty`：难度等级（可选）
- `description`：特征描述（可选）

## 使用方式

在 `evaluation/main.py` 的 CONFIG 中已默认配置：

```python
'sysprompt_excel': "data/sysprompts.xlsx",
```

系统会先扫描 `data/sysprompts/` 目录下的 txt 文件，再读取 xlsx 文件（xlsx 中的配置会覆盖同名 txt 文件）。

# 评估系统配置文件目录

将以下两个基础配置表格放入本目录，系统即可直接读取，无需修改代码路径。

## 必须放入的文件

| 文件名 | 说明 |
|--------|------|
| `sysprompts.xlsx` | 各阶段系统提示词配置表 |
| `schema.xlsx` | 指令生成的任务类型 Schema 表（可选） |

## sysprompts.xlsx 格式

| stage | sysprompt |
|-------|-----------|
| generate_instructions | （指令生成阶段的系统提示词） |
| evaluate_instructions | （质量评估阶段的系统提示词） |
| generate_criteria | （评分标准生成阶段的系统提示词） |
| generate_references | （参考答案生成阶段的系统提示词） |
| evaluate_replies | （回复评估阶段的系统提示词） |
| generate_report | （报告生成阶段的系统提示词） |
| expand_multiturn | （多轮扩展阶段的系统提示词） |

## schema.xlsx 格式（可选）

用于控制指令生成的任务类型分布，包含以下列：
- `L1`：一级任务类型
- `L2`：二级任务类型
- `L3`：三级任务类型（可选）
- `count`：已生成数量（系统自动维护）
- `target`：目标生成数量（可选）

## 使用方式

在 `evaluation/main.py` 的 CONFIG 中已默认配置：

```python
'sysprompt_excel': "data/evaluation/sysprompts.xlsx",
```

将你的 `sysprompts.xlsx` 和 `schema.xlsx` 直接放入本目录即可。

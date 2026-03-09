# 系统提示词示例（占位）

本目录为**占位示例**，不含真实业务提示词。使用前请：

1. **复制本目录为 `data/sysprompts`**（与 `sysprompts.example` 同级）：
   ```bash
   cp -r data/sysprompts.example data/sysprompts
   ```
2. 在 `data/sysprompts/` 下按阶段填写各 `.txt` 内容（文件名即 stage key，见下方列表）。
3. 配置中指定 `sysprompt_excel` 为 `data/sysprompts.xlsx` 时，系统会从同级的 `sysprompts/` 目录加载 `.txt`；若使用项目目录 `outputs/<project_id>/sysprompts.xlsx`，则从该项目目录下的 `sysprompts/` 加载。

**阶段 key 与文件名对应**：

| 文件名 | 用途 |
|--------|------|
| instruction_generation.txt | 指令生成 |
| instruction_quality_evaluation.txt | 指令质量评估 |
| criteria_generation.txt | 评分标准生成 |
| reference_generation.txt | 参考答案生成 |
| reply_evaluation.txt | 回复评估（裁判） |
| report_analysis.txt | 报告分析 |
| multiturn_expansion.txt | 多轮扩展 |

**注意**：`data/sysprompts/` 已加入 `.gitignore`，你的真实提示词不会被提交到仓库。

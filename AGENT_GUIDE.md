# 评测系统 Agent 操作指南

> 本文档是给 Agent 看的系统说明书。你的目标是：自主完成一次完整的多模型能力评测，产出可供人类查阅的评测报告。

---

## 一、系统目标

本系统评测多个 AI 模型在**中文复杂指令跟随**任务上的能力。

**核心流程**：合成测试指令 → 生成评分标准 → 生成参考答案 → 多模型作答 → 裁判模型评分 → 输出报告

**最终产物**：
- `outputs/evaluation/reports/evaluation_report_*.html` — 可视化评测报告
- `outputs/evaluation/reports/analysis_report.xlsx` — 统计分析数据

---

## 二、快速启动

```bash
# Step 0: 安装依赖
pip install -r requirements.txt

# Step 1: 自检（确认环境就绪）
python agent_runner.py --mode check

# Step 2: 测试模式（验证全流程无 bug，约 5-10 分钟）
python agent_runner.py --mode test

# Step 3: 完整评测（正式运行，约 2-8 小时，取决于指令数量和模型数量）
python agent_runner.py --mode full

# 如果中途中断，续跑：
python agent_runner.py --mode resume
```

---

## 三、前置条件（必须人工完成）

在运行任何模式前，需要确认以下配置已就绪：

### 3.1 API Key 配置

打开 `config.py`，将所有 `"YOUR_API_KEY_HERE"` 替换为真实的 API Key。

**最少需要配置的 provider**（用于裁判模型）：
- 在 `config.example.py` 复制为 `config.py` 后配置任一 provider（如 `openai`、`dashscope`、`openrouter`）

**被测模型**（在 `evaluation/main.py` 的 `CONFIG['reply_model_configs']` 中配置）：
```python
'reply_model_configs': [
    {"model": "qwen3-max-2026-01-23", "enable_thinking": True},
    {"model": "gpt-5.2-chat-latest", "enable_thinking": False},
    # 添加更多被测模型...
],
```

### 3.2 裁判模型配置

在 `evaluation/main.py` 的 `CONFIG` 中确认：
```python
'provider': "openai",       # 裁判模型的 provider（与 config.py 一致）
'model': "claude_sonnet4_5", # 裁判模型名称
```

### 3.3 Sysprompt 文件

确认 `data/sysprompts/` 目录下以下文件存在且有内容：
- `instruction_generation.txt` — 指令生成提示词
- `instruction_quality_evaluation.txt` — 质量评估提示词
- `criteria_generation.txt` — 评分标准生成提示词
- `reference_generation.txt` — 参考答案生成提示词
- `reply_evaluation.txt` — 回复评估提示词
- `report_analysis.txt` — 报告分析提示词
- `multiturn_expansion.txt` — 多轮扩展提示词

---

## 四、各阶段详解

### Stage 0: 指令生成（generate_instructions）

**目标**：调用 LLM 批量生成复杂中文测试指令，输出 JSON 格式

**输入**：无（或可选的 schema.xlsx 控制任务类型分布）

**输出**：`outputs/stage0_generation/generated_responses.xlsx`
- 列：`id`, `response`（JSON 数组字符串）, `L1`, `L2`, `L3`

**关键配置**：
```python
'generation': {
    'num_batches': 15,      # 生成批次数，每批 3 条，共约 45 条原始指令
    'items_per_batch': 3,   # 每批生成几条
}
```

**常见报错**：
- `FileNotFoundError: generated_responses.xlsx` → 正常，第一次运行会自动创建
- `API 调用失败` → 检查 `config.py` 中对应 provider 的 API key

---

### Stage 0.5: 指令提取（extract_instructions）

**目标**：解析 stage0 输出的 JSON 字符串，提取每条独立指令

**输入**：`stage0_generation/generated_responses.xlsx`

**输出**：`stage0.5_extraction/extracted_instructions.xlsx`
- 列：`qid`（如 `batch_001_Q1`）, `original_id`, `item_num`, `task_type`, `query`

**常见报错**：
- `JSON 解析失败` → 正常，解析器会跳过格式错误的批次，不影响整体
- 输出为空 → 检查 stage0 的 response 列是否包含有效 JSON

---

### Stage 1: 质量评估（evaluate_instructions）【可选】

**目标**：用裁判模型对每条指令打分，过滤低质量指令

**输入**：`stage0.5_extraction/extracted_instructions.xlsx`

**输出**：`stage1_quality/evaluated_instructions.xlsx`
- 新增列：`raw_response`（YAML 格式评估结果）, `status`（ok/filtered）

**注意**：`status=ok` 的指令才会进入后续流程

**常见报错**：
- `连续 3 次评估失败` → 裁判模型不可用，检查 provider/model 配置

---

### Stage 0.7: 多轮扩展（expand_multiturn）【可选】

**目标**：将单轮指令扩展为多轮对话场景

**输入**：`stage0.5_extraction/extracted_instructions.xlsx`

**输出**：`stage0.7_multiturn/multiturn_instructions.xlsx`
- 列：`session_id`, `turn_id`, `qid`, `query`, `history_context`

---

### promote_to_questions

**目标**：将合成数据转为标准评测题目格式

**数据源优先级**（自动选择）：
1. `stage1_quality/evaluated_instructions.xlsx`（已质量过滤）
2. `stage0.7_multiturn/multiturn_instructions.xlsx`（多轮）
3. `stage0.5_extraction/extracted_instructions.xlsx`（单轮原始）

**输出**：`questions/questions.xlsx`

---

### Stage 1.5: 评分标准生成（generate_criteria）

**目标**：为每条指令生成 Rubric 检查清单（D1_1, D1_2... 格式）

**输入**：`questions/questions.xlsx`

**输出**：`questions/questions_with_criteria.xlsx`
- 新增列：`evaluation_criteria`（Rubric 文本）

**关键**：Rubric 质量直接决定评分的准确性，这是最重要的阶段之一

---

### Stage 2: 参考答案生成（generate_references）

**目标**：为每条指令生成高质量参考答案

**输入**：`questions/questions_with_criteria.xlsx`

**输出**：`questions/questions_complete.xlsx`
- 新增列：`reference`（参考答案）, `reference_type`

---

### Stage 3: 回复生成（generate_replies）

**目标**：让所有被测模型回答每条指令

**输入**：`questions/questions_complete.xlsx`

**输出**：`replies/replies.xlsx`
- 列：`qid`, `model`, `reply`, `timestamp`

**关键配置**：
```python
'reply_model_configs': [
    {"model": "模型名称"},
    {"model": "模型名称", "enable_thinking": True},  # 开启思考模式
]
```

---

### Stage 4: 回复评估（evaluate_replies）

**目标**：裁判模型按 Rubric 逐条评分，输出 JSON 格式评分结果

**输入**：`questions/questions_complete.xlsx` + `replies/replies.xlsx`

**输出**：`replies/replies.xlsx`（原地更新，新增 `eval_{batch_id}` 列）

**评分格式**（JSON）：
```json
{
  "FINAL_SCORE": 85,
  "SATISFIED_ALL_REQUIREMENTS": false,
  "FATAL_FAILURES": ["D3_2: 未按要求输出表格格式"],
  "rubrics_check": {"D1_1": "PASS", "D3_2": "FAIL"}
}
```

**常见报错**：
- `缺少 evaluation_criteria 列` → 需要先运行 generate_criteria
- `缺少 reference 列` → 需要先运行 generate_references

---

### Stage 5a: 统计分析（analyze_results）

**目标**：计算各模型的综合得分、维度得分、一致性指标

**输出**：`reports/analysis_report.xlsx`（多个 Sheet）

---

### Stage 5b: 可视化报告（generate_report）

**目标**：生成 HTML 和 Markdown 格式的评测报告

**输出**：
- `reports/evaluation_report_*.html`
- `reports/evaluation_report_*.md`

---

## 五、数据流图

```
[无输入]
    ↓ generate_instructions（LLM 生成 JSON 批次）
generated_responses.xlsx
    ↓ extract_instructions（解析 JSON）
extracted_instructions.xlsx
    ↓ evaluate_instructions（可选，质量过滤）
evaluated_instructions.xlsx
    ↓ expand_multiturn（可选，多轮扩展）
multiturn_instructions.xlsx
    ↓ promote_to_questions（自动选最优数据源）
questions.xlsx
    ↓ generate_criteria（生成 Rubric）
questions_with_criteria.xlsx
    ↓ generate_references（生成参考答案）
questions_complete.xlsx
    ↓ generate_replies（多模型作答）
replies.xlsx
    ↓ evaluate_replies（裁判评分）
replies.xlsx（含评分列）
    ↓ analyze_results + generate_report
analysis_report.xlsx + evaluation_report.html
```

---

## 六、常见问题与修复

### Q1: `FileNotFoundError: No such file or directory: 'outputs/...'`

**原因**：上游阶段未运行，输入文件不存在

**修复**：
1. 检查 `outputs/` 目录下已有哪些文件
2. 用 `--mode resume` 自动检测并从正确位置续跑
3. 或手动在 `main.py` 的 `CONFIG['stages']` 中添加缺失的上游阶段

---

### Q2: `连续 N 次评估失败，评估模型可能不可用`

**原因**：裁判模型 API 调用失败

**修复步骤**：
1. 检查 `config.py` 中 `provider` 对应的 `api_key` 是否正确
2. 检查 `model` 名称是否在 `MODEL_PROVIDER_MAPPING` 中
3. 尝试换一个 provider（如从 `openai` 换到 `dashscope`）

---

### Q3: `缺少必需列: evaluation_criteria`

**原因**：`questions.xlsx` 缺少 Rubric 列，需要先运行 `generate_criteria`

**修复**：在 `CONFIG['stages']` 中确保 `generate_criteria` 在 `generate_references` 之前

---

### Q4: `JSON 解析失败` / 提取结果为空

**原因**：LLM 输出的 JSON 格式不合法

**修复**：
1. 检查 `data/sysprompts/instruction_generation.txt` 末尾的输出格式说明是否完整
2. 适当降低 `instruction_temperature`（从 0.9 降到 0.7）
3. 换一个更稳定的生成模型

---

### Q5: `SyspromptManager` 读取为空

**原因**：sysprompt 文件名与代码中的 key 不匹配

**文件名 ↔ key 对照表**：

| 文件名 | 代码中的 key |
|--------|-------------|
| `instruction_generation.txt` | `instruction_generation` |
| `instruction_quality_evaluation.txt` | `instruction_quality_evaluation` |
| `criteria_generation.txt` | `criteria_generation` |
| `reference_generation.txt` | `reference_generation` |
| `reply_evaluation.txt` | `reply_evaluation` |
| `report_analysis.txt` | `report_analysis` |
| `multiturn_expansion.txt` | `multiturn_expansion` |

---

### Q6: 评分结果全为 0 或 NaN

**原因**：`evaluate_replies` 阶段的 JSON 解析失败

**修复**：
1. 查看 `replies.xlsx` 中 `eval_{batch_id}` 列的原始内容
2. 检查 `data/sysprompts/reply_evaluation.txt` 中的输出格式要求
3. 查看 `evaluation/stages/stage4_evaluate.py` 中的 `extract_scores_from_evaluation` 函数

---

## 七、调整评测规模

### 小规模测试（快速验证，约 30 分钟）
```python
# evaluation/main.py
CONFIG = {
    'stages': ['generate_criteria', 'generate_references', 'generate_replies', 'evaluate_replies'],
    # 使用 scripts/generate_test_data.py 预先生成的 3 条测试指令
    'reply_model_configs': [{"model": "qwen3-max"}],  # 只测 1 个模型
    'max_workers': 2,
}
```

### 中规模评测（推荐，约 2-4 小时）
```python
CONFIG = {
    'stages': ['generate_instructions', 'extract_instructions', 'evaluate_instructions',
               'promote_to_questions', 'generate_criteria', 'generate_references',
               'generate_replies', 'evaluate_replies', 'analyze_results', 'generate_report'],
    'generation': {'num_batches': 20, 'items_per_batch': 3},  # 约 60 条指令
    'reply_model_configs': [  # 3-5 个被测模型
        {"model": "qwen3-max"},
        {"model": "gpt-4o"},
        {"model": "claude_sonnet4_5"},
    ],
    'max_workers': 5,
}
```

### 大规模评测（完整，约 8-24 小时）
```python
CONFIG = {
    'generation': {'num_batches': 50, 'items_per_batch': 3},  # 约 150 条指令
    'reply_model_configs': [...],  # 10+ 个被测模型
    'max_workers': 10,
}
```

---

## 八、输出文件说明

```
outputs/
├── stage0_generation/
│   └── generated_responses.xlsx    # LLM 生成的原始 JSON 批次
├── stage0.5_extraction/
│   └── extracted_instructions.xlsx # 解析后的独立指令
├── stage1_quality/
│   └── evaluated_instructions.xlsx # 质量评估结果（含 status 列）
├── stage0.7_multiturn/
│   └── multiturn_instructions.xlsx # 多轮对话版本
├── questions/
│   ├── questions.xlsx              # 标准评测题目
│   ├── questions_with_criteria.xlsx # 含 Rubric
│   └── questions_complete.xlsx     # 含 Rubric + 参考答案（最终题目文件）
├── replies/
│   └── replies.xlsx                # 各模型回复 + 评分结果
├── reports/
│   ├── analysis_report.xlsx        # 统计分析（多 Sheet）
│   ├── evaluation_report_*.html    # 可视化报告（主要查阅文件）
│   └── evaluation_report_*.md      # Markdown 格式报告
└── library/
    ├── model_availability_test.xlsx # 模型可用性测试结果
    └── constraint_library.xlsx      # 约束库（自动维护）
```

---

## 九、Agent 自主决策原则

1. **遇到报错先读代码**：定位出错的文件和行号，理解逻辑后再修复
2. **优先续跑而非重跑**：已完成的阶段有 checkpoint，不要删除已有输出文件
3. **修复后验证**：修复 bug 后，先用 `--mode test` 验证，再用 `--mode resume` 续跑
4. **不要修改 sysprompt**：sysprompt 文件由人工设计，不要自行修改内容
5. **不要修改 config.py 中的 API key**：这是敏感信息，只读不写
6. **遇到模型不可用**：在 `CONFIG['reply_model_configs']` 中移除不可用的模型，继续运行

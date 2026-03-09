# 复杂指令遵循评测系统 — 完整使用指南

> 本文档面向评测系统的使用者，涵盖从环境准备、数据准备、配置设置到运行评测、查看报告的完整流程。

---

## 目录

1. [快速开始](#1-快速开始)
2. [系统架构与数据流](#2-系统架构与数据流)
3. [三种使用模式](#3-三种使用模式)
4. [目录与文件规划](#4-目录与文件规划)
5. [配置文件详解](#5-配置文件详解)
   - 5.1 [sysprompts.xlsx — 系统提示词配置](#51-syspromptsxlsx--系统提示词配置)
   - 5.2 [schema.xlsx — 任务体系表（可选）](#52-schemaxlsx--任务体系表可选)
   - 5.3 [see.xlsx — 扩充种子表（可选）](#53-seexlsx--扩充种子表可选)
   - 5.4 [questions.xlsx — 题目表](#54-questionsxlsx--题目表)
   - 5.5 [human.xlsx — 人工标注表（可选）](#55-humanxlsx--人工标注表可选)
6. [main.py CONFIG 完整配置说明](#6-mainpy-config-完整配置说明)
7. [全流程运行步骤（含操作示例）](#7-全流程运行步骤含操作示例)
   - 7.1 [模式A：全链路数据合成 + 评测](#71-模式a全链路数据合成--评测)
   - 7.2 [模式B：已有题目，直接评测](#72-模式b已有题目直接评测)
   - 7.3 [模式C：仅数据合成，不评测](#73-模式c仅数据合成不评测)
   - 7.4 [多轮对话评测](#74-多轮对话评测)
   - 7.5 [增量评估（新增模型或新批次）](#75-增量评估新增模型或新批次)
8. [各阶段详细说明](#8-各阶段详细说明)
9. [分析报告与可视化报告说明](#9-分析报告与可视化报告说明)
10. [常见问题与注意事项](#10-常见问题与注意事项)

---

## 1. 快速开始

### 环境要求

```bash
pip install pandas openpyxl scipy numpy tqdm
```

### 运行命令

```bash
python -m evaluation.main
```

推荐以项目配置为准：在 `outputs/<project_id>/config.json` 中配置并运行（例如 `outputs/my_project/config.json`）。  
`evaluation/main.py` 的 `CONFIG` 作为默认模板/兜底配置，通常不需要频繁修改。

配置与流程速查见：`docs/CONFIG_PLAYBOOK.md`；阶段模板与单阶段列表见：`docs/STAGES_REFERENCE.md`。

### 最简运行示例（已有题目，只做评测）

**第一步**：准备 `outputs/evaluation/questions/questions.xlsx`，至少包含 `qid` 和 `query` 两列。

**第二步**：修改 `evaluation/main.py`：

```python
CONFIG = {
    'stages': ['generate_criteria', 'generate_references', 'generate_replies', 'evaluate_replies'],
    'sysprompt_excel': 'data/evaluation/sysprompts.xlsx',
    'output_base_dir': 'outputs/evaluation',
    'provider': 'openai',  # 或 dashscope 等，对应 config.py 中配置的 provider
    'model': 'claude_sonnet4_5',
    'timeout': 300,
    'batch_id': 'batch_1',
    'reply_model_configs': [
        {'model': 'gpt-4o'},
        {'model': 'qwen-max'},
    ],
    'max_workers': 5,
    'checkpoint_interval': 10,
}
```

**第三步**：运行：

```bash
python -m evaluation.main
```

---

## 2. 系统架构与数据流

```
【数据合成链路（可选）】
sysprompts.xlsx + schema.xlsx + see.xlsx
        │
        ▼
Stage 0: generate_instructions
        │  generated_responses.xlsx（JSON批次）
        ▼
Stage 0.5: extract_instructions
        │  extracted_instructions.xlsx（每条query独立一行，含qid）
        ▼
Stage 1: evaluate_instructions（可选，质量过滤）
        │  evaluated_instructions.xlsx（含status=ok/fail）
        ▼
Stage 0.7: expand_multiturn（可选，单轮→多轮扩展）
        │  multiturn_instructions.xlsx（含session_id/turn_id/history_context）
        ▼
promote_to_questions（自动选择最优数据源）
        │
        ▼
【评测链路（核心）】
questions.xlsx（qid, query, [L1/L2/L3], [human_rubrics], [reference]）
        │
        ▼
Stage 1.5: generate_criteria
        │  questions_with_criteria.xlsx（+ evaluation_criteria）
        ▼
Stage 2: generate_references
        │  questions_complete.xlsx（+ reference, reference_type）
        ▼
Stage 3: generate_replies（多模型并发）
        │  replies.xlsx（qid, model, reply, ...）
        ▼
Stage 4: evaluate_replies（裁判模型评分）
        │  replies.xlsx（新增 eval_{batch_id} 列）
        ▼
Stage 5a: analyze_results → analysis_report.xlsx
Stage 5b: generate_report → evaluation_report.html + .md
```

**关键设计原则**：
- 每个阶段读取上一阶段的 Excel 输出，**断点续跑**（已处理的行自动跳过）
- 全链路使用 `qid` 作为唯一标识符
- 多轮对话字段（`session_id`、`turn_id`、`history_context`）全程透传

---

## 3. 三种使用模式

| 模式 | 适用场景 | 必须准备的文件 | 运行的 stages |
|------|----------|----------------|---------------|
| **模式A** | 从零开始，自动生成题目并评测 | `sysprompts.xlsx`（含 `instruction_generation`） | `generate_instructions` → `extract_instructions` → `promote_to_questions` → `generate_criteria` → `generate_references` → `generate_replies` → `evaluate_replies` |
| **模式B** | 已有题目，直接评测 | `sysprompts.xlsx` + `questions.xlsx` | `generate_criteria` → `generate_references` → `generate_replies` → `evaluate_replies` |
| **模式C** | 仅合成数据，不评测 | `sysprompts.xlsx` | `generate_instructions` → `extract_instructions` → `evaluate_instructions`（可选）→ `promote_to_questions` |

---

## 4. 目录与文件规划

### 推荐目录结构

```
项目根目录/
├── evaluation/              # 代码目录（不需要修改）
├── data/
│   └── evaluation/
│       ├── sysprompts.xlsx  # ← 必须准备（Sysprompt 配置）
│       ├── schema.xlsx      # ← 可选（任务体系表，控制生成类型分布）
│       └── see.xlsx         # ← 可选（扩充种子表，提升生成质量）
└── outputs/
    └── evaluation/          # 系统自动创建，所有输出在此
        ├── stage0_generation/
        │   └── generated_responses.xlsx
        ├── stage0.5_extraction/
        │   └── extracted_instructions.xlsx
        ├── stage0.7_multiturn/
        │   └── multiturn_instructions.xlsx
        ├── stage1_quality/
        │   └── evaluated_instructions.xlsx
        ├── questions/
        │   ├── questions.xlsx              # ← 模式B时你需要手动放置这个文件
        │   ├── questions_with_criteria.xlsx
        │   └── questions_complete.xlsx
        ├── replies/
        │   └── replies.xlsx
        ├── library/
        │   └── model_availability_test.xlsx
        └── reports/
            ├── analysis_report.xlsx
            ├── evaluation_report_*.html
            └── evaluation_report_*.md
```

---

## 5. 配置文件详解

### 5.1 sysprompts.xlsx — 系统提示词配置

**格式**：两列 Excel 文件

| 列名 | 说明 |
|------|------|
| `stage` | 阶段标识符（固定值，见下表） |
| `sysprompt` | 该阶段使用的系统提示词 |

**支持的 stage 标识符**：

| stage 值 | 对应阶段 | 是否必填 |
|----------|----------|----------|
| `instruction_generation` | Stage 0 指令生成 | 模式A必填 |
| `instruction_quality_evaluation` | Stage 1 指令质量评估 | 可选 |
| `criteria_generation` | Stage 1.5 评分标准生成（基础模式） | 强烈建议 |
| `criteria_generation_with_human` | Stage 1.5（有人工初版时） | 可选 |
| `criteria_generation_with_expert` | Stage 1.5（有专家示范时） | 可选 |
| `reference_generation` | Stage 2 参考答案生成 | 强烈建议 |
| `evaluation` | Stage 4 回复评估打分 | **必填** |
| `report_analysis` | Stage 5 价值题目 AI 分析 | 可选 |
| `multiturn_expansion` | Stage 0.7 多轮扩展 | 使用多轮时必填 |

**evaluation Sysprompt 设计要点**（Stage 4 评分质量的关键）：

```
你是一位严格、公正的评测专家。请根据评分标准对模型回复进行评分。

评分规则：
1. 评分范围：0-10分（或 0-100分，与评分标准保持一致）
2. 逐条评估每个约束条目，给出该条目的得分和理由
3. 最后给出总分，格式必须为：总分：XX 或 总分: XX分
4. 参考答案仅作参考，不是唯一正确答案
5. 保持客观公正，不受模型品牌影响
```

---

### 5.2 schema.xlsx — 任务体系表（可选）

**作用**：精确控制 Stage 0 生成什么类型的指令、各类型生成多少批次。不配置时系统退回纯 Sysprompt 驱动模式。

**Sheet1 — 任务体系定义**：

| 字段名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `L1` | 字符串 | ✅ | 一级任务类型（如：写作、代码、推理） |
| `L2` | 字符串 | ✅ | 二级任务类型（如：创意写作、算法编程） |
| `L3` | 字符串 | ✅ | 三级任务类型（最细粒度，注入 prompt 中） |
| `count` | 整数 | ✅ | 该 L3 子类型需要生成的批次数量 |
| `difficulty` | 字符串 | 可选 | 难度等级（如 `A`/`B`/`C`/`D`） |
| `description` | 字符串 | 可选 | 特征描述，进一步约束生成方向 |
| `example` | 字符串 | 可选 | 体系示范案例，直接注入 prompt 作为参考 |

**Sheet1 示例**：

| L1 | L2 | L3 | count | difficulty | description | example |
|----|----|----|-------|------------|-------------|---------|
| 写作 | 创意写作 | 短篇故事续写 | 5 | C | 包含明确字数和风格约束 | 请续写以下故事片段... |
| 代码 | 算法编程 | 数据结构实现 | 8 | B | Python/Java，需附单元测试 | 实现一个线程安全的LRU缓存... |
| 推理 | 逻辑推理 | 多步因果推断 | 4 | A | 多步推理，答案唯一可验证 | |

**Sheet2 — 合成数量计数器**（系统自动维护，无需手动创建）：

| 字段名 | 说明 |
|--------|------|
| `L1` / `L2` / `L3` | 类型标识 |
| `target_count` | 目标批次数（来自 Sheet1 的 count） |
| `synthesized_count` | 已累计合成批次数（系统自动更新） |

> 配置 `schema.xlsx` 后，`num_batches` 参数将被忽略，总批次数由 Sheet1 中所有 `count` 之和决定。

---

### 5.3 see.xlsx — 扩充种子表（可选）

**作用**：为每个类型补充典型示例，系统按 L3 > L2 > L1 优先级匹配，随机抽取最多 3 条作为 few-shot 参考。

| 字段名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `query` | 字符串 | ✅ | 示例指令内容 |
| `L1` | 字符串 | 可选 | 一级类型（用于优先匹配） |
| `L2` | 字符串 | 可选 | 二级类型 |
| `L3` | 字符串 | 可选 | 三级类型（匹配优先级最高） |

**示例**：

| query | L1 | L2 | L3 |
|-------|----|----|-----|
| 请用不超过300字，以第一人称视角写一篇关于"第一次独自旅行"的短文，要求包含至少3个具体的感官描写。 | 写作 | 创意写作 | 短篇故事续写 |
| 实现一个Python装饰器，用于统计函数执行时间，要求支持多次调用取平均值，并提供重置功能。 | 代码 | 算法编程 | 数据结构实现 |

---

### 5.4 questions.xlsx — 题目表

**模式B（已有题目）时需要手动放置到** `outputs/evaluation/questions/questions.xlsx`。

**必填字段**：

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `qid` | 字符串 | 题目唯一 ID，建议格式 `Q001`、`Q_001` |
| `query` | 字符串 | 题目内容（指令文本） |

**推荐字段（用于分维度分析）**：

| 字段名 | 类型 | 说明 | 示例值 |
|--------|------|------|--------|
| `L1` | 字符串 | 一级分类 | `写作`、`代码`、`推理` |
| `L2` | 字符串 | 二级分类 | `创意写作`、`Python编程` |
| `L3` | 字符串 | 三级分类 | `故事续写`、`算法题` |
| `source` | 字符串 | 数据来源 | `H`（人工）、`M`（模型）、`HM`（混合） |
| `difficulty_level` | 字符串 | 难度等级 | `E`/`D`/`C`/`B`/`A`/`S`（从易到难） |

**可选字段（用于增强评分标准生成质量）**：

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `human_rubrics` | 字符串 | 人工初版评分标准，Stage 1.5 会在此基础上优化 |
| `reference` | 字符串 | 专家示范回复，Stage 2 会直接保留（reference_type=human） |
| `reply_evaluation` | 字符串 | 专家对示范回复的评分说明，辅助生成更精准的评分标准 |

**示例数据**：

```
qid       | query                              | L1   | L2       | difficulty_level | human_rubrics
----------|------------------------------------|----- |----------|------------------|---------------
Q_001     | 请写一篇500字的科技新闻报道...      | 写作 | 新闻写作  | C                |
Q_002     | 用Python实现一个二叉树的层序遍历... | 代码 | 算法     | B                | 1.正确性(5分) 2.时间复杂度(3分) 3.注释(2分)
```

---

### 5.5 human.xlsx — 人工标注表（可选）

用于计算人机一致性和标注员组内一致性，在 `analyze_results` 和 `generate_report` 阶段使用。

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `qid` 或 `QID` | 字符串 | 题目 ID（系统自动将 QID 重命名为 qid） |
| `model` | 字符串 | 被标注的模型名称 |
| `ann1_score` | 数值 | 标注员1的打分 |
| `ann2_score` | 数值 | 标注员2的打分 |
| `ann1_name` | 字符串 | 标注员1姓名（可选） |
| `ann2_name` | 字符串 | 标注员2姓名（可选） |

---

## 6. main.py CONFIG 完整配置说明

`evaluation/main.py` 中的 `CONFIG` 字典是系统的**唯一配置入口**，无需修改其他文件。

```python
CONFIG = {
    # ========== 执行阶段（按需开启，顺序由系统自动排序）==========
    'stages': [
        # --- 数据合成阶段（可选）---
        # 'test_models',           # 测试模型可用性（建议首次运行时开启）
        # 'generate_instructions', # Stage 0: 生成指令批次（JSON格式）
        # 'extract_instructions',  # Stage 0.5: 解析JSON，提取每条query
        # 'evaluate_instructions', # Stage 1: 指令质量评估（status=ok才进入后续）
        # 'expand_multiturn',      # Stage 0.7: 单轮→多轮对话扩展（可选）
        # 'promote_to_questions',  # 将合成数据转为评测题目格式

        # --- 评测阶段（核心）---
        'generate_criteria',       # Stage 1.5: 生成评分标准
        'generate_references',     # Stage 2: 生成参考答案
        'generate_replies',        # Stage 3: 多模型生成回复
        'evaluate_replies',        # Stage 4: 裁判模型评分

        # --- 分析报告阶段 ---
        # 'analyze_results',       # Stage 5a: 统计分析（生成 Excel 报告）
        # 'generate_report',       # Stage 5b: 可视化报告（生成 HTML + MD）
    ],

    # ========== 基础路径配置 ==========
    'sysprompt_excel': 'data/evaluation/sysprompts.xlsx',
    'output_base_dir': 'outputs/evaluation',

    # ========== 裁判模型配置（用于 Stage 1/1.5/2/4/5）==========
    'provider': 'openai',  # 或 dashscope 等，对应 config.py 中配置的 provider           # Provider 名称（对应 config.py 中的配置）
    'model': 'claude_sonnet4_5',     # 裁判模型名称
    'timeout': 300,                  # 单次请求超时（秒）

    # ========== 温度配置 ==========
    'instruction_temperature': 0.9,  # Stage 0 生成温度（高多样性）
    'criteria_temperature': 0.3,     # Stage 1.5 生成温度（低随机性，保证一致性）
    'reference_temperature': 0.7,    # Stage 2 生成温度
    'reply_temperature': 0.6,        # Stage 3 生成温度
    'evaluation_temperature': 0.3,   # Stage 4 评估温度（低随机性，保证稳定性）

    # ========== 数据合成配置（Stage 0）==========
    'generation': {
        'num_batches': 15,           # 生成批次数（配置 schema.xlsx 后此参数被忽略）
        'items_per_batch': 3,        # 每批次生成的指令数量
        'schema_excel': None,        # 任务体系表路径，None 表示纯 Sysprompt 驱动
        'see_excel': None,           # 扩充种子表路径，None 表示不使用种子
    },

    # ========== 多轮扩展配置（Stage 0.7，可选）==========
    'multiturn': {
        'min_turns': 3,              # 最少轮次
        'max_turns': 8,              # 最多轮次
        'temperature': 0.8,          # 生成温度
    },

    # ========== promote_to_questions 数据源（可选）==========
    # None 时按优先级自动选择：stage1_quality > stage0.7_multiturn > stage0.5_extraction
    # 设置后直接使用指定文件，忽略自动选择逻辑
    'promote_source_excel': None,

    # ========== 评估批次 ID ==========
    # 每次评估会在 replies.xlsx 中新增 eval_{batch_id} 列
    # 修改 batch_id 可保留历史评估，进行多批次对比
    'batch_id': 'batch_1',

    # ========== 评估覆盖策略 ==========
    # 'skip'      - 跳过已有评估，只评估空白数据（默认，断点续跑）
    # 'overwrite' - 清空已有评估列，全部重新评估
    # 'new_batch' - 自动生成新 batch_id（时间戳），保留历史评估
    'overwrite_mode': 'skip',

    # ========== 回复文件路径（Stage 3/4/5 共用）==========
    # None 时使用默认 outputs/evaluation/replies/replies.xlsx
    'replies_excel': None,

    # ========== 待测模型配置（Stage 3 使用）==========
    'reply_model_configs': [
        {'model': 'gpt-4o', 'enable_thinking': False},
        {'model': 'qwen3-max', 'enable_thinking': True},   # enable_thinking=True 开启思维链
        {'model': 'claude-3-5-sonnet', 'enable_thinking': False},
    ],

    # ========== 并发配置 ==========
    'max_workers': 5,                # 并发线程数（建议根据 API 限速设置）
    'checkpoint_interval': 10,       # 每处理 N 条保存一次检查点
    'test_timeout': 300,             # 模型可用性测试超时

    # ========== 数据筛选配置（Stage 3/4 使用）==========
    'data_filters': {
        'qid_list': None,            # 指定 qid 列表，None 表示全部
        'model_list': None,          # 指定模型列表，None 表示全部
        'reference_type': None,      # 按参考答案类型筛选（'human'/'model'）
        'batch_size': None,          # 限制处理数量（调试用）
    },

    # ========== 分析阶段配置（analyze_results 使用）==========
    'analysis': {
        'replies_excel': None,       # 自定义 replies 路径，None 使用默认路径
        'human_excel': None,         # 人工标注表路径，None 跳过人机一致性分析
        'eval_batch_id': None,       # 使用哪个批次的评分列，None 自动选择最新批次
    },

    # ========== 报告阶段配置（generate_report 使用）==========
    'report': {
        'replies_excel': None,       # 自定义 replies 路径
        'human_excel': None,         # 人工标注表路径
        'eval_batch_id': None,       # 使用哪个批次的评分列
        'top_n_cases': 20,           # AI 深度分析的题目数量
        'max_workers': 3,            # 并发分析线程数
        'timeout': 120,              # 单次分析超时
        'temperature': 0.3,          # 分析温度
        'report_title': '多模型能力评测报告',  # 报告标题
    },
}
```

---

## 7. 全流程运行步骤（含操作示例）

### 7.1 模式A：全链路数据合成 + 评测

**适用场景**：从零开始，自动生成题目并完成评测。

**第一步：准备配置文件**

```
data/evaluation/
├── sysprompts.xlsx   # 至少配置 instruction_generation 和 evaluation
├── schema.xlsx       # 可选，控制生成类型分布
└── see.xlsx          # 可选，提升生成质量
```

**第二步：配置 main.py**

```python
CONFIG = {
    'stages': [
        'generate_instructions',   # 生成指令批次
        'extract_instructions',    # 提取每条 query
        'evaluate_instructions',   # 可选：质量过滤
        'promote_to_questions',    # 转为评测题目格式
        'generate_criteria',       # 生成评分标准
        'generate_references',     # 生成参考答案
        'generate_replies',        # 多模型生成回复
        'evaluate_replies',        # 裁判模型评分
        'analyze_results',         # 统计分析
        'generate_report',         # 可视化报告
    ],
    'sysprompt_excel': 'data/evaluation/sysprompts.xlsx',
    'output_base_dir': 'outputs/evaluation',
    'provider': 'openai',  # 或 dashscope 等，对应 config.py 中配置的 provider
    'model': 'claude_sonnet4_5',
    'timeout': 300,
    'generation': {
        'num_batches': 20,
        'items_per_batch': 3,
        'schema_excel': 'data/evaluation/schema.xlsx',   # 可选
        'see_excel': 'data/evaluation/see.xlsx',          # 可选
    },
    'batch_id': 'batch_1',
    'reply_model_configs': [
        {'model': 'gpt-4o'},
        {'model': 'qwen-max'},
    ],
    'max_workers': 5,
    'checkpoint_interval': 10,
}
```

**第三步：运行**

```bash
python -m evaluation.main
```

**控制台输出示例**：

```
============================================================
🚀 基于约束的完整评估系统 v9.0 (灵活化重构版)
============================================================

============================================================
🎯 执行流程  阶段数量: 10
============================================================
  1. 指令生成 (generate_instructions)
  2. 指令提取 (extract_instructions)
  3. 指令质量评估（可选） (evaluate_instructions)
  4. 数据提升为评测题目 (promote_to_questions)
  5. 评估标准生成 (generate_criteria)
  6. 参考答案生成 (generate_references)
  7. 回复生成 (generate_replies)
  8. 回复评估 (evaluate_replies)
  9. 评测结果综合分析 (analyze_results)
  10. 可视化报告生成 (generate_report)
============================================================
```

---

### 7.2 模式B：已有题目，直接评测

**适用场景**：已有 `questions.xlsx`，跳过数据合成阶段。

**第一步：放置题目文件**

将题目表放到：`outputs/evaluation/questions/questions.xlsx`

**第二步：配置 main.py**

```python
CONFIG = {
    'stages': [
        'generate_criteria',
        'generate_references',
        'generate_replies',
        'evaluate_replies',
        'analyze_results',
        'generate_report',
    ],
    'sysprompt_excel': 'data/evaluation/sysprompts.xlsx',
    'output_base_dir': 'outputs/evaluation',
    'provider': 'openai',  # 或 dashscope 等，对应 config.py 中配置的 provider
    'model': 'claude_sonnet4_5',
    'timeout': 300,
    'batch_id': 'batch_1',
    'reply_model_configs': [
        {'model': 'gpt-4o'},
        {'model': 'claude-3-5-sonnet'},
        {'model': 'qwen-max'},
    ],
    'max_workers': 5,
    'checkpoint_interval': 10,
    'report': {
        'report_title': '指令遵循多模型评测报告',
        'top_n_cases': 20,
    },
}
```

**第三步：运行**

```bash
python -m evaluation.main
```

---

### 7.3 模式C：仅数据合成，不评测

**适用场景**：只需要生成题目数据，后续手动处理或导入其他系统。

```python
CONFIG = {
    'stages': [
        'generate_instructions',
        'extract_instructions',
        'evaluate_instructions',   # 可选，过滤低质量指令
        'promote_to_questions',
    ],
    'sysprompt_excel': 'data/evaluation/sysprompts.xlsx',
    'output_base_dir': 'outputs/evaluation',
    'provider': 'openai',  # 或 dashscope 等，对应 config.py 中配置的 provider
    'model': 'claude_sonnet4_5',
    'timeout': 300,
    'generation': {
        'num_batches': 30,
        'items_per_batch': 5,
        'schema_excel': 'data/evaluation/schema.xlsx',
        'see_excel': 'data/evaluation/see.xlsx',
    },
    'max_workers': 5,
    'checkpoint_interval': 10,
}
```

运行后，`outputs/evaluation/questions/questions.xlsx` 即为最终合成的题目表，可直接导出使用。

---

### 7.4 多轮对话评测

**适用场景**：评测模型在多轮对话中的表现（情感陪伴、客服等场景）。

**数据流**：单轮指令 → Stage 0.7 扩展为多轮 → 评测

```python
CONFIG = {
    'stages': [
        'generate_instructions',
        'extract_instructions',
        'expand_multiturn',        # 关键：单轮→多轮扩展
        'promote_to_questions',    # 自动选择多轮数据（优先级高于单轮）
        'generate_criteria',
        'generate_references',
        'generate_replies',        # Stage 3 自动读取 history_context，构建多轮消息
        'evaluate_replies',        # Stage 4 自动使用 history_context 做缓存评测
        'analyze_results',
        'generate_report',
    ],
    'sysprompt_excel': 'data/evaluation/sysprompts.xlsx',
    'output_base_dir': 'outputs/evaluation',
    'provider': 'openai',  # 或 dashscope 等，对应 config.py 中配置的 provider
    'model': 'claude_sonnet4_5',
    'timeout': 300,
    'generation': {
        'num_batches': 20,
        'items_per_batch': 3,
        'schema_excel': 'data/evaluation/schema.xlsx',   # 建议配置情感陪伴类型体系
    },
    'multiturn': {
        'min_turns': 3,            # 最少 3 轮对话
        'max_turns': 8,            # 最多 8 轮对话
        'temperature': 0.8,
    },
    'batch_id': 'batch_1',
    'reply_model_configs': [
        {'model': 'gpt-4o'},
        {'model': 'qwen-max'},
    ],
    'max_workers': 3,              # 多轮评测建议降低并发
    'checkpoint_interval': 10,
}
```

**多轮数据字段说明**：

| 字段名 | 说明 |
|--------|------|
| `session_id` | 对话会话 ID（同一多轮对话共享） |
| `turn_id` | 当前轮次编号（从 1 开始） |
| `qid` | 当前轮次的唯一 ID（格式：`{session_id}_turn{turn_id}`） |
| `query` | 当前轮次的用户输入 |
| `history_context` | JSON 格式的历史对话记录（前 N-1 轮的 user/assistant 交替） |

**history_context 格式示例**：

```json
[
  {"user": "你好，我最近压力很大", "assistant": "我理解你的感受，能告诉我是什么让你感到压力吗？"},
  {"user": "工作上的事情太多了", "assistant": "工作压力确实很常见，你具体遇到了什么困难呢？"}
]
```

---

### 7.5 增量评估（新增模型或新批次）

**场景一：新增待测模型**

```python
CONFIG = {
    'stages': ['generate_replies', 'evaluate_replies'],
    # 只添加新模型，已有模型的回复会自动跳过
    'reply_model_configs': [
        {'model': 'gemini-2.0-flash'},   # 新增模型
    ],
    'batch_id': 'batch_1',               # 保持原 batch_id
    'overwrite_mode': 'skip',            # 跳过已有评估
    ...
}
```

**场景二：用新裁判模型重新评分**

```python
CONFIG = {
    'stages': ['evaluate_replies'],
    'provider': 'openai',
    'model': 'gpt-4o',                   # 换用新裁判模型
    'batch_id': 'batch_2',               # 新 batch_id，保留 batch_1 的历史评分
    'overwrite_mode': 'skip',
    ...
}
```

**场景三：强制重新评估某批次**

```python
CONFIG = {
    'stages': ['evaluate_replies'],
    'batch_id': 'batch_1',
    'overwrite_mode': 'overwrite',       # 清空 batch_1 列，全部重新评估
    ...
}
```

---

## 8. 各阶段详细说明

### Stage 0 — generate_instructions（指令生成）

- **输入**：sysprompts.xlsx + 可选的 schema.xlsx + see.xlsx
- **输出**：`stage0_generation/generated_responses.xlsx`（每行是一个批次的 JSON 数组）
- **断点续跑**：按批次 `id` 去重，已生成的批次自动跳过

**三种生成模式**：

| 模式 | 配置方式 | 适用场景 |
|------|----------|----------|
| 纯 Sysprompt 驱动 | 不配置 schema/see | 快速验证，对类型分布无要求 |
| Schema 驱动 | 仅配置 schema.xlsx | 精确控制各 L3 子类型的生成数量 |
| Schema + 种子驱动 | 同时配置 schema.xlsx 和 see.xlsx | 有高质量示例库，追求风格一致性 |

---

### Stage 0.5 — extract_instructions（指令提取）

- **输入**：`stage0_generation/generated_responses.xlsx`
- **输出**：`stage0.5_extraction/extracted_instructions.xlsx`
- **作用**：将每个批次的 JSON 数组解析为独立行，每行一条 query，分配唯一 `qid`

---

### Stage 1 — evaluate_instructions（指令质量评估，可选）

- **输入**：`stage0.5_extraction/extracted_instructions.xlsx`
- **输出**：`stage1_quality/evaluated_instructions.xlsx`（含 `status` 列）
- **作用**：裁判模型评估每条指令的质量，`status=ok` 的才会进入后续流程
- **断点续跑**：按 `qid` 去重，已评估的自动跳过

---

### Stage 0.7 — expand_multiturn（多轮扩展，可选）

- **输入**：`stage0.5_extraction/extracted_instructions.xlsx`
- **输出**：`stage0.7_multiturn/multiturn_instructions.xlsx`
- **作用**：将单轮指令扩展为多轮对话，生成 `session_id`、`turn_id`、`history_context` 字段

---

### promote_to_questions（数据提升）

- **输入**：自动选择最优数据源（优先级：用户指定 > stage1_quality > stage0.7_multiturn > stage0.5_extraction）
- **输出**：`questions/questions.xlsx`
- **作用**：将合成数据转为标准评测题目格式，过滤 `status != ok` 的行

---

### Stage 1.5 — generate_criteria（评分标准生成）

- **输入**：`questions/questions.xlsx`
- **输出**：`questions/questions_with_criteria.xlsx`
- **三种模式**（根据输入字段自动切换）：
  - **模式A（纯模型）**：无 `human_rubrics` 和 `reference`，模型自主设计评分标准
  - **模式B（人工初版）**：有 `human_rubrics`，模型在人工标准基础上优化
  - **模式C（专家示范）**：有 `reference` 或 `reply_evaluation`，结合专家示范生成标准

---

### Stage 2 — generate_references（参考答案生成）

- **输入**：`questions/questions_with_criteria.xlsx`
- **输出**：`questions/questions_complete.xlsx`
- **逻辑**：
  - 已有 `reference` 字段 → 直接保留（`reference_type=human`）
  - 无 `reference` → 模型生成（`reference_type=model`），有 `reply_evaluation` 时参考专家说明

---

### Stage 3 — generate_replies（回复生成）

- **输入**：`questions/questions_complete.xlsx`
- **输出**：`replies/replies.xlsx`
- **特性**：
  - 多模型并发生成，按 `(qid, model)` 去重断点续跑
  - 支持 `enable_thinking=True` 开启思维链
  - 自动读取 `history_context` 字段，多轮对话时构建完整消息历史
  - 自动检测权限错误，将不可用模型加入黑名单

---

### Stage 4 — evaluate_replies（回复评估）

- **输入**：`questions/questions_complete.xlsx` + `replies/replies.xlsx`
- **输出**：在 `replies.xlsx` 中新增 `eval_{batch_id}` 和 `eval_{batch_id}_raw` 列
- **特性**：
  - 使用 Prompt Caching（题目+评分标准+参考答案进入缓存层，节省 token）
  - 多轮对话时，历史上下文也进入缓存层
  - `overwrite_mode` 控制覆盖策略

---

### Stage 5a — analyze_results（统计分析）

- **输入**：`questions/questions_complete.xlsx` + `replies/replies.xlsx` + 可选 `human.xlsx`
- **输出**：`reports/analysis_report.xlsx`（多 Sheet）

---

### Stage 5b — generate_report（可视化报告）

- **输入**：同 analyze_results
- **输出**：`reports/evaluation_report_YYYYMMDD_HHMMSS.html` + `.md`

---

## 9. 分析报告与可视化报告说明

### analysis_report.xlsx 各 Sheet 说明

| 工作表 | 内容 | 使用场景 |
|--------|------|----------|
| **综合排名** | 整体/L1/L2/L3/难度/Source 排名 | 了解各模型综合表现 |
| **专家纠偏排名** | 专家打分纠偏后的排名 | 有专家打分时使用 |
| **每道题排名一致性** | 每道题人工 vs 模型排名相关性 | 评估模型评分可靠性 |
| **组内一致性** | 标注员之间的一致性指标 | 评估标注质量 |
| **模型专家一致性** | 模型打分与专家打分相关性 | 验证自动评分可信度 |
| **价值题目TOP20** | 最具区分度的 20 道题 | 筛选高质量评测题目 |
| **题目完整分析** | 每道题的信度/效度/区分度 | 题目质量审查 |
| **约束类型分析** | 各约束类型得分分布 | 分析模型能力短板 |
| **典型案例** | 典型高/低分案例 | 定性分析参考 |
| **指标定义说明** | 所有指标的定义和计算方法 | 理解指标含义 |

### HTML 报告功能

- **整体概况**：模型数、题目数、评测次数统计卡片 + 综合排名表
- **数据可视化**：模型平均分柱状图、L1 维度得分热力图、难度等级得分热力图
- **一致性分析摘要**：标注员组内一致性 + 模型排名一致性
- **价值题目深度分析**：TOP20 价值题目，每道题含可折叠详情卡片（题目内容、各模型得分对比、专家意见、AI 综合评估、各模型完整回复 Tab 切换）

---

## 10. 常见问题与注意事项

### ⚠️ 重要注意事项

**1. qid 必须是字符串类型**

建议使用 `Q001`、`Q_001` 等带前缀的格式，避免纯数字导致的前导零丢失问题。

**2. batch_id 要保持一致**

`evaluate_replies` 时设置的 `batch_id` 必须与 `analyze_results` 和 `generate_report` 中的 `eval_batch_id` 一致，否则系统找不到对应的评分列。

**3. 断点续跑机制**

- Stage 3（回复生成）：已有 `(qid, model)` 组合的行自动跳过
- Stage 4（评估打分）：`eval_{batch_id}` 列已有值的行自动跳过
- 如需重新评估，修改 `batch_id` 为新值，或设置 `overwrite_mode='overwrite'`

**4. 专家打分的时机**

专家打分应在 Stage 4 完成后、运行 `analyze_results` 之前，手动填入 `replies.xlsx` 的 `专家打分` 和 `专家理由` 列。

**5. 并发数设置**

- `max_workers` 建议根据 API 限速设置，通常 3-5 即可
- 多轮对话评测建议降低到 2-3，避免上下文混乱
- Stage 5 的 `report.max_workers` 建议设为 3

**6. promote_to_questions 数据源优先级**

当多个中间文件同时存在时，系统按以下优先级选择：
1. `promote_source_excel`（用户显式指定）
2. `stage1_quality/evaluated_instructions.xlsx`（质量过滤后的单轮数据）
3. `stage0.7_multiturn/multiturn_instructions.xlsx`（多轮扩展数据）
4. `stage0.5_extraction/extracted_instructions.xlsx`（原始提取数据）

如果同时运行了 `evaluate_instructions` 和 `expand_multiturn`，系统会优先选择 stage1_quality（单轮）。若要使用多轮数据，请显式设置 `promote_source_excel`。

### ❓ 常见问题

**Q: 运行 analyze_results 报错"结果表中未找到评估列"**

A: replies.xlsx 中没有 `eval_*` 列。需要先运行 Stage 4 评估，或手动添加评分列（列名格式为 `eval_batch_1`）。

**Q: Stage 1.5 全部走了模式A，没有用到 human_rubrics？**

A: `questions.xlsx` 中 `human_rubrics` 列是否存在且有值。系统通过 `_is_valid()` 判断，空字符串、`nan`、`None` 均视为无效。

**Q: 多轮对话时模型回复没有历史上下文？**

A: 确认 `questions_complete.xlsx` 中有 `history_context` 列。该字段由 Stage 0.7 生成，经 Stage 1.5 和 Stage 2 透传到 `questions_complete.xlsx`，Stage 3 会自动读取并构建多轮消息。

**Q: 如何只分析部分模型？**

A: 在 `data_filters.model_list` 中指定模型列表，如 `['gpt-4o', 'claude-3-5-sonnet']`。

**Q: HTML 报告中图表不显示？**

A: 需要网络连接加载 Plotly.js CDN。离线环境下可将 Plotly.js 下载到本地并修改 `evaluation/analysis/report_writer_html.py` 中的 CDN 链接。

**Q: 如何添加新的评测维度（如 L4）？**

A: 在 `questions.xlsx` 中添加 `L4` 列，然后在 `evaluation/analysis/ranking.py` 的 `generate_all_rankings()` 中添加对应的维度分析逻辑。

**Q: 情感陪伴项目如何配置 schema.xlsx？**

A: 在 schema.xlsx 中定义情感陪伴相关的 L1/L2/L3 体系，例如：

| L1 | L2 | L3 | count | description |
|----|----|----|-------|-------------|
| 情感陪伴 | 情绪支持 | 压力疏导 | 5 | 用户表达工作/生活压力，需要共情和建议 |
| 情感陪伴 | 情绪支持 | 悲伤安慰 | 4 | 用户经历失去或挫折，需要温暖陪伴 |
| 情感陪伴 | 日常陪伴 | 闲聊互动 | 6 | 轻松日常对话，考察自然流畅度 |
| 情感陪伴 | 危机干预 | 负面情绪识别 | 3 | 识别并妥善处理用户的负面情绪信号 |

配合 `expand_multiturn` 将单轮扩展为多轮，更贴近真实情感陪伴场景。

---

*文档版本：v2.0 | 最后更新：2026-02*

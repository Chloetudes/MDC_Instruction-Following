# 复杂指令遵循评测系统 — 全流程运行效果演示

> 本文档通过模拟真实数据，逐阶段展示每个 Pipeline Stage 的输入 Excel、控制台输出、以及输出 Excel 的字段结构，便于验证系统逻辑是否符合预期。

---

## 目录

1. [系统启动 & 配置](#1-系统启动--配置)
2. [Stage 0 — 指令生成（三种模式）](#2-stage-0--指令生成三种模式)
3. [Stage 0.5 — 指令提取](#3-stage-05--指令提取)
4. [Stage 1 — 指令质量评估（可选）](#4-stage-1--指令质量评估可选)
5. [Stage 0.7 — 多轮对话扩展（可选）](#5-stage-07--多轮对话扩展可选)
6. [promote_to_questions — 数据提升](#6-promote_to_questions--数据提升)
7. [Stage 1.5 — 评分标准生成（三种模式）](#7-stage-15--评分标准生成三种模式)
8. [Stage 2 — 参考答案生成](#8-stage-2--参考答案生成)
9. [Stage 3 — 模型回复生成](#9-stage-3--模型回复生成)
10. [Stage 4 — 回复评估](#10-stage-4--回复评估)
11. [Stage 5 — 可视化报告生成](#11-stage-5--可视化报告生成)
12. [analyze_results — 综合统计分析](#12-analyze_results--综合统计分析)
13. [数据流全链路图](#13-数据流全链路图)

---

## 1. 系统启动 & 配置

### 入口文件：`evaluation/main.py`

所有配置均在 `CONFIG` 字典中完成，运行命令：

```bash
python -m evaluation.main
```

**示例配置（模式B：已有题目，直接评测）**：

```python
CONFIG = {
    'stages': ['generate_criteria', 'generate_references', 'generate_replies', 'evaluate_replies'],
    'sysprompt_excel': "data/evaluation/sysprompts.xlsx",
    'output_base_dir': "outputs/evaluation",
    'provider': "openai",  # 与 config.py 中配置一致
    'model': "claude_sonnet4_5",
    'timeout': 300,
    'criteria_temperature': 0.3,
    'reference_temperature': 0.7,
    'reply_temperature': 0.6,
    'evaluation_temperature': 0.3,
    'batch_id': "batch_1",
    'reply_model_configs': [
        {"model": "qwen3-max-2026-01-23", "enable_thinking": True},
        {"model": "gpt-5.2-chat-latest", "enable_thinking": False},
    ],
    'max_workers': 5,
    'checkpoint_interval': 10,
}
```

### 控制台启动输出

```
============================================================
🚀 基于约束的完整评估系统 v9.0 (灵活化重构版)
============================================================

============================================================
🎯 执行流程  阶段数量: 4
============================================================
  1. 评估标准生成 (generate_criteria)
  2. 参考答案生成 (generate_references)
  3. 回复生成 (generate_replies)
  4. 回复评估 (evaluate_replies)
============================================================
```

---

## 2. Stage 0 — 指令生成（三种模式）

> **触发条件**：`stages` 中包含 `generate_instructions`
> **输出**：`stage0_generation/generated_responses.xlsx`

---

### 模式一：纯 Sysprompt 驱动（不配置 schema/see）

#### 配置

```python
CONFIG = {
    'stages': ['generate_instructions', 'extract_instructions', ...],
    'generation': {
        'num_batches': 15,
        'items_per_batch': 3,
        # schema_excel 和 see_excel 均为 None
    },
}
```

**sysprompts.xlsx** 中 `stage` = `instruction_generation` 的提示词示例：

```
你是一位专业的指令设计专家。请生成高质量的中文指令，要求：
1. 涵盖不同难度层次（简单/中等/复杂）
2. 包含明确的约束条件
3. 适合评测大语言模型的综合能力
4. 以 JSON 数组格式输出，每条指令包含 query 和 task_type 字段
```

#### 发送给模型的 Prompt

```
[System]
你是一位专业的指令设计专家。请生成高质量的中文指令...

[User]
请生成 3 条指令，以 JSON 数组格式输出。
```

#### 控制台输出

```
============================================================
🚀 模块0: 生成优质指令
============================================================

  模式：纯 Sysprompt 驱动
  需要生成: 15 个批次（共 15 个）

🔄 生成进度: 100%|████████████████| 15/15 [02:34<00:00, 10.3s/it]

✅ 指令生成完成: outputs/evaluation/stage0_generation/generated_responses.xlsx  总批次数: 15
```

#### 输出文件：`stage0_generation/generated_responses.xlsx`

| id | response |
|----|----------|
| BATCH0001 | `[{"query": "请用不超过200字描述量子纠缠的原理，要求使用类比手法，避免专业术语，面向初中生读者。", "task_type": "科普写作"}, {"query": "写一首关于秋天的七言绝句，要求押韵，且每句必须包含颜色词，整体意境需积极向上。", "task_type": "诗歌创作"}, {"query": "设计一个Python函数，接受整数列表，返回所有质数，要求时间复杂度O(n√n)以内，并附单元测试。", "task_type": "代码编写"}]` |
| BATCH0002 | `[{"query": "...", "task_type": "..."}, ...]` |

---

### 模式二：Schema 驱动（仅配置 schema.xlsx）

#### 配置

```python
CONFIG = {
    'stages': ['generate_instructions', 'extract_instructions', ...],
    'generation': {
        'items_per_batch': 3,
        'schema_excel': 'data/evaluation/schema.xlsx',
        # see_excel 为 None
    },
}
```

#### schema.xlsx Sheet1 示例

| L1 | L2 | L3 | count | difficulty | description | example |
|----|----|----|-------|------------|-------------|---------|
| 写作 | 创意写作 | 短篇故事续写 | 3 | C | 包含明确字数和风格约束 | 请续写以下故事片段... |
| 代码 | 算法编程 | 数据结构实现 | 4 | B | Python/Java，需附单元测试 | 实现一个线程安全的LRU缓存... |
| 推理 | 逻辑推理 | 多步因果推断 | 2 | A | 多步推理，答案唯一可验证 | |

#### 发送给模型的 Prompt（以"数据结构实现"批次为例）

```
[System]
你是一位专业的指令设计专家。请生成高质量的中文指令...

[User]
【本批次生成要求】
一级类型（L1）：代码
二级类型（L2）：算法编程
三级类型（L3）：数据结构实现
难度等级：B
特征描述：Python/Java，需附单元测试

【体系示范案例】
实现一个线程安全的LRU缓存...

请生成 3 条指令，以 JSON 数组格式输出。
```

#### 控制台输出

```
============================================================
🚀 模块0: 生成优质指令
============================================================

✅ 加载 schema.xlsx: 3 种子类型，共 9 个生成任务
  写作 > 创意写作 > 短篇故事续写: 3 批次
  代码 > 算法编程 > 数据结构实现: 4 批次
  推理 > 逻辑推理 > 多步因果推断: 2 批次

  模式：Schema 驱动（L1/L2/L3 层级体系，含计数器）
  需要生成: 9 个批次（共 9 个）

🔄 生成进度: 100%|████████████████| 9/9 [01:32<00:00, 10.2s/it]

✅ 指令生成完成: outputs/evaluation/stage0_generation/generated_responses.xlsx  总批次数: 9

📊 计数器已更新（schema.xlsx Sheet2）：
  短篇故事续写: 3/3
  数据结构实现: 4/4
  多步因果推断: 2/2
```

#### 输出文件：`stage0_generation/generated_responses.xlsx`

| id | response | L1 | L2 | L3 | difficulty |
|----|----------|----|----|----|------------|
| BATCH0001 | `[{"query": "请续写以下故事片段，字数不超过500字...", "task_type": "短篇故事续写"}, ...]` | 写作 | 创意写作 | 短篇故事续写 | C |
| BATCH0004 | `[{"query": "实现一个Python的双端队列（Deque），要求支持O(1)的头尾插入删除...", "task_type": "数据结构实现"}, ...]` | 代码 | 算法编程 | 数据结构实现 | B |

#### schema.xlsx Sheet2（计数器，系统自动更新）

| L1 | L2 | L3 | target_count | synthesized_count |
|----|----|----|--------------|-------------------|
| 写作 | 创意写作 | 短篇故事续写 | 3 | 3 |
| 代码 | 算法编程 | 数据结构实现 | 4 | 4 |
| 推理 | 逻辑推理 | 多步因果推断 | 2 | 2 |

---

### 模式三：Schema + 种子驱动（同时配置 schema.xlsx 和 see.xlsx）

#### 配置

```python
CONFIG = {
    'stages': ['generate_instructions', 'extract_instructions', ...],
    'generation': {
        'items_per_batch': 3,
        'schema_excel': 'data/evaluation/schema.xlsx',
        'see_excel':    'data/evaluation/see.xlsx',
    },
}
```

#### see.xlsx 示例

| query | L1 | L2 | L3 |
|-------|----|----|-----|
| 实现一个Python装饰器，用于统计函数执行时间，要求支持多次调用取平均值，并提供重置功能。 | 代码 | 算法编程 | 数据结构实现 |
| 设计一个支持泛型的栈结构，要求实现push/pop/peek/isEmpty方法，并附完整单元测试。 | 代码 | 算法编程 | 数据结构实现 |
| 请续写：夜深了，她站在窗边，看着远处的灯火，心里想起了那个夏天... 要求续写不少于300字，保持原文的忧郁基调。 | 写作 | 创意写作 | 短篇故事续写 |

#### 发送给模型的 Prompt（L3 精确匹配到 2 条种子）

```
[System]
你是一位专业的指令设计专家。请生成高质量的中文指令...

[User]
【本批次生成要求】
一级类型（L1）：代码
二级类型（L2）：算法编程
三级类型（L3）：数据结构实现
难度等级：B
特征描述：Python/Java，需附单元测试

【体系示范案例】
实现一个线程安全的LRU缓存...

【参考示例（仅供风格参考，请勿直接复制）】
示例1：实现一个Python装饰器，用于统计函数执行时间，要求支持多次调用取平均值，并提供重置功能。
示例2：设计一个支持泛型的栈结构，要求实现push/pop/peek/isEmpty方法，并附完整单元测试。

请生成 3 条指令，以 JSON 数组格式输出。
```

#### 控制台输出

```
✅ 加载 schema.xlsx: 3 种子类型，共 9 个生成任务
✅ 加载 see.xlsx: 3 条示例种子

  模式：Schema + 种子驱动（L1/L2/L3 层级体系，含计数器）
  需要生成: 9 个批次（共 9 个）

🔄 生成进度: 100%|████████████████| 9/9 [01:35<00:00, 10.6s/it]

✅ 指令生成完成: outputs/evaluation/stage0_generation/generated_responses.xlsx  总批次数: 9

📊 计数器已更新（schema.xlsx Sheet2）：
  短篇故事续写: 3/3
  数据结构实现: 4/4
  多步因果推断: 2/2
```

> **断点续跑**：若中途中断，重新运行时系统自动跳过已有批次（按 `id` 去重），从断点处继续生成。

---

## 3. Stage 0.5 — 指令提取

> **输入**：`stage0_generation/generated_responses.xlsx`
> **输出**：`stage0.5_extraction/extracted_instructions.xlsx`

### 控制台输出

```
============================================================
🚀 模块0.5: 结构化指令提取
============================================================

  读取原始响应: 9 条批次
  开始解析结构化指令...

🔄 提取进度: 100%|████████████████| 9/9 [00:01<00:00,  7.1it/s]

✅ 提取完成: outputs/evaluation/stage0.5_extraction/extracted_instructions.xlsx
  原始批次: 9  提取指令数: 27
```

### 输出文件：`stage0.5_extraction/extracted_instructions.xlsx`

| qid | original_id | item_num | query | task_type | L1 | L2 | L3 |
|-----|-------------|----------|-------|-----------|----|----|-----|
| Q001 | BATCH0001 | 1 | 请用不超过200字描述量子纠缠的原理，要求使用类比手法，避免专业术语，面向初中生读者。 | 科普写作 | | | |
| Q002 | BATCH0001 | 2 | 写一首关于秋天的七言绝句，要求押韵，且每句必须包含颜色词，整体意境需积极向上。 | 诗歌创作 | | | |
| Q003 | BATCH0001 | 3 | 设计一个Python函数，接受整数列表，返回所有质数，要求时间复杂度O(n√n)以内，并附单元测试。 | 代码编写 | | | |
| Q004 | BATCH0004 | 1 | 实现一个Python的双端队列（Deque），要求支持O(1)的头尾插入删除... | 数据结构实现 | 代码 | 算法编程 | 数据结构实现 |

---

## 4. Stage 1 — 指令质量评估（可选）

> **输入**：`stage0.5_extraction/extracted_instructions.xlsx`（必需列：`qid`, `query`）
> **输出**：`stage1_quality/evaluated_instructions.xlsx`

### 控制台输出

```
============================================================
🚀 模块1: 指令质量评估与约束提取
============================================================

✅ 客户端初始化成功

  数据行数: 27

💾 发现已有结果: 0 条
📝 待处理任务: 27 条

🔄 评估进度:  44%|████████▌         | 12/27 [01:00<01:15,  5.0s/it]
💾 检查点: 已保存 12 条
🔄 评估进度: 100%|████████████████| 27/27 [02:15<00:00,  5.0s/it]

✅ 评估结果已保存: outputs/evaluation/stage1_quality/evaluated_instructions.xlsx  数量: 27
```

### 输出文件：`stage1_quality/evaluated_instructions.xlsx`

| qid | query | raw_response | status | timestamp |
|-----|-------|-------------|--------|-----------|
| Q001 | 请用不超过200字描述量子纠缠... | **质量评分**: 8.5/10\n**约束列表**:\n- 字数约束: 不超过200字\n- 手法约束: 使用类比手法\n- 词汇约束: 避免专业术语\n- 受众约束: 面向初中生\n\n**综合评价**: 指令清晰，约束明确，难度适中。 | ok | 2026-02-21 10:08:01 |
| Q002 | 写一首关于秋天的七言绝句... | **质量评分**: 9.0/10\n**约束列表**:\n- 格式约束: 七言绝句\n- 押韵约束: 要求押韵\n- 内容约束: 每句含颜色词\n- 情感约束: 意境积极向上\n\n**综合评价**: 约束丰富且可验证，是优质的诗歌创作评测题。 | ok | 2026-02-21 10:08:04 |

> **过滤逻辑**：`promote_to_questions` 阶段会自动过滤 `status != ok` 的行，只有高质量指令才进入评测流程。

---

## 5. Stage 0.7 — 多轮对话扩展（可选）

> **输入**：`stage0.5_extraction/extracted_instructions.xlsx`
> **输出**：`stage0.7_multiturn/multiturn_instructions.xlsx`
> **适用场景**：情感陪伴、客服等需要多轮对话评测的场景

### 配置

```python
CONFIG = {
    'stages': [
        'generate_instructions',
        'extract_instructions',
        'expand_multiturn',        # 开启多轮扩展
        'promote_to_questions',    # 自动选择多轮数据（优先级高于单轮）
        ...
    ],
    'multiturn': {
        'min_turns': 3,
        'max_turns': 8,
        'temperature': 0.8,
    },
}
```

### 控制台输出

```
============================================================
🚀 Stage 0.7: 多轮对话扩展
============================================================

✅ 客户端初始化成功

  输入指令数: 27
  目标轮次范围: 3-8 轮

💾 发现已有结果: 0 条
📝 待处理任务: 27 条

🔄 扩展进度: 100%|████████████████| 27/27 [05:24<00:00, 12.0s/it]

✅ 多轮扩展完成: outputs/evaluation/stage0.7_multiturn/multiturn_instructions.xlsx
  原始指令: 27  扩展后总轮次: 135  平均轮次: 5.0
```

### 输出文件：`stage0.7_multiturn/multiturn_instructions.xlsx`

| session_id | turn_id | qid | query | history_context | task_type | L1 | L2 | L3 |
|------------|---------|-----|-------|-----------------|-----------|----|----|-----|
| S001 | 1 | S001_turn1 | 你好，我最近压力很大，不知道该怎么办。 | `[]` | 情感陪伴 | | | |
| S001 | 2 | S001_turn2 | 主要是工作上的事情，感觉做什么都不对。 | `[{"user": "你好，我最近压力很大...", "assistant": "我理解你的感受，能告诉我是什么让你感到压力吗？"}]` | 情感陪伴 | | | |
| S001 | 3 | S001_turn3 | 我的上司总是否定我的方案，我感觉很沮丧。 | `[{"user": "你好，我最近压力很大...", "assistant": "..."}, {"user": "主要是工作上的事情...", "assistant": "工作压力确实很常见，你具体遇到了什么困难呢？"}]` | 情感陪伴 | | | |

> **history_context 格式**：JSON 数组，每个元素包含 `user`（用户输入）和 `assistant`（模型回复）字段，代表前 N-1 轮的完整对话历史。

---

## 6. promote_to_questions — 数据提升

> **作用**：将合成数据转为标准评测题目格式，自动选择最优数据源
> **输出**：`questions/questions.xlsx`

### 数据源优先级（自动选择）

```
用户显式指定（promote_source_excel）
    ↓ 不存在时
stage1_quality/evaluated_instructions.xlsx（质量过滤后的单轮数据）
    ↓ 不存在时
stage0.7_multiturn/multiturn_instructions.xlsx（多轮扩展数据）
    ↓ 不存在时
stage0.5_extraction/extracted_instructions.xlsx（原始提取数据）
```

### 控制台输出

```
============================================================
🚀 执行阶段: 数据提升为评测题目
============================================================

  📖 数据来源: stage0.7_multiturn（多轮）
  📌 按 status=ok 过滤: 135 → 135 条
  ✅ 题目已写入: outputs/evaluation/questions/questions.xlsx  共 135 条
```

> **注意**：若要强制使用多轮数据（而非 stage1_quality 的单轮数据），请在 CONFIG 中设置：
> ```python
> 'promote_source_excel': 'outputs/evaluation/stage0.7_multiturn/multiturn_instructions.xlsx'
> ```

---

## 7. Stage 1.5 — 评分标准生成（三种模式）

> **输入**：`questions/questions.xlsx`（必需列：`qid`, `query`；可选列：`human_rubrics`, `reference`, `reply_evaluation`）
> **输出**：`questions/questions_with_criteria.xlsx`

### 输入文件示例：`questions/questions.xlsx`

| qid | query | human_rubrics | reference | reply_evaluation |
|-----|-------|---------------|-----------|-----------------|
| Q001 | 请用不超过200字描述量子纠缠的原理，要求使用类比手法，避免专业术语，面向初中生读者。 | （空） | （空） | （空） |
| Q002 | 写一首关于秋天的七言绝句，要求押韵，且每句必须包含颜色词，整体意境需积极向上。 | 1.格式正确（4分）2.押韵（3分）3.每句含颜色词（2分）4.意境积极（1分） | （空） | （空） |
| Q003 | 设计一个Python函数，接受整数列表，返回所有质数，要求时间复杂度O(n√n)以内，并附上单元测试。 | （空） | `def find_primes(nums):\n    ...` | 该示范回复正确实现了质数判断，时间复杂度符合要求。扣分点：未处理空列表输入，缺少类型注解。 |

### 控制台输出

```
============================================================
🚀 模块1.5: 批量生成评估标准
============================================================

✅ 客户端初始化成功

  数据行数: 3
  检测到可选列: human_rubrics, reference, reply_evaluation
  检测到多轮字段: session_id, turn_id, history_context（将透传到输出）

💾 发现已有结果: 0 条
📝 待处理任务: 3 条

🔄 生成进度: 100%|████████████████| 3/3 [00:18<00:00,  6.1s/it]

✅ 评估标准已保存: outputs/evaluation/questions/questions_with_criteria.xlsx  数量: 3
  模式分布 — 纯模型: 1  人工初版: 1  专家示范: 1
```

---

### 模式A：纯模型生成（Q001 — 无任何可选参数）

**发送给模型的 User Prompt：**

```
请为以下指令设计详细的评分标准（rubrics）。

题目ID: Q001

【指令内容】
请用不超过200字描述量子纠缠的原理，要求使用类比手法，避免专业术语，面向初中生读者。
```

**模型返回的 `evaluation_criteria`：**

```
## Q001 评分标准（满分10分）

### 一、字数约束（2分）
- 2分：全文不超过200字
- 0分：超过200字

### 二、类比手法（3分）
- 3分：使用了清晰、贴切的类比（如用"心灵��应"、"双胞胎"等日常概念类比量子纠缠）
- 2分：有类比但不够贴切或清晰
- 1分：仅有隐喻，无明确类比
- 0分：未使用类比手法

### 三、专业术语控制（2分）
- 2分：全文无专业术语（如"波函数"、"叠加态"等）
- 1分：出现1-2个专业术语但有解释
- 0分：大量使用专业术语

### 四、受众适配性（2分）
- 2分：语言通俗易懂，初中生可理解
- 1分：部分内容偏难
- 0分：完全不适合初中生阅读

### 五、内容准确性（1分）
- 1分：量子纠缠的核心概念（两粒子状态关联）描述正确
- 0分：存在明显科学错误
```

---

### 模式B：基于人工初版优化（Q002 — 有 `human_rubrics`）

**发送给模型的 User Prompt：**

```
请基于人工初版评分标准，对以下指令的评分标准进行定向优化和完善。

题目ID: Q002

【指令内容】
写一首关于秋天的七言绝句，要求押韵，且每句必须包含颜色词，整体意境需积极向上。

【人工初版评分标准】
1.格式正确（4分）2.押韵（3分）3.每句含颜色词（2分）4.意境积极（1分）

请在保留人工标准核心意图的基础上，补充遗漏的约束条目、明确评分细则、完善分值分配。
```

**模型返回的 `evaluation_criteria`（在人工标准基础上细化）：**

```
## Q002 评分标准（满分10分）

### 一、格式规范（3分）
- 3分：严格符合七言绝句格式（4句，每句7字，共28字）
- 2分：句数正确但个别句字数有误（±1字）
- 1分：整体结构为绝句但多处字数不符
- 0分：不符合绝句格式

### 二、押韵（2分）
- 2分：第一、二、四句韵脚相同（符合绝句押韵规则）
- 1分：有押韵意识但韵脚不统一
- 0分：完全不押韵

### 三、颜色词覆盖（3分）
- 3分：四句均含颜色词（红、橙、黄、绿、蓝、紫、白、黑、金、银等）
- 2分：三句含颜色词
- 1分：一至两句含颜色词
- 0分：无颜色词

### 四、意境积极（1分）
- 1分：整体情感基调积极向上，无悲秋、伤感情绪
- 0分：意境消极或中性

### 五、文学质量（1分）
- 1分：意象生动，语言凝练，有诗意
- 0分：语言平淡，缺乏诗意
```

---

### 模式C：结合专家示范（Q003 — 有 `reference` + `reply_evaluation`）

**发送给模型的 User Prompt：**

```
请结合专家示范，为以下指令生成或优化评分标准（rubrics）。

题目ID: Q003

【指令内容】
设计一个Python函数，接受整数列表，返回所有质数，要求时间复杂度O(n√n)以内，并附上单元测试。

【专家示范回复】
def find_primes(nums):
    def is_prime(n):
        if n < 2: return False
        for i in range(2, int(n**0.5)+1):
            if n % i == 0: return False
        return True
    return [n for n in nums if is_prime(n)]

【专家对示范回复的评分说明】
该示范回复正确实现了质数判断，时间复杂度符合要求。扣分点：未处理空列表输入，缺少类型注解。

请参考专家示范回复和评分说明，提炼核心答题方向和评分要点，补充或优化评分标准，确保标准能有效区分高质量与低质量回复。
```

**模型返回的 `evaluation_criteria`（针对性补全了专家指出的扣分点）：**

```
## Q003 评分标准（满分10分）

### 一、功能正确性（4分）
- 4分：函数正确返回所有质数，包含边界情况（0、1、负数返回空/不包含）
- 3分：主要逻辑正确，但边界情况处理有误
- 2分：基本逻辑有误但思路正确
- 0分：函数无法运行或结果完全错误

### 二、时间复杂度（2分）
- 2分：单个数判断复杂度为O(√n)，整体O(n√n)以内
- 1分：有优化意识但未达到O(√n)（如用n/2作为上界）
- 0分：暴力O(n²)或更差

### 三、单元测试（2分）
- 2分：测试覆盖边界情况（空列表、含0/1/负数）和正常情况
- 1分：仅测试正常情况，缺少边界测试
- 0分：无单元测试

### 四、代码质量（1分）
- 1分：有类型注解且代码结构清晰
- 0分：无类型注解或代码可读性差

### 五、空列表处理（1分）
- 1分：显式处理空列表输入（返回空列表，不报错）
- 0分：未处理空列表（可能引发异常）
```

### 输出文件：`questions/questions_with_criteria.xlsx`

| qid | query | evaluation_criteria | human_rubrics | reference | reply_evaluation | session_id | turn_id | history_context | status | timestamp |
|-----|-------|---------------------|---------------|-----------|-----------------|------------|---------|-----------------|--------|-----------|
| Q001 | 请用不超过200字... | ## Q001 评分标准... | （空） | （空） | （空） | （空） | （空） | （空） | ok | 2026-02-21 10:15:01 |
| Q002 | 写一首关于秋天... | ## Q002 评分标准... | 1.格式正确... | （空） | （空） | （空） | （空） | （空） | ok | 2026-02-21 10:15:07 |

> **多轮字段透传**：`session_id`、`turn_id`、`history_context` 字段从 `questions.xlsx` 全程透传到 `questions_complete.xlsx`，Stage 3 和 Stage 4 会自动读取使用。

---

## 8. Stage 2 — 参考答案生成

> **输入**：`questions/questions_with_criteria.xlsx`（必需列：`qid`, `query`, `evaluation_criteria`；可选列：`reference`（已有则直接保留）, `reply_evaluation`）
> **输出**：`questions/questions_complete.xlsx`

### 控制台输出

```
============================================================
🚀 模块2: 批量生成参考答案
============================================================

✅ 客户端初始化成功

  数据行数: 3
  已有参考答案: 1 条
  专家评分说明: 1 条
  检测到多轮字段: session_id, turn_id, history_context（将透传到输出）

💾 发现已有结果: 0 条
📝 待处理任务: 3 条

🔄 处理进度: 100%|████████████████| 3/3 [00:22<00:00,  7.3s/it]

✅ 参考答案处理完成: outputs/evaluation/questions/questions_complete.xlsx
  总数量: 3  人工参考: 1  模型参考: 2  失败: 0
```

### Q001 — 无 `reply_evaluation`，模型自主生成

**发送给模型的 User Prompt：**

```
请根据以下指令和评分标准，生成高质量的参考答案。

题目ID: Q001

【指令内容】
请用不超过200字描述量子纠缠的原理，要求使用类比手法，避免专业术语，面向初中生读者。

【评分标准】
## Q001 评分标准（满分10分）
...（完整评分标准）...

请生成一个符合评分标准的高质量参考答案。
```

**模型生成的参考答案：**

```
想象一对双胞胎，从小就心灵相通。无论他们相距多远，一个人开心，另一个也会莫名感到快乐；一个人难过，另一个也会心情低落。

量子纠缠就像这对神奇的双胞胎。两个粒子（比如光子）在一起"出生"后，就建立了一种特殊的联系。即使把它们分开到宇宙的两端，只要你测量其中一个的状态，另一个的状态会瞬间确定——就好像它们之间有一条看不见的"心灵感应线"。

这种联系不需要任何信号传递，比光速还快，是大自然最神奇的现象之一。（共148字）
```

### Q003 — 有 `reply_evaluation`，参考专家评分说明

**发送给模型的 User Prompt（关键差异部分）：**

```
...（题目和评分标准）...

【专家评分说明】
该示范回复正确实现了质数判断，时间复杂度符合要求。扣分点：未处理空列表输入，缺少类型注解。

请参考专家评分说明中提炼的核心答题方向和评分要点，确保参考答案充分覆盖高分要素。
```

**模型生成的参考答案（针对性补全了专家指出的扣分点）：**

```python
def find_primes(nums: list[int]) -> list[int]:
    """返回整数列表中所有质数。"""
    if not nums:
        return []

    def is_prime(n: int) -> bool:
        if n < 2:
            return False
        for i in range(2, int(n ** 0.5) + 1):
            if n % i == 0:
                return False
        return True

    return [n for n in nums if is_prime(n)]


import unittest

class TestFindPrimes(unittest.TestCase):
    def test_empty_list(self):
        self.assertEqual(find_primes([]), [])

    def test_no_primes(self):
        self.assertEqual(find_primes([0, 1, -5, 4, 6]), [])

    def test_all_primes(self):
        self.assertEqual(find_primes([2, 3, 5, 7]), [2, 3, 5, 7])

    def test_mixed(self):
        self.assertEqual(find_primes([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]), [2, 3, 5, 7])
```

### 输出文件：`questions/questions_complete.xlsx`

| qid | query | evaluation_criteria | reference | reference_type | reply_evaluation | session_id | turn_id | history_context | status | timestamp |
|-----|-------|---------------------|-----------|----------------|-----------------|------------|---------|-----------------|--------|-----------|
| Q001 | 请用不超过200字... | ## Q001 评分标准... | 想象一对双胞胎... | model | （空） | （空） | （空） | （空） | ok | 2026-02-21 10:22:01 |
| Q002 | 写一首关于秋天... | ## Q002 评分标准... | 金风送爽叶红飞... | model | （空） | （空） | （空） | （空） | ok | 2026-02-21 10:22:08 |
| Q003 | 设计一个Python函数... | ## Q003 评分标准... | `def find_primes...` | human | 该示范回复正确实现... | （空） | （空） | （空） | ok | 2026-02-21 10:22:15 |

---

## 9. Stage 3 — 模型回复生成

> **输入**：`questions/questions_complete.xlsx`（必需列：`qid`, `query`；可选列：`history_context`）
> **输出**：`replies/replies.xlsx`

### 控制台输出

```
============================================================
🚀 模块3: 批量生成回复
============================================================

  题目数量: 3  模型数量: 2  多轮对话: 否
  总任务数: 6

  ✅ 客户端初始化成功 (协议: openai)

💾 发现已有结果: 0 条，将跳过

📝 待处理任务: 6 条

🔄 生成进度: 100%|████████████████| 6/6 [01:45<00:00, 17.5s/it]

✅ 保存成功: outputs/evaluation/replies/replies.xlsx

============================================================
✅ 回复生成完成!
============================================================
  总结果数: 6  新增: 6
  成功: 6  失败: 0  跳过: 0
  开启 thinking: 3 条  平均推理长度: 1247 字符
============================================================
```

### 多轮对话时的 Prompt 构建

当 `questions_complete.xlsx` 中存在 `history_context` 字段时，Stage 3 自动构建多轮消息格式：

**history_context 内容（JSON）：**
```json
[
  {"user": "你好，我最近压力很大，不知道该怎么办。", "assistant": "我理解你的感受，能告诉我是什么让你感到压力吗？"},
  {"user": "主要是工作上的事情，感觉做什么都不对。", "assistant": "工作压力确实很常见，你具体遇到了什么困难呢？"}
]
```

**构建后发送给模型的 messages 格式：**
```json
[
  {"role": "user", "content": "你好，我最近压力很大，不知道该怎么办。"},
  {"role": "assistant", "content": "我理解你的感受，能告诉我是什么让你感到压力吗？"},
  {"role": "user", "content": "主要是工作上的事情，感觉做什么都不对。"},
  {"role": "assistant", "content": "工作压力确实很常见，你具体遇到了什么困难呢？"},
  {"role": "user", "content": "我的上司总是否定我的方案，我感觉很沮丧。"}
]
```

### 输出文件：`replies/replies.xlsx`

| qid | model | reply | reasoning | reply_len | reasoning_len | finish_reason | enable_thinking | status | timestamp |
|-----|-------|-------|-----------|-----------|---------------|---------------|-----------------|--------|-----------|
| Q001 | qwen3-max-2026-01-23 | 想象你有一双神奇的手套，左手和右手永远是一对... | 用户要求用类比手法，面向初中生，我需要找一个日常生活中的类比... | 186 | 312 | stop | True | ok | 2026-02-21 10:30:01 |
| Q001 | gpt-5.2-chat-latest | 量子纠缠就像两个被施了魔法的骰子... | （空） | 172 | 0 | stop | False | ok | 2026-02-21 10:30:08 |
| Q002 | qwen3-max-2026-01-23 | 金叶飘零映碧空，红枫似火照山峰，白云悠悠秋意浓，绿水长流万里通。 | 需要写七言绝句，四句各7字，押韵（空、峰、浓、通押ong韵），每句含颜色词... | 28 | 287 | stop | True | ok | 2026-02-21 10:30:15 |

---

## 10. Stage 4 — 回复评估

> **输入**：`questions/questions_complete.xlsx` + `replies/replies.xlsx`
> **输出**：在 `replies.xlsx` 中新增 `eval_{batch_id}` 和 `eval_{batch_id}_raw` 列

### 控制台输出

```
============================================================
🚀 模块4: 批量评估回复（带缓存）
============================================================

✅ 客户端初始化成功

  题目数量: 3  回复数量: 6
  批次ID: batch_1
  覆盖模式: skip（跳过已有评估）
  待评估任务: 6 条

🔄 评估进度:  50%|████████          | 3/6 [00:45<00:45, 15.0s/it]
💾 检查点: 已保存 3 条
🔄 评估进度: 100%|████████████████| 6/6 [01:30<00:00, 15.0s/it]

✅ 评估完成: outputs/evaluation/replies/replies.xlsx
  总评估数: 6  成功: 6  失败: 0
```

### 评估 Prompt 结构（发送给裁判模型）

```
[SYSTEM]
你是一位严格、公正的评测专家。请根据评分标准对模型回复进行评分。

[USER - 缓存部分（Prompt Caching，多个回复共享此部分）]
题目ID: Q001

【指令内容】
请用不超过200字描述量子纠缠的原理，要求使用类比手法，避免专业术语，面向初中生读者。

【评分标准】
## Q001 评分标准（满分10分）
...（完整评分标准）...

【参考答案】
想象一对双胞胎，从小就心灵相通...

[USER - 动态部分（每个回复独立）]
【待评估回复】（模型：qwen3-max-2026-01-23）
想象你有一双神奇的手套，左手和右手永远是一对...

请按照评分标准逐项打分，并给出总分和评价。
```

### 裁判模型返回的评估结果

```
## 评分结果

### 一、字数约束（2/2分）
回复共186字，符合不超过200字的要求。✅

### 二、类比手法（3/3分）
使用了"神奇手套"的类比，形象生动，贴近初中生日常经验。✅

### 三、专业术语控制（2/2分）
全文无"波函数"、"叠加态"等专业术语。✅

### 四、受众适配性（2/2分）
语言通俗，逻辑清晰，初中生可理解。✅

### 五、内容准确性（0/1分）
"手套"类比侧重于关联性，但未明确说明量子纠缠的"测量即确定"特性，存在轻微概念偏差。❌

**总分：9/10**

**综合评价**：回复质量优秀，类比创意新颖，字数控制精准，仅在核心概念的精确性上略有不足。
```

### 输出文件：`replies/replies.xlsx`（新增评估列）

| qid | model | reply | eval_batch_1 | eval_batch_1_raw | status |
|-----|-------|-------|-------------|-----------------|--------|
| Q001 | qwen3-max-2026-01-23 | 想象你有一双神奇的手套... | 9.0 | ## 评分结果\n\n### 一、字数约束（2/2分）... | ok |
| Q001 | gpt-5.2-chat-latest | 量子纠缠就像两个被施了魔法的骰子... | 8.5 | ## 评分结果\n\n### 一、字数约束（2/2分）... | ok |
| Q002 | qwen3-max-2026-01-23 | 金叶飘零映碧空... | 9.5 | ## 评分结果\n\n### 一、格式规范（3/3分）... | ok |
| Q003 | qwen3-max-2026-01-23 | `def find_primes...` | 9.0 | ## 评分结果\n\n### 一、功能正确性（4/4分）... | ok |

---

## 11. Stage 5 — 可视化报告生成

> **输入**：`questions/questions_complete.xlsx` + `replies/replies.xlsx`
> **输出**：`reports/evaluation_report_20260221_103000.html` + `reports/evaluation_report_20260221_103000.md`

### 控制台输出

```
============================================================
🚀 Stage 5: 生成可视化评测报告
============================================================

✅ 客户端初始化成功

  题目数量: 3  回复数量: 6
  批次ID: batch_1
  Top-N 案例分析: 20

📊 加载数据...
  ✅ 数据加载完成

🔍 筛选高价值题目（Top-20）...
  ✅ 筛选完成: 3 道题目

🤖 逐题深度分析（调用裁判模型）...
🔄 分析进度: 100%|████████████████| 3/3 [00:45<00:00, 15.0s/it]

📝 生成 HTML 报告...
  ✅ HTML 报告已保存: outputs/evaluation/reports/evaluation_report_20260221_103000.html

📝 生成 Markdown 报告...
  ✅ Markdown 报告已保存: outputs/evaluation/reports/evaluation_report_20260221_103000.md

============================================================
✅ 报告生成完成！
============================================================
```

### HTML 报告结构（关键章节）

```
总览卡片
├── 模型数: 2
├── 题目数: 3
└── 评测批次: batch_1

综合排名表
├── 🥇 1. qwen3-max-2026-01-23  平均分: 9.17
└── 🥈 2. gpt-5.2-chat-latest   平均分: 8.50

数据可视化
├── 模型平均分柱状图（含误差棒）
├── L1 维度得分热力图
└── 难度等级得分热力图

高价值题目深度分析（可折叠卡片）
├── 案例 #1 — Q003（代码编写）
│   ├── 题目内容（Markdown 渲染）
│   ├── 各模型得分对比
│   ├── AI 综合评估
│   ├── 失分点分析
│   └── 各模型完整回复（Tab 切换）
├── 案例 #2 — Q001（科普写作）
└── 案例 #3 — Q002（诗歌创作）
```

### Markdown 报告结构

```markdown
# 多模型能力评测报告

**生成时间**: 2026-02-21 10:30:00
**评测题目数**: 3
**参与模型数**: 2
**评测批次**: batch_1

---

## 一、综合排名

| 排名 | 模型 | 平均分 | 题目数 |
|------|------|--------|--------|
| 🥇 1 | qwen3-max-2026-01-23 | 9.17 | 3 |
| 🥈 2 | gpt-5.2-chat-latest | 8.50 | 1 |

## 二、高价值题目深度分析

### 案例 #1 — Q003

**题目**: 设计一个Python函数，接受整数列表，返回所有质数...

**各模型得分**:
- qwen3-max-2026-01-23: 9.0/10
- gpt-5.2-chat-latest: 8.0/10

**深度分析**:
qwen3-max 在代码质量维度（类型注解、空列表处理）上明显优于 gpt-5.2，
体现了其在代码规范性方面的优势...
```

---

## 12. analyze_results — 综合统计分析

> **输入**：`questions/questions_complete.xlsx` + `replies/replies.xlsx` + （可选）`human_scores.xlsx`
> **输出**：`reports/analysis_report.xlsx`（多 Sheet）

### 控制台输出

```
============================================================
🚀 综合统计分析
============================================================

📊 加载数据...
  ✅ 题目: 3 条  回复: 6 条

📈 计算模型综合排名...
📈 计算L1维度排名（任务类型）...
📈 计算L2维度排名...
📈 计算显著性检验...
📈 计算题目分析指标...
📈 筛选高价值题目（Top-20）...

✅ 分析报告已保存: outputs/evaluation/reports/analysis_report.xlsx
  Sheet列表: 综合排名, L1维度排名, 题目分析, 高价值题目, 指标说明
```

### 输出文件：`reports/analysis_report.xlsx`（各 Sheet 示例）

**Sheet: 综合排名**

| 模型 | 平均分 | 中位数 | 标准差 | 最高分 | 最低分 | 题目数 |
|------|--------|--------|--------|--------|--------|--------|
| qwen3-max-2026-01-23 | 9.17 | 9.0 | 0.24 | 9.5 | 9.0 | 3 |
| gpt-5.2-chat-latest | 8.50 | 8.5 | 0.00 | 8.5 | 8.5 | 1 |

**Sheet: 题目分析**

| qid | 平均分 | 区分度 | 难度系数 | 信度(α) | 质量等级 |
|-----|--------|--------|----------|---------|---------|
| Q001 | 8.75 | 0.50 | 0.875 | 0.72 | 良好 |
| Q002 | 9.50 | 0.00 | 0.950 | N/A | 优秀 |
| Q003 | 8.50 | 1.00 | 0.850 | 0.85 | 优秀 |

**Sheet: 高价值题目**

| 排名 | qid | 综合价值分 | 区分度 | 难度 | 推荐原因 |
|------|-----|-----------|--------|------|---------|
| 1 | Q003 | 0.92 | 1.00 | 0.85 | 区分度高，能有效区分模型能力差异 |
| 2 | Q001 | 0.78 | 0.50 | 0.875 | 难度适中，区分度良好 |

---

## 13. 数据流全链路图

```
【数据合成链路（可选）】

sysprompts.xlsx + schema.xlsx + see.xlsx
        │
        ▼
Stage 0: generate_instructions
（generated_responses.xlsx — JSON 批次格式）
        │
        ▼
Stage 0.5: extract_instructions
（extracted_instructions.xlsx — qid, query, task_type, L1/L2/L3）
        │
        ├──────────────────────────────────────────────────────────┐
        ▼                                                          ▼
Stage 1: evaluate_instructions（可选）          Stage 0.7: expand_multiturn（可选）
（evaluated_instructions.xlsx — 含 status）    （multiturn_instructions.xlsx — 含 session_id/turn_id/history_context）
        │                                                          │
        └──────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                        promote_to_questions
                （自动选择最优数据源，过滤 status!=ok）
                                    │
                                    ▼

【评测链路（核心）】

questions.xlsx（qid, query, [L1/L2/L3], [human_rubrics], [reference], [history_context]）
        │
        ▼
Stage 1.5: generate_criteria
（questions_with_criteria.xlsx — + evaluation_criteria，透传多轮字段）
        │
        ▼
Stage 2: generate_references
（questions_complete.xlsx — + reference, reference_type，透传多轮字段）
        │
        ├──────────────────────────────────────────────────────────┐
        ▼                                                          ▼
Stage 3: generate_replies                              Stage 4: evaluate_replies
（多模型并发，自动读取 history_context 构建多轮消息）  （裁判模型评分，Prompt Caching 节省 token）
        │                                                          │
        └──────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                        replies.xlsx（含 eval_{batch_id} 列）
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
          analyze_results                    generate_report
          （analysis_report.xlsx）           （evaluation_report.html + .md）
```

---

## 附录：常见问题排查

### Q: Stage 1.5 全部走了模式A，没有用到 human_rubrics？

**检查**：`questions.xlsx` 中 `human_rubrics` 列是否存在且有值。系统通过 `_is_valid()` 判断，空字符串、`nan`、`None` 均视为无效。

### Q: Stage 2 生成的参考答案质量不高？

**检查**：`reply_evaluation` 列是否填写了专家对示范回复的评分说明。有此字段时，模型会参考专家指出的扣分点，生成更有针对性的高质量参考答案。

### Q: Stage 4 评估结果列找不到？

**检查**：`batch_id` 配置是否正确。评估结果存储在 `eval_{batch_id}` 列（如 `eval_batch_1`），分析阶段通过 `eval_batch_id` 参数指定读取哪一批次。

### Q: 多轮对话时模型回复没有历史上下文？

**检查**：`questions_complete.xlsx` 中是否有 `history_context` 列。该字段由 Stage 0.7 生成，经 Stage 1.5 和 Stage 2 透传，Stage 3 会自动读取并构建多轮消息格式。

### Q: 断点续跑如何工作？

每个 Stage 在处理前会检查输出文件是否已存在，并读取已完成的 `qid`（或 `qid+model` 组合），跳过已处理的任务。每隔 `checkpoint_interval`（默认10条）自动保存一次。

### Q: promote_to_questions 选错了数据源？

当 `stage1_quality` 和 `stage0.7_multiturn` 同时存在时，系统优先选择 `stage1_quality`（单轮）。若要强制使用多轮数据，请在 CONFIG 中显式设置：

```python
'promote_source_excel': 'outputs/evaluation/stage0.7_multiturn/multiturn_instructions.xlsx'
```

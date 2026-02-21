# Stage 1.5 criteria 生成改造计划

## 现状分析

### Stage 1（指令质量评估）

* 当前：`evaluate(query)` 只接收 query，逻辑正确，无需改动

### Stage 1.5（评分标准生成）—— 需要重点改造

当前 `CriteriaGenerator.generate(qid, query)` 只接收 query，prompt 写死为：

```plaintext
"请为以下指令生成详细的评分标准。\n\n题目ID: {qid}\n\n指令内容:\n{query}"
```

**缺失的可选参数**：

* `human_rubrics`：人工初版标准（Excel 列名：`human_rubrics`）

* `reference`：专家示范回复（Excel 列名：`reference`）

* `reply_evaluation`：专家对示范回复的评分说明（Excel 列名：`reply_evaluation`）

### Stage 2（参考答案生成）

* 当前：`generate(qid, query, evaluation_criteria)` 已包含 criteria，逻辑正确

* 需要补充：支持读取 `reply_evaluation`（专家示范评分）作为额外上下文

### Stage 3（回复生成）

* 当前：只用 query，逻辑正确，无需改动

### Stage 4（回复评估）

* 当前：已包含 query + criteria + reference + reply，逻辑正确，无需改动

***

## 改造方案

### 核心改造：stage1_5_criteria.py

#### 1. `CriteriaGenerator.generate()` 新增可选参数

```python
def generate(
    self,
    qid: str,
    query: str,
    human_rubrics: str = '',
    reference: str = '',
    reply_evaluation: str = '',
) -> Tuple[str, str]:
```

#### 2. Prompt 构建逻辑（三种模式）

**模式A：纯模型生成（无任何可选参数）**

```plaintext
sysprompt: criteria_generation
user: 题目ID + query
→ 模型自主设计 rubrics
```

**模式B：基于人工初版优化（有 human_rubrics）**

```plaintext
sysprompt: criteria_generation_with_human（新增 stage key）
user: 题目ID + query + 人工初版标准
→ 模型在人工标准基础上做定向优化
```

**模式C：结合专家示范（有 reference 或 reply_evaluation）**

```plaintext
sysprompt: criteria_generation_with_expert（新增 stage key）
user: 题目ID + query + [human_rubrics 如有] + 专家示范回复 + 专家评分说明
→ 借鉴专家示范补充优化 rubrics
```

优先级：C > B > A（有更多信息时用更丰富的 prompt）

#### 3. `batch_generate_criteria()` 改造

* 读取 Excel 时检测可选列：`human_rubrics`、`reference`、`reply_evaluation`

* 将可选字段传入 task dict

* 调用 `generator.generate()` 时传入可选参数

* 断点续跑逻辑不变

### 次要改造：stage2_reference.py

`ReferenceAnswerGenerator.generate()` 新增可选参数 `reply_evaluation`：

* 若有专家评分说明，在 prompt 中补充"专家对示范回复的评分要点"

* 帮助模型理解核心答题方向，生成更靠谱的参考答案

### Sysprompt 新增 stage key

| stage key                         | 用途               |
| --------------------------------- | ---------------- |
| `criteria_generation`             | 原有：纯模型生成 rubrics |
| `criteria_generation_with_human`  | 新增：基于人工初版优化      |
| `criteria_generation_with_expert` | 新增：结合专家示范优化      |

***

## Excel 输入字段设计

questions.xlsx 新增可选列：

| 列名                 | 类型  | 说明                     |
| ------------------ | --- | ---------------------- |
| `human_rubrics`    | 字符串 | 人工初版评分标准（可选）           |
| `reference`        | 字符串 | 专家示范回复（可选，Stage 2 也会用） |
| `reply_evaluation` | 字符串 | 专家对示范回复的评分说明（可选）       |

***

## 文件改动清单

1. `evaluation/stages/stage1_5_criteria.py` — 主要改造

2. `evaluation/stages/stage2_reference.py` — 补充 reply_evaluation 支持

3. `docs/USER_GUIDE.md` — 更新字段说明

# CIF 评测系统 — 使用指南

> 本文档面向评测系统的使用者，涵盖从环境准备、数据准备、配置设置到运行评测、查看报告的完整流程。

---

## 目录

1. [快速开始](#1-快速开始)
2. [目录与文件规划](#2-目录与文件规划)
3. [题目表设计（questions.xlsx）](#3-题目表设计questionsxlsx)
4. [回复表设计（replies.xlsx）](#4-回复表设计repliesxlsx)
5. [人工标注表设计（human.xlsx）](#5-人工标注表设计humanxlsx)
6. [Sysprompt 配置表（sysprompts.xlsx）](#6-sysprompt-配置表syspromptsxlsx)
7. [主配置文件（main.py CONFIG）](#7-主配置文件mainpy-config)
8. [全流程使用步骤](#8-全流程使用步骤)
9. [各阶段单独运行说明](#9-各阶段单独运行说明)
10. [分析报告说明](#10-分析报告说明)
11. [可视化报告说明](#11-可视化报告说明)
12. [常见问题与注意事项](#12-常见问题与注意事项)

---

## 1. 快速开始

### 环境要求

```bash
pip install pandas openpyxl scipy numpy tqdm
```

### 最简运行（已有题目和回复，只做分析）

```python
# evaluation/main.py
CONFIG = {
    'stages': ['analyze_results'],
    'sysprompt_excel': 'data/evaluation/sysprompts.xlsx',
    'output_base_dir': 'outputs/evaluation',
    'provider': 'your_provider',
    'model': 'your_judge_model',
    'timeout': 300,
    'analysis': {
        'replies_excel': 'path/to/your/replies.xlsx',
        'human_excel': None,
        'eval_batch_id': 'batch_1',
    },
}
```

```bash
python -m evaluation.main
```

---

## 2. 目录与文件规划

### 推荐目录结构

```
项目根目录/
├── evaluation/          # 代码目录（不需要修改）
├── data/
│   └── evaluation/
│       └── sysprompts.xlsx    # ← 你需要准备这个文件
├── outputs/
│   └── evaluation/            # 系统自动创建，所有输出在此
│       ├── questions/
│       │   ├── questions.xlsx              # 初始题目表（你提供）
│       │   ├── questions_with_criteria.xlsx # Stage 1.5 生成
│       │   └── questions_complete.xlsx      # Stage 2 生成
│       ├── replies/
│       │   └── replies.xlsx               # Stage 3/4 生成或你提供
│       └── reports/
│           ├── analysis_report.xlsx        # 统计分析报告
│           ├── evaluation_report_*.html    # 可视化 HTML 报告
│           └── evaluation_report_*.md     # Markdown 报告
└── evaluation/main.py   # ← 你需要修改这个文件的 CONFIG
```

### 文件路径说明

- **系统自动管理**的路径：`outputs/evaluation/` 下所有文件，由 `DirectoryManager` 统一管理
- **你需要手动放置**的文件：
  - `data/evaluation/sysprompts.xlsx`（Sysprompt 配置）
  - `outputs/evaluation/questions/questions.xlsx`（初始题目，如果跳过 Stage 0-1）
  - 外部 replies 文件（如果直接提供回复数据）

---

## 3. 题目表设计（questions.xlsx）

### 必填字段

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `qid` | 字符串 | 题目唯一 ID，如 `Q001`、`CIF_001` |
| `query` | 字符串 | 题目内容（指令文本） |

### 推荐字段（用于分维度分析）

| 字段名 | 类型 | 说明 | 示例值 |
|--------|------|------|--------|
| `L1` | 字符串 | 一级分类 | `写作`、`代码`、`推理` |
| `L2` | 字符串 | 二级分类 | `创意写作`、`Python编程` |
| `L3` | 字符串 | 三级分类 | `故事续写`、`算法题` |
| `source` | 字符串 | 数据来源 | `H`（人工）、`M`（模型）、`HM`（混合）、`公开数据集名` |
| `difficulty_level` | 字符串 | 难度等级 | `E`（最易）/ `D` / `C` / `B` / `A` / `S`（最难） |

### 系统生成字段（Stage 1.5 和 Stage 2 后自动添加）

| 字段名 | 说明 |
|--------|------|
| `evaluation_criteria` | 评分标准（约束条目列表） |
| `reference` | 参考答案 |
| `reference_type` | 参考答案类型（`model`/`human`） |

### 示例数据

```
qid       | query                              | L1   | L2     | difficulty_level
----------|------------------------------------|----- |--------|------------------
CIF_001   | 请写一篇500字的科技新闻报道...      | 写作 | 新闻写作 | C
CIF_002   | 用Python实现一个二叉树的层序遍历... | 代码 | 算法   | B
```

---

## 4. 回复表设计（replies.xlsx）

### 必填字段

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `qid` | 字符串 | 对应题目 ID |
| `model` | 字符串 | 模型名称，如 `gpt-4o`、`claude-3-5-sonnet` |
| `reply` | 字符串 | 模型回复内容 |

### 评分列（系统自动添加）

| 字段名 | 说明 |
|--------|------|
| `eval_{batch_id}` | 某批次的评分结果（数值） |
| `eval_{batch_id}_raw` | 该批次的原始评估文本 |

> **注意**：每次运行 Stage 4 会新增一对 `eval_*` 和 `eval_*_raw` 列，不会覆盖已有列。

### 专家打分字段（可选，人工填写）

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `专家打分` | 数值 | 专家对该 `(qid, model)` 的打分 |
| `专家理由` | 字符串 | 专家打分的理由说明 |

> **专家打分的作用**：用于生成「专家纠偏排名」，对难题（模型评分不可靠的题目）用专家分替换，得到更准确的模型排名。

### 示例数据

```
qid     | model          | reply          | eval_batch_1 | 专家打分 | 专家理由
--------|----------------|----------------|--------------|---------|--------
CIF_001 | gpt-4o         | 这是一篇...    | 85           |         |
CIF_001 | claude-3-5     | 科技新闻...    | 92           | 88      | 格式略有问题
CIF_002 | gpt-4o         | def level_...  | 78           |         |
```

---

## 5. 人工标注表设计（human.xlsx）

人工标注表是**可选的**，用于计算人机一致性和标注员组内一致性。

### 字段设计

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `qid` 或 `QID` | 字符串 | 题目 ID（系统自动将 QID 重命名为 qid） |
| `model` | 字符串 | 被标注的模型名称 |
| `ann1_score` | 数值 | 标注员1的打分 |
| `ann2_score` | 数值 | 标注员2的打分 |
| `ann1_name` | 字符串 | 标注员1姓名（可选） |
| `ann2_name` | 字符串 | 标注员2姓名（可选） |
| `ann1_raw_eval` | 字符串 | 标注员1的评估文本（可选） |
| `ann2_raw_eval` | 字符串 | 标注员2的评估文本（可选） |

> 也支持多维度打分格式：`ann1_score_m1`、`ann1_score_m2`、`ann1_score_m3`，系统会自动取均值。

---

## 6. 数据合成配置文件（schema.xlsx & see.xlsx）

这两个文件用于 **Stage 0（指令生成）** 阶段，控制模型生成什么类型的指令、以及提供示例种子。两者均为**可选**，不配置时系统退回纯 Sysprompt 驱动模式。

- **schema.xlsx**：最小体系化种子库，定义 L1/L2/L3 三级任务类型体系、特征描述和示范案例，同时通过第二个 Sheet 维护每个子类型的合成数量计数器，用于均衡控制数据分布
- **see.xlsx**：扩充种子库，在 schema 基础上为每个类型补充更多典型代表性数据，作为 few-shot 参考引导生成更优质的指令

在 `main.py` 的 `CONFIG` 中通过 `generation` 子配置指定路径：

```python
CONFIG = {
    'stages': ['generate_instructions', ...],
    ...
    'generation': {
        'schema_excel': 'data/evaluation/schema.xlsx',   # 可选
        'see_excel':    'data/evaluation/see.xlsx',      # 可选
    },
}
```

---

### 6.1 schema.xlsx — 层级任务体系表（含计数器）

**作用**：定义 L1/L2/L3 三级任务类型体系，精确控制每种子类型生成多少批次，替代 `num_instruction_batches` 的均匀分配方式。

#### Sheet1 — 任务体系定义

| 字段名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `L1` | 字符串 | ✅ | 一级任务类型（如：写作、代码、推理） |
| `L2` | 字符串 | ✅ | 二级任务类型（如：创意写作、算法编程） |
| `L3` | 字符串 | ✅ | 三级任务类型（最细粒度，注入 prompt 中） |
| `count` | 整数 | ✅ | 该 L3 子类型需要生成的批次数量 |
| `difficulty` | 字符串 | 可选 | 难度等级（如 `A`/`B`/`C`/`D`），注入 prompt 中 |
| `description` | 字符串 | 可选 | 特征描述，进一步约束生成方向 |
| `example` | 字符串 | 可选 | 体系示范案例，直接注入 prompt 作为参考 |

#### Sheet1 示例表格

| L1 | L2 | L3 | count | difficulty | description | example |
|----|----|----|-------|------------|-------------|---------|
| 写作 | 创意写作 | 短篇故事续写 | 5 | C | 包含明确字数和风格约束 | 请续写以下故事片段... |
| 代码 | 算法编程 | 数据结构实现 | 8 | B | Python/Java，需附单元测试 | 实现一个线程安全的LRU缓存... |
| 推理 | 逻辑推理 | 多步因果推断 | 4 | A | 多步推理，答案唯一可验证 | |
| 知识 | 事实问答 | 科学常识 | 3 | D | 事实性问题，有明确正确答案 | |

#### Sheet2 — 合成数量计数器（系统自动维护）

Sheet2 由系统在首次运行时自动初始化，无需手动创建。每次生成完成后，系统会将本次新增的合成数量写回 Sheet2，用于追踪各子类型的累计合成进度。

| 字段名 | 说明 |
|--------|------|
| `L1` | 一级类型 |
| `L2` | 二级类型 |
| `L3` | 三级类型（子类型标识） |
| `target_count` | 目标生成批次数（来自 Sheet1 的 count） |
| `synthesized_count` | 已累计合成的批次数（系统自动更新） |

#### 运行效果

配置上表后，系统会生成 **20 个批次**（5+8+4+3），每个批次的 User Prompt 中自动注入对应的层级约束：

```
【本批次生成要求】
一级类型（L1）：代码
二级类型（L2）：算法编程
三级类型（L3）：数据结构实现
难度等级：B
特征描述：Python/Java，需附单元测试

【体系示范案例】
实现一个线程安全的LRU缓存...

请生成指令。
```

运行结束后，控制台输出计数器更新情况：

```
📊 计数器已更新（schema.xlsx Sheet2）：
  数据结构实现: 8/8
  多步因果推断: 4/4
  ...
```

> **注意**：配置 `schema.xlsx` 后，`num_instruction_batches` 参数将被忽略，总批次数由 Sheet1 中所有 `count` 之和决定。

---

### 6.2 see.xlsx — 扩充种子表（Few-shot Seeds）

**作用**：在 schema 体系基础上，为每个类型补充更多典型代表性数据。系统在每次生成时按 L3 > L2 > L1 优先级匹配同类型种子，随机抽取最多 3 条作为 few-shot 参考，引导模型生成风格一致、质量更高的指令。

#### 字段说明

| 字段名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `query` | 字符串 | ✅ | 示例指令内容 |
| `L1` | 字符串 | 可选 | 一级类型（与 schema.xlsx 对应，用于优先匹配） |
| `L2` | 字符串 | 可选 | 二级类型 |
| `L3` | 字符串 | 可选 | 三级类型（匹配优先级最高） |
| `task_type` | 字符串 | 可选 | 兼容旧格式，与 L3 等效 |

#### 示例表格

| query | L1 | L2 | L3 |
|-------|----|----|-----|
| 请用不超过300字，以第一人称视角写一篇关于"第一次独自旅行"的短文，要求包含至少3个具体的感官描写。 | 写作 | 创意写作 | 短篇故事续写 |
| 实现一个Python装饰器，用于统计函数执行时间，要求支持多次调用取平均值，并提供重置功能。 | 代码 | 算法编程 | 数据结构实现 |
| 一个房间里有3盏灯，对应3个开关在房间外。你只能进入房间一次，如何判断哪个开关控制哪盏灯？ | 推理 | 逻辑推理 | 多步因果推断 |

#### 种子抽取逻辑

- **优先级**：L3 精确匹配 → L2 匹配 → L1 匹配 → 全库随机补充
- **数量**：每批次最多抽取 3 条，不足时从更宽泛的范围补充
- 种子仅作为**风格参考**，Prompt 中明确说明"请勿直接复制"

#### 生成的 User Prompt 示例（schema + see 同时配置）

```
【本批次生成要求】
一级类型（L1）：代码
二级类型（L2）：算法编程
三级类型（L3）：数据结构实现
难度等级：B
特征描述：Python/Java，需附单元测试

【参考示例（仅供风格参考，请勿直接复制）】
示例1：实现一个Python装饰器，用于统计函数执行时间，要求支持多次调用取平均值，并提供重置功能。

请生成指令。
```

---

### 6.3 三种生成模式对比

| 模式 | 配置方式 | 适用场景 |
|------|----------|----------|
| **纯 Sysprompt 驱动** | 不配置 schema/see | 快速验证，对类型分布无要求 |
| **Schema 驱动** | 仅配置 schema.xlsx | 需要精确控制各 L3 子类型的生成数量，含计数器追踪 |
| **Schema + 种子驱动** | 同时配置 schema.xlsx 和 see.xlsx | 有高质量示例库，追求风格一致性，按 L1/L2/L3 优先匹配 |

---

## 7. Sysprompt 配置表（sysprompts.xlsx）

### 表格格式

Excel 文件必须包含两列：

| 列名 | 说明 |
|------|------|
| `stage` | 阶段标识符（固定值，见下表） |
| `sysprompt` | 该阶段使用的系统提示词 |

### 支持的 stage 标识符

| stage 值 | 对应阶段 | 说明 |
|----------|----------|------|
| `instruction_generation` | Stage 0 | 指令生成的 Sysprompt |
| `instruction_quality` | Stage 1 | 指令质量评估的 Sysprompt |
| `criteria_generation` | Stage 1.5 | 评分标准生成的 Sysprompt |
| `reference_generation` | Stage 2 | 参考答案生成的 Sysprompt |
| `evaluation` | Stage 4 | 回复评估打分的 Sysprompt |
| `report_analysis` | Stage 5 | 价值题目 AI 分析的 Sysprompt |

### 示例表格内容

```
stage                  | sysprompt
-----------------------|--------------------------------------------------
instruction_generation | 你是一位专业的AI评测题目设计专家...
criteria_generation    | 你是一位评分标准设计专家，请为以下题目设计评分标准...
evaluation             | 你是一位严格的AI评测裁判，请按照以下评分标准对模型回复打分...
report_analysis        | 你是一位专业的AI模型评测分析师，请基于提供的题目信息...
```

### Sysprompt 设计建议

#### evaluation（评估打分）Sysprompt 要点

```
1. 明确评分范围（如 0-100 分）
2. 要求输出格式包含"总分: XX"或"总分：XX分"
3. 要求逐条评估每个约束条目
4. 说明参考答案的使用方式（参考而非标准答案）
5. 强调客观公正，不受模型品牌影响
```

#### report_analysis（报告分析）Sysprompt 要点

```
1. 要求输出包含【综合评估】和【失分点分析】两个固定章节
2. 综合评估控制在 100 字以内
3. 失分点分析按模型逐一说明
4. 如有专家意见，优先参考
```

---

## 7. 主配置文件（main.py CONFIG）

`evaluation/main.py` 中的 `CONFIG` 字典是系统的唯一配置入口。

### 完整配置说明

```python
CONFIG = {
    # ========== 执行阶段（按需开启） ==========
    'stages': [
        # 'test_models',           # 测试模型可用性（建议首次运行时开启）
        # 'generate_instructions', # Stage 0: 生成指令
        # 'extract_instructions',  # Stage 0.5: 提取指令
        # 'evaluate_instructions', # Stage 1: 指令质量评估
        # 'generate_criteria',     # Stage 1.5: 生成评分标准
        # 'generate_references',   # Stage 2: 生成参考答案
        # 'generate_replies',      # Stage 3: 生成模型回复
        # 'evaluate_replies',      # Stage 4: 评估打分
        'analyze_results',         # 统计分析（生成 Excel 报告）
        'generate_report',         # 可视化报告（生成 HTML + MD）
    ],

    # ========== 文件路径配置 ==========
    'sysprompt_excel': 'data/evaluation/sysprompts.xlsx',
    'output_base_dir': 'outputs/evaluation',

    # ========== 裁判模型配置 ==========
    # 用于 Stage 1/1.5/2/4/5 的评估和生成
    'provider': 'idealab',           # Provider 名称（对应 config.py 中的配置）
    'model': 'claude_sonnet4_5',     # 裁判模型名称
    'timeout': 300,                  # 单次请求超时（秒）

    # ========== 温度配置 ==========
    'instruction_temperature': 0.9,  # Stage 0 生成温度（高多样性）
    'criteria_temperature': 0.3,     # Stage 1.5 生成温度（低随机性）
    'reference_temperature': 0.7,    # Stage 2 生成温度
    'reply_temperature': 0.6,        # Stage 3 生成温度
    'evaluation_temperature': 0.3,   # Stage 4 评估温度（低随机性）

    # ========== 批次配置 ==========
    'num_instruction_batches': 15,   # Stage 0 生成批次数
    'batch_id': 'batch_1',           # Stage 4 评估批次 ID（用于区分多次评估）

    # ========== 待测模型配置（Stage 3 使用） ==========
    'reply_model_configs': [
        {'model': 'gpt-4o', 'provider': 'openai'},
        {'model': 'claude-3-5-sonnet', 'provider': 'anthropic'},
        {'model': 'qwen-max', 'enable_thinking': False},
    ],

    # ========== 并发配置 ==========
    'max_workers': 5,                # 并发线程数
    'checkpoint_interval': 10,       # 每处理 N 条保存一次检查点
    'test_timeout': 300,             # 模型可用性测试超时

    # ========== 数据筛选（Stage 4 使用） ==========
    'data_filters': {
        'qid_list': None,            # 指定 qid 列表，None 表示全部
        'model_list': None,          # 指定模型列表，None 表示全部
        'reference_type': None,      # 按参考答案类型筛选
        'batch_size': None,          # 限制处理数量（调试用）
    },

    # ========== 分析阶段配置（analyze_results 使用） ==========
    'analysis': {
        'replies_excel': None,       # 自定义 replies 路径，None 使用默认路径
        'human_excel': None,         # 人工标注表路径，None 跳过人机一致性分析
        'eval_batch_id': 'batch_1',  # 使用哪个批次的评分列
    },

    # ========== 报告阶段配置（generate_report 使用） ==========
    'report': {
        'replies_excel': None,       # 自定义 replies 路径
        'human_excel': None,         # 人工标注表路径
        'eval_batch_id': 'batch_1',  # 使用哪个批次的评分列
        'top_n_cases': 20,           # AI 深度分析的题目数量
        'max_workers': 3,            # 并发分析线程数
        'timeout': 120,              # 单次分析超时
        'temperature': 0.3,          # 分析温度
        'report_title': '多模型能力评测报告',  # 报告标题
    },
}
```

---

## 8. 全流程使用步骤

### 场景一：从零开始（含题目生成）

```
步骤 1: 准备 sysprompts.xlsx（配置 instruction_generation 等 Sysprompt）
步骤 2: 配置 CONFIG['stages'] = ['generate_instructions', 'extract_instructions', ...]
步骤 3: 运行 python -m evaluation.main
步骤 4: 检查 outputs/evaluation/questions/questions_complete.xlsx
步骤 5: 配置待测模型 reply_model_configs
步骤 6: 运行 Stage 3 + Stage 4 采集回复并评分
步骤 7: 运行 analyze_results + generate_report 生成报告
```

### 场景二：已有题目，直接评测（最常用）

```
步骤 1: 将题目表放到 outputs/evaluation/questions/questions.xlsx
步骤 2: 配置 sysprompts.xlsx（至少配置 criteria_generation 和 evaluation）
步骤 3: 配置 CONFIG['stages'] = ['generate_criteria', 'generate_references', 'generate_replies', 'evaluate_replies']
步骤 4: 配置 reply_model_configs（待测模型列表）
步骤 5: 运行 python -m evaluation.main
步骤 6: 运行 analyze_results + generate_report
```

### 场景三：已有回复数据，只做分析

```
步骤 1: 确保 replies.xlsx 包含 eval_* 评分列
步骤 2: 配置 CONFIG['analysis']['replies_excel'] = 'path/to/replies.xlsx'
步骤 3: 配置 CONFIG['stages'] = ['analyze_results', 'generate_report']
步骤 4: 运行 python -m evaluation.main
```

### 场景四：增量评估（新增模型或新批次）

```
步骤 1: 在 reply_model_configs 中添加新模型
步骤 2: 修改 batch_id 为新批次号（如 'batch_2'）
步骤 3: 配置 stages = ['generate_replies', 'evaluate_replies']
步骤 4: 运行，系统自动跳过已有回复/评分，只处理新增部分
```

---

## 9. 各阶段单独运行说明

### 只运行评分（Stage 4）

```python
CONFIG = {
    'stages': ['evaluate_replies'],
    'provider': 'your_provider',
    'model': 'your_judge_model',
    'batch_id': 'batch_2',          # 新批次 ID
    'evaluation_temperature': 0.3,
    'max_workers': 5,
    'checkpoint_interval': 10,
    'timeout': 300,
    'data_filters': {
        'model_list': ['gpt-4o'],   # 只评估特定模型
        'qid_list': None,
    },
    ...
}
```

### 只运行分析报告

```python
CONFIG = {
    'stages': ['analyze_results'],
    'analysis': {
        'replies_excel': 'outputs/evaluation/replies/cif_400_all_replies.xlsx',
        'human_excel': 'data/human_annotations.xlsx',  # 可选
        'eval_batch_id': 'batch_1',
    },
    ...
}
```

### 只生成可视化报告

```python
CONFIG = {
    'stages': ['generate_report'],
    'provider': 'your_provider',
    'model': 'your_judge_model',
    'report': {
        'replies_excel': 'outputs/evaluation/replies/cif_400_all_replies.xlsx',
        'human_excel': None,
        'eval_batch_id': 'batch_1',
        'top_n_cases': 20,
        'report_title': 'CIF 400 多模型评测报告 2026Q1',
    },
    ...
}
```

---

## 10. 分析报告说明

运行 `analyze_results` 后，在 `outputs/evaluation/reports/analysis_report.xlsx` 中生成以下工作表：

| 工作表 | 内容 | 使用场景 |
|--------|------|----------|
| **1_多维度排名** | 整体/L1/L2/L3/难度/Source 排名 | 了解各模型综合表现 |
| **1_专家纠偏模型排名** | 专家打分纠偏后的排名 | 有专家打分时使用 |
| **2_每道题排名一致性** | 每道题人工 vs 模型排名相关性 | 评估模型评分可靠性 |
| **3_组内一致性成绩单** | 标注员之间的一致性指标 | 评估标注质量 |
| **4_模型专家一致性** | 模型打分与专家打分相关性 | 验证自动评分可信度 |
| **5_价值题目TOP20** | 最具区分度的 20 道题 | 筛选高质量评测题目 |
| **6_题目完整分析** | 每道题的信度/效度/区分度 | 题目质量审查 |
| **7_约束类型分析** | 各约束类型得分分布 | 分析模型能力短板 |
| **8_典型案例** | 典型高/低分案例 | 定性分析参考 |
| **9_人工校验分析** | 人机评分详细对照 | 有人工标注时使用 |
| **指标定义说明** | 所有指标的定义和计算方法 | 理解指标含义 |

---

## 11. 可视化报告说明

运行 `generate_report` 后，在 `outputs/evaluation/reports/` 生成：

- `evaluation_report_YYYYMMDD_HHMMSS.html`：交互式 HTML 报告
- `evaluation_report_YYYYMMDD_HHMMSS.md`：Markdown 格式报告

### HTML 报告功能

- **整体概况**：模型数、题目数、评测次数统计卡片 + 综合排名表
- **数据可视化**：
  - 模型平均分柱状图（含误差棒）
  - L1 维度得分热力图
  - 难度等级得分热力图
- **一致性分析摘要**：标注员组内一致性 + 模型排名一致性
- **价值题目深度分析**：
  - TOP20 价值题目概览表
  - 每道题的可折叠详情卡片，包含：
    - 题目内容（Markdown 渲染）
    - 各模型得分对比
    - 专家意见（如有）
    - AI 综合评估和失分点分析
    - 各模型完整回复（Tab 切换）

### Markdown 报告功能

适合导出为 PDF 或在 Git 中版本管理，包含所有分析内容的文本版本。

---

## 12. 常见问题与注意事项

### ⚠️ 注意事项

**1. qid 必须是字符串类型**

系统内部统一将 qid 转为字符串处理。如果 Excel 中 qid 是纯数字，请确保读取时不会丢失前导零。建议使用 `Q001`、`CIF_001` 等带前缀的格式。

**2. eval_batch_id 要保持一致**

`evaluate_replies` 时设置的 `batch_id` 必须与 `analyze_results` 和 `generate_report` 中的 `eval_batch_id` 一致，否则系统找不到对应的评分列。

**3. replies.xlsx 的 Sheet 名称**

系统优先读取名为 `Sheet1` 或 `replies` 的工作表，其他名称的 Sheet 会读取第一个工作表。

**4. 断点续跑机制**

- Stage 3（回复生成）：已有 `(qid, model)` 组合的行自动跳过
- Stage 4（评估打分）：`eval_{batch_id}` 列已有值的行自动跳过
- 如需重新评估，修改 `batch_id` 为新值

**5. 专家打分的时机**

专家打分应在 Stage 4 完成后、运行 `analyze_results` 之前填入 `replies.xlsx` 的 `专家打分` 和 `专家理由` 列。

**6. 人工标注表的字段名**

系统支持 `QID` 和 `qid` 两种写法（自动转换），但其他字段名必须严格匹配（`ann1_score`、`ann2_score` 等）。

**7. Sysprompt 文件不存在时**

系统不会报错，会使用空 Sysprompt 或内置默认值继续运行。但 Stage 0/1/1.5/2/4 的质量高度依赖 Sysprompt，强烈建议配置。

**8. 并发数设置**

- `max_workers` 建议根据 API 限速设置，通常 3-5 即可
- Stage 5 的 `report.max_workers` 建议设为 3，避免触发 API 限速

### ❓ 常见问题

**Q: 运行 analyze_results 报错"结果表中未找到评估列"**

A: replies.xlsx 中没有 `eval_*` 列。需要先运行 Stage 4 评估，或手动添加评分列（列名格式为 `eval_batch_1`）。

**Q: 专家纠偏排名为空**

A: replies.xlsx 中没有 `专家打分` 列，或该列全为空。添加专家打分后重新运行分析。

**Q: HTML 报告中图表不显示**

A: 需要网络连接加载 Plotly.js CDN。离线环境下可将 Plotly.js 下载到本地并修改 `report_writer_html.py` 中的 CDN 链接。

**Q: 如何只分析部分模型**

A: 在 `data_filters.model_list` 中指定模型列表，或在 replies.xlsx 中只保留目标模型的数据。

**Q: 如何添加新的评测维度（如 L4）**

A: 在 questions.xlsx 中添加 `L4` 列，然后在 `ranking.py` 的 `generate_all_rankings()` 中添加对应的维度分析逻辑。

**Q: 报告中的模型图标不对**

A: 在 `evaluation/analysis/report_writer.py` 的 `MODEL_ICONS` 字典中添加或修改模型名称到图标 URL 的映射。

---

*文档版本：v1.0 | 最后更新：2026-02*

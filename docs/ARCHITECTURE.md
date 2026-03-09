# 复杂指令遵循评测与数据合成系统 — 全链路架构设计文档

> 本文档描述自动化评测与数据合成系统的各功能模块设计逻辑，供开发与二次开发参考。

---

## 目录

1. [系统总览](#1-系统总览)
2. [目录结构](#2-目录结构)
3. [核心模块：Pipeline 管道](#3-核心模块pipeline-管道)
4. [Stage 0：指令生成](#4-stage-0指令生成)
5. [Stage 0.5：指令提取](#5-stage-05指令提取)
6. [Stage 1：指令质量评估](#6-stage-1指令质量评估)
7. [Stage 1.5：评分标准生成](#7-stage-15评分标准生成)
8. [Stage 2：参考答案生成](#8-stage-2参考答案生成)
9. [Stage 3：模型回复生成](#9-stage-3模型回复生成)
10. [Stage 4：回复评估打分](#10-stage-4回复评估打分)
11. [Stage 5：可视化报告生成](#11-stage-5可视化报告生成)
12. [分析模块：analyze_results](#12-分析模块analyze_results)
13. [数据加载器 data_loader](#13-数据加载器-data_loader)
14. [排名分析 ranking](#14-排名分析-ranking)
15. [一致性分析 consistency](#15-一致性分析-consistency)
16. [价值题目分析 valuable_questions](#16-价值题目分析-valuable_questions)
17. [题目质量分析 item_analysis](#17-题目质量分析-item_analysis)
18. [报告生成器 report_writer](#18-报告生成器-report_writer)
19. [基础设施模块](#19-基础设施模块)
20. [数据流全链路图](#20-数据流全链路图)

---

## 1. 系统总览

本系统是一套**基于约束的 AI 模型评测 Pipeline**，支持从题目生成、模型回复采集、自动评分，到统计分析、可视化报告的全流程自动化。

### 核心设计原则

- **阶段化流水线**：每个 Stage 独立可运行，支持断点续跑
- **约束驱动评分**：评分标准由约束条目构成，支持细粒度分析
- **缓存优先**：已完成的评估结果不重复计算，支持增量评估
- **专家纠偏**：支持人工专家打分覆盖模型评分，用于排名校正
- **多模型并发**：ThreadPoolExecutor 并发调用多个模型

---

## 2. 目录结构

```
evaluation/
├── main.py                    # 系统入口，CONFIG 配置在此
├── pipeline.py                # PipelineManager，阶段调度核心
├── core/
│   ├── types.py               # Constraint 数据类型定义
│   ├── utils.py               # safe_str / safe_save_excel 等工具函数
│   ├── blacklist.py           # 模型黑名单管理
│   └── cache_messages.py      # 多 Provider 缓存消息构建
├── managers/
│   ├── directory.py           # 输出目录管理
│   ├── sysprompt.py           # Sysprompt Excel 读取管理
│   └── constraint_library.py  # 约束库管理
├── testing/
│   └── model_tester.py        # 模型可用性测试
├── stages/
│   ├── stage0_generate.py     # 指令生成
│   ├── stage0_5_extract.py    # 指令提取
│   ├── stage1_quality.py      # 指令质量评估
│   ├── stage1_5_criteria.py   # 评分标准生成
│   ├── stage2_reference.py    # 参考答案生成
│   ├── stage3_reply.py        # 模型回复生成
│   ├── stage4_evaluate.py     # 回复评估打分
│   └── stage5_report.py       # 可视化报告生成
└── analysis/
    ├── data_loader.py          # 数据加载与预处理
    ├── metrics.py              # 科学统计指标（Cronbach α、ICC、Cohen's κ 等）
    ├── ranking.py              # 模型排名分析
    ├── consistency.py          # 人机/组内一致性分析
    ├── valuable_questions.py   # 价值题目筛选
    ├── item_analysis.py        # 题目质量分析（信度/效度/区分度）
    ├── report.py               # Excel 综合分析报告生成
    ├── report_writer.py        # 报告工具函数（图标/HTML转义等）
    ├── report_writer_html.py   # HTML 可视化报告生成
    └── report_writer_md.py     # Markdown 报告生成

data/
└── evaluation/
    └── sysprompts.xlsx         # 各阶段 Sysprompt 配置表

outputs/
└── evaluation/                 # 所有输出文件的根目录
    ├── stage0_generation/
    ├── stage0.5_extraction/
    ├── stage1_quality/
    ├── questions/
    ├── replies/
    ├── evaluations/
    ├── library/
    └── reports/
```

---

## 3. 核心模块：Pipeline 管道

**文件**：`evaluation/pipeline.py`

### 设计逻辑

`PipelineManager` 是整个系统的调度核心，负责：

1. **阶段定义**：`STAGE_DEFINITIONS` 字典声明每个阶段的名称、输入文件、输出文件
2. **阶段排序**：`_get_sorted_stages()` 按预定义顺序执行，防止乱序
3. **阶段执行**：`execute_stage()` 根据 stage 名称分发到对应函数
4. **资源初始化**：构造时初始化 `DirectoryManager`、`SyspromptManager`、`ConstraintLibraryManager`

### 阶段执行顺序

```
test_models → generate_instructions → extract_instructions → evaluate_instructions
→ generate_criteria → generate_references → generate_replies → evaluate_replies
→ analyze_results → generate_report
```

### 关键设计

- 每个 stage 从 `cfg`（CONFIG 字典）读取配置，不硬编码参数
- `dm.get_path(stage_dir, filename)` 统一管理文件路径
- `sp.get(stage_key, default)` 统一读取 Sysprompt

---

## 4. Stage 0：指令生成

**文件**：`evaluation/stages/stage0_generate.py`

### 设计逻辑

调用裁判模型批量生成评测指令（题目）。

- 读取 `instruction_generation` sysprompt
- 循环调用 `client.chat()` 生成 `num_batches` 批次
- 支持断点续跑：已有结果的批次 ID 跳过
- 输出：`stage0_generation/generated_responses.xlsx`，每行一个批次的原始生成文本

### 关键参数

| 参数 | 说明 |
|------|------|
| `num_instruction_batches` | 生成批次数量 |
| `instruction_temperature` | 生成温度（建议 0.8-0.9，保证多样性） |

---

## 5. Stage 0.5：指令提取

**文件**：`evaluation/stages/stage0_5_extract.py`

### 设计逻辑

将 Stage 0 生成的原始文本解析为结构化指令条目。

- 从 `generated_responses.xlsx` 读取原始文本
- 用正则/LLM 提取每条指令的 `qid`、`query`、`L1/L2/L3`、`difficulty_level`、`source` 等字段
- 输出：`stage0.5_extraction/extracted_instructions.xlsx`

---

## 6. Stage 1：指令质量评估

**文件**：`evaluation/stages/stage1_quality.py`

### 设计逻辑

对提取出的指令进行质量筛选，过滤低质量题目。

- 读取 `instruction_quality` sysprompt
- 对每条指令调用裁判模型评估质量（是否清晰、可评估、有区分度）
- 输出质量评分和是否通过标志
- 输出：`stage1_quality/evaluated_instructions.xlsx`

---

## 7. Stage 1.5：评分标准生成

**文件**：`evaluation/stages/stage1_5_criteria.py`

### 设计逻辑

为每道题目生成结构化评分标准（evaluation_criteria）。

- 读取 `criteria_generation` sysprompt
- 对每道题调用裁判模型生成约束条目列表
- 评分标准格式：约束类型（流程/格式/边界/数量/教学/素材）+ 分值 + 描述
- 支持断点续跑（已有 criteria 的题目跳过）
- 输出：`questions/questions_with_criteria.xlsx`

### 约束类型体系

| 约束类型 | 说明 | 是否参与评分 |
|----------|------|-------------|
| 流程约束 | 回答步骤、逻辑顺序 | ✅ |
| 格式约束 | 输出格式、结构要求 | ✅ |
| 边界约束 | 范围限制、禁止内容 | ✅ |
| 数量约束 | 字数、条目数量 | ✅ |
| 教学约束 | 教学目标（仅计入难度） | ❌ |
| 素材约束 | 参考材料（仅计入难度） | ❌ |

---

## 8. Stage 2：参考答案生成

**文件**：`evaluation/stages/stage2_reference.py`

### 设计逻辑

基于题目和评分标准，生成高质量参考答案。

- 读取 `reference_generation` sysprompt
- 将 `query + evaluation_criteria` 一起传给裁判模型
- 参考答案用于后续评估时作为对照
- 输出：`questions/questions_complete.xlsx`（包含 query + criteria + reference）

---

## 9. Stage 3：模型回复生成

**文件**：`evaluation/stages/stage3_reply.py`

### 设计逻辑

对所有待测模型批量采集回复。

- 从 `questions_complete.xlsx` 读取题目列表
- 对 `reply_model_configs` 中每个模型并发调用
- 支持断点续跑：已有回复的 `(qid, model)` 组合跳过
- 输出：`replies/replies.xlsx`，每行为一个 `(qid, model, reply)` 记录

### 关键参数

| 参数 | 说明 |
|------|------|
| `reply_model_configs` | 待测模型列表，每项含 `model`、`provider`（可选）、`enable_thinking` 等 |
| `reply_temperature` | 回复生成温度（建议 0.6） |

---

## 10. Stage 4：回复评估打分

**文件**：`evaluation/stages/stage4_evaluate.py`

### 设计逻辑

用裁判模型对每条回复按评分标准打分。

#### 评分流程

1. 读取 `questions_complete.xlsx` 和 `replies.xlsx`
2. 对每个 `(qid, model)` 构建评估 prompt（含 query、criteria、reference、reply）
3. 调用裁判模型，解析返回的分数（支持多种格式：`总分: 85`、`85/100` 等）
4. 将分数写入 `replies.xlsx` 的 `eval_{batch_id}` 列

#### 缓存消息机制

`cache_messages.py` 根据 Provider 类型（Claude/OpenAI/Gemini）构建不同格式的缓存消息，将 query+criteria+reference 作为缓存前缀，减少重复 token 消耗。

#### 增量评估

- 通过 `batch_id` 区分不同评估批次
- 已有评分的行（`eval_{batch_id}` 列非空）自动跳过
- 支持 `data_filters` 过滤特定 qid、model、reference_type

#### 专家打分字段

replies.xlsx 中可包含 `专家打分` 和 `专家理由` 列，用于后续专家纠偏排名。

---

## 11. Stage 5：可视化报告生成

**文件**：`evaluation/stages/stage5_report.py`

### 设计逻辑

在统计分析基础上，对价值题目进行 AI 深度分析，生成 HTML + Markdown 报告。

#### 执行流程

```
load_and_preprocess()
    ↓
运行所有分析器（ranking / consistency / valuable_questions / item_analysis）
    ↓
筛选 TOP N 价值题目作为分析候选
    ↓
ThreadPoolExecutor 并发调用裁判模型分析每道题
    ↓
generate_html_report() + generate_markdown_report()
```

#### AI 分析 Prompt 构建

`_build_case_analysis_prompt()` 将以下信息组装为 prompt：
- 题目内容（query）
- 评分标准（evaluation_criteria）
- 各模型得分排名
- 评估详情节选（前 5 名模型的 eval_raw 文本）
- 专家意见（如有）

#### 响应解析

`_parse_analysis_response()` 从 LLM 返回中提取：
- `【综合评估】` → `ai_summary`
- `【失分点分析】` → `ai_analysis`

#### Sysprompt 配置

从 Excel 读取 `stage = report_analysis` 的行，未配置时使用内置 `DEFAULT_REPORT_SYSPROMPT`。

---

## 12. 分析模块：analyze_results

**文件**：`evaluation/analysis/report.py`

### 设计逻辑

生成完整的 Excel 统计分析报告，包含 9 大分析维度：

| Sheet | 内容 |
|-------|------|
| 1_多维度排名 | 整体/L1/L2/L3/Source/难度/显著性检验 |
| 1_专家纠偏模型排名 | 用专家打分替换难题模型打分后的排名 |
| 2_每道题排名一致性 | 人工与模型在每道题上的排名相关性 |
| 2_人机一致性排名 | 标注员与模型的整体排名一致性 |
| 3_组内一致性成绩单 | 标注员之间的 ICC/Kappa 等指标 |
| 3_与专家一致性 | 各标注员与专家的一致性 |
| 4_模型专家一致性 | 模型打分与专家打分的相关性 |
| 5_价值题目TOP20 | 综合价值分最高的 20 道题 |
| 6_题目完整分析 | 每道题的信度/效度/区分度指标 |
| 7_约束类型分析 | 各约束类型的得分分布 |
| 8_典型案例 | 典型高/低分案例 |
| 9_人工校验分析 | 人机评分详细对照 |
| 指标定义说明 | 所有指标的定义和计算方法 |

---

## 13. 数据加载器 data_loader

**文件**：`evaluation/analysis/data_loader.py`

### 设计逻辑

统一的数据加载入口，返回标准化的 `data` 字典。

#### 返回的 data 字典结构

```python
{
    'questions': pd.DataFrame,          # 题目表
    'replies': pd.DataFrame,            # 回复+评分表（含 eval_score 列）
    'human': pd.DataFrame,              # 人工标注表（可为空）
    'rater_scores': pd.DataFrame,       # 标注员打分（长格式）
    'expert_scores': pd.DataFrame,      # 专家打分（从 replies 的专家打分列提取）
    'replies_with_question': pd.DataFrame,  # replies LEFT JOIN questions
    'eval_column': str,                 # 当前使用的评估列名
}
```

#### eval_column 解析逻辑

1. 若指定 `eval_batch_id`，优先使用 `eval_{batch_id}` 列
2. 否则使用最后一个 `eval_*` 列（按列名排序）
3. 找不到则抛出 `ValueError`

#### 专家打分提取

从 `replies.xlsx` 的 `专家打分` 列提取，构建 `expert_scores` DataFrame，包含 `qid`、`model`、`score`、`reason` 字段。

---

## 14. 排名分析 ranking

**文件**：`evaluation/analysis/ranking.py`

### ModelRankingAnalyzer

基于 `replies_with_question` 生成多维度排名：

- **整体排名**：按模型平均分降序，含标准差、最高/最低分、各分段数量
- **L1/L2/L3 维度排名**：按题目分类维度分组计算各模型得分
- **Source 维度**：自建数据 vs 公开数据
- **难度等级**：E/D/C/B/A/S 六级
- **显著性检验**：ANOVA + 两两 t-test

### ExpertCorrectedRankingAnalyzer

专家纠偏排名：对有专家打分的题目，用专家分替换模型自动评分，重新计算排名，并标注排名变化。

---

## 15. 一致性分析 consistency

**文件**：`evaluation/analysis/consistency.py`

### HumanModelConsistencyAnalyzer

- **每道题排名一致性**：对每道题，计算人工排名与模型排名的 Spearman 相关
- **整体排名一致性**：标注员均分排名 vs 模型自动评分排名

### HumanExpertConsistencyAnalyzer

- **标注员组内一致性**：每位标注员与其他标注员的 ICC、Kappa、Pearson 相关
- **标注员 vs 专家**：每位标注员与专家打分的一致性
- **人工均分 vs 专家**：整体人工均分与专家打分的相关性

### ModelReliabilityAnalyzer

- **模型 vs 专家**：模型自动评分与专家打分的相关性（整体 + 分模型）
- **模型排名一致性**：不同评估批次间模型排名的稳定性

---

## 16. 价值题目分析 valuable_questions

**文件**：`evaluation/analysis/valuable_questions.py`

### 设计逻辑

筛选最具评测价值的题目（TOP 20），综合以下维度：

| 维度 | 权重 | 说明 |
|------|------|------|
| 区分度（D值） | 高 | 高分组与低分组得分差 |
| 分数方差 | 中 | 模型间得分离散程度 |
| 难度适中性 | 中 | 避免过难/过易题目 |
| 专家关注度 | 高 | 有专家打分的题目优先 |
| 人工标注覆盖 | 中 | 有人工标注的题目优先 |

输出 `综合价值分` 排名，包含最佳/最差模型、分数范围等信息。

---

## 17. 题目质量分析 item_analysis

**文件**：`evaluation/analysis/item_analysis.py`

### ItemAnalyzer

对每道题计算心理测量学指标：

| 指标 | 计算方法 | 说明 |
|------|----------|------|
| Cronbach α | 内部一致性系数 | 题目信度 |
| 折半信度 | 奇偶分半相关 | 信度验证 |
| 构念效度 | 与指令难度的相关 | 效度指标 |
| 预测效度 | 与通过率的相关 | 效度指标 |
| 区分度指数 D | 高低分组差值 | 区分能力 |
| 点二列相关 | 与总分的相关 | 题目质量 |
| 综合质量分 | 加权综合 | 最终质量评级 |

### ConstraintTypeAnalyzer

按约束类型（流程/格式/边界/数量）分析各类约束的得分分布和通过率。

### TypicalCaseSelector

从 `item_analysis_df` 中筛选典型案例：优先选择区分度高、质量好、覆盖不同 L1 维度的题目。

---

## 18. 报告生成器 report_writer

### report_writer.py（基础工具）

- `MODEL_ICONS`：主流模型图标 URL 映射表
- `_get_model_icon(model_name)`：模糊匹配模型名返回图标
- `_escape_html(text)`：HTML 特殊字符转义
- `_nl2br(text)`：换行转 `<br>`
- `_safe_float(value, default)`：安全浮点转换
- `_safe_str(value, max_len)`：安全字符串转换

### report_writer_html.py（HTML 报告）

生成包含以下 Section 的单文件 HTML：

1. **整体概况**：统计数字卡片 + 模型综合排名表
2. **数据可视化**：Plotly 柱状图（模型对比）+ L1 热力图 + 难度热力图
3. **一致性分析摘要**：标注员组内一致性 + 模型排名一致性
4. **价值题目深度分析**：TOP20 概览表 + 可折叠案例卡片（含模型回复 Tab 切换）

技术栈：内嵌 CSS + Plotly.js + marked.js（Markdown 渲染）+ highlight.js

### report_writer_md.py（Markdown 报告）

生成结构化 Markdown 文档，包含目录、各维度排名表、案例分析文本，适合导出为 PDF 或在 Git 中版本管理。

---

## 19. 基础设施模块

### DirectoryManager（managers/directory.py）

统一管理输出目录，`get_path(stage, filename)` 返回完整路径并确保目录存在。

### SyspromptManager（managers/sysprompt.py）

从 Excel 文件加载各阶段 Sysprompt，`get(stage, default)` 按 stage key 查询，未配置时返回 default。

### ConstraintLibraryManager（managers/constraint_library.py）

管理约束条目库，支持按类型/子类型查询，持久化到 Excel。

### ModelBlacklist（core/blacklist.py）

记录调用失败的模型，避免重复调用失败模型浪费资源。

### ScientificMetrics（analysis/metrics.py）

封装统计学指标计算：
- `cronbach_alpha(df)`：Cronbach α 系数
- `icc_2_1(scores1, scores2)`：组内相关系数
- `discrimination_index(scores)`：区分度指数
- `cohens_kappa_weighted(y1, y2)`：加权 Cohen's κ
- `cohens_d(scores1, scores2)`：效应量
- `kendall_w(ranks_df)`：Kendall W 一致性系数

---

## 20. 数据流全链路图

```
[sysprompts.xlsx]
       │
       ▼
[Stage 0] generate_instructions
       │ generated_responses.xlsx
       ▼
[Stage 0.5] extract_structured_instructions
       │ extracted_instructions.xlsx
       ▼
[Stage 1] batch_evaluate_instruction_quality
       │ evaluated_instructions.xlsx
       ▼
[Stage 1.5] batch_generate_criteria
       │ questions_with_criteria.xlsx
       ▼
[Stage 2] batch_generate_references
       │ questions_complete.xlsx ──────────────────────┐
       ▼                                               │
[Stage 3] batch_generate_replies                       │
       │ replies.xlsx ─────────────────────────────────┤
       ▼                                               │
[Stage 4] batch_evaluate_responses_with_cache          │
       │ replies.xlsx (新增 eval_{batch_id} 列)        │
       │                                               │
       ├──────────────────────────────────────────────►│
       ▼                                               ▼
[analyze_results]                            [generate_report]
  data_loader.load_and_preprocess()           data_loader.load_and_preprocess()
       │                                               │
       ├─ ModelRankingAnalyzer                         ├─ ModelRankingAnalyzer
       ├─ ExpertCorrectedRankingAnalyzer               ├─ ValuableQuestionAnalyzer
       ├─ HumanModelConsistencyAnalyzer                ├─ ItemAnalyzer
       ├─ HumanExpertConsistencyAnalyzer               ├─ AI 深度分析（LLM）
       ├─ ModelReliabilityAnalyzer                     │
       ├─ ValuableQuestionAnalyzer                     ├─ generate_html_report()
       ├─ ItemAnalyzer                                 └─ generate_markdown_report()
       └─ ConstraintTypeAnalyzer                              │
              │                                              ▼
              ▼                                    evaluation_report_*.html
       analysis_report.xlsx                        evaluation_report_*.md
```

---

*文档版本：v1.0 | 最后更新：2026-02*

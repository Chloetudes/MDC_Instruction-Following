# 系统重构计划：灵活化 + 多场景适配（最终版 v2）

## 用户确认的核心决策

1. **Stage 0 输出格式**：统一 JSON 格式，一个种子生成 N 条数据（可配置 `items_per_batch`），stage0_5 解析 JSON 数组提取每条 query
2. **Stage 4 覆盖策略**：完全通过 CONFIG 配置文件控制 `overwrite_mode`，**彻底去掉 `input()` 交互**
3. **Stage 1 衔接**：Stage 1 是**可选阶段**（质量把控），全链路时 stage1 输出自动流转到 stage1.5（字段统一为 `qid`）
4. **情感陪伴适配**：同样用 JSON 格式，stage0_5 解析多轮对话 JSON，`query` 字段存储对话 JSON 字符串
5. **多轮对话扩展（新增 Stage 0.7）**：
   - 将单轮 query 拆分/扩展为多轮对话（sysprompt 驱动）
   - 数据结构：`session_id`（原 qid）+ `turn_id`（第几轮，从 1 开始）
   - 每轮独立 `qid = {session_id}_T{turn_id}`，可独立配置评估标准
   - 评测时支持历史轮次缓存：评估第 N 轮时，前 N-1 轮全部进入 prompt cache
   - 作为**可选阶段**，不影响现有单轮流程

---

## 统一的 Stage 0 输出 JSON 格式

### 指令遵循项目
```json
[
  {"task_type": "创意写作-诗歌", "query": "请写一首关于秋天的七言绝句..."},
  {"task_type": "逻辑推理", "query": "有5个人站成一排..."}
]
```

### 情感陪伴项目（query 为多轮对话 JSON 字符串）
```json
[
  {
    "task_type": "情感支持-失恋安慰",
    "query": [
      {"role": "user", "content": "我最近失恋了，心里很难受..."},
      {"role": "assistant", "content": "我能感受到你现在的痛苦..."}
    ]
  }
]
```

### Stage 0.7 多轮扩展后的数据结构（Excel 行）
| session_id | turn_id | qid | query | history_context |
|-----------|---------|-----|-------|----------------|
| B001_Q1 | 1 | B001_Q1_T1 | 你好，我最近... | [] |
| B001_Q1 | 2 | B001_Q1_T2 | 那我该怎么办 | [turn1 完整对话] |
| B001_Q1 | 3 | B001_Q1_T3 | 谢谢你的建议 | [turn1+turn2 完整对话] |

---

## 核心问题修复清单

### 🔴 P0 - 字段统一（`id` → `qid`）
- `stage0_5_extract.py:69`：输出 `qid` 而非 `id`
- `stage1_quality.py:68,83,94`：`id` 列全部改为 `qid`，`existing_ids` → `existing_qids`
- 全链路字段流：`qid` 贯穿 stage0.5 → stage1 → stage1.5 → stage2 → stage3 → stage4

### 🔴 P0 - 硬编码路径修复
- `pipeline.py:191,207,221`：三处 `cif_400_all_replies.xlsx` → 从 config 读取，默认 `replies.xlsx`
- 顶层 `replies_excel` 配置项，三个阶段共用

### 🔴 P0 - 移除 `input()` 阻塞
- `stage4_evaluate.py:292`：移除 `input()` 交互
- `batch_evaluate_responses_with_cache` 增加 `overwrite_mode: str = 'skip'` 参数
- `pipeline.py` 传递 `cfg.get('overwrite_mode', 'skip')`

---

## 文件修改详情

### 1. `evaluation/stages/stage0_generate.py`
- 增加 `items_per_batch: int = 3` 参数
- `_build_user_prompt()` 明确要求模型输出 JSON 数组格式，包含 `task_type` 和 `query` 字段
- 情感陪伴模式下，`query` 为多轮对话数组

### 2. `evaluation/stages/stage0_5_extract.py`（重写）
- 移除 `$` 分隔符解析逻辑
- 新增 `_parse_json_response(response_text, original_id)` 函数：
  - 从 response 中提取 JSON 数组（支持 markdown 代码块包裹，容错处理）
  - 每个 item 提取 `task_type` 和 `query`
  - `qid = {original_id}_Q{n}`（从 1 开始）
  - `query` 字段：如果是 list（多轮对话），`json.dumps` 转字符串存储
- 输出列：`qid`, `original_id`, `item_num`, `task_type`, `query`

### 3. `evaluation/stages/stage0_7_multiturn.py`（新建）
- 新增 `expand_to_multiturn` 函数
- 输入：`extracted_instructions.xlsx`（含 `qid`, `query`）
- 通过 sysprompt 驱动模型将单轮 query 扩展为 3-10 轮对话
- 输出列：`session_id`, `turn_id`, `qid`（= `{session_id}_T{turn_id}`）, `query`（当轮用户输入）, `history_context`（JSON 字符串，前 N-1 轮完整对话）, `task_type`
- 支持 `min_turns`/`max_turns` 配置

### 4. `evaluation/stages/stage1_quality.py`
- `id` → `qid` 全局替换（required_cols、existing_qids、result_row 等）

### 5. `evaluation/stages/stage4_evaluate.py`
- `batch_evaluate_responses_with_cache` 增加 `overwrite_mode: str = 'skip'` 参数
- 移除 `input()` 交互代码块（约 287-304 行）
- 根据 `overwrite_mode` 自动处理：
  - `'skip'`：跳过已有评估（默认）
  - `'overwrite'`：清空已有评估列重新评估
  - `'new_batch'`：自动生成新 batch_id（时间戳）
- **多轮对话评测缓存优化**：
  - 检测 `history_context` 列是否存在
  - 若存在，将 `history_context` 中的历史轮次追加到 prompt cache 的 context 部分
  - 评估时按 `session_id` + `turn_id` 排序，确保历史轮次按序进入缓存

### 6. `evaluation/core/cache_messages.py`（修改）
- `_build_cached_context` 函数增加 `history_context: str = ''` 参数
- 若 `history_context` 非空，在 context 中追加历史对话轮次（作为 cached 内容）
- `build_cached_messages_*` 系列函数同步增加 `history_context` 参数透传

### 7. `evaluation/pipeline.py`
- **修复硬编码路径**：三处 `cif_400_all_replies.xlsx` 改为 `cfg.get('replies_excel') or dm.get_path("replies", "replies.xlsx")`
- **新增 `expand_multiturn` 阶段**：
  - 调用 `expand_to_multiturn`
  - 输入：`stage0.5_extraction/extracted_instructions.xlsx`
  - 输出：`stage0.7_multiturn/multiturn_instructions.xlsx`
- **新增 `promote_to_questions` 阶段**：
  - 优先读取 `stage1_quality/evaluated_instructions.xlsx`，否则读取 `stage0.5_extraction/extracted_instructions.xlsx`，或 `stage0.7_multiturn/multiturn_instructions.xlsx`
  - 过滤 `status == 'ok'`（如有）
  - 写入 `questions/questions.xlsx`
- **传递新参数**：`items_per_batch`、`overwrite_mode`、`history_context`（stage4）
- **STAGE_DEFINITIONS** 新增 `expand_multiturn` 和 `promote_to_questions` 阶段定义

### 8. `evaluation/stages/__init__.py`（修改）
- 导出 `expand_to_multiturn`

### 9. `evaluation/main.py`（重构 CONFIG）
```python
CONFIG = {
    # ========== 执行阶段 ==========
    # 全链路模式（数据合成 + 评测）：
    # 'stages': ['generate_instructions', 'extract_instructions',
    #            'evaluate_instructions',        # 可选，质量把控
    #            'expand_multiturn',             # 可选，多轮扩展
    #            'promote_to_questions',
    #            'generate_criteria', 'generate_references',
    #            'generate_replies', 'evaluate_replies',
    #            'analyze_results', 'generate_report']
    #
    # 自定义评测模式（已有 questions.xlsx）：
    # 'stages': ['generate_criteria', 'generate_references', 'generate_replies',
    #            'evaluate_replies', 'analyze_results', 'generate_report']
    'stages': ['generate_criteria'],

    # ========== 基础配置 ==========
    'sysprompt_excel': "data/evaluation/sysprompts.xlsx",
    'output_base_dir': "outputs/evaluation",

    # ========== 裁判模型配置 ==========
    'provider': "idealab",
    'model': "claude_sonnet4_5",
    'timeout': 300,

    # ========== 温度配置 ==========
    'instruction_temperature': 0.9,
    'criteria_temperature': 0.3,
    'reference_temperature': 0.7,
    'reply_temperature': 0.6,
    'evaluation_temperature': 0.3,

    # ========== 数据合成配置 ==========
    'generation': {
        'num_batches': 15,
        'items_per_batch': 3,           # 每批生成几条数据（1-5）
        'schema_excel': None,           # schema 文件路径（可选）
        'see_excel': None,              # see 种子文件路径（可选）
    },

    # ========== 多轮扩展配置（Stage 0.7，可选）==========
    'multiturn': {
        'min_turns': 3,
        'max_turns': 8,
    },

    # ========== 评估批次ID ==========
    'batch_id': "batch_1",

    # ========== 评估覆盖策略 ==========
    'overwrite_mode': 'skip',  # 'skip' | 'overwrite' | 'new_batch'

    # ========== 回复文件路径（三个阶段共用）==========
    'replies_excel': None,  # None 时使用默认 replies/replies.xlsx

    # ========== 待测试模型配置 ==========
    'reply_model_configs': [
        {"model": "qwen3-max-2026-01-23", "enable_thinking": True},
        {"model": "gpt-5.2-chat-latest", "enable_thinking": False},
    ],

    # ========== 并发配置 ==========
    'max_workers': 5,
    'checkpoint_interval': 10,

    # ========== 数据筛选配置 ==========
    'data_filters': {
        'qid_list': None,
        'model_list': None,
        'reference_type': None,
        'batch_size': None,
    },

    # ========== 分析/报告配置 ==========
    'analysis': {
        'human_excel': None,
        'eval_batch_id': None,
    },
    'report': {
        'human_excel': None,
        'eval_batch_id': None,
        'top_n_cases': 20,
        'report_title': '多模型能力评测报告',
    },
}
```

---

## 多轮对话评测缓存设计

### 评测时的 Prompt 结构（以第 3 轮为例）

```
[SYSTEM - cached]
  评测 sysprompt

[USER - cached]
  题目信息（query 当轮用户输入 + evaluation_criteria）
  历史对话上下文（turn1 + turn2 完整对话，全部 cached）

[USER - not cached]
  当前被测模型的回复（turn3 reply）

[ASSISTANT]
  评分结果
```

### `cache_messages.py` 修改点
- `_build_cached_context` 增加 `history_context` 参数
- 若 `history_context` 非空（JSON 字符串），解析后追加到 context 的 cached 部分：
  ```
  【历史对话记录】
  [第1轮]
  用户：...
  助手：...
  [第2轮]
  用户：...
  助手：...
  ```

---

## 完整数据流（修复后）

```
Stage 0: generate_instructions
  输出: generated_responses.xlsx (id, response, L1, L2, L3)
  response = JSON 数组字符串

Stage 0.5: extract_instructions
  输入: generated_responses.xlsx
  解析 JSON → 每条 item 一行
  输出: extracted_instructions.xlsx (qid, original_id, item_num, task_type, query)

Stage 0.7: expand_multiturn [可选]
  输入: extracted_instructions.xlsx
  输出: multiturn_instructions.xlsx (session_id, turn_id, qid, query, history_context, task_type)

Stage 1: evaluate_instructions [可选]
  输入: extracted_instructions.xlsx 或 multiturn_instructions.xlsx (qid, query)
  输出: evaluated_instructions.xlsx (qid, query, raw_response, status, ...)

Stage promote: promote_to_questions
  输入: evaluated_instructions.xlsx 或 extracted_instructions.xlsx 或 multiturn_instructions.xlsx
  输出: questions/questions.xlsx (qid, query, task_type, ...)

Stage 1.5: generate_criteria
  输入: questions.xlsx (qid, query)  ← 字段已统一，无断链
  输出: questions_with_criteria.xlsx (qid, query, evaluation_criteria)

Stage 2 → 3: 正常流转（qid 贯穿）

Stage 4: evaluate_replies
  - 单轮：正常评测
  - 多轮：按 session_id + turn_id 排序，history_context 进入 prompt cache
  输出: replies.xlsx（含 eval_{batch_id} 列）

Stage 5 → analyze → report: 正常流转
```

---

## 关键文件路径

| 文件 | 改动类型 | 核心改动 |
|------|---------|---------|
| `evaluation/stages/stage0_generate.py` | 修改 | 增加 `items_per_batch`，prompt 要求 JSON 输出 |
| `evaluation/stages/stage0_5_extract.py` | 重写 | JSON 解析替代 `$` 分隔符，输出 `qid` |
| `evaluation/stages/stage0_7_multiturn.py` | 新建 | 单轮→多轮扩展，`history_context` 字段 |
| `evaluation/stages/stage1_quality.py` | 修改 | `id` → `qid` 全局替换 |
| `evaluation/stages/stage4_evaluate.py` | 修改 | 移除 `input()`，增加 `overwrite_mode`，多轮缓存支持 |
| `evaluation/core/cache_messages.py` | 修改 | 增加 `history_context` 参数支持 |
| `evaluation/pipeline.py` | 修改 | 修复硬编码路径，新增两个阶段，传递新参数 |
| `evaluation/stages/__init__.py` | 修改 | 导出 `expand_to_multiturn` |
| `evaluation/main.py` | 重构 | 完整 CONFIG 结构，两种模式注释说明 |

---

## 实现顺序

1. `stage0_generate.py` - 增加 `items_per_batch`，JSON 格式输出
2. `stage0_5_extract.py` - 重写为 JSON 解析，输出 `qid`
3. `stage0_7_multiturn.py` - 新建多轮扩展模块
4. `stage1_quality.py` - `id` → `qid` 替换
5. `cache_messages.py` - 增加 `history_context` 参数
6. `stage4_evaluate.py` - 移除 `input()`，增加 `overwrite_mode`，多轮缓存
7. `pipeline.py` - 修复路径，新增阶段，传递参数
8. `stages/__init__.py` - 导出新模块
9. `main.py` - 重构 CONFIG

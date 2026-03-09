# -*- coding: utf-8 -*-
"""
main.py - 评估系统入口
基于约束的完整评估系统 v9.0 (项目化通用版)

========== 项目化配置 ==========
  - project_id: 项目编号（如 "cif", "tom"），输出在 outputs/{project_id}/ 下
  - data_batch: 同项目多批次数据时使用。文件带后缀：
      questions_self.xlsx, replies_self.xlsx, analysis_report_self.xlsx 等
  - 项目目录：
      outputs/{project_id}/
        config.json       # 可选，覆盖 CONFIG（stages、data_batch、report_title 等）
        sysprompts.xlsx   # 可选，项目专用提示词（存在则自动使用）
        questions/        # questions{_batch}.xlsx, questions_with_criteria{_batch}.xlsx, ...
        replies/          # replies{_batch}.xlsx
        reports/          # analysis_report{_batch}.xlsx, evaluation_report{_batch}_*.html
  - 使用：project_id + data_batch 确定数据链；将题目放入对应 questions_{batch}.xlsx 即可

========== 使用模式 / Pipeline 阶段 ==========

【模式A：全链路数据合成 + 评测】
  stages: [
    'generate_instructions',   # Stage 0: 生成原始指令批次（JSON格式）
    'extract_instructions',    # Stage 0.5: 解析JSON，提取每条query
    'evaluate_instructions',   # Stage 1: 可选，质量过滤（status=ok才进入后续）
    'expand_multiturn',        # Stage 0.7: 可选，单轮→多轮对话扩展
    'promote_to_questions',    # 将合成数据转为评测题目格式
    'generate_criteria',       # Stage 1.5: 生成评分标准
    'generate_references',     # Stage 2: 生成参考答案
    'generate_replies',        # Stage 3: 多模型生成回复
    'evaluate_replies',        # Stage 4: 裁判模型评分
    'analyze_results',         # Stage 5a: 统计分析
    'generate_report',         # Stage 5b: 可视化报告
  ]

【模式B：自定义评测（已有 questions.xlsx）】
  stages: [
    'generate_criteria',
    'generate_references',
    'generate_replies',
    'evaluate_replies',
    'analyze_results',
    'generate_report',
  ]

【单轮 vs 多轮评测】
  - 单轮：promote 使用 stage0.5_extraction 或 stage1_quality → questions.xlsx；评估标准/参考答案仅基于当前 query。
  - 多轮：promote 使用 stage0.7_multiturn（或 promote_source_excel 指向 multiturn_instructions.xlsx）
    → questions.xlsx + questions_multiturn.xlsx；评估标准/参考答案会带入 history_context，生成与对话历史连贯的标准与参考。
  - 多轮题库会写入 questions 文件夹（questions_multiturn.xlsx）。若希望本次从多轮题库跑标准/参考/回复/评估，可设 questions_input_excel='questions_multiturn.xlsx'。
  - 多轮评估标准：按轮次叠加（1轮 abc、2轮 abcd、3轮 abcde），话题关联；若某轮意图与历史冲突可删减标准。复用逐轮打分即可定位多轮中哪一轮失败。
  - 多轮回复表：与单轮相同列（qid, model, reply, eval_*），多出「轮次编号」turn_id 与「历史对话记录」history_context（及 session_id），便于多轮分析与定位失败轮次。
  - 阶段 analyze_multiturn：基于回复表做多轮分析，输出每 session+model 的轮次得分、首败轮次、会话是否通过；后续可扩展多轮维度和指标。

【模式C：仅数据合成（不评测）】
  stages: [
    'generate_instructions',
    'extract_instructions',
    'evaluate_instructions',   # 可选
    'expand_multiturn',        # 可选
    'promote_to_questions',
  ]

【模式D：直接对现成题目 + 多模型回复做评估】
  适用于：单独提供题目表和多个模型回复结果表，只跑回复评估 + 分析 + 报告。
  stages: [
    'evaluate_replies',
    'analyze_results',
    'generate_report',         # 综合报告（HTML/MD），支持缓存避免重复跑 AI 分析
    'generate_series_reports', # 厂商专项报告（Excel），可单独运行
  ]
  配置要点：
  - questions_excel: 现成题目表路径（相对 cwd 或绝对路径）。需含 qid, query, evaluation_criteria；不填则用 outputs/questions/questions_complete.xlsx
  - replies_excel: 单表填一个路径；多表填列表 [ "path/a.xlsx", "path/b.xlsx" ]，会合并后评估（合并结果写入 replies/merged_replies.xlsx）。表需含 qid, model, reply
  - 若部分行已有分数，evaluate_replies 会跳过已评估行，只补评空白（overwrite_mode=skip）

【智能增量更新（复制覆盖输入表时）】
  - 题目表可随时用「复制覆盖」更新（如 human_rubrics、query）。系统会按输入指纹判断每题是否变化：
  - generate_criteria：仅对「输入列（query、human_rubrics 等）有变化」或新增题目重新生成 evaluation_criteria，未变化的题目保留原结果不覆盖。
  - generate_references：仅对「query、evaluation_criteria 等有变化」或新增题目重新生成 reference，未变化保留。
  - evaluate_replies：默认 overwrite_mode=skip，只对尚未评估的 (qid, model) 调用裁判，已有分数不覆盖。
  - 因此可频繁覆盖输入表，只重算有改动的题目/行，节省时间且不破坏未改动的数据。

【补充人工评测】
  - 方式1：在回复表中直接填写某次评估列（如 eval_batch_1）的部分单元格，再跑 evaluate_replies(batch_id=batch_1)，
            只会对空白行调用裁判模型，已填写的行保留不动。
  - 方式2：在回复表增加列「专家打分」及「专家理由」（或「专家意见」）。同一题下专家对部分模型的评估会作为「价值锚点」注入裁判 prompt；分析/报告会用于模型与专家一致性、专家纠偏排名等。
  - 方式3：使用独立人工标注表（human_excel），在 analysis/report 的配置中指定，用于 rater_scores 与标注员组内一致性、人机一致性排名等。

========== 综合报告 vs 厂商专项报告（已拆分）==========
  - generate_report：综合报告（HTML/MD），含排名、热力图、20 题典型案例 AI 分析；支持缓存，数据未变时微调报告格式可不重跑 AI 分析。
  - generate_series_reports：厂商专项报告（Excel），按厂商出定向分析；可单独运行，不依赖综合报告。

========== 统计分析（analyze_results）==========
  - 补充专家/人工打分后出统计：只读 Excel + 本地计算，不调 API，通常几分钟内完成。
  - 模型打分 vs 专家/人工 一致性计算：
    · 专家：来自回复表列「专家打分」（及「专家理由」），与 eval_{batch_id} 在 (qid,model) 上对齐；
    · 人工：来自 human_excel，列名需含 ann*_score / ann*_avg_score 等，见 data_loader._detect_annotators；
    · 指标：斯皮尔曼 ρ、皮尔逊 r、ICC(2,1)、MAE/归一化MAE、加权 Kappa；排名一致性为模型均分排名 vs 专家/人工排名的斯皮尔曼。
  - 模块功能：专家纠偏排名、模型与专家一致性、标注员组内/与专家一致性、人机排名一致性、价值题目 TOP20、题目信度效度区分度等均可用；无专家/人工数据时对应 sheet 为空或跳过。
  - rubrics 优化验证：当存在多列评估（eval_batch_1、eval_batch_2…）且有专家打分时，报告会生成「4_各批次人机一致性」表，按批次统计专家打分与裁判模型打分的一致性（斯皮尔曼、皮尔逊、ICC、MAE）及「与上一批次斯皮尔曼变化」。可据此观察 human_rubrics 优化或评估标准调整前后的一致性变化，引导专家迭代 rubrics 或对齐自己的评估标准与模型打分。
  - 专家数据验证仅统计：在 analysis 中设置 stats_only: true 时，analyze_results 只生成一张 sheet「专家数据质量与一致性」，集中呈现：①专家数据质量（每位专家的人机一致性、ref 质量、题目区分度、综合排名）②各批次人机一致性（专家打分 vs 各 eval_*，观察 rubrics 优化前后变化）③多批次评估可靠性（哪批更稳定）。不做评测相关统计（无专家榜单、无模型排名、无价值题目/典型案例等）；若 stages 含 generate_report 则自动跳过 HTML/MD 报告。
  - 单独只跑专家统计：stages 设为 "expert_stats"（或 ["analyze_results"]），且 analysis.stats_only: true；会只执行 analyze_results，读取当前 questions_{batch}.xlsx、replies_{batch}.xlsx，输出 reports/analysis_report_{batch}.xlsx 内一张「专家数据质量与一致性」。

========== 数据流说明 ==========

  generated_responses.xlsx  (id, response, L1, L2, L3)
    ↓ extract_instructions
  extracted_instructions.xlsx  (qid, original_id, item_num, task_type, query)
    ↓ evaluate_instructions [可选，过滤低质量]
  evaluated_instructions.xlsx  (qid, query, raw_response, status, ...)
    ↓ expand_multiturn [可选，多轮扩展]
  multiturn_instructions.xlsx  (session_id, turn_id, qid, query, history_context, ...)
    ↓ promote_to_questions [自动选择最优数据源]
  questions.xlsx  (qid, query, task_type, ...)  多轮时另存 questions_multiturn.xlsx 作为多轮题库副本
    ↓ generate_criteria  [支持多轮：含 history_context 时在 prompt 中带入对话历史生成语境相关标准]
  questions_with_criteria.xlsx  (qid, query, evaluation_criteria, ...)
    ↓ generate_references  [支持多轮：同上，生成与对话历史连贯的参考答案]
  questions_complete.xlsx  (qid, query, evaluation_criteria, reference, reference_type, ...)
    ↓ generate_replies
  replies.xlsx  (qid, model, reply [, session_id, turn_id, history_context] 多轮时多出轮次与历史列)
    ↓ evaluate_replies
  replies.xlsx  (新增 eval_{batch_id} 列，多轮格式不变)

========== 回复评估输出说明（evaluate_replies）==========
  - 输出路径：与输入回复表同一文件（如 replies_excel='outputs/replies/replies_6m.xlsx' 则直接写回该文件）
  - 文件结构：Excel 两个 sheet
    · Sheet1：回复表原列 + 新增列 eval_{batch_id}（数值分数）、eval_{batch_id}_raw（裁判完整输出 JSON/文本）
    · batch_log：本批评估日志（batch_id, timestamp, total_tasks, completed, failed, eval_model, temperature, max_workers, success_rate）
  - batch_id：CONFIG 中 batch_id（默认 "batch_1"），列名即 eval_batch_1、eval_batch_1_raw
  - 整合到已有表：按 (qid, model) 匹配，将本次输出的 eval_{batch_id}、eval_{batch_id}_raw 复制到你的总表；整合后需重新跑 analyze_results + generate_report，并在 analysis/report 中指定 eval_batch_id 为该批次，以刷新榜单统计
    ↓ analyze_multiturn [可选] 多轮分析 → reports/multiturn_analysis.xlsx
    ↓ analyze_results / generate_report
  analysis_report.xlsx / evaluation_report.html
"""
import sys
import os

_this_file = os.path.abspath(__file__)
_evaluation_pkg_dir = os.path.dirname(_this_file)
_PROJECT_ROOT = os.path.dirname(_evaluation_pkg_dir)

if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from evaluation.pipeline import PipelineManager
from evaluation.models_from_excel import load_models_from_excel, update_availability_in_excel, try_use_cached_availability
from evaluation.config_loader import resolve_config

CONFIG = {
    # ========== 执行阶段 ==========
    # 留空则从项目 config.json 读取；无项目时需在此配置
    'stages': [
    #'test_judge_models',       # 独立运行：测裁判模型可用性并交互选择（Claude/Gemini/GPT5.2）
    #'generate_instructions',   # Stage 0: 生成原始指令批次（JSON格式）
    #'extract_instructions',    # Stage 0.5: 解析JSON，提取每条query
    #'evaluate_instructions',   # Stage 1: 可选，质量过滤（status=ok才进入后续）
    #'expand_multiturn',        # Stage 0.7: 可选，单轮→多轮对话扩展
    #'promote_to_questions',    # 将合成数据转为评测题目格式
    #'generate_criteria',       # Stage 1.5: 为 questions_400 补充 evaluation_criteria → questions_with_criteria.xlsx
    #'generate_references',     # Stage 2: 生成参考答案（本次不跑）
    #'generate_replies',        # Stage 3: 多模型生成回复（本次不跑，已有 replies_6m.xlsx）
    #'summarize_expert_assessments',  # Stage 3.5: 从回复表第2 sheet 归纳专家打分→题目表 专家洞察
    #'evaluate_replies',        # Stage 4: 用 questions_with_criteria + replies_6m 直接评估
    #'analyze_multiturn',       # 多轮分析（可选）
    'analyze_results',         # Stage 5a: 补全其他模型评估后再单独跑
    'generate_report',         # Stage 5b: 综合报告（HTML/MD），缓存后微调格式可不重跑 AI 分析
    'generate_series_reports', # Stage 5c: 厂商专项报告（Excel），可单独运行
    ],

    # ========== 基础配置 ==========
    'sysprompt_excel': "data/sysprompts.xlsx",
    'output_base_dir': "outputs",

    # ========== 裁判模型配置 ==========
    # 固定裁判：直接使用下方 provider/model，不测可用性。需要选型时在 stages 中加入 test_judge_models 或设 check_judge_before_use=True
    'provider': "openai",  # 与 config.py 中配置一致
    'model': "claude-opus-4-5 ",
    'timeout': 300,
    # 是否在每次用裁判前先测可用性并交互选择（默认 False：用上面固定裁判；True 时为主动验证选型）
    'check_judge_before_use': False,
    # 为 True 时跳过裁判验证：不测可用性、不交互选择，直接使用上方 provider/model（裁判候选均不可用时设为 True 可继续出报告）
    'skip_judge_validation': False,
    # 选型时用的裁判候选；自定义时可填 [{"model":"claude-sonnet-4-5-20250929"}, ...]，None 用 JUDGE_CANDIDATE_MODELS
    'judge_model_configs': None,

    # ========== 温度配置 ==========
    'instruction_temperature': 0.9,
    'criteria_temperature': 0.3,
    'reference_temperature': 0.7,
    'reply_temperature': 0.6,
    'evaluation_temperature': 0.3,

    # ========== 数据合成配置（Stage 0）==========
    'generation': {
        'num_batches': 12,
        'items_per_batch': 5,
        'schema_excel': None,
        'see_excel': None,
    },

    # ========== 多轮扩展配置（Stage 0.7，可选）==========
    'multiturn': {
        'min_turns': 3,
        'max_turns': 8,
        'temperature': 0.8,
    },

    # ========== 多轮分析（analyze_multiturn）==========
    # 低于此分的轮次记为「首败轮次」；会话全部轮次均>=阈值则 session_passed=True
    'multiturn_pass_threshold': 60.0,

    # ========== promote_to_questions 数据源（可选）==========
    # None 时按优先级自动选择：stage1_quality > stage0.7_multiturn > stage0.5_extraction
    # 设置后直接使用指定文件，忽略自动选择逻辑。多轮数据会同时写入 questions_multiturn.xlsx 作为多轮题库
    'promote_source_excel': None,

    # ========== 项目（project_id）==========
    # 项目编号，输出在 outputs/{project_id}/ 下。为空则输出到 output_base_dir 根下。
    'project_id': 'cif',

    # ========== 数据批次（data_batch）==========
    # 同一项目下多批次数据时使用，如 "self" 自建、"expert" 专家。文件自动带后缀：
    # questions_self.xlsx, replies_self.xlsx, analysis_report_self.xlsx 等。为空则无后缀。
    'data_batch': 'eval',

    # ========== 题目输入（仅用于首次生成 complete 时）==========
    # 当尚无 questions_complete_{batch}.xlsx 时，generate_criteria 会从 questions_{batch}.xlsx（如 questions_prof.xlsx）读取并写出到 questions_complete_{batch}.xlsx，保留原表全部列并补充 evaluation_criteria；之后 generate_references 等均在 complete 表上读写，不再分两表
    'questions_input_excel': 'questions.xlsx',

    # ========== 现成题目表（evaluate_replies / analyze_results 共用）==========
    # 为空时使用 questions_complete_{data_batch}.xlsx（唯一题目表：含专家、criteria、reference、reply1/reply2 等全部字段，由 generate_criteria/generate_references 写回同一表并保留所有列）
    'questions_excel': None,

    # ========== 回复文件路径（generate_replies/evaluate_replies/analyze/report 共用）==========
    # 为空时使用 replies/replies_{data_batch}.xlsx（如 prof→replies_prof.xlsx）
    'replies_excel': None,
    # 运行说明（第二批 prof 为例）：要看到回复表「出题人」列并算 ICC，需先跑 evaluate_replies 再跑 analyze_results。
    # 1. stages 中取消注释 'evaluate_replies'（与 analyze_results 一起跑，或先单独跑 evaluate_replies）
    # 2. evaluate_replies 会从题目表把【专家】按 qid 写入回复表「出题人」、把 ref/reply1/reply2 及专家打分注入回复表，并对空白行跑裁判
    # 3. 有专家打分的行必须有对应的 eval_* 分数（裁判评估）才能参与有效人机对，≥3 对才计算 ICC；若只注入未跑裁判则有效人机对=0

    # ========== 评估批次ID ==========
    # 本次评估写入列 eval_{batch_id}、eval_{batch_id}_raw；补齐时 overwrite_mode=skip 且 batch_id 与回复表列名对应（如列 eval_batch_1 或 eval_batch1 填 batch_1 即可，会自动对齐）
    'batch_id': "batch_2",

    # ========== 评估覆盖策略 ==========
    # 'skip'      - 跳过已有评估，只评估空白数据（默认）；可先人工填部分行再跑，只补评空白
    # 'overwrite' - 清空已有评估列，全部重新评估
    # 'new_batch' - 自动生成新 batch_id（时间戳），保留历史评估；配合 expert_qids_only 可换裁判重评专家题得双裁判对比
    'overwrite_mode': 'skip',

    # 容量参考：1200 条约 1–2 小时（max_workers=5）；12400 条约 14–21 小时（同配置），可提高 max_workers 缩短（如 8–10 约 7–12 小时，需注意 API 限流）

    # ========== 待测试模型配置 ==========
    # 方式一（推荐）：从模型表格加载，测试后更新「可用状态」，再在清单中勾选
    'use_models_from_excel': False,
    'models_excel': 'data/idealab_models.xlsx',  # 或自定义路径
    # 仅加载该 provider 时填写；None 或留空则加载表格内全部来源
    'models_excel_provider': None,
    # 方式二：在下方 reply_model_configs 中手写列表；当 use_models_from_excel 为 False 或表格不存在时使用
    # 支持：仅 model、指定 provider、同一模型多 providers
    'reply_model_configs': [],
    # 执行 generate_replies 前是否先检测可用性并交互选择参与模型（默认 True）
    'check_models_before_reply': True,

    # ========== 并发配置 ==========
    'max_workers': 20,
    'checkpoint_interval': 40,
    # 可用性测试超时，建议 >= 批量回复 timeout；若批量常报 RemoteDisconnected，可增大此处与 timeout、或降低 max_workers
    'test_timeout': 300,
    # 表格中「最后测试时间」距当前不足 N 天时，跳过 API 检测；回复模型用表格，裁判模型用 library/judge_availability_cache.json（默认 14 天）
    'availability_test_max_age_days': 14,
    # 可选：更严谨探针。默认 None 使用短句；设为较长字符串时用该内容测一次，更接近真实请求
    'test_prompt': None,

    # ========== 数据筛选配置 ==========
    'data_filters': {
        'qid_list': None,
        'model_list': None,
        'reference_type': None,
        'batch_size': None,
        # 设为 True 时，evaluate_replies 仅重评有专家打分/理由的题目（专家洞察注入裁判 prompt，可换裁判模型再测一遍得双裁判对比）
        'expert_qids_only': False,
    },

    # ========== 分析/报告配置 ==========
    # 【两套统计方案】由 analysis.stats_only 区分，互不混用：
    # 1) 评测统计（stats_only 默认 False）：以「所有模型」为核心。按题目表维度统计：source（公开/自建）、L1、difficulty_level 等多维度排名，
    #    D1–D5 约束维度 ILA、厂商排名、全景总榜单、价值题目、典型案例等；综合报告与厂商报告均基于此。同时会附带专家视角的 sheet（4_专家数据质量排名等）作为补充。
    # 2) 专家统计（stats_only=True）：以「数据质量与人的一致性」为核心。只输出一张 sheet「专家数据质量与一致性」（专家质量排名、各批次人机一致性、多批次可靠性等），
    #    不做任何模型排名/维度分析/价值题目/典型案例；generate_report 会跳过 HTML/MD。
    # 专家出题统计：评测模式下打开 analysis_report_{batch}.xlsx 的 sheet「专家数据质量与一致性」即可看每位专家出题情况；出题人若在回复表为空会按 qid 从题目表补全。
    'analysis': {
        'human_excel': None,
        'eval_batch_id': 'batch_2',  # 最新评估批次（batch_1 为历史批次）
        'replies_excel': None,
        'stats_only': False,  # 评测版本：全量统计（多维度排名、D1-D5、厂商、价值题目、典型案例）+ 专家视角 sheet；True=仅专家数据质量一张 sheet
        # 厂商专项报告（Excel）：配置后自动生成对应系列，无需交互选择。Qwen 系列匹配回复表中 model 名含 qwen 的模型
        'model_series': {'Qwen': ['qwen']},
        # 系列报告「重点模型做错题案例分析」关注的模型，需与回复表 model 列完全一致（如 qwen3.5-plus / qwen3.5）。不填则每系列取均分最低的模型
        'series_focus_model': 'qwen3.5-plus',
    },
    # 报告：若典型案例带专家评估意见，会展示专家意见并调用 LLM 生成综合评估与失分点分析；输出 evaluation_report_{timestamp}.html / .md
    'report': {
        'human_excel': None,
        'eval_batch_id': 'batch_2',  # 与 analysis 保持一致
        'top_n_cases': 30,  # 典型案例数量，多则报告洞察更丰富
        'report_title': '多模型能力评测报告',
        'replies_excel': None,
        # 通用全面报告：None=全模型统计与洞察（推荐）；定向某模型时设为 ['qwen3.5-plus'] 等
        'model_list': None,
        # 厂商系列版本递进：同系列内版本顺序与均分变化。None=不展示；如 {'Qwen': ['qwen3.5-plus','Qwen3-Max']}
        'vendor_series': None,
        # 思考模型名单：用于报告内「思考 vs 非思考」能力对比，例: ["deepseek-r1", "o1"]
        'thinking_models': None,
        # 报告分析缓存：use_report_cache=True 时可用缓存跳过重分析；force_refresh=True 时忽略缓存强制重跑
        'use_report_cache': True,
        'force_refresh': True,
        # 是否生成 HTML 报告；默认 False，仅输出 Markdown（统计分析用 Markdown 即可）
        'generate_html': False,
    },
}


def main():
    print(f"\n{'=' * 60}")
    print(f"🚀 基于约束的完整评估系统 v9.0 (项目化通用版)")
    print(f"{'=' * 60}\n")

    # 合并项目配置：project_id 有值时加载 outputs/{project_id}/config.json 并覆盖
    base_dir = CONFIG.get('output_base_dir', 'outputs')
    config = resolve_config(CONFIG, _PROJECT_ROOT, base_dir)
    if config.get('project_id'):
        out_path = f"{base_dir}/{config['project_id']}/"
        batch = (config.get('data_batch') or '').strip()
        msg = f"  📂 项目: {config['project_id']}  输出: {out_path}"
        if batch:
            msg += f"  数据批次: {batch}"
        print(msg + "\n")

    pipeline = PipelineManager(config)

    if 'test_models' in config['stages']:
        print(f"\n{'=' * 60}")
        print(f"🧪 步骤1: 测试所有模型可用性")
        print(f"{'=' * 60}\n")

        model_configs = config.get('reply_model_configs') or []
        models_excel_path = None
        if config.get('use_models_from_excel'):
            path = config.get('models_excel') or ''
            if path and not os.path.isabs(path):
                path = os.path.join(_PROJECT_ROOT, path)
            if path and os.path.exists(path):
                models_excel_path = path
                try:
                    provider = config.get('models_excel_provider')
                    model_configs = load_models_from_excel(path, provider=provider)
                    print(f"  📂 已从表格加载待测模型: {path}  共 {len(model_configs)} 个\n")
                except Exception as e:
                    print(f"  ⚠️ 从表格加载失败: {e}，改用 reply_model_configs\n")
                    model_configs = config.get('reply_model_configs') or []

        max_age_days = config.get('availability_test_max_age_days', 14)
        test_results = None
        used_cache = False
        if models_excel_path and model_configs:
            can_skip, cached_df = try_use_cached_availability(
                models_excel_path, model_configs,
                max_age_days=max_age_days,
                provider=config.get('models_excel_provider'),
            )
            if can_skip and cached_df is not None:
                test_results = cached_df
                used_cache = True
                print(f"  📋 使用表格缓存的可用状态（最后检测距今 < {max_age_days} 天），跳过 API 检测\n")

        if test_results is None:
            test_results = pipeline.test_models(
                model_configs,
                output_excel=pipeline._resolve_path(
                    pipeline.dir_manager.get_path("library", "model_availability_test.xlsx")
                )
            )
        if models_excel_path and not test_results.empty and not used_cache:
            try:
                update_availability_in_excel(
                    models_excel_path, test_results,
                    provider=config.get('models_excel_provider'),
                )
                print(f"  ✅ 已更新表格可用状态: {models_excel_path}\n")
            except Exception as e:
                print(f"  ⚠️ 写回表格失败: {e}\n")

        if test_results['available'].sum() == 0:
            print("❌ 所有模型都不可用，请检查配置")
            return

        if not config.get('provider') or not config.get('model'):
            if not pipeline.auto_select_judge_model(test_results):
                print("❌ 无法自动选择裁判模型，请在 CONFIG 中手动配置 provider 和 model")
                return

        available_models = test_results[test_results['available']]
        config['reply_model_configs'] = [
            {'provider': row['provider'], 'model': row['model'], 'enable_thinking': row.get('enable_thinking', False)}
            for _, row in available_models.iterrows()
        ]

        print(f"\n{'=' * 60}")
        print(f"✅ 模型筛选完成")
        print(f"{'=' * 60}")
        print(f"  原始模型数: {len(test_results)}  可用模型数: {len(config['reply_model_configs'])}")
        print(f"  裁判模型: {config['provider']} / {config['model']}")
        print(f"{'=' * 60}\n")

    if 'test_judge_models' in config['stages']:
        pipeline._judge_checked_this_run = False
        pipeline.execute_stage('test_judge_models')
    remaining_stages = [s for s in config['stages'] if s not in ('test_models', 'test_judge_models')]
    if remaining_stages:
        pipeline.run(remaining_stages, preserve_judge_selection='test_judge_models' in config['stages'])


if __name__ == "__main__":
    main()

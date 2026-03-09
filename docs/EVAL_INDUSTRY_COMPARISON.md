# 自动评测行业调研与系统设计水准对照

> 调研时间：2025 年 2 月。用于了解业界类似做法，并对照本系统设计水准。

---

## 一、业界类似做法概览

### 1. Rubric 驱动 + 多维度


| 工作                                   | 做法                                                                                 | 与我们的关系                                                                            |
| ------------------------------------ | ---------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| **LLM-Rubric** (Microsoft, ACL 2024) | 多维度 rubric、LLM 输出概率分布 + **小神经网络校准**预测人工分数；9 维度（自然度、简洁性、引用质量等）；相对未校准基线约 **2× 提升**。  | 我们也是**按题目的 rubric/约束**打分、多维度（D1–D5 业务理解等），但**未做**“LLM 分 → 人工分”的校准模型。              |
| **SedarEval** (ACL/EMNLP)            | **自适应的 per-question 评分标准**，模仿人类阅卷的主次标准；1000 题；专门训练的 evaluator LM 与人类打分一致性高于 GPT-4。 | 我们**按题目生成 evaluation_criteria**（约束条目），再据此打分，思路接近“每题定制标准”；裁判用通用模型，未单独训练 evaluator。 |


### 2. 专家/人工对齐


| 工作                          | 做法                                                                        | 与我们的关系                                                   |
| --------------------------- | ------------------------------------------------------------------------- | -------------------------------------------------------- |
| **IDEAlign**                | 用“选不同类”等 triplet 判断，看 LLM 标注是否与**专家**一致；LLM-as-judge 相对词/向量方法对齐提升约 9–30%。 | 我们**显式引入专家打分 + 理由**，用于排名纠偏和报告中的“专家意见 + LLM 分析”并列，强调专家逻辑。 |
| **ExpertLongBench / CLEAR** | 多领域**专家校验过的 rubric**，长文本；用 checklist（来自模型输出与参考资料）做细粒度评估。                  | 我们通过**专家意见/理由**参与报告与典型题筛选，典型题优先选“有专家意见”的题，与“专家参与评估逻辑”一致。 |
| **AlignEval**               | 通过评估“LLM 作为裁判”的能力来间接衡量生成对齐，与人类偏好排序相关。                                     | 我们更直接：在同一套题上既有**模型打分**也有**专家打分**，做一致性分析与专家纠偏排名。          |

#### 2.1 少量专家打分的「以少博大」对齐策略（调研要点）

当专家只对**少量题目/少量回复**打分时，如何让裁判模型与专家尺度对齐、泛化到其余大批量打分，业界有如下做法：

| 做法 | 工作/来源 | 核心机制 | 样本需求 | 与我们对比 |
|------|-----------|----------|----------|------------|
| **线性映射校准** | Aligning Black-box LMs (arXiv 2502.04997) | 学习 LLM 输出→人工分数的**线性映射**，无需重训；29 个任务上约 142% 一致性提升；支持零样本/少样本。 | 少量校准样本 | 我们**未做**后置线性校准；可考虑在专家覆盖题目上拟合映射，校正批量打分。 |
| **小网络组合校准** | LLM-Rubric (ACL 2024) | 多维度 LLM 预测→小前馈网络→人工总分；RMS 误差 &lt; 0.5，约 2× 提升。 | 需人工标注 | 我们按 DX_Y rubrics 逐条判；若专家覆盖足够，可引入「维度分→人工分」校准层。 |
| **锚定样例** | Langfuse、JudgeBench 等 | 在 prompt 中为各分数档提供**典型锚例**，让裁判按相同尺度对齐。 | 每档 1–2 例 | 我们**已有**：专家对部分模型的「得分+理由」作为锚点；但为**原始罗列**，未做归纳。 |
| **专家打分要点归纳** | 本系统设计目标 | 有专家评估时**先总结专家打分核心要点**，再注入裁判；确保至少复杂题与专家一致，以少博大。 | 专家少样本即可 | 我们**待增强**：当前直接注入原始专家意见；可增加 LLM 归纳步骤，提炼「本题专家关注点与尺度」。 |
| **智能采样标注** | Human calibration 研究 | 选**信息量最大**样本做人工标注，可比随机减少约 18% 标注量。 | 策略化选择 | 典型题优先有专家意见，可进一步结合难度、区分度做「应优先专家复核」推荐。 |
| **置信度与升级人工** | Trust or Escalate | 估计裁判**置信度**，低置信时升级人工。 | 校准集 | 我们**未做**；可识别「争议题」供人工抽检。 |

**小结（以少博大）**：Prompt 侧我们已用专家示范作为锚点；可进一步增强：对同一题下专家意见做**归纳总结**（打分核心要点、尺度偏好）再注入裁判。后置校准方面，业界多用线性或小型 NN 映射；我们若积累专家数据可引入。复杂题、高价值题优先保证与专家对齐，与我们典型题优先含专家意见的思路一致。


### 3. 流水线与基础设施


| 工作                                     | 做法                                        | 与我们的关系                                                    |
| -------------------------------------- | ----------------------------------------- | --------------------------------------------------------- |
| **HELM** (Stanford CRFM)               | 统一接口、多指标（准确率/效率/偏见/毒性等）、标准数据集、可复现、Web 榜单。 | 我们也是**阶段化 pipeline**（生成→标准→回复→评估→分析→报告），支持断点续跑、增量评估、多模型。  |
| **lm-evaluation-harness** (EleutherAI) | 可复现评测、YAML 配置、多后端、prompt 模板、答案提取与后处理。     | 我们通过 CONFIG + Sysprompt 表配置，阶段清晰，输出统一到 `outputs`，便于生产与复现。 |


### 4. LLM-as-Judge 的共识与局限

- **校准**：直接使用 LLM 分数往往与人工有偏差；**校准**（如 LLM-Rubric 用 NN 映射到人工）可显著提升一致性。
- **量表**：部分研究指出 **0–5 分制**下与人工的 ICC 对齐最好；我们当前为 0–100 或比例，若要做严格人机一致性研究可考虑统一量表。
- **共性局限**：LLM 裁判仍明显低于“人人一致性”；对 prompt 敏感、易偏宽松；最佳实践是**结合人类/专家**做纠偏与抽检。

---

## 本系统的任务意图、约束与评估设计（基于系统提示词）

以下基于 `data/sysprompts/` 中的全流程方案提炼，用于与业界工作做精确对照。

### 1. 任务意图设计框架

- **层级与驱动**：**L1 / L2 / L3** 任务分类（L3 为最细粒度，如信息抽取、标签分类）；可选 **任务意图表（schema）** 注入，限定本批次生成的任务类型；含**难度**、**特征描述**、**示范案例**，设计指令时需与之匹配。
- **指令结构**：每条指令由多部分构成——主任务、背景知识、规则教学、**目标期望约束**、**任务逻辑约束**、**边界范围约束**、**排版输出约束**、示范案例、输入素材。其中**目标期望**为主观（优质程度有差异）；**任务逻辑、边界范围、排版输出**为客观、必须满足。
- **约束类型表（指令生成侧）**：

| 一级类目 | 二级类目 | 定义 | 难度区间 | 主观/客观 |
|----------|----------|------|----------|------------|
| 主任务 | 直白描述/角色场景 | 宽泛要求、角色与目标 | 0–1 | 主观 |
| 规则教学 | 规则知识 | 执行任务的具体规则（细颗粒度、限于指令内可传达） | +1 | 辅助 |
| 任务逻辑 | **流程步骤** | 打分、分类、排序、抽取、链式子任务、条件判断等 | 3–5 | **客观** |
| 任务逻辑 | **边界范围** | 主题、集合、时间、情感、数值等范围限制 | 1–2 | **客观** |
| 任务逻辑 | **数量篇幅** | 个数、条数、长度要求 | 1–2 | **客观** |
| 输出排版 | **格式形式** | 表格、JSON、Markdown 等 | 1–3 | **客观** |
| 示范案例 / 输入素材 | 任务示范/输出示范/输入素材 | 演示与待处理材料 | +1–5 | 辅助 |

- **设计原则**：客观约束 3–10 个为主、主观最多 3 个；回复要具体可检验；难度上流程步骤（简单子任务→3 分、链条式→4 分、条件判断→5 分）、边界/数量/格式在 1–3 分区间。
- **题目质量评估（instruction_quality_evaluation）**：在指令生成后对单题做**约束识别与难度评估**，约束类型体系包含**教学约束、素材约束、流程步骤、格式输出、边界范围、数量篇幅**，并区分显式/隐式、客观/可评估主观/难以评估主观；过滤规则（如客观约束数 &lt; 2、独立任务堆积、严重问题约束）保证题目可评估且有区分度。

### 2. Rubric（评分标准）设计逻辑

- **定位**：评分标准生成阶段（criteria_generation）明确采用 **AdvancedIF Rubrics 生成器**，将「用户指令 + 人工评分点」整理为**可直接用于评审的检查清单**，不改变人工评分点的核心语义与判断逻辑。
- **MCOAB 原则**：**M**ECE（不重复、覆盖要点）、**C**onstructive（具体考点、无宽泛表述）、**O**bjective（可验证）、**A**tomic（一检查点一事）、**B**inary（仅 PASS/FAIL，通过多个二值检查点形成质量梯度）。
- **五维度框架（D1–D5）**：与 AdvancedIF 对齐，代码中 `rubric_dimension_analysis` 的维度标签与之一致。

| 维度 | 职责 | 占比 | 口诀 | 检查点数量 |
|------|------|------|------|------------|
| **D1 业务场景理解** | 仅在有理解分歧时启用 | 0–10% | — | 0–2 |
| **D2 操作执行逻辑** | 是否做了（完整性、顺序性） | 15–20% | 缺了→D2 | 3–5 |
| **D3 边界范围限制** | 是否越界（禁止项、来源、范围、数量） | 20–25% | 超了→D3 | 4–6 |
| **D4 格式与形式化要求** | 形式规范（结构、标识符、排版） | 10–15% | 歪了→D4 | 2–4 |
| **D5 内容质量** | 做得对不对（准确性、深度） | 40–55% | 错了→D5 | 8–15 |

- **检查点数量分级**：简单任务 15–20、中等 20–25、复杂 25–30；上限 30、下限 15。
- **E/I/F 标记**：(E) 直接来自人工/指令、(I) 允许的补充、(F) 致命项；致命项比例约 20–40%（核心任务可放宽）。输出格式为 **## AdvancedIF Rubrics**，**### D2/D3/D4/D5**，每条 **Dx_Y: [检查点]？(E/I)(F)**。

### 3. 回复评估逻辑

- **角色与依据**：**指令遵循审计员**；**DX_Y rubrics 为唯一判定标准**；参考回复可选、若与 rubrics 冲突以 rubrics 为准。
- **二元判定**：每条 rubric 仅 **PASS** 或 **FAIL**；任何偏差（缺失/错误/不全/不一致/格式不符）均判 FAIL；FAIL 时需给出**可验证的证据说明**（不写主观评价）。
- **致命项（F）**：任一致命项 FAIL → **SATISFIED_ALL_REQUIREMENTS = "NO"**；所有条目 PASS → "YES"。
- **得分**：`passed / total`，**FINAL_SCORE** 格式为 `"{score}% ({passed}/{total})"`（如 `"89% (24/27)"`）；**FATAL_FAILURES** 为所有 FAIL 且为 (F) 的条目编号数组。
- **输出结构**：严格 JSON，含 **FINAL_SCORE**、**SATISFIED_ALL_REQUIREMENTS**、**FATAL_FAILURES**、**rubrics_check**（每 Dx_Y 对应 `result` + `reason`）。下游从 `rubrics_check` 解析并按 D1–D5 汇总通过率，用于报告中的维度得失分。

### 4. 报告分析要求

- **输入**：题目内容、评分标准（Rubric）、各模型得分、评估详情（逐条 PASS/FAIL）、专家意见（可选）。
- **输出**：【综合评估】≤100 字；【失分点分析】结合具体 Rubric 条目（如 D5_3、D3_1），区分形式性失分与实质性失分；**如有专家意见，优先以专家意见为准**。

### 与调研工作的对应关系（小结）

- **AdvancedIF**：本系统评分标准即 **AdvancedIF Rubrics 生成器**，五维度 D1–D5、二值检查点、致命项 (F)、输出格式与 AdvancedIF 对齐；回复评估阶段按 DX_Y 逐条 PASS/FAIL 并输出 rubrics_check，与“rubric 既用于评测”一致。
- **指令遵循类（ComplexBench / CFbench / FollowBench / InFoBench）**：指令生成侧约束类型（流程步骤、边界范围、数量篇幅、格式形式）与上述基准的约束分类同向；题目质量评估侧有更细的约束类型与难度公式；Rubric 侧将“多约束”落实为 D2–D5 下的原子检查点，与“多约束 + 逐条判定”一致。
- **专家对齐**：专家意见在报告分析中**优先**，典型题优先选有专家意见的题，与 IDEAlign/ExpertLongBench 的“专家参与评估逻辑”一致。

---

## 二、本系统设计水准简要评估

### 优势（与业界对齐或略超前）

1. **全链路、阶段化**
  从题目生成 → 评分标准生成 → 参考答案 → 回复采集 → **按 rubric 评估** → 统计分析 → **报告（含专家 + LLM）**，阶段清晰、可断点续跑，与 HELM/lm-eval 的 pipeline 思路一致，且更贴近“业务题 + 专家”场景。任务意图、约束类型与 Rubric 设计均在系统提示词中显式定义（见上文「本系统的任务意图、约束与评估设计」）。
2. **Per-question 评分标准 + 多维度（AdvancedIF 对齐）**
  评分标准生成采用 **AdvancedIF Rubrics 生成器**，每题输出 D1–D5 下的原子二值检查点（MCOAB、E/I/F 标记）；回复评估按 DX_Y 逐条 PASS/FAIL，输出 rubrics_check 并汇总维度通过率。与 SedarEval 的“每题定制标准”、LLM-Rubric 的“多维度”同向，且与 AdvancedIF 的 rubric 形态与五维度框架一致。
3. **专家深度参与**
  专家打分与理由用于：排名纠偏、报告中的“典型案例 + 专家意见 + LLM 分析”、典型题优先选“有专家意见”的题。这与 IDEAlign/ExpertLongBench 强调的“专家对齐”一致，且落地到可操作的数据流和报告形态。
4. **生产可用**
  检查点保存、增量评估、按 qid/model 排序、路径与配置统一（如 `outputs`）、补分脚本（仅从 raw 解析不重调 API）等，适合长时间、大规模回复评估。
5. **报告信息密度高**
  除总分与排名外，提供：维度得失分、厂商版本递进、思考 vs 非思考对比、典型题与“本题最佳”差距、专家意见与 LLM 分析并列，便于人工微调和决策。

### 可改进方向（与顶会/工业界对比）


| 方向                | 说明                                                                   |
| ----------------- | -------------------------------------------------------------------- |
| **校准**            | 若需更高“与专家/人工一致”，可引入小规模标注 + 简单校准模型（如 LLM-Rubric 式、线性映射），将 LLM 分映射到人工分或置信区间。 |
| **专家要点归纳** | 有专家评估时，先对同一题下专家意见做**归纳总结**（打分核心要点、尺度偏好），再注入裁判 prompt，减少噪音、聚焦关键对齐信号（见 2.1）。 |
| **裁判一致性**         | 可增加：同一回复多 prompt/多裁判、方差或置信区间，用于识别“争议题”或需人工复核的题。                      |
| **量表与指标**         | 若发表或对外对标，可统一评分量表（如 0–5）并报告 ICC/Kappa 等，与文献可比。                        |
| **Evaluator 专用化** | 若有充足专家标注数据，可考虑对评估任务微调/专门化裁判模型（类似 SedarEval），进一步提升与专家一致性。             |


---

## 三、结论

- **业界是否有类似做法**：有。本系统在系统提示词中**显式采用 AdvancedIF Rubrics 与 D1–D5 五维度框架**，任务意图与约束类型（流程步骤/边界范围/数量篇幅/格式形式等）有完整定义，与 Rubric/约束驱动、per-question 标准、多维度、专家/人工对齐、阶段化 pipeline 在 ACL/EMNLP 与开源框架中的做法一致；**指令遵循**类（AdvancedIF、IFEval、ComplexBench、CFbench、FollowBench、InFoBench、EIFBench、MultiChallenge 等）与我们的“题目 + 约束/标准 → 按条评估”同属一条技术线，且在**专家参与报告与典型题选择**上结合得较紧。
- **系统设计水准**：在全链路自动评测场景下，架构清晰、rubric 与维度完整、专家纠偏与报告可用、支持大规模增量运行。若后续要做严格人机一致性研究或对外对标，可在校准、量表、置信度与裁判一致性上再做一轮增强。

---

## 参考文献与链接（示例）

**Rubric / 多维度 / 校准 / 以少博大**
- Aligning Black-box LMs with Human Judgments (线性映射校准): [arxiv.org/abs/2502.04997](https://arxiv.org/abs/2502.04997)
- LLM-Rubric: [arxiv.org/abs/2501.00274](https://arxiv.org/abs/2501.00274), [github.com/microsoft/LLM-Rubric](https://github.com/microsoft/LLM-Rubric)
- Trust or Escalate (置信度与升级人工): [arxiv.org/abs/2407.18370](https://arxiv.org/abs/2407.18370)
- SedarEval: [arxiv.org/abs/2501.15595](https://arxiv.org/abs/2501.15595)
- IDEAlign (expert alignment): [arxiv.org/abs/2509.02855](https://arxiv.org/abs/2509.02855)
- HELM: [crfm-helm.readthedocs.io](https://crfm-helm.readthedocs.io)
- lm-evaluation-harness: [github.com/EleutherAI/lm-evaluation-harness](https://github.com/EleutherAI/lm-evaluation-harness)
- Grading scale & ICC: “Grading Scale Impact on LLM-as-Judge: Human-LLM Alignment Is Highest on 0-5 Scale”

**指令遵循（Instruction Following）**
- AdvancedIF: [arxiv.org/abs/2511.10507](https://arxiv.org/abs/2511.10507), [Meta AI](https://ai.meta.com/research/publications/rubric-based-benchmarking-and-reinforcement-learning-for-advancing-llm-instruction-following/)
- IFEval: [arxiv.org/abs/2311.07911](https://arxiv.org/abs/2311.07911), [google/IFEval (Hugging Face)](https://huggingface.co/datasets/google/IFEval), [google-research/instruction_following_eval](https://github.com/google-research/google-research/tree/master/instruction_following_eval)
- ComplexBench: [arxiv.org/abs/2407.03978](https://arxiv.org/abs/2407.03978), [thu-coai/ComplexBench](https://github.com/thu-coai/ComplexBench), NeurIPS 2024 Datasets and Benchmarks
- EIFBench: [ACL Anthology EMNLP 2025](https://aclanthology.org/2025.emnlp-main.1059/)
- MultiChallenge: [arxiv.org/abs/2501.17399](https://arxiv.org/abs/2501.17399), [Scale AI MultiChallenge](https://scale.com/leaderboard/multichallenge)
- InFoBench: [arxiv.org/abs/2401.03601](https://arxiv.org/abs/2401.03601), [InfoBench (GitHub)](https://github.com/qinyiwei/InfoBench)
- CFbench: [ACL 2025](https://aclanthology.org/2025.acl-long.1581/), [pku-baichuan-mlsystemlab/cfbench](https://github.com/pku-baichuan-mlsystemlab/cfbench)
- FollowBench: [arxiv.org/abs/2310.20410](https://arxiv.org/abs/2310.20410), [ACL 2024](https://aclanthology.org/2024.acl-long.257/), [FollowBench (GitHub)](https://github.com/YJiangcm/FollowBench)


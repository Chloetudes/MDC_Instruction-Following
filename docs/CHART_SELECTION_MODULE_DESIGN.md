# 统计与图表选型模块设计 — 敏捷评测场景

> 目标：将「用户自然语言 → 分析需求 → 维度识别 → 数据特性 → 图表选型 → 制图」链路封装为可复用的自动化模块，支持 Markdown 报告优先输出。

---

## 一、评测场景下的通用维度与字段

### 1.1 必选/常见字段（与 data_loader、ranking 一致）

| 字段/维度 | 类型 | 说明 | 数据特性 |
|----------|------|------|----------|
| **L1 / L2 / L3** | 分类 | 三层能力/意图分类体系 | 离散、有序层级、类别数 5–50 |
| **source / source_group** | 分类 | 数据来源（公开/自建、H/R/HM/M） | 离散、类别数 2–8 |
| **difficulty_level** | 分类 | 难度等级 E/D/C/B/A/S | 有序离散、类别数 6 |
| **D1–D5** | 数值 | 维度通过率（业务理解/流程步骤/边界范围/格式形式/内容质量） | 连续 [0,100] |
| **model** | 分类 | 模型名称 | 离散、类别数 5–50 |
| **eval_score** | 数值 | 主分数 | 连续 [0,100] |

### 1.2 辅助字段

| 字段 | 类型 | 说明 |
|------|------|------|
| 出题人 | 分类 | 若有 |
| vendor | 分类 | 厂商（模型归属） |
| ranking_score | 数值 | 维度加权主分数 |

---

## 二、自然语言需求 → 客观分析需求（翻译层）

### 2.1 常见表述与映射

| 用户表述（示例） | 分析需求 |
|-----------------|----------|
| "各模型整体表现如何" | 维度：model；指标：eval_score；聚合：mean；图表：柱状图 |
| "哪个意图类型最难" | 维度：L2 或 L3；指标：eval_score；聚合：mean + std；图表：柱状图或箱线图 |
| "模型在不同难度上的表现" | 维度：difficulty_level × model；图表：热力图 |
| "各维度通过率对比" | 维度：D2–D5 × model；图表：热力图或雷达图 |
| "公开 vs 自建数据区分度" | 维度：source_group × model；图表：热力图或散点图 |
| "哪个模型波动大" | 维度：model；指标：eval_score；聚合：std；图表：柱状图带误差条 |
| "分数分布" | 维度：eval_score；图表：直方图或箱线图 |

### 2.2 翻译接口（可扩展）

```python
# 伪代码
def translate_nl_to_analysis_intent(nl_query: str) -> AnalysisIntent:
    """
    输入：用户自然语言
    输出：AnalysisIntent {
        primary_dim: str,      # 主分析维度 L1/L2/L3/source/difficulty/model
        secondary_dim: str,    # 可选，如 model
        metric: str,           # eval_score, pass_rate, ...
        agg: str,              # mean, std, count, ...
        chart_preference: str, # 用户偏好的图表类型（可选）
    }
    """
    # 可先用规则/关键词匹配；复杂场景再用 LLM
```

---

## 三、维度 → 数据特性 → 图表选型

### 3.1 数据特性分类

| 特性 | 说明 | 示例 |
|------|------|------|
| 单变量-连续 | 一个连续指标 | eval_score 分布 |
| 单变量-离散 | 一个分类维度 | L1 各类别题目数 |
| 双变量-分类×数值 | 分类 × 分数 | model × mean(eval_score) |
| 双变量-分类×分类 | 两个分类 | L1 × model |
| 多变量-数值 | 多个连续维度 | D2–D5 × model |
| 对比-分组 | 分组对比 | 公开 vs 自建 |

### 3.2 图表选型规则表

| 分析意图 | 主维度 | 数据特性 | 推荐图表 | 备选 |
|----------|--------|----------|----------|------|
| 模型整体排名 | model | 分类×数值(mean) | 柱状图 | — |
| 模型排名+波动 | model | 分类×数值(mean±std) | 柱状图+误差条 | 箱线图 |
| 意图类型表现 | L1/L2/L3 | 分类×数值 | 柱状图 | 热力图 |
| 意图×模型 | L1/L2/L3 × model | 分类×分类×数值 | 热力图 | 分组柱状图 |
| 维度通过率×模型 | D2–D5 × model | 多维度×分类 | 热力图 / 雷达图 | 分组柱状图 |
| 难度×模型 | difficulty × model | 分类×分类×数值 | 热力图 | 箱线图 |
| 来源×模型 | source × model | 分类×分类×数值 | 热力图 / 散点图 | — |
| 分数分布 | eval_score | 连续单变量 | 直方图 / 箱线图 | — |
| 公私域对比 | source_group × model | 分组对比 | 散点图(公均分, 自均分) | 柱状图 |
| 格式 vs 逻辑 | D4 × D2 | 两连续变量 | 散点图 | — |

### 3.3 选型接口

```python
def select_chart(
    primary_dim: str,
    metric: str = "eval_score",
    secondary_dim: str = None,
    data_profile: dict = None,  # 实际数据的统计摘要
) -> ChartConfig:
    """
    输入：主维度、指标、可选次维度、数据摘要
    输出：ChartConfig {
        chart_type: str,   # bar, heatmap, radar, box, scatter, histogram
        x_dim: str,
        y_dim: str,
        color_dim: str,
        title: str,
        mermaid_or_image: str,  # "mermaid" | "image"
    }
    """
```

---

## 四、Markdown 优先的图表输出

### 4.1 输出形式

| 图表类型 | Markdown 输出 | 说明 |
|----------|---------------|------|
| 柱状图 | 图片 `![标题](figures/bar_xxx.png)` | matplotlib/plotly 保存 PNG |
| 热力图 | 图片 `![标题](figures/heatmap_xxx.png)` | 同上 |
| 雷达图 | 图片 | 同上 |
| 箱线图 | 图片 | 同上 |
| 散点图 | 图片 | 同上 |
| 直方图 | 图片 | 同上 |
| 简单流程图 | Mermaid 代码块 | 无需渲染，GitHub 等直接展示 |

### 4.2 与报告流水线结合

```
load_and_preprocess()
    ↓
根据报告章节/用户需求 → 生成 AnalysisIntent 列表
    ↓
for each intent:
    select_chart(intent) → ChartConfig
    render_chart(data, ChartConfig) → 图片路径 或 Mermaid 字符串
    写入 Markdown 段落
    ↓
LLM 文本分析/总结（可注入图表路径或摘要）
    ↓
组装完整 Markdown 报告
    ↓
[可选] 转为 HTML
```

---

## 五、模块结构建议

```
evaluation/analysis/
  chart_selection/
    __init__.py
    intent_translator.py   # 自然语言 → AnalysisIntent（规则 + 可选 LLM）
    chart_selector.py      # 维度+数据特性 → ChartConfig
    chart_renderer.py      # ChartConfig + data → 图片 / Mermaid
    data_profiler.py       # 数据 → 统计摘要（data_profile）
  report/
    report_writer_md.py    # 调用 chart_selection，生成 Markdown（含图片引用）
```

### 5.1 核心接口

```python
# chart_selector.py
CHART_RULES = [
    {"dims": ["model"], "metric": "eval_score", "agg": "mean", "chart": "bar"},
    {"dims": ["L1", "model"], "chart": "heatmap"},
    {"dims": ["D2", "D3", "D4", "D5"], "per": "model", "chart": "heatmap"},
    {"dims": ["D2", "D3", "D4", "D5"], "per": "model", "chart": "radar", "when": "model_count <= 10"},
    {"dims": ["difficulty_level", "model"], "chart": "heatmap"},
    {"dims": ["source_group", "model"], "chart": "heatmap"},
    {"dims": ["eval_score"], "chart": "histogram"},
    # ...
]

def select_chart(intent: AnalysisIntent, data_profile: dict) -> ChartConfig: ...
```

```python
# chart_renderer.py
def render_to_image(data: pd.DataFrame, config: ChartConfig, output_path: str) -> str: ...
def render_to_mermaid(data: pd.DataFrame, config: ChartConfig) -> str: ...
```

---

## 六、与现有代码的对接

| 现有模块 | 对接方式 |
|----------|----------|
| `data_loader.load_and_preprocess` | 输出 `replies_with_question` 含 L1/L2/L3、source、difficulty、D2–D5 等 |
| `ranking.py` | 已有的 `analyze_l1_dimension` 等可输出 DataFrame → 作为 chart_renderer 输入 |
| `rubric_dimension_analysis` | `model_dimension_df`、`dimension_pivot_df` 直接用于维度热力图 |
| `report_writer_html._build_data_viz_charts` | 逻辑迁移到 chart_renderer，输出 PNG 而非 JS |
| `report_writer_md` | 增加图表段落，插入 `![...](figures/xxx.png)` |

---

## 七、迭代与扩展

1. **新增维度**：在 `CHART_RULES` 增加规则，在 `data_profiler` 识别新列
2. **新增图表类型**：在 `chart_renderer` 增加分支
3. **自然语言扩展**：在 `intent_translator` 增加关键词或调用 LLM
4. **项目级配置**：`outputs/{project_id}/chart_rules.yaml` 覆盖默认规则

---

---

## 八、实现状态（已落地）

- `evaluation/analysis/chart_selection/`
  - `data_profiler.py`：数据画像
  - `chart_selector.py`：选型规则与 ChartConfig
  - `chart_renderer.py`：matplotlib 渲染 bar/heatmap/radar/box/histogram → PNG
- `report_writer_md.py`：在「三、模型能力概览」下增加「3.1.1 数据可视化」，自动生成图表并嵌入 Markdown
- 依赖：`matplotlib>=3.5.0` 已加入 requirements.txt

`intent_translator`（自然语言→分析意图）留作后续扩展，当前由选型规则直接根据数据画像产出图表列表。

---

*文档版本：v1，随实现更新。*

# 人工标注表配置说明 — 用于人工打分结果验证

人工标注表用于**人机一致性**、**标注员组内一致性**、**模型排名与人工排名对比**等验证分析。配置后，统计分析（analyze_results）和报告（generate_report）会自动读取并产出对应 sheet / 章节。

---

## 一、文件放哪里

- **推荐**：放在项目下任意可访问路径，例如：
  - `outputs/human_annotation.xlsx`
  - `data/human_scores.xlsx`
- 路径可以是**相对路径**（相对当前工作目录，即运行 `python evaluation/main.py` 时的 cwd）或**绝对路径**。

---

## 二、在配置里指定路径

在 **evaluation/main.py** 的 `CONFIG` 中，为**分析**和**报告**两处都填上同一个路径（若只跑分析或只跑报告，填对应一处即可）：

```python
'analysis': {
    'human_excel': 'outputs/human_annotation.xlsx',  # 或绝对路径，如 '/path/to/human_annotation.xlsx'
    'eval_batch_id': 'batch_2',
    ...
},
'report': {
    'human_excel': 'outputs/human_annotation.xlsx',  # 与 analysis 保持一致
    ...
},
```

保存后，运行 **analyze_results** 或 **generate_report** 时会自动加载该表并做人机一致性等验证。

---

## 三、表格格式要求

### 1. 必列

| 列名 | 说明 |
|------|------|
| **qid** | 题目 ID，与题目表、回复表一致（若表里是 `QID` 也会被自动识别并当作 qid） |

### 2. 可选但建议有

| 列名 | 说明 |
|------|------|
| **model** | 模型名；有此项时按 (qid, model) 与人机一致性对齐；没有则按 qid 聚合，部分分析会受限 |

### 3. 标注员分数列（必含至少一组）

系统通过列名**自动识别标注员**：列名以 `ann` 开头且包含 `score` 的列会被视为该标注员的分数。

- **单分数列**：`ann1_score`、`ann2_score`、…  
  每列一个标注员对该行 (qid, model) 的分数。
- **多模型分数列**：`ann1_score_m1`、`ann1_score_m2`、…  
  同一标注员对多个模型的分数时，会先按行或列聚合成该标注员的 `ann1_avg_score` 再参与计算。

可选辅助列（不影响核心验证，用于展示）：

- `ann1_name`、`ann2_name`：标注员姓名或编号
- `ann1_raw_eval`、`ann2_raw_eval`：原始评语文本

### 4. 示例结构（按 (qid, model) 一行一条）

| qid | model   | ann1_score | ann2_score | ann1_name | ann2_name |
|-----|---------|------------|------------|-----------|-----------|
| 1   | model-A | 85         | 82         | 张三      | 李四      |
| 1   | model-B | 78         | 80         | 张三      | 李四      |
| 2   | model-A | 90         | 88         | 张三      | 李四      |

同一 (qid, model) 可有多名标注员（ann1、ann2…），系统会算各标注员均分、组内一致性，并与模型打分做对比。

---

## 四、验证会产出什么

配置正确且表格式符合上述要求时：

1. **Excel 分析报告**（analyze_results 生成的 `analysis_report.xlsx`）中会出现：
   - **2_每道题排名一致性**：每道题上人工排名 vs 模型排名的一致性
   - **2_人机一致性排名**：人机打分/排名对比
   - **3_组内一致性成绩单**：标注员之间一致性
   - **3_与专家一致性**：若同时有专家数据
   - **4_模型专家一致性** / **4_模型与专家一致性排名** 等（与专家数据一起时）

2. **HTML/MD 报告**（generate_report）中会有：
   - **一致性分析**：人机一致性、标注员组内一致性、模型排名与人工排名一致性等说明与表格。

若未配置 `human_excel` 或文件不存在，这些与人工相关的 sheet/章节会跳过或显示“无人工标注数据”。

---

## 五、常见问题

- **Q：表里是 QID 不是 qid？**  
  A：可以，程序会自动把列名 `QID` 识别为 `qid`。

- **Q：没有 model 列可以吗？**  
  A：可以加载，但按 (qid, model) 的人机一致性、排名对比等需要 model 列与回复表对齐；没有 model 时部分分析会为空或仅按题目聚合。

- **Q：路径写相对还是绝对？**  
  A：相对路径按**运行 main.py 时的当前工作目录**解析；建议用 `outputs/human_annotation.xlsx` 这类相对路径，并把文件放在项目下对应位置。

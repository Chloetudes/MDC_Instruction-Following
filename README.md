# 复杂指令遵循评测框架

基于约束的中文复杂指令跟随能力评测框架，支持全流程自动化：**题目与评分标准 → 参考答案 → 多模型回复 → 裁判评分 → 维度化分析（D1–D5）→ 可视化报告**。适用于自建/公开数据混合、按来源切换统计口径（公开/自建/全量），并可输出维度失分率、L1 失分特征与数据合成建议。

---

## 特性

- **阶段化 Pipeline**：可配置阶段（生成标准、参考、回复、评估、分析、报告），支持断点续跑与缓存。
- **五维度评分（D1–D5）**：业务理解、流程步骤、边界范围、格式形式、内容质量；支持从裁判原始输出（eval_raw）解析检查点并汇总失分率。
- **统计口径可切换**：全量 / 仅公开 / 仅自建（含 R）/ 自定义 source 筛选，便于对比公开基准与自建难度。
- **项目化配置**：以 `outputs/<project_id>/config.json` 为主配置入口，无需改代码即可切换批次与报告参数。

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API Key（裁判与回复模型）

**请勿提交真实 Key 到仓库。**

```bash
cp config.example.py config.py
# 编辑 config.py，将 YOUR_*_API_KEY_HERE 替换为真实 key，或使用环境变量
```

支持通过环境变量配置，例如：`OPENAI_API_KEY`、`DASHSCOPE_API_KEY`、`OPENROUTER_API_KEY`。  
`config.py` 已加入 `.gitignore`，不会被提交。

### 3. 准备数据与项目配置

- **系统提示词**：本仓库不包含真实提示词。请复制占位示例并填写：`cp -r data/sysprompts.example data/sysprompts`，再编辑 `data/sysprompts/*.txt`。详见 [data/sysprompts.example/README.md](data/sysprompts.example/README.md)。  
- 题目表：至少包含 `qid`、`query`，推荐含 `L1`、`source`。  
- 回复表：至少包含 `qid`、`model`、`reply`；若已跑过评测，需有 `eval_<batch_id>` 与 `eval_<batch_id>_raw`。  
- 数据格式详见：[docs/DATA_SCHEMA.md](docs/DATA_SCHEMA.md)

在项目目录下创建配置（示例）：

```bash
mkdir -p outputs/my_project
cp config.example.json outputs/my_project/config.json
# 按需修改 outputs/my_project/config.json（如 project_id、data_batch、eval_batch_id、stages）
```

将题目表、回复表放到 `outputs/my_project/questions/`、`outputs/my_project/replies/`，或在 `config.json` 中指定 `questions_excel`、`replies_excel` 路径。

### 4. 运行

**推荐入口**（使用项目 config）：

```bash
python -m evaluation.main
```

程序会读取 `evaluation/main.py` 中的默认 CONFIG，若存在 `project_id`，则加载 `outputs/<project_id>/config.json` 并覆盖，按其中 `stages` 依次执行（如 `analyze_results`、`generate_report`）。

---

## 目录结构（公开版）

```
├── config.example.py      # 配置模板，复制为 config.py 并填写 key
├── config.example.json    # 项目配置示例
├── evaluation/
│   ├── main.py            # 入口与默认 CONFIG
│   ├── config_loader.py   # 项目 config 合并与阶段解析
│   ├── pipeline.py        # 阶段调度
│   ├── analysis/          # 统计、排名、报告生成
│   └── stages/            # 各阶段实现（评估、报告等）
├── outputs/               # 输出目录（不提交真实数据）
│   └── .gitkeep
├── docs/
│   ├── CONFIG_PLAYBOOK.md # 配置与流程速查
│   ├── STAGES_REFERENCE.md# 阶段列表与 preset
│   ├── DATA_SCHEMA.md     # 题目/回复表字段说明
│   └── ...
├── requirements.txt
└── README.md
```

---

## 评测流程概览

```
题目表(questions) → [生成标准/参考] → 回复表(replies) → [裁判评估] → eval_* / eval_*_raw
       → 统计分析(analyze_results) → 报告(generate_report) → Markdown/HTML
```

统计与报告支持：综合榜单、维度失分率（D1–D5）、L1 失分特征、D5×L1 内容质量分布、数据合成建议等。  
阶段与 preset 完整列表见：[docs/STAGES_REFERENCE.md](docs/STAGES_REFERENCE.md)  
配置说明见：[docs/CONFIG_PLAYBOOK.md](docs/CONFIG_PLAYBOOK.md)。

---

## 文档索引

| 文档 | 说明 |
|------|------|
| [docs/SYSTEM_OVERVIEW.md](docs/SYSTEM_OVERVIEW.md) | **系统流程与架构概览**（推荐先读） |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 全链路架构与模块设计 |
| [docs/CONFIG_PLAYBOOK.md](docs/CONFIG_PLAYBOOK.md) | 配置与流程速查 |
| [docs/STAGES_REFERENCE.md](docs/STAGES_REFERENCE.md) | 阶段列表与 preset 代号 |
| [docs/DATA_SCHEMA.md](docs/DATA_SCHEMA.md) | 题目表、回复表字段说明 |
| [docs/USER_GUIDE.md](docs/USER_GUIDE.md) | 使用指南 |

---

## 只放方法论分享到 GitHub

本仓库按「只放方法论」整理：不含真实 API Key、不含业务数据与评测结果。  

- **发布前自检**：[docs/SHARING_GITHUB.md](docs/SHARING_GITHUB.md) — 自检项与取消不应提交的暂存文件。  
- **推送到你的仓库**：[docs/PUSH_TO_YOUR_GITHUB.md](docs/PUSH_TO_YOUR_GITHUB.md) — 填入你的 GitHub 仓库地址并按步骤执行即可推送。

---

## 许可证

本项目采用 [MIT License](LICENSE)。使用与二次开发时请保留版权与许可说明。

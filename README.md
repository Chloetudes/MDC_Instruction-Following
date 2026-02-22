# 多模型能力评测系统

基于约束的中文复杂指令跟随能力评测框架，支持全流程自动化：指令合成 → 评分标准生成 → 参考答案生成 → 多模型作答 → 裁判评分 → 可视化报告。

---

## 快速开始

### 第一步：安装依赖

```bash
pip install -r requirements.txt
```

### 第二步：配置 API Key

打开 `config.py`，**至少配置一个 provider** 的 API Key（用于裁判模型）：

```python
# 推荐配置其中一个：
"idealab": ProviderConfig(
    api_key="你的真实 API Key",   # ← 替换这里
    ...
),

# 或者：
"routify_claude": ProviderConfig(
    api_key="你的真实 API Key",   # ← 替换这里
    ...
),
```

然后在 `evaluation/main.py` 的 `CONFIG` 中确认裁判模型和被测模型：

```python
CONFIG = {
    'provider': "idealab",           # 裁判模型的 provider
    'model': "claude_sonnet4_5",     # 裁判模型名称
    'reply_model_configs': [
        {"model": "qwen3-max"},      # 被测模型列表
        {"model": "gpt-4o"},
    ],
}
```

### 第三步：自检

```bash
python agent_runner.py --mode check
```

看到 `✅ 自检通过` 即可继续。

### 第四步：运行评测

```bash
# 测试模式（验证全流程，约 5-10 分钟）
python agent_runner.py --mode test

# 完整评测（正式运行，约 2-8 小时）
python agent_runner.py --mode full

# 中途中断后续跑
python agent_runner.py --mode resume
```

---

## 目录结构

```
├── config.py                    # API Key 和模型配置（需要修改）
├── evaluation/main.py           # 评测参数配置（需要修改）
├── agent_runner.py              # 运行入口
├── requirements.txt             # Python 依赖
├── data/
│   └── sysprompts/              # 各阶段系统提示词（已内置）
│       ├── instruction_generation.txt
│       ├── criteria_generation.txt
│       ├── reference_generation.txt
│       ├── reply_evaluation.txt
│       └── ...
└── outputs/evaluation/          # 所有输出文件（自动创建）
    ├── questions/               # 评测题目
    ├── replies/                 # 各模型回复和评分
    └── reports/                 # 最终报告（HTML + Excel）
```

---

## 评测流程

```
指令生成 → 指令提取 → 质量过滤（可选）→ 多轮扩展（可选）
    → 评分标准生成 → 参考答案生成 → 多模型作答 → 裁判评分
    → 统计分析 → 可视化报告
```

最终产物：
- `outputs/evaluation/reports/evaluation_report_*.html` — 可视化评测报告
- `outputs/evaluation/reports/analysis_report.xlsx` — 统计分析数据

---

## 详细文档

- **操作指南**：[AGENT_GUIDE.md](AGENT_GUIDE.md) — 各阶段详解、常见报错处理
- **架构设计**：[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- **使用指南**：[docs/USER_GUIDE.md](docs/USER_GUIDE.md)

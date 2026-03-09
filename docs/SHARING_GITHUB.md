# 如何把本项目以「只放方法论」分享到 GitHub

本仓库已按「只放方法论」整理：**不包含真实 API Key、不包含业务数据与评测结果**，只保留框架代码、文档与示例配置，方便他人复现与二次开发。

---

## 一、发布前自检（必做）

### 1. 确认这些文件**从未**被提交

| 内容 | 已在 .gitignore |
|------|-----------------|
| `config.py`（真实 API Key） | ✅ |
| `outputs/`（项目数据与报告） | ✅ |
| `evaluation/outputs/`（评测中间结果） | ✅ |
| `*.xlsx`（题目/回复/业务表） | ✅ |
| `data/sysprompts/`（系统提示词） | ✅ |
| `.env`、`.report_cache/`、`.cursor/` | ✅ |

若之前误提交过 `config.py` 或含敏感数据的文件，需要从历史中删除后再推送（见下文「若曾误提交敏感文件」）。

### 2. 取消已暂存但不应提交的文件

若你执行过 `git add .`，可能把 `outputs/`、`data/*.xlsx` 等也加进了暂存区。**.gitignore 只对「未跟踪」文件生效**，已暂存的文件需要手动取消：

```bash
# 在项目根目录执行
cd /path/to/Evaluation_xr

# 取消 outputs、evaluation/outputs、data 下 xlsx 等（保留 .gitkeep 与 README）
git restore --staged outputs/
git restore --staged evaluation/outputs/
git restore --staged data/*.xlsx
git restore --staged "data/~$"*
# 若 .cursor 曾被 add，也取消
git restore --staged .cursor/

# 再次确认：不应出现 config.py、outputs 下业务文件、evaluation/outputs
git status
```

确认 `git status` 里没有 `config.py`、没有 `outputs/` 下的项目数据、没有 `evaluation/outputs/` 下的题目/回复/报告。

---

## 二、推送到 GitHub 的步骤

### 1. 在 GitHub 上建新仓库

- 打开 https://github.com/new
- Repository name 例如：`complex-instruction-following-eval`
- 选 Public，**不要**勾选 “Add a README”（本地已有）
- 创建后记下仓库 URL，如：`https://github.com/你的用户名/complex-instruction-following-eval.git`

### 2. 本地已有 Git 时（当前仓库）

```bash
# 确认当前分支（例如 main 或 onedaybot-dev）
git branch

# 若想用 main 作为公开分支，可重命名或新建
git checkout -b main   # 或保持当前分支名

# 添加远程（仅分享方法论时可用新仓库）
git remote add github https://github.com/你的用户名/complex-instruction-following-eval.git

# 推送（首次）
git push -u github main
```

若远程已存在，可保留原 origin，单独添加新远程（如 `mdc`）指向公开仓库。

### 3. 本地尚未初始化 Git 时

```bash
git init
git add .
# 先执行「一、2」里的 restore --staged，再 add
git add .
git status   # 再次确认无 config.py、无 outputs 业务数据
git commit -m "chore: 公开方法论与框架，不含数据与密钥"
git branch -M main
git remote add origin https://github.com/你的用户名/仓库名.git
git push -u origin main
```

---

## 三、仓库里「方法论」应包含的内容

- **代码**：`evaluation/` 下 pipeline、分析、报告、各 stage 实现；`clients/`、`data/` 下脚本可保留，但不要带业务 xlsx 与真实 sysprompts。
- **文档**：`README.md`、`docs/`（CONFIG_PLAYBOOK、STAGES_REFERENCE、DATA_SCHEMA、ARCHITECTURE 等）。
- **示例配置**：`config.example.py`、`config.example.json`，以及 `outputs/.gitkeep`、`outputs/README.md`。
- **依赖与许可**：`requirements.txt`、`LICENSE`。

不含：`config.py`、真实题目/回复/报告、任何 API Key 或内部 URL。

---

## 四、若曾误提交过敏感文件

若历史提交里出现过 `config.py` 或含密钥/数据的文件：

1. **不要**直接 `git push`，否则历史里仍会保留。
2. 可用 `git filter-repo` 或 BFG 从历史中删除该文件，或新建一个「干净」分支，只包含当前干净的文件再推送。
3. 若不确定，可新建一个空目录、重新 `git init`，只复制当前需要的文件（不含 config、outputs、业务 xlsx），再 `add`、`commit`、`remote`、`push`，这样历史里不会有敏感内容。

---

## 五、README 说明建议

在 README 中已说明：

- 本项目为**方法论与框架**，不包含任何业务数据与 API Key。
- 使用前需复制 `config.example.py` 为 `config.py` 并自行配置；数据格式见 `docs/DATA_SCHEMA.md`。

这样他人一眼可知这是「可复现的方法论仓库」，需自备配置与数据。

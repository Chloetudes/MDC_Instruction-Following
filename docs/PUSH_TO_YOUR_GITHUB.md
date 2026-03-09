# 推送到你的 GitHub 仓库

按「只放方法论」整理后，在本地执行以下步骤即可把本仓库推送到**你自己的 GitHub**。

---

## 前提

1. 已按 [SHARING_GITHUB.md](SHARING_GITHUB.md) 完成发布前自检（无 `config.py`、无 `outputs/` 业务数据、已取消不应提交的暂存）。
2. 已在 GitHub 上创建好**空仓库**（不要勾选 README / .gitignore），并记下仓库地址。

---

## 步骤一：仓库地址

当前文档对应的仓库：**https://github.com/Chloetudes/MDC_project**

若需推送到其他仓库，将下面命令中的 URL 替换即可。

---

## 步骤二：在项目根目录执行

在终端进入本项目根目录（`Evaluation_xr`），依次执行：

```bash
# 1. 若尚未初始化 Git
git init

# 2. 添加远程 → 推送到 https://github.com/Chloetudes/MDC_project
git remote add origin https://github.com/Chloetudes/MDC_project.git

# 若已有 origin 且是别的地址，可改用其他名字再添加：
# git remote add github https://github.com/Chloetudes/MDC_project.git

# 3. 确认当前分支为 main
git branch -M main

# 4. 只添加会被提交的文件（.gitignore 会排除 config.py、outputs 等）
git add .
git status
# 再次确认列表里没有 config.py、没有 outputs/ 下的业务文件

# 5. 提交
git commit -m "chore: 自动化评测与数据合成系统 — 架构与代码（仅方法论，无敏感信息）"

# 6. 推送到你的 GitHub（首次）
git push -u origin main
# 若上面用的是 git remote add github ...，则：
# git push -u github main
```

---

## 步骤三：在 GitHub 上检查

- 打开你的仓库页面，确认 README、`evaluation/`、`docs/`（含 SYSTEM_OVERVIEW、ARCHITECTURE、CONFIG_PLAYBOOK 等）均已存在。
- 确认**没有** `config.py`、没有 `outputs/` 下的题目/回复/报告文件。

---

## 说明

- **无法代你执行推送**：需要你在本机执行上述命令（需已安装 Git、已登录 GitHub）。
- 若仓库已存在且已有历史，可新建分支再推送，或先 `git pull origin main --rebase` 再 `git push`。
- 若你提供的是「用户名 + 仓库名」，可自行拼成 URL：`https://github.com/用户名/仓库名.git`。

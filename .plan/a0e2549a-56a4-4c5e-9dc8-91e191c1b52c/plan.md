# 开箱即用改造计划

## 用户诉求

"下载了就可以直接运行" — 即克隆/下载项目后，只需填入 API Key，执行一条命令就能跑起来。

## 当前问题分析

### 1. 缺少 requirements.txt（已创建）

✅ 已创建 requirements.txt（pandas, openpyxl, tqdm, requests, scipy, numpy, scikit-learn）

### 2. 没有 README.md（项目根目录）

没有任何说明文档告诉用户如何快速上手。

### 3. setup.sh 已创建

✅ 已创建 setup.sh，但内容可以更精简。

### 4. data/README.md 中的 stage key 名称与代码不匹配

data/README.md 中写的是旧版本 key（如 `generate_instructions`、`evaluate_instructions`）， 实际代码中的 key 是（如 `instruction_generation`、`instruction_quality_evaluation`）。 这会误导用户配置 sysprompts.xlsx 时填错 stage 名称。

### 5. config.py 缺少"最少配置哪个 provider"的引导

用户不知道最少需要配置哪个 provider 才能跑起来。

## 改造方案

### 核心目标：3步启动

```plaintext
1. git clone / 下载解压
2. 编辑 config.py，填入 API Key（最少1个 provider）
3. pip install -r requirements.txt
4. python agent_runner.py --mode check
```

### 具体改动清单

#### A. 创建项目根目录 README.md（新建）

内容：

* 项目简介（一句话）

* 快速开始（4步）

* 最少配置说明（只需配置 idealab 或 routify_claude 的 key）

* 运行命令说明（check/test/full/resume）

* 目录结构说明

#### B. 修复 data/README.md 中的 stage key 名称（修改）

将旧版 key 名称更新为与代码实际一致的名称：

| 旧（错误）                 | 新（正确）                          |
| --------------------- | ------------------------------ |
| generate_instructions | instruction_generation         |
| evaluate_instructions | instruction_quality_evaluation |
| generate_criteria     | criteria_generation            |
| generate_references   | reference_generation           |
| evaluate_replies      | reply_evaluation               |
| generate_report       | report_analysis                |
| expand_multiturn      | multiturn_expansion            |

#### C. 更新 AGENT_GUIDE.md 快速启动部分（修改）

在 Step 1 前加：`pip install -r requirements.txt`

#### D. 在 config.py 顶部加最少配置引导注释（修改）

在文件顶部注释中标注：

* 最少需要配置 `idealab` 或 `routify_claude` 中的一个

* 被测模型需要对应 provider 的 key

#### E. 确认 requirements.txt 依赖完整（已完成）

✅ 已包含：pandas, openpyxl, tqdm, requests, scipy, numpy, scikit-learn

## 不需要改动的部分

* 代码逻辑（已经稳定）

* sysprompt 文件（已有内容）

* agent_runner.py（已完整）

* evaluation/ 下的所有模块

* setup.sh（已创建）

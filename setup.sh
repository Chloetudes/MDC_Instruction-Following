#!/bin/bash
# 评测系统一键安装脚本
set -e

echo "============================================================"
echo "🚀 评测系统安装脚本"
echo "============================================================"

# 1. 安装 Python 依赖
echo ""
echo "📦 安装 Python 依赖..."
pip install -r requirements.txt

# 2. 检查 config.py 中的 API key
echo ""
echo "🔑 检查 API Key 配置..."
if grep -q "YOUR_API_KEY_HERE" config.py; then
    echo "⚠️  请编辑 config.py，将 'YOUR_API_KEY_HERE' 替换为真实的 API Key"
    echo "   至少需要配置一个 provider（推荐 idealab 或 routify_claude）"
else
    echo "✅ API Key 已配置"
fi

# 3. 检查 sysprompts 目录
echo ""
echo "📝 检查 Sysprompt 文件..."
SYSPROMPTS_DIR="data/sysprompts"
REQUIRED_FILES=(
    "instruction_generation.txt"
    "instruction_quality_evaluation.txt"
    "criteria_generation.txt"
    "reference_generation.txt"
    "reply_evaluation.txt"
    "report_analysis.txt"
    "multiturn_expansion.txt"
)

ALL_OK=true
for filename in "${REQUIRED_FILES[@]}"; do
    filepath="$SYSPROMPTS_DIR/$filename"
    if [ -f "$filepath" ] && [ -s "$filepath" ]; then
        echo "  ✅ $filename"
    else
        echo "  ❌ $filename 缺失或为空"
        ALL_OK=false
    fi
done

if [ "$ALL_OK" = true ]; then
    echo "✅ 所有 Sysprompt 文件就绪"
fi

# 4. 创建输出目录
echo ""
echo "📁 创建输出目录..."
mkdir -p outputs/evaluation

echo ""
echo "============================================================"
echo "✅ 安装完成！"
echo ""
echo "下一步："
echo "  1. 编辑 config.py，填入真实的 API Key"
echo "  2. 编辑 evaluation/main.py，配置裁判模型和被测模型"
echo "  3. 运行自检: python agent_runner.py --mode check"
echo "  4. 测试流程: python agent_runner.py --mode test"
echo "  5. 完整评测: python agent_runner.py --mode full"
echo "============================================================"

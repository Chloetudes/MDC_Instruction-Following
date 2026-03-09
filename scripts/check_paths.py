#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查路径解析是否正确，运行前可先执行此脚本"""
import os
import sys

_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)
sys.path.insert(0, _project_root)
os.chdir(_project_root)

def main():
    print("=" * 50)
    print("路径与配置检查")
    print("=" * 50)
    print(f"项目根目录: {_project_root}")
    print(f"当前工作目录: {os.getcwd()}")
    print()

    # 1. Config loader
    from evaluation.config_loader import resolve_config
    CONFIG = {
        'project_id': 'cif', 'data_batch': 'self', 'output_base_dir': 'outputs',
        'stages': ['generate_criteria'], 'sysprompt_excel': 'data/sysprompts.xlsx',
    }
    cfg = resolve_config(CONFIG, _project_root, 'outputs')
    print("1. 配置加载: OK")
    print(f"   project_id={cfg.get('project_id')}, data_batch={cfg.get('data_batch')}")

    # 2. Pipeline + DirectoryManager
    from evaluation.pipeline import PipelineManager
    pm = PipelineManager(cfg)
    print("2. PipelineManager: OK")

    # 3. Paths
    q_path = pm._resolve_questions_excel_for_evaluate()
    r_path = pm._resolve_replies_excel()
    print(f"3. 题目表: {q_path}")
    print(f"   存在: {os.path.exists(q_path)}")
    print(f"4. 回复表: {r_path}")
    print(f"   存在: {os.path.exists(r_path)}")

    # 4. generate_criteria input
    qi = cfg.get('questions_input_excel') or f"questions{pm._batch_suffix()}.xlsx"
    inp = pm.dir_manager.get_path("questions", qi)
    if not os.path.isabs(inp):
        inp = os.path.join(_project_root, inp)
    print(f"5. generate_criteria 输入: {inp}")
    print(f"   存在: {os.path.exists(inp)}")

    # 5. Required files
    sysprompt = cfg.get('sysprompt_excel', 'data/sysprompts.xlsx')
    if not os.path.isabs(sysprompt):
        sysprompt = os.path.join(_project_root, sysprompt)
    print(f"6. 提示词: {sysprompt}")
    print(f"   存在: {os.path.exists(sysprompt)}")

    print()
    print("=" * 50)
    if not os.path.exists(inp):
        print("⚠️  run generate_criteria 前需准备: outputs/<project_id>/questions/questions_self.xlsx")
    if not os.path.exists(sysprompt):
        print("⚠️  提示词文件缺失，请准备 data/sysprompts.xlsx 或 outputs/<project_id>/sysprompts.xlsx")
    print("=" * 50)

if __name__ == "__main__":
    main()

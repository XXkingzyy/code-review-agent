"""
tools/__init__.py —— 工具集统一出口
=====================================
四个工具复用自 Homework 1 的代码审查 Agent：
读文件 / 语法检查 / 执行代码 / 复杂度分析。
"""
from tools.code_executor import run_python_code
from tools.complexity_analyzer import analyze_complexity
from tools.file_reader import read_code_file, read_text_file
from tools.syntax_checker import check_python_syntax

__all__ = [
    "analyze_complexity",
    "check_python_syntax",
    "read_code_file",
    "read_text_file",
    "run_python_code",
]

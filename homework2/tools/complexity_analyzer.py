"""
complexity_analyzer.py —— 代码复杂度分析工具（复用自 Homework 1）
==================================================================
统计函数数、类数、圈复杂度、最长函数，给审查 Agent 提供量化证据。
"""
from __future__ import annotations

import ast

from langchain_core.tools import tool

_COMPLEXITY_NODES = (
    ast.If,
    ast.For,
    ast.While,
    ast.ExceptHandler,
    ast.With,
    ast.BoolOp,
    ast.IfExp,
)
HIGH_COMPLEXITY_THRESHOLD = 10
LONG_FUNC_THRESHOLD = 50


@tool
def analyze_complexity(code: str) -> str:
    """静态分析 Python 源码的结构指标（函数数、类数、各函数复杂度、最大嵌套深度等）。
    用于评估代码是否过长/过深/圈复杂度过高。

    Args:
        code: 要分析的 Python 源码字符串
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return f"[错误] 代码有语法错误，无法做复杂度分析：{exc}"

    funcs: list[dict] = []

    class FuncsVisitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            complexity = 1
            for child in ast.walk(node):
                if isinstance(child, _COMPLEXITY_NODES):
                    complexity += 1
            length = (node.end_lineno or node.lineno) - node.lineno + 1
            funcs.append(
                {
                    "name": node.name,
                    "lineno": node.lineno,
                    "lines": length,
                    "complexity": complexity,
                }
            )
            self.generic_visit(node)

    FuncsVisitor().visit(tree)
    class_count = sum(1 for node in ast.walk(tree) if isinstance(node, ast.ClassDef))

    lines_out = [
        f"函数总数：{len(funcs)}",
        f"类总数：{class_count}",
        "各函数指标：",
    ]
    for item in sorted(funcs, key=lambda x: -x["complexity"]):
        flag = " ⚠️高复杂度" if item["complexity"] > HIGH_COMPLEXITY_THRESHOLD else ""
        lines_out.append(
            f"  - {item['name']}() @行{item['lineno']}：{item['lines']} 行，圈复杂度={item['complexity']}{flag}"
        )
    if funcs:
        longest = max(funcs, key=lambda x: x["lines"])
        lines_out.append(
            f"最长函数：{longest['name']}()，{longest['lines']} 行"
            + (" ⚠️超过 50 行建议拆分" if longest["lines"] > LONG_FUNC_THRESHOLD else "")
        )
    return "\n".join(lines_out)

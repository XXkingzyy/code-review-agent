"""
syntax_checker.py —— Python 语法静态检查工具（复用自 Homework 1）
==================================================================
用 ast.parse 做语法门禁，并在系统装有 ruff 时附带风格/潜在 Bug 提示。
"""
from __future__ import annotations

import ast
import shutil
import subprocess

from langchain_core.tools import tool


@tool
def check_python_syntax(code: str) -> str:
    """检查一段 Python 源码是否存在语法错误。在正式审查前先用它确认代码能解析。

    Args:
        code: 待检查的 Python 源码字符串（不要传文件路径，要传源码本身）
    """
    errors: list[str] = []
    try:
        ast.parse(code)
    except SyntaxError as exc:
        errors.append(
            f"语法错误：第 {exc.lineno} 行，列 {exc.offset}：{exc.msg}\n"
            f"  出错代码：{exc.text.strip() if exc.text else '?'}"
        )

    if shutil.which("ruff") is not None:
        try:
            proc = subprocess.run(
                ["ruff", "-", "--output-format=concise"],
                input=code,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if proc.stdout.strip():
                errors.append("ruff 静态检查提示：\n" + proc.stdout.strip())
        except Exception as exc:  # ruff 自身失败不影响主流程
            errors.append(f"（ruff 调用失败，已跳过：{exc}）")

    if not errors:
        return "✅ 语法检查通过：AST 解析成功，未发现语法错误。"
    return "❌ 发现以下问题：\n" + "\n".join(f"- {error}" for error in errors)

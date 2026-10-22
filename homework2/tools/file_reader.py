"""
file_reader.py —— 代码文件读取工具（复用并改造自 Homework 1）
==============================================================
提供两层能力：
  1. read_text_file()：纯函数，供 Workflow 入口读取用户指定的代码文件；
  2. read_code_file：LangChain 工具，供 Agent 按需读取文件（保留作业1的用法）。
"""
from __future__ import annotations

import os

from langchain_core.tools import tool

# 单文件大小上限：防止把巨型文件塞进上下文
MAX_FILE_BYTES = 200 * 1024


class FileReadError(RuntimeError):
    """文件不存在/过大/解码失败时抛出。"""


def read_text_file(file_path: str) -> str:
    """读取文本文件的原始内容（不含行号），自动兼容 utf-8 / gbk。"""
    abs_path = os.path.abspath(file_path)
    if not os.path.isfile(abs_path):
        raise FileReadError(f"文件不存在：{abs_path}")
    if os.path.getsize(abs_path) > MAX_FILE_BYTES:
        raise FileReadError(f"文件超过 {MAX_FILE_BYTES // 1024}KB 限制，请拆分后再处理")
    try:
        with open(abs_path, encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        # Windows 下不少中文文件是 GBK 编码
        with open(abs_path, encoding="gbk") as f:
            return f.read()


@tool
def read_code_file(file_path: str) -> str:
    """读取本地代码文件的文本内容。需要查看某个文件时调用本工具。

    Args:
        file_path: 代码文件的路径（相对或绝对均可，例如 "examples/bad_code.py"）
    """
    try:
        content = read_text_file(file_path)
    except FileReadError as exc:
        return f"[错误] {exc}"
    except Exception as exc:  # 兜底：工具永远不抛异常，错误以字符串返回给 Agent
        return f"[错误] 读取失败：{exc}"
    # 加行号，便于 Agent 在审查报告中精确引用
    lines = content.splitlines()
    numbered = [f"{i + 1:>4} | {line}" for i, line in enumerate(lines)]
    return f"# 文件：{os.path.abspath(file_path)}（共 {len(lines)} 行）\n" + "\n".join(numbered)

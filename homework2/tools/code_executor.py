"""
code_executor.py —— 代码执行工具（复用自 Homework 1）
======================================================
在子进程中执行代码并捕获 stdout/stderr/退出码，用于复现运行时 Bug。
注意：仅作业演示使用，带超时但不是真正的容器沙箱，不要执行不可信代码。
"""
from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import tempfile

from langchain_core.tools import tool


@tool
def run_python_code(code: str) -> str:
    """在子进程中执行一段 Python 代码，返回 stdout / stderr / 退出码。
    当你怀疑代码有运行时错误（而非语法错误）时调用本工具验证。

    Args:
        code: 要执行的 Python 源码字符串
    """
    timeout = int(os.environ.get("CODE_EXEC_TIMEOUT", "5"))
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(code)
        tmp_path = f.name
    try:
        proc = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env={
                "PATH": os.environ.get("PATH", ""),
                "PYTHONIOENCODING": "utf-8",
            },
        )
        out = proc.stdout.strip()
        err = proc.stderr.strip()
        report = f"退出码：{proc.returncode}\n"
        report += f"--- stdout ---\n{out if out else '(空)'}\n"
        report += f"--- stderr ---\n{err if err else '(空)'}"
        return report
    except subprocess.TimeoutExpired:
        return f"⏱️ 执行超时（>{timeout}s），疑似死循环或阻塞调用。"
    except Exception as exc:
        return f"[错误] 执行失败：{exc}"
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)

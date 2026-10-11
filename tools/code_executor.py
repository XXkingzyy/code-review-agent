"""
code_executor.py —— 代码执行工具
==================================
功能：在受限超时下执行一段 Python 源码，捕获标准输出/错误输出，
     让 Agent 能"跑一下看看结果"，从而发现运行时 Bug。
注意：本工具仅用于作业演示，未做系统级沙箱隔离，请勿执行不可信代码。
"""
import contextlib  # 上下文管理器工具：suppress 静默吞掉指定异常
import os  # 路径环境变量
import subprocess  # 子进程执行
import sys  # 拿当前解释器路径
import tempfile  # 临时文件：把代码写到临时 .py 再执行

from langchain_core.tools import tool  # 工具装饰器


@tool                                       # 注册工具
def run_python_code(code: str) -> str:      # 入参源码字符串，返回执行结果
    """在沙箱子进程里执行一段 Python 代码，返回 stdout / stderr / 返回码。
    当你怀疑代码有运行时错误（而非语法错误）时调用本工具验证。

    Args:
        code: 要执行的 Python 源码字符串
    """
    # 从环境变量读超时，默认 5 秒（与 .env 中 CODE_EXEC_TIMEOUT 对应）
    timeout = int(os.environ.get("CODE_EXEC_TIMEOUT", "5"))
    # 写一个临时 .py 文件，用完即删
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"  # 文本模式、utf-8、自动删除=False 以便手动清理
    ) as f:
        f.write(code)                       # 把源码写入临时文件
        tmp_path = f.name                   # 记下临时文件路径
    try:
        # 用当前解释器跑这个临时文件；捕获输出；禁止联网/弹窗
        proc = subprocess.run(
            [sys.executable, tmp_path],       # sys.executable 即当前 python.exe
            capture_output=True,              # 管道捕获 stdout/stderr
            text=True,                        # 文本模式
            timeout=timeout,                  # 超时则抛 TimeoutExpired
            check=False,                      # 不抛 CalledProcessError：退出码非 0 由我们自己读
            env={                             # 传入一个最小化环境变量，避免污染
                "PATH": os.environ.get("PATH", ""),
                "PYTHONIOENCODING": "utf-8",  # 强制输出 utf-8，防 Windows 中文乱码
            },
        )
        # 把执行结果整理成可读报告
        out = proc.stdout.strip()             # 标准输出
        err = proc.stderr.strip()             # 标准错误
        report = f"退出码：{proc.returncode}\n"   # 退出码 0 表示正常
        report += f"--- stdout ---\n{out if out else '(空)'}\n"  # 追加 stdout
        report += f"--- stderr ---\n{err if err else '(空)'}"    # 追加 stderr
        return report                         # 返回给 Agent
    except subprocess.TimeoutExpired:        # 超时（死循环/卡死）
        return f"⏱️ 执行超时（>{timeout}s），疑似死循环或阻塞调用。"
    except Exception as ex:                  # 其他异常
        return f"[错误] 执行失败：{ex}"
    finally:                                 # 无论成功失败都删临时文件
        with contextlib.suppress(OSError):  # 静默吞掉"文件已被占用/不存在"等删除失败
            os.unlink(tmp_path)              # 删除临时 .py

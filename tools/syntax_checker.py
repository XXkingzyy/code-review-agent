"""
syntax_checker.py —— Python 语法静态检查工具
===============================================
功能：用 Python 内置的 ast.parse 对源码做语法解析，
     捕获 SyntaxError 并返回精确的出错行号与原因；
     可选调用 ruff 做风格/潜在 Bug 检查。
"""
import ast  # Python 抽象语法树模块：ast.parse 可做语法校验
import shutil  # 用于检测 ruff 是否在 PATH 中
import subprocess  # 子进程模块：调用外部 ruff 命令

from langchain_core.tools import tool  # LangChain 工具装饰器


@tool                                       # 注册为 Agent 工具
def check_python_syntax(code: str) -> str:  # 入参是源码字符串，返回检查报告
    """检查一段 Python 源码是否存在语法错误。在正式审查前先用它确认代码能解析。

    Args:
        code: 待检查的 Python 源码字符串（不要传文件路径，要传源码本身）
    """
    errors = []                             # 收集所有错误信息
    # 第一步：用 ast.parse 做语法级校验（这是最硬的错误）
    try:
        ast.parse(code)                     # 把源码解析成 AST；语法错误会抛 SyntaxError
    except SyntaxError as e:                # 捕获语法错误
        # 组装一条人类可读的错误描述
        errors.append(
            f"语法错误：第 {e.lineno} 行，列 {e.offset}：{e.msg}\n"
            f"  出错代码：{e.text.strip() if e.text else '?'}"
        )
    # 第二步：如果系统装了 ruff，就跑一遍静态检查（找不到就跳过，不报错）
    if shutil.which("ruff") is not None:    # ruff 在 PATH 里才执行
        try:
            # 用 ruff 检查代码：- 表示从 stdin 读，--output-format=concise 输出紧凑格式
            proc = subprocess.run(
                ["ruff", "-", "--output-format=concise"],  # 命令行参数
                input=code,                               # 把源码喂给 stdin
                capture_output=True,                      # 捕获 stdout/stderr
                text=True,                                # 以文本模式（而非字节）返回
                timeout=5,                                # 5 秒超时
                check=False,                              # 不抛异常：非 0 退出码由我们自己判断
            )
            if proc.stdout.strip():                   # ruff 有输出就说明发现了问题
                errors.append("ruff 静态检查提示：\n" + proc.stdout.strip())
        except Exception as ex:                       # ruff 自身崩了不影响主流程
            errors.append(f"（ruff 调用失败，已跳过：{ex}）")
    # 汇总返回
    if not errors:                                    # 没有任何错误
        return "✅ 语法检查通过：AST 解析成功，未发现语法错误。"
    return "❌ 发现以下问题：\n" + "\n".join(f"- {e}" for e in errors)  # 列表拼接成报告

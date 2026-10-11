"""
file_reader.py —— 代码文件读取工具
=====================================
功能：根据用户传入的相对/绝对路径，安全地读取文本文件内容，
     并做大小截断，避免把超大文件一次性塞进上下文撑爆 Token。
"""
import os  # 操作系统接口：路径拼接、文件大小判断

from langchain_core.tools import tool  # LangChain 工具装饰器：把普通函数变成 Agent 可调用的工具


@tool                                       # @tool 装饰器：自动把函数签名+docstring 转成工具描述喂给 LLM
def read_code_file(file_path: str) -> str:  # 工具函数：接收一个文件路径字符串，返回文件内容字符串
    """读取本地代码文件的文本内容。当用户给你一个文件路径让你审查时，先调用本工具拿到源码。

    Args:
        file_path: 代码文件的路径（相对或绝对均可，例如 "examples/bad_code.py"）
    """
    # 把传入路径转成绝对路径，避免相对路径歧义
    abs_path = os.path.abspath(file_path)
    # 先判断文件是否存在，不存在直接返回错误提示（让 Agent 自己决定下一步）
    if not os.path.isfile(abs_path):
        return f"[错误] 文件不存在：{abs_path}，请检查路径是否正确。"
    # 限制单文件最多读 200KB，防止巨型文件撑爆上下文
    if os.path.getsize(abs_path) > 200 * 1024:
        return "[错误] 文件超过 200KB 限制，请拆分后再审查。"
    # 尝试用 utf-8 读取，失败则退回 gbk（兼容 Windows 下中文注释文件）
    try:
        with open(abs_path, encoding="utf-8") as f:  # 以只读、utf-8 打开文件
            content = f.read()                            # 一次性读入内存
    except UnicodeDecodeError:                           # utf-8 解码失败
        with open(abs_path, encoding="gbk") as f:   # 改用 gbk 再试一次
            content = f.read()                            # 读入内容
    # 给内容加上路径和行数前缀，方便 Agent 定位问题行
    lines = content.splitlines()                         # 按行切分成列表
    numbered = [f"{i+1:>4} | {ln}" for i, ln in enumerate(lines)]  # 每行加行号，右对齐占4位
    # 拼接成最终返回串，并附上文件元信息
    return f"# 文件：{abs_path}（共 {len(lines)} 行）\n" + "\n".join(numbered)

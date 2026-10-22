"""
code_utils.py —— 代码块提取、语法校验、JSON 解析
==================================================
LLM 的输出是自然语言，Workflow 需要把它变成可执行的机器输入：
  1. 从回复中提取 ```python 代码块；
  2. 用 ast 做语法门禁（不合格的代码不进入下一节点）；
  3. 从审查回复中提取 JSON，供条件分支判断“是否通过”。
"""
from __future__ import annotations

import ast
import json
import re

# 匹配 Markdown 代码围栏；允许 python/py/java 等常见语言标记，也允许无标记
_CODE_FENCE = re.compile(
    r"```[ \t]*(?:python|py|java|javascript|js|typescript|ts|cpp|c\+\+|c|go|rust|kotlin)?[ \t]*\n(.*?)```",
    re.DOTALL | re.IGNORECASE,
)
_JSON_FENCE = re.compile(r"```(?:json)?[ \t]*\n(.*?)```", re.DOTALL | re.IGNORECASE)


class OutputParseError(RuntimeError):
    """Agent 输出无法解析成代码/JSON 时抛出。"""


def extract_code_block(text: str) -> str | None:
    """提取回复中最长的一个代码块；没有代码围栏时返回 None。"""
    blocks = [match.group(1).strip() for match in _CODE_FENCE.finditer(text)]
    blocks = [block for block in blocks if block]
    if not blocks:
        return None
    return max(blocks, key=len)


def syntax_error(code: str, language: str = "python") -> str | None:
    """返回 Python 语法错误描述；语法正确返回 None。非 Python 语言跳过检查。"""
    if language.lower() not in ("python", "py"):
        return None
    try:
        ast.parse(code)
    except SyntaxError as exc:
        return f"第 {exc.lineno} 行：{exc.msg}"
    return None


def extract_json_object(text: str) -> dict | None:
    """从文本中提取第一个可解析的 JSON 对象。

    优先解析 ```json 围栏，失败后再在全文里扫描 '{' 尝试 raw_decode。
    """
    candidates: list[str] = []
    for match in _JSON_FENCE.finditer(text):
        candidates.append(match.group(1).strip())
    candidates.append(text)

    decoder = json.JSONDecoder()
    for candidate in candidates:
        for index, char in enumerate(candidate):
            if char != "{":
                continue
            try:
                value, _ = decoder.raw_decode(candidate[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
    return None


def strip_json_block(text: str) -> str:
    """去掉回复末尾用于路由的 JSON 块，保留给用户看的 Markdown 报告。"""
    match = re.search(r"```json\s*\{.*?\}\s*```", text, re.DOTALL | re.IGNORECASE)
    if match:
        return text[: match.start()].strip()
    # 没有 json 围栏时，退化为第一个 '{' 之前的正文
    brace = text.find("{")
    if brace > 0:
        return text[:brace].strip()
    return text.strip()

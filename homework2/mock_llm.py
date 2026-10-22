"""
mock_llm.py —— 离线 Mock 模型（仅用于自测/演示）
==================================================
没有 API Key 时，用它跑通整条 Workflow：节点、状态、条件分支、修复循环、
日志与 Web 界面都能真实执行，只是“推理”结果由确定性规则生成。

它不是项目的核心能力，真实的编码/审查/修复仍由 .env 中配置的 LLM 完成。
"""
from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import AIMessage

from code_utils import extract_code_block

# ---------------------------------------------------------------------------
# 离线演示用的“初版代码”：故意埋了可变默认参数、除零、C 风格循环等问题
# ---------------------------------------------------------------------------
BUGGY_CODE = '''```python
"""成绩统计工具（离线 Mock 生成的演示代码）。"""


def average_score(scores, cache=[]):
    """计算及格（>=60）成绩的平均分。"""
    total = 0
    count = 0
    for i in range(len(scores)):
        if scores[i] >= 60:
            total = total + scores[i]
            count = count + 1
    avg = total / count
    cache.append(avg)
    return avg


def main():
    print(average_score([90, 80, 70]))
    print(average_score([]))


if __name__ == "__main__":
    main()
```'''

FIXED_CODE = '''```python
"""成绩统计工具（离线 Mock 修复后的版本）。"""

from collections.abc import Iterable


def average_score(scores: Iterable[float]) -> float:
    """计算及格（>=60）成绩的平均分；空输入返回 0.0。"""
    values = [score for score in scores if score >= 60]
    if not values:
        return 0.0
    return sum(values) / len(values)


def main() -> None:
    print(average_score([90, 80, 70]))
    print(average_score([]))


if __name__ == "__main__":
    main()
```'''


def _issue(severity: str, line: int | None, title: str, detail: str, suggestion: str) -> dict[str, Any]:
    return {
        "severity": severity,
        "line": line,
        "title": title,
        "detail": detail,
        "suggestion": suggestion,
    }


def _find_line(code: str, pattern: str) -> int | None:
    for index, line in enumerate(code.splitlines(), 1):
        if re.search(pattern, line):
            return index
    return None


def _detect_issues(code: str, prompt: str) -> list[dict[str, Any]]:
    """用正则做“确定性审查”，模拟 LLM 的问题发现过程。"""
    issues: list[dict[str, Any]] = []

    # 1) 可变默认参数
    if re.search(r"def\s+\w+\([^)]*=\s*\[\s*\]", code):
        issues.append(
            _issue(
                "critical",
                _find_line(code, r"def\s+\w+\([^)]*=\s*\[\s*\]"),
                "可变默认参数",
                "默认参数使用可变列表，多次调用会共享并累积状态。",
                "默认值改为 None，函数内部再创建新列表。",
            )
        )

    # 2) 除零风险：出现除法，但代码里没有空值/零值保护
    if re.search(r"/\s*(cnt|count|len\()", code) and not re.search(r"if\s+not\s+\w+|==\s*0|if\s+len\(", code):
        issues.append(
            _issue(
                "critical",
                _find_line(code, r"/\s*(cnt|count|len\()"),
                "除零风险",
                "当输入为空或没有及格成绩时，除数可能为 0，触发 ZeroDivisionError。",
                "除法前判断分母是否为 0，空输入直接返回 0.0。",
            )
        )

    # 3) 硬编码密钥/口令
    if re.search(r"(SECRET|PASSWORD|API_KEY)\s*=\s*['\"][^'\"]+['\"]", code):
        issues.append(
            _issue(
                "critical",
                _find_line(code, r"(SECRET|PASSWORD|API_KEY)\s*="),
                "硬编码密钥",
                "密钥写在源码里，提交仓库后会泄露。",
                "改从环境变量读取，并加入 .gitignore / 密钥管理。",
            )
        )

    # 4) eval/exec
    if re.search(r"\b(eval|exec)\s*\(", code):
        issues.append(
            _issue(
                "critical",
                _find_line(code, r"\b(eval|exec)\s*\("),
                "危险的动态执行",
                "eval/exec 可能执行任意代码，存在注入风险。",
                "改用显式解析（ast.literal_eval 或 json）。",
            )
        )

    # 5) 文件未使用 with
    if re.search(r"=\s*open\s*\(", code) and "with open" not in code:
        issues.append(
            _issue(
                "major",
                _find_line(code, r"=\s*open\s*\("),
                "文件未关闭",
                "open 后未使用 with，异常时文件句柄可能泄漏。",
                "改用 with open(...) as f: 结构。",
            )
        )

    # 6) 运行时证据：退出码非 0
    exit_match = re.search(r"退出码：([1-9]\d*)", prompt)
    if exit_match:
        stderr = re.search(r"--- stderr ---\n(.+?)(?:\n###|\Z)", prompt, re.DOTALL)
        error_name = "运行时异常"
        if stderr:
            first_line = stderr.group(1).strip().splitlines()[-1] if stderr.group(1).strip() else ""
            error_name = first_line[:80] or error_name
        issues.append(
            _issue(
                "critical",
                None,
                f"运行失败：{error_name}",
                "实际执行代码时进程以非 0 退出码结束。",
                "根据 stderr 定位异常位置并补齐边界处理。",
            )
        )

    # 7) 复杂度证据
    if "⚠️高复杂度" in prompt:
        issues.append(
            _issue(
                "major",
                None,
                "圈复杂度过高",
                "存在分支过多/嵌套过深的函数，维护成本高。",
                "拆分函数、提前返回，降低嵌套层级。",
            )
        )

    return issues


def _score(issues: list[dict[str, Any]]) -> float:
    score = 9.5
    for issue in issues:
        score -= {"critical": 2.5, "major": 1.0, "minor": 0.5}.get(issue["severity"], 1.0)
    return round(min(10.0, max(1.0, score)), 1)


def _build_review(code: str, prompt: str) -> str:
    threshold_match = re.search(r"通过阈值\s*[:：]\s*([\d.]+)", prompt)
    threshold = float(threshold_match.group(1)) if threshold_match else 8.0
    issues = _detect_issues(code, prompt)
    score = _score(issues)
    passed = score >= threshold and not any(item["severity"] == "critical" for item in issues)

    critical = [item for item in issues if item["severity"] == "critical"]
    major = [item for item in issues if item["severity"] == "major"]
    minor = [item for item in issues if item["severity"] == "minor"]

    def format_items(items: list[dict[str, Any]]) -> str:
        if not items:
            return "- 无\n"
        return "".join(
            f"- [{item['line'] if item['line'] is not None else '-'} 行] {item['title']}："
            f"{item['detail']} → {item['suggestion']}\n"
            for item in items
        )

    strengths = []
    if '"""' in code:
        strengths.append("包含模块/函数 docstring，可读性基础较好")
    if "if __name__" in code:
        strengths.append("提供了可运行的演示入口")
    if not strengths:
        strengths.append("代码结构简单，便于定位问题")

    strengths_text = "".join(f"- {item}\n" for item in strengths)
    markdown = (
        "## 代码审查报告（离线 Mock）\n"
        f"### 🔴 严重问题（必须改）\n{format_items(critical)}"
        f"### 🟡 改进建议（建议改）\n{format_items(major + minor)}"
        f"### 🟢 优点（写得好的地方）\n{strengths_text}"
        "### 总结评分（满分 10）\n"
        f"- 正确性：{max(1.0, score - 1):.1f}/10\n"
        f"- 可读性：{max(1.0, score):.1f}/10\n"
        f"- 安全性：{max(1.0, score + 0.5):.1f}/10\n"
        f"- 综合：{score:.1f}/10\n"
        f"\n**结论：{'通过' if passed else '未通过'}（阈值 {threshold:.1f}）**\n"
    )
    payload = {
        "score": score,
        "summary": "离线 Mock 审查：发现严重问题，需要修复。" if not passed else "离线 Mock 审查：未发现阻断性问题。",
        "issues": issues,
        "strengths": strengths,
        "dimensions": {
            "correctness": round(max(1.0, score - 1), 1),
            "readability": round(max(1.0, score), 1),
            "security": round(min(10.0, score + 0.5), 1),
        },
    }
    return markdown + "\n```json\n" + json.dumps(payload, ensure_ascii=False, indent=2) + "\n```"


def _mock_fix(code: str) -> str:
    """离线修复：针对演示模板返回修复版；其他代码做通用小修补。"""
    if "def average_score(scores, cache=[])" in code:
        return FIXED_CODE

    fixed = code
    # 通用修补 1：把 def 签名里的 result=[] / cache=[] 改成 None
    fixed = re.sub(r"(def\s+\w+\([^)]*?)(\w+)\s*=\s*\[\s*\]", r"\1\2=None", fixed)
    # 通用修补 2：硬编码密钥改为环境变量
    fixed = re.sub(
        r"(SECRET|PASSWORD|API_KEY)\s*=\s*['\"][^'\"]+['\"]",
        r'\1 = os.environ.get("\1", "")',
        fixed,
    )
    return "```python\n" + fixed.strip() + "\n```"


class MockLLM:
    """最小可用的离线模型：按角色返回确定性结果。"""

    def invoke(self, messages: list[Any]) -> AIMessage:
        system = str(messages[0].content) if messages else ""
        human = str(messages[-1].content) if messages else ""
        code = extract_code_block(human) or ""
        if "Fix Agent" in system:
            return AIMessage(content=_mock_fix(code))
        if "Review Agent" in system:
            return AIMessage(content=_build_review(code, human))
        # 默认按编码 Agent 处理
        return AIMessage(content=BUGGY_CODE)

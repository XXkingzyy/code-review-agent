"""
review_parser.py —— 审查结果解析与路由判定
=============================================
把审查 Agent 的 Markdown + JSON 输出转换成 WorkflowState 中的 ReviewResult：
  - score：综合评分（0~10）
  - issues：结构化问题列表
  - passed：是否通过（评分达到阈值且没有 critical 问题）

解析失败会抛 ReviewParseError，由审查 Agent 触发一次重试。
"""
from __future__ import annotations

from code_utils import extract_json_object, strip_json_block
from state import ReviewIssue, ReviewResult

# 严重程度别名归一化：兼容中英文、大小写
_SEVERITY_MAP = {
    "critical": "critical",
    "high": "critical",
    "严重": "critical",
    "major": "major",
    "medium": "major",
    "important": "major",
    "重要": "major",
    "minor": "minor",
    "low": "minor",
    "suggestion": "minor",
    "建议": "minor",
}


class ReviewParseError(RuntimeError):
    """审查输出缺少可解析的 JSON 时抛出。"""


def _to_score(value: object) -> float:
    """把任意输入转成 0~10 的评分。"""
    try:
        score = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return round(min(10.0, max(0.0, score)), 1)


def _to_line(value: object) -> int | None:
    """把行号转成 int；解析不了就返回 None。"""
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        digits = "".join(char for char in value if char.isdigit())
        if digits:
            return int(digits)
    return None


def _normalize_issue(raw: dict) -> ReviewIssue:
    """把模型给出的问题对象归一化，容忍字段缺失。"""
    severity = _SEVERITY_MAP.get(str(raw.get("severity", "major")).lower(), "major")
    return ReviewIssue(
        severity=severity,
        line=_to_line(raw.get("line")),
        title=str(raw.get("title") or raw.get("description") or "未命名问题"),
        detail=str(raw.get("detail") or raw.get("description") or ""),
        suggestion=str(raw.get("suggestion") or raw.get("fix") or ""),
    )


def parse_review(raw: str, threshold: float) -> ReviewResult:
    """解析审查 Agent 的原始输出，计算是否通过。"""
    payload = extract_json_object(raw)
    if payload is None:
        raise ReviewParseError("审查输出中没有找到 JSON 代码块")

    score = _to_score(payload.get("score"))
    issues: list[ReviewIssue] = []

    raw_issues = payload.get("issues")
    if isinstance(raw_issues, list):
        issues = [_normalize_issue(item) for item in raw_issues if isinstance(item, dict)]

    # 兼容部分模型把严重问题/建议拆成两个字段
    for key, severity in (("critical", "critical"), ("suggestions", "minor")):
        extra = payload.get(key)
        if isinstance(extra, list):
            for item in extra:
                if isinstance(item, dict):
                    normalized = _normalize_issue(item)
                    normalized["severity"] = severity
                    issues.append(normalized)
                elif isinstance(item, str) and item.strip():
                    issues.append(
                        ReviewIssue(
                            severity=severity,
                            line=None,
                            title=item.strip()[:60],
                            detail=item.strip(),
                            suggestion="",
                        )
                    )

    strengths: list[str] = []
    raw_strengths = payload.get("strengths")
    if isinstance(raw_strengths, list):
        strengths = [str(item) for item in raw_strengths if str(item).strip()]

    dimensions: dict[str, float] = {}
    raw_dimensions = payload.get("dimensions") or payload.get("scores_detail") or {}
    if isinstance(raw_dimensions, dict):
        dimensions = {str(key): _to_score(value) for key, value in raw_dimensions.items()}

    has_critical = any(issue["severity"] == "critical" for issue in issues)
    passed = score >= threshold and not has_critical
    markdown = strip_json_block(raw) or str(payload.get("summary", ""))

    return ReviewResult(
        score=score,
        passed=passed,
        summary=str(payload.get("summary", "")),
        issues=issues,
        strengths=strengths,
        dimensions=dimensions,
        markdown=markdown,
        threshold=threshold,
        evidence={},
    )

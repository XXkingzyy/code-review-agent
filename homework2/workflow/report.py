"""
report.py —— 最终报告生成
============================
把整条 Workflow 的过程汇总成一份可提交、可阅读的 Markdown 报告：
状态、轮数、评分轨迹、最后一轮审查报告、最终代码、运行产物。
"""
from __future__ import annotations

from state import WorkflowState

_STATUS_TEXT = {
    "passed": "✅ 通过",
    "failed": "❌ 未通过（达到最大轮数或评分不足）",
    "error": "⚠️ 流程异常终止",
}


def build_final_report(state: WorkflowState, final_status: str) -> str:
    """生成最终报告 Markdown。"""
    review = state.get("review")
    reviews = state.get("reviews", [])
    task = state.get("task", "").strip() or "（用户直接提供了代码）"
    source = "已有代码文件（跳过编码 Agent）" if state.get("code_source") == "file" else "自然语言需求"

    lines: list[str] = [
        "# 代码审查 Workflow 最终报告",
        "",
        f"- **状态**：{_STATUS_TEXT.get(final_status, final_status)}",
        f"- **输入来源**：{source}",
        f"- **语言**：{state.get('language', 'python')}",
        f"- **审查轮数**：{state.get('round', 0)} / {state.get('max_rounds', 0)}",
        f"- **通过阈值**：{state.get('threshold', 0):.1f} / 10",
        f"- **运行目录**：`{state.get('run_dir', '')}`",
        "",
        "## 1. 需求",
        "",
        task,
        "",
        "## 2. 评分轨迹",
        "",
        "| 轮次 | 评分 | 严重问题 | 改进建议 | 结论 |",
        "| --- | --- | --- | --- | --- |",
    ]

    if reviews:
        for item in reviews:
            lines.append(
                f"| {item['round']} | {item['score']:.1f} | {item['critical']} | "
                f"{item['major']} | {'通过' if item['passed'] else '未通过'} |"
            )
    else:
        lines.append("| - | - | - | - | 无审查记录 |")

    lines.extend(["", "## 3. 最终审查报告", ""])
    if review:
        lines.append(review.get("markdown") or "(审查报告为空)")
    else:
        lines.append("(没有可用的审查结果)")

    lines.extend(["", "## 4. 运行中的错误", ""])
    if state.get("errors"):
        for error in state["errors"]:
            lines.append(f"- {error}")
    else:
        lines.append("- 无")

    lines.extend(
        [
            "",
            "## 5. 最终代码",
            "",
            f"```{state.get('language', 'python')}",
            state.get("code", ""),
            "```",
        ]
    )

    messages = state.get("messages", [])
    lines.extend(
        [
            "",
            "## 6. Agent 协作记录",
            "",
            "| 时间 | 发送方 | 接收方 | 类型 | 内容 |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    if messages:
        for message in messages:
            content = str(message.get("content", "")).replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| {message.get('timestamp', '')} | {message.get('sender', '')} | "
                f"{message.get('recipient', '')} | {message.get('kind', '')} | {content} |"
            )
    else:
        lines.append("| - | - | - | - | 无消息记录 |")

    lines.extend(
        [
            "",
            "## 7. 运行产物",
            "",
            "- `trace.jsonl`：完整执行日志（节点、LLM 调用、工具调用、错误）",
            "- `90_final_code.py`：最终代码",
            "- `20_review_vN.md / .json`：每轮审查报告与结构化结果",
            "- `99_state.json`：工作流最终状态快照",
        ]
    )
    return "\n".join(lines)

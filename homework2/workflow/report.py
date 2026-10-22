"""
report.py —— 最终报告生成
============================
把整条 Workflow 的过程汇总成一份可提交、可阅读的 Markdown 报告：
状态、轮数、评分轨迹、最后一轮审查报告、修复 Diff、最终代码、运行产物。
"""
from __future__ import annotations

from state import WorkflowState

_STATUS_TEXT = {
    "passed": "✅ 通过",
    "failed": "❌ 未通过（达到最大轮数或评分不足）",
    "error": "⚠️ 流程异常终止",
    "awaiting_confirmation": "⏸ 等待人工确认（已暂停在修复前）",
}


def _diff_section(diffs: list[dict]) -> list[str]:
    """第 4 节：每轮修复前后的 unified diff。"""
    lines = ["", "## 4. 代码变更摘要", ""]
    if not diffs:
        lines.append("- 无（未进入修复阶段或没有代码差异）")
        return lines
    for diff in diffs:
        lines.extend(
            [
                f"### 第 {diff.get('round', '?')} 轮修复（+{diff.get('added', 0)} / -{diff.get('removed', 0)} 行）",
                "",
                "```diff",
                str(diff.get("text", "")).strip() or "(无差异)",
                "```",
                "",
            ]
        )
    return lines


def _message_section(messages: list[dict]) -> list[str]:
    """第 7 节：Agent 协作记录。"""
    lines = [
        "",
        "## 7. Agent 协作记录",
        "",
        "| 时间 | 发送方 | 接收方 | 类型 | 内容 |",
        "| --- | --- | --- | --- | --- |",
    ]
    if not messages:
        lines.append("| - | - | - | - | 无消息记录 |")
        return lines
    for message in messages:
        content = str(message.get("content", "")).replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {message.get('timestamp', '')} | {message.get('sender', '')} | "
            f"{message.get('recipient', '')} | {message.get('kind', '')} | {content} |"
        )
    return lines


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
    lines.append((review or {}).get("markdown") or "(没有可用的审查结果)")
    lines.extend(_diff_section(state.get("diffs", [])))

    lines.extend(["", "## 5. 运行中的错误", ""])
    errors = state.get("errors") or []
    if errors:
        lines.extend(f"- {error}" for error in errors)
    else:
        lines.append("- 无")

    lines.extend(
        [
            "",
            "## 6. 最终代码",
            "",
            f"```{state.get('language', 'python')}",
            state.get("code", ""),
            "```",
        ]
    )
    lines.extend(_message_section(state.get("messages", [])))
    lines.extend(
        [
            "",
            "## 8. 运行产物",
            "",
            "- `trace.jsonl`：完整执行日志（节点、LLM 调用、工具调用、错误）",
            "- `90_final_code.py`：最终代码",
            "- `20_review_vN.md / .json`：每轮审查报告与结构化结果",
            "- `31_diff_vN.txt`：每轮修复前后的 unified diff",
            "- `99_state.json`：工作流状态快照（暂停/恢复的兜底信息）",
            "- `checkpoints.sqlite`：LangGraph 检查点，可用于断点恢复",
        ]
    )
    return "\n".join(lines)

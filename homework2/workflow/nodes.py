"""
nodes.py —— Workflow 节点实现
================================
五个节点：
  prepare   —— 初始化运行目录、读取输入、写任务说明
  coding    —— 调用编码 Agent 生成初版代码
  review    —— 调用审查 Agent，产出结构化结果并决定是否通过
  fix       —— 调用修复 Agent，产出修复版本（随后回到 review，形成循环）
  finalize  —— 汇总报告、落盘最终产物

每个节点只返回“状态增量”，由 LangGraph 合并；节点内部捕获异常，
把错误写入 state.errors 并设置 status=error，尽量让整条流程可预期地收尾。
"""
from __future__ import annotations

import json
from difflib import unified_diff
from pathlib import Path

from agents.coding_agent import CodingAgent, code_stats
from agents.fix_agent import FixAgent
from agents.review_agent import ReviewAgent, review_to_record, summarize_review
from state import WorkflowState, make_message
from workflow.report import build_final_report
from workflow.trace import TraceLogger


def _save(run_dir: str, name: str, content: str) -> None:
    """把文本产物写入运行目录。"""
    path = Path(run_dir) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def save_state_snapshot(state: WorkflowState, name: str = "99_state.json") -> None:
    """保存状态快照；既用于收尾，也用于暂停点恢复与排查。"""
    snapshot = {key: value for key, value in state.items() if key != "final_report"}
    _save(state["run_dir"], name, json.dumps(snapshot, ensure_ascii=False, indent=2, default=str))


def _build_diff(before: str, after: str, round_no: int) -> dict:
    """生成修复前后的 unified diff，并统计增删行数。"""
    diff_text = "\n".join(
        unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"修复前（第 {round_no} 轮审查）",
            tofile=f"修复后（第 {round_no} 轮）",
            lineterm="",
        )
    )
    added = sum(1 for line in diff_text.splitlines() if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff_text.splitlines() if line.startswith("-") and not line.startswith("---"))
    return {
        "round": round_no,
        "path": f"31_diff_v{round_no}.txt",
        "text": diff_text or "（本轮没有代码差异）",
        "added": added,
        "removed": removed,
    }


def prepare_node(state: WorkflowState) -> dict:
    """入口准备：写任务说明与原始代码，决定第一个业务 Agent。"""
    logger = TraceLogger(state["run_dir"])
    logger.event("node_start", node="prepare")

    task = state.get("task", "").strip()
    code = state.get("code", "")
    source = state.get("code_source", "task")

    _save(state["run_dir"], "00_task.md", f"# 任务说明\n\n{task or '（无需求描述，直接审查已有代码）'}\n")
    if code:
        _save(state["run_dir"], "01_input_code.py", code)

    if source == "file" and not code.strip():
        error = "输入模式为 file，但没有读到任何代码"
        logger.event("node_end", node="prepare", level="error", error=error)
        return {
            "status": "error",
            "errors": [error],
            "messages": [make_message("system", "user", "error", error)],
        }

    next_agent = "coding_agent" if source == "task" else "review_agent"
    message = (
        f"任务已接收，代码来源：{'已有代码文件' if source == 'file' else '自然语言需求'}；"
        f"下一节点：{next_agent}。"
    )
    logger.event("node_end", node="prepare", next_node=next_agent)
    return {
        "status": "running",
        "messages": [make_message("system", next_agent, "task", message)],
    }


def coding_node(state: WorkflowState, agent: CodingAgent) -> dict:
    """编码 Agent 节点：需求 → 初版代码。"""
    logger = TraceLogger(state["run_dir"])
    logger.event("node_start", node="coding")
    try:
        code = agent.run(state.get("task", ""), state.get("language", "python"), state)
    except Exception as exc:  # 节点兜底：任何异常都转成可展示的错误状态
        error = f"编码 Agent 失败：{exc}"
        logger.event("node_end", node="coding", level="error", error=error)
        return {
            "status": "error",
            "errors": [error],
            "messages": [make_message("coding_agent", "user", "error", error)],
        }

    _save(state["run_dir"], "10_code_v0.py", code)
    logger.event("node_end", node="coding", lines=len(code.splitlines()))
    message = f"初版代码已生成（{code_stats(code)}），提交给审查 Agent。"
    return {
        "code": code,
        "status": "running",
        "history": [{"version": 0, "stage": "coding", "lines": len(code.splitlines())}],
        "messages": [make_message("coding_agent", "review_agent", "result", message, 0)],
    }


def review_node(state: WorkflowState, agent: ReviewAgent) -> dict:
    """审查 Agent 节点：代码 + 工具证据 → 结构化审查结果。"""
    logger = TraceLogger(state["run_dir"])
    logger.event("node_start", node="review", round=state.get("round", 0) + 1)
    round_no = int(state.get("round", 0)) + 1
    try:
        review = agent.run(
            task=state.get("task", ""),
            code=state.get("code", ""),
            language=state.get("language", "python"),
            round_no=round_no,
            state=state,
        )
    except Exception as exc:  # 节点兜底
        error = f"审查 Agent 失败：{exc}"
        logger.event("node_end", node="review", level="error", round=round_no, error=error)
        return {
            "status": "error",
            "round": round_no,
            "errors": [error],
            "messages": [make_message("review_agent", "user", "error", error, round_no)],
        }

    _save(state["run_dir"], f"20_review_v{round_no}.md", review.get("markdown", ""))
    _save(
        state["run_dir"],
        f"20_review_v{round_no}.json",
        json.dumps(review, ensure_ascii=False, indent=2, default=str),
    )
    summary = summarize_review(review)
    logger.event(
        "node_end",
        node="review",
        round=round_no,
        score=review["score"],
        passed=review["passed"],
        issues=len(review["issues"]),
    )
    return {
        "review": review,
        "round": round_no,
        "status": "reviewing",
        "reviews": [review_to_record(round_no, review)],
        "messages": [make_message("review_agent", "router", "review", summary, round_no)],
    }


def fix_node(state: WorkflowState, agent: FixAgent) -> dict:
    """修复 Agent 节点：审查问题 → 修复版本，随后回到审查形成循环。"""
    logger = TraceLogger(state["run_dir"])
    round_no = int(state.get("round", 1))
    logger.event("node_start", node="fix", round=round_no)
    review = state.get("review")
    if review is None:
        error = "修复节点缺少审查结果"
        logger.event("node_end", node="fix", level="error", error=error)
        return {
            "status": "error",
            "errors": [error],
            "messages": [make_message("fix_agent", "user", "error", error, round_no)],
        }

    try:
        fixed = agent.run(
            task=state.get("task", ""),
            code=state.get("code", ""),
            language=state.get("language", "python"),
            review=review,
            round_no=round_no,
            state=state,
        )
    except Exception as exc:  # 节点兜底
        error = f"修复 Agent 失败：{exc}"
        logger.event("node_end", node="fix", level="error", round=round_no, error=error)
        return {
            "status": "error",
            "errors": [error],
            "messages": [make_message("fix_agent", "user", "error", error, round_no)],
        }

    _save(state["run_dir"], f"30_code_fix_v{round_no}.py", fixed)
    diff = _build_diff(state.get("code", ""), fixed, round_no)
    _save(state["run_dir"], diff["path"], diff["text"] + "\n")
    logger.event(
        "node_end",
        node="fix",
        round=round_no,
        lines=len(fixed.splitlines()),
        diff=diff["path"],
        added=diff["added"],
        removed=diff["removed"],
    )
    message = (
        f"第 {round_no} 轮修复完成（{code_stats(fixed)}，+{diff['added']}/-{diff['removed']} 行），提交复审。"
    )
    return {
        "code": fixed,
        "status": "running",
        "history": [{"version": round_no, "stage": "fix", "lines": len(fixed.splitlines())}],
        "diffs": [diff],
        "messages": [make_message("fix_agent", "review_agent", "fix", message, round_no)],
    }


def finalize_node(state: WorkflowState) -> dict:
    """收尾：判定最终状态、生成报告、落盘所有产物。"""
    logger = TraceLogger(state["run_dir"])
    logger.event("node_start", node="finalize")

    review = state.get("review")
    if state.get("status") == "error":
        final_status = "error"
    elif review is not None and review["passed"]:
        final_status = "passed"
    else:
        final_status = "failed"

    report = build_final_report(state, final_status)
    _save(state["run_dir"], "90_final_code.py", state.get("code", ""))
    _save(state["run_dir"], "90_final_report.md", report)

    save_state_snapshot(state)

    logger.event("workflow_end", node="finalize", status=final_status, rounds=state.get("round", 0))
    logger.event("node_end", node="finalize", status=final_status)
    message = f"Workflow 结束，最终状态：{final_status}，审查轮数：{state.get('round', 0)}。"
    return {
        "status": final_status,
        "final_report": report,
        "messages": [make_message("workflow", "user", "done", message)],
    }


# ---------------------------------------------------------------------------
# 条件路由（Workflow 的“大脑”）
# ---------------------------------------------------------------------------
def route_entry(state: WorkflowState) -> str:
    """入口分支：有现成代码就直接审查，否则先编码。"""
    if state.get("status") == "error":
        return "finalize"
    if state.get("code_source") == "file" and state.get("code", "").strip():
        return "review"
    return "coding"


def route_after_coding(state: WorkflowState) -> str:
    """编码失败直接收尾，成功则进入审查。"""
    return "finalize" if state.get("status") == "error" else "review"


def route_after_review(state: WorkflowState) -> str:
    """审查后的核心分支：通过 / 达到轮数上限 / 出错 → 收尾；否则进入修复。"""
    if state.get("status") == "error":
        return "finalize"
    review = state.get("review")
    if review is not None and review["passed"]:
        return "finalize"
    if int(state.get("round", 0)) >= int(state.get("max_rounds", 1)):
        return "finalize"
    return "fix"


def route_after_fix(state: WorkflowState) -> str:
    """修复失败直接收尾，成功则回到审查（循环）。"""
    return "finalize" if state.get("status") == "error" else "review"

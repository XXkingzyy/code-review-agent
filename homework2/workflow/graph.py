"""
graph.py —— 用 LangGraph 编排 Agent Workflow
==============================================
图结构（顺序 + 条件分支 + 循环）：

    START → prepare ─┬─(已有代码)──────────────→ review
                     └─(仅需求)──→ coding ─────→ review
                                                   │
                                ┌──────────────────┼──────────────────┐
                                │ 通过/达到最大轮数/出错             │ 未通过且还有轮数
                                ▼                                     ▼
                             finalize ←────────────────────────────── fix
                                │                                     │
                               END                        修复后回到 review（循环）

LangGraph 的 updates 流让我们可以在每个节点结束时回调 UI/CLI，
实现执行过程可视化与状态追踪。
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from agents.coding_agent import CodingAgent
from agents.fix_agent import FixAgent
from agents.review_agent import ReviewAgent
from config import Settings
from llm import build_model
from state import WorkflowState, initial_state, make_message
from workflow.nodes import (
    coding_node,
    finalize_node,
    fix_node,
    prepare_node,
    review_node,
    route_after_coding,
    route_after_fix,
    route_after_review,
    route_entry,
)
from workflow.trace import TraceLogger

# updates 流中需要“追加”而不是“覆盖”的字段（与 state.py 的 reducer 保持一致）
_LIST_FIELDS = {"messages", "history", "reviews", "errors"}

NodeCallback = Callable[[str, WorkflowState], None]


def _create_run_dir(settings: Settings) -> Path:
    """创建本次运行的产物目录：runs/YYYYMMDD-HHMMSS-xxxxxx/。"""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    unique = uuid.uuid4().hex[:6]
    run_dir = settings.runs_root / f"{stamp}-{unique}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def merge_update(state: WorkflowState, update: dict[str, Any]) -> WorkflowState:
    """把 LangGraph 的节点增量合并进本地状态副本（与 reducer 行为一致）。"""
    merged: dict[str, Any] = dict(state)
    for key, value in update.items():
        if key in _LIST_FIELDS:
            merged[key] = list(state.get(key, [])) + list(value or [])
        else:
            merged[key] = value
    return merged  # type: ignore[return-value]


def build_graph(settings: Settings, model: Any):
    """装配三个 Agent 与五个节点，编译成可执行的 LangGraph。"""
    coding_agent = CodingAgent(model, settings)
    review_agent = ReviewAgent(model, settings)
    fix_agent = FixAgent(model, settings)

    graph = StateGraph(WorkflowState)
    graph.add_node("prepare", prepare_node)
    graph.add_node("coding", lambda state: coding_node(state, coding_agent))
    graph.add_node("review", lambda state: review_node(state, review_agent))
    graph.add_node("fix", lambda state: fix_node(state, fix_agent))
    graph.add_node("finalize", finalize_node)

    graph.add_edge(START, "prepare")
    graph.add_conditional_edges(
        "prepare",
        route_entry,
        {"coding": "coding", "review": "review", "finalize": "finalize"},
    )
    graph.add_conditional_edges(
        "coding",
        route_after_coding,
        {"review": "review", "finalize": "finalize"},
    )
    graph.add_conditional_edges(
        "review",
        route_after_review,
        {"fix": "fix", "finalize": "finalize"},
    )
    graph.add_conditional_edges(
        "fix",
        route_after_fix,
        {"review": "review", "finalize": "finalize"},
    )
    graph.add_edge("finalize", END)
    return graph.compile()


def run_workflow(
    *,
    task: str,
    language: str,
    code: str,
    code_source: str,
    settings: Settings,
    model: Any | None = None,
    on_node: NodeCallback | None = None,
) -> WorkflowState:
    """执行一次完整 Workflow，返回最终状态。

    参数：
        code_source："task"（从需求开始）或 "file"（从已有代码开始）。
        on_node：每个节点执行完后的回调，参数为 (节点名, 当前状态快照)。
    """
    run_dir = _create_run_dir(settings)
    state = initial_state(
        task=task,
        language=language,
        code=code,
        code_source=code_source,
        max_rounds=settings.max_rounds,
        threshold=settings.pass_threshold,
        run_dir=str(run_dir),
    )
    logger = TraceLogger(run_dir)
    logger.event(
        "workflow_start",
        task=task[:300],
        code_source=code_source,
        offline=settings.offline,
        model="mock" if settings.offline else settings.llm_model,
        max_rounds=settings.max_rounds,
        threshold=settings.pass_threshold,
    )

    app = build_graph(settings, model or build_model(settings))
    final_state: WorkflowState = state
    recursion_limit = max(25, settings.max_rounds * 6 + 10)

    try:
        for chunk in app.stream(
            state,
            config={"recursion_limit": recursion_limit},
            stream_mode="updates",
        ):
            for node_name, update in chunk.items():
                if not isinstance(update, dict):
                    continue
                final_state = merge_update(final_state, update)
                if on_node is not None:
                    on_node(node_name, final_state)
    except Exception as exc:  # 框架级异常：写日志、生成兜底报告，而不是抛给用户
        logger.event("workflow_crash", level="error", error=str(exc))
        error = f"Workflow 执行异常：{exc}"
        final_state = merge_update(
            final_state,
            {
                "status": "error",
                "errors": [error],
                "messages": [make_message("workflow", "user", "error", error)],
            },
        )
        final_state = merge_update(final_state, finalize_node(final_state))
        if on_node is not None:
            on_node("finalize", final_state)

    return final_state

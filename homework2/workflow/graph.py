"""
graph.py —— 用 LangGraph 编排 Agent Workflow
==============================================
图结构（顺序 + 条件分支 + 循环 + 人工确认）：

    START → prepare ─┬─(已有代码)──────────────→ review
                     └─(仅需求)──→ coding ─────→ review
                                                   │
                                ┌──────────────────┼──────────────────┐
                                │ 通过/达到最大轮数/出错             │ 未通过且还有轮数
                                ▼                                     ▼
                             finalize ←────────────────────────────── fix
                                │                                     │
                               END                        修复后回到 review（循环）

开启 CHECKPOINT 后，每次进入 fix 之前会暂停（interrupt_before），
把状态写入 runs/<run_id>/checkpoints.sqlite；人工确认后从同一个
thread_id 继续执行，实现“人机协作 + 断点恢复”。
"""
from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
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
    save_state_snapshot,
)
from workflow.trace import TraceLogger

# updates 流中需要“追加”而不是“覆盖”的字段（与 state.py 的 reducer 保持一致）
_LIST_FIELDS = {"messages", "history", "reviews", "errors", "diffs"}

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


def build_graph(
    settings: Settings,
    model: Any,
    *,
    checkpointer: Any | None = None,
    pause_before_fix: bool = False,
):
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
    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["fix"] if pause_before_fix else None,
    )


def _consume_stream(
    app: Any,
    input_state: WorkflowState | None,
    config: dict[str, Any],
    initial_state: WorkflowState,
    logger: TraceLogger,
    on_node: NodeCallback | None,
) -> WorkflowState:
    """消费 LangGraph 的 updates 流；遇到人工确认暂停点时写入快照并返回。"""
    final_state = initial_state
    for chunk in app.stream(input_state, config=config, stream_mode="updates"):
        if "__interrupt__" in chunk:
            round_no = int(final_state.get("round", 0))
            final_state = merge_update(
                final_state,
                {
                    "status": "awaiting_confirmation",
                    "messages": [
                        make_message(
                            "workflow",
                            "user",
                            "pause",
                            f"第 {round_no} 轮审查未通过，已暂停在修复前；确认后继续。",
                            round_no,
                        )
                    ],
                },
            )
            save_state_snapshot(final_state)
            logger.event(
                "workflow_pause",
                node="review",
                round=round_no,
                checkpoint=str(Path(final_state["run_dir"]) / "checkpoints.sqlite"),
            )
            if on_node is not None:
                on_node("await_confirmation", final_state)
            return final_state

        for node_name, update in chunk.items():
            if node_name.startswith("__") or not isinstance(update, dict):
                continue
            final_state = merge_update(final_state, update)
            if on_node is not None:
                on_node(node_name, final_state)
    return final_state


def run_workflow(
    *,
    task: str,
    language: str,
    code: str,
    code_source: str,
    settings: Settings,
    model: Any | None = None,
    on_node: NodeCallback | None = None,
    pause_before_fix: bool | None = None,
    resume_run_dir: str | None = None,
) -> WorkflowState:
    """执行或恢复一次 Workflow，返回最终状态。

    参数：
        code_source："task"（从需求开始）或 "file"（从已有代码开始）。
        on_node：每个节点执行完后的回调，参数为 (节点名, 当前状态快照)。
        pause_before_fix：是否在每次修复前暂停；None 表示使用 settings 中的配置。
        resume_run_dir：传入暂停运行的目录时，从 checkpoint 继续执行。
    """
    resume = resume_run_dir is not None
    if resume:
        run_dir = Path(resume_run_dir).expanduser().resolve()
        snapshot_path = run_dir / "99_state.json"
        if not snapshot_path.is_file():
            raise RuntimeError(f"找不到状态快照：{snapshot_path}")
        state: WorkflowState = json.loads(snapshot_path.read_text(encoding="utf-8"))
        state["run_dir"] = str(run_dir)
        pause_before_fix = bool(state.get("pause_before_fix", pause_before_fix or False))
        # 离线运行的恢复必须继续使用 Mock 模型，避免无 Key 时意外走真实 API
        if state.get("offline") and not settings.offline:
            settings = replace(settings, offline=True)
        logger = TraceLogger(run_dir)
        logger.event("workflow_resume", run_dir=str(run_dir), round=state.get("round", 0))
    else:
        run_dir = _create_run_dir(settings)
        pause_before_fix = settings.pause_before_fix if pause_before_fix is None else pause_before_fix
        state = initial_state(
            task=task,
            language=language,
            code=code,
            code_source=code_source,
            max_rounds=settings.max_rounds,
            threshold=settings.pass_threshold,
            run_dir=str(run_dir),
            pause_before_fix=bool(pause_before_fix),
            offline=settings.offline,
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
            pause_before_fix=bool(pause_before_fix),
        )

    checkpoint_path = run_dir / "checkpoints.sqlite"
    final_state: WorkflowState = state
    recursion_limit = max(25, int(state.get("max_rounds", settings.max_rounds)) * 6 + 10)
    config = {
        "configurable": {"thread_id": run_dir.name},
        "recursion_limit": recursion_limit,
    }

    try:
        with SqliteSaver.from_conn_string(str(checkpoint_path)) as checkpointer:
            app = build_graph(
                settings,
                model or build_model(settings),
                checkpointer=checkpointer,
                pause_before_fix=bool(pause_before_fix),
            )
            if resume:
                existing = app.get_state(config)
                if not existing.values:
                    raise RuntimeError(
                        "找不到可恢复的 checkpoint。请确认 run_dir 下的 checkpoints.sqlite 完整。"
                    )
                final_state = dict(existing.values)
                final_state["run_dir"] = str(run_dir)
                if not existing.next:
                    logger.event("workflow_resume_noop", node="finalize", status=final_state.get("status"))
                    return final_state
                round_no = int(final_state.get("round", 0))
                final_state = merge_update(
                    final_state,
                    {
                        "status": "running",
                        "messages": [
                            make_message(
                                "workflow",
                                "user",
                                "resume",
                                f"已从暂停点恢复，继续第 {round_no} 轮修复。",
                                round_no,
                            )
                        ],
                    },
                )
                logger.event(
                    "workflow_resume_checkpoint",
                    round=round_no,
                    next=list(existing.next),
                    checkpoint=str(checkpoint_path),
                )
                if on_node is not None:
                    on_node("resume", final_state)

            final_state = _consume_stream(
                app,
                None if resume else state,
                config,
                final_state,
                logger,
                on_node,
            )
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


def resume_workflow(
    *,
    run_dir: str,
    settings: Settings,
    model: Any | None = None,
    on_node: NodeCallback | None = None,
) -> WorkflowState:
    """从暂停点恢复一次 Workflow；任务、轮数、阈值都从状态快照读取。"""
    return run_workflow(
        task="",
        language="python",
        code="",
        code_source="task",
        settings=settings,
        model=model,
        on_node=on_node,
        resume_run_dir=run_dir,
    )

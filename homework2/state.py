"""
state.py —— Workflow 共享状态与 Agent 通信消息模型
====================================================
作业2的核心考察点之一是“Agent 间的消息传递或状态共享”。
本模块用两部分实现：

1. WorkflowState：整条流水线共享的状态（代码、审查结果、轮数、错误等），
   由 LangGraph 在各节点之间传递；节点只返回“增量”，框架负责合并。
2. AgentMessage：结构化消息，记录“谁在什么时候把什么结果交给谁”，
   用于展示 Agent 协作过程、写入运行日志、在 Web 界面回溯。
"""
from __future__ import annotations

import operator
from datetime import datetime
from typing import Annotated, Any, TypedDict


class AgentMessage(TypedDict):
    """Agent 之间传递的一条结构化消息。"""

    timestamp: str
    sender: str
    recipient: str
    kind: str
    round: int
    content: str


class ReviewIssue(TypedDict):
    """审查发现的一个问题项。"""

    severity: str
    line: int | None
    title: str
    detail: str
    suggestion: str


class ReviewResult(TypedDict):
    """审查 Agent 输出的结构化结果，是路由判断的直接依据。"""

    score: float
    passed: bool
    summary: str
    issues: list[ReviewIssue]
    strengths: list[str]
    dimensions: dict[str, float]
    markdown: str
    threshold: float
    evidence: dict[str, str]


class WorkflowState(TypedDict, total=False):
    """LangGraph 在节点之间共享的状态。

    说明：
      - 普通字段后一个节点覆盖前一个节点；
      - messages / history / reviews / errors 使用 operator.add 归约，
        节点只需返回“新增的条目”，框架自动追加，避免手工拼接。
    """

    task: str
    language: str
    code: str
    original_code: str
    code_source: str
    review: ReviewResult | None
    round: int
    max_rounds: int
    threshold: float
    status: str
    run_dir: str
    final_report: str
    errors: Annotated[list[str], operator.add]
    messages: Annotated[list[AgentMessage], operator.add]
    history: Annotated[list[dict[str, Any]], operator.add]
    reviews: Annotated[list[dict[str, Any]], operator.add]


def now_iso() -> str:
    """当前本地时间（带时区），用于消息与日志时间戳。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def make_message(
    sender: str,
    recipient: str,
    kind: str,
    content: str,
    round_no: int = 0,
) -> AgentMessage:
    """构造一条 Agent 消息。kind 取值：task/result/review/fix/error/done。"""
    return AgentMessage(
        timestamp=now_iso(),
        sender=sender,
        recipient=recipient,
        kind=kind,
        round=round_no,
        content=content,
    )


def initial_state(
    *,
    task: str,
    language: str,
    code: str,
    code_source: str,
    max_rounds: int,
    threshold: float,
    run_dir: str,
) -> WorkflowState:
    """构造工作流初始状态。

    code_source：
        "task" —— 只有需求描述，先由编码 Agent 生成代码；
        "file" —— 用户提供了已有代码，直接从审查 Agent 开始（条件分支入口）。
    """
    return WorkflowState(
        task=task,
        language=language,
        code=code,
        original_code=code,
        code_source=code_source,
        review=None,
        round=0,
        max_rounds=max_rounds,
        threshold=threshold,
        status="pending",
        run_dir=run_dir,
        final_report="",
        errors=[],
        messages=[],
        history=[],
        reviews=[],
    )

"""
base.py —— Agent 基类
========================
统一处理：模型调用、LLM 重试、执行日志，让三个业务 Agent 只关注自己的 Prompt 与输出解析。
"""
from __future__ import annotations

from typing import Any

from config import Settings
from llm import call_llm
from state import WorkflowState
from workflow.trace import TraceLogger


class AgentError(RuntimeError):
    """Agent 在多次尝试后仍无法产出合格结果时抛出。"""


class BaseAgent:
    """所有业务 Agent 的基类。"""

    name = "base_agent"

    def __init__(self, model: Any, settings: Settings) -> None:
        self.model = model
        self.settings = settings

    def ask(self, state: WorkflowState, system_prompt: str, user_prompt: str, label: str) -> str:
        """调用 LLM 并把过程写入 trace.jsonl。"""
        logger = TraceLogger(state["run_dir"])
        logger.event("agent_start", node=self.name, label=label)
        try:
            text = call_llm(
                self.model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                retries=self.settings.llm_retries,
                logger=logger,
                label=f"{self.name}:{label}",
            )
        except Exception as exc:
            logger.event("agent_error", node=self.name, level="error", label=label, error=str(exc))
            raise
        logger.event("agent_end", node=self.name, label=label, chars=len(text))
        return text

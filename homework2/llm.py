"""
llm.py —— LLM 客户端构建与统一调用封装
=========================================
  - 真实模式：ChatOpenAI（OpenAI 兼容协议，可接 DeepSeek/通义/OpenAI/Ollama）；
  - 离线模式：MockLLM（无需 API Key，用确定性结果跑通 Workflow，便于自测）；
  - call_llm：统一的消息构造、重试、日志记录。
"""
from __future__ import annotations

import time
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config import Settings


class LLMError(RuntimeError):
    """LLM 调用在重试后仍然失败时抛出。"""


def build_model(settings: Settings) -> Any:
    """按配置构建模型客户端（离线模式返回 MockLLM）。"""
    if settings.offline:
        # 延迟导入：正常使用时完全不加载 Mock
        from mock_llm import MockLLM  # noqa: PLC0415

        return MockLLM()
    return ChatOpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        temperature=settings.temperature,
        timeout=settings.llm_timeout,
    )


def message_text(message: BaseMessage) -> str:
    """把 AIMessage.content 统一转成纯文本（兼容多段内容结构）。"""
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "\n".join(parts)
    return str(content)


def call_llm(
    model: Any,
    *,
    system_prompt: str,
    user_prompt: str,
    retries: int,
    logger: Any | None = None,
    label: str = "llm",
) -> str:
    """调用模型并返回纯文本；网络抖动/限流时指数退避重试。"""
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    last_error: Exception | None = None

    for attempt in range(1, max(1, retries) + 1):
        started = time.perf_counter()
        try:
            result = model.invoke(messages)
            text = message_text(result).strip() if isinstance(result, BaseMessage) else str(result).strip()
            if not text:
                raise LLMError("模型返回了空内容")
            if logger is not None:
                logger.event(
                    "llm_call",
                    node=label,
                    attempt=attempt,
                    duration_ms=round((time.perf_counter() - started) * 1000),
                    chars=len(text),
                )
            return text
        except Exception as exc:  # 统一收集后重试
            last_error = exc
            if logger is not None:
                logger.event(
                    "llm_error",
                    node=label,
                    level="warning",
                    attempt=attempt,
                    error=str(exc),
                )
            if attempt < retries:
                time.sleep(1.5 * attempt)

    raise LLMError(f"LLM 调用失败（{retries} 次）：{last_error}")


def make_ai_message(text: str) -> AIMessage:
    """供 MockLLM 复用：构造 AIMessage。"""
    return AIMessage(content=text)

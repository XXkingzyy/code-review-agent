"""
coding_agent.py —— 编码 Agent（Workflow 第 1 个节点）
======================================================
职责：把自然语言需求变成一份可运行的初版代码。
输出纪律：只接受 Markdown 代码块，且必须通过 ast 语法门禁；不合格自动重试一次。
"""
from __future__ import annotations

import re

from agents.base import AgentError, BaseAgent
from code_utils import extract_code_block, syntax_error
from prompts import CODING_SYSTEM_PROMPT, build_coding_prompt
from state import WorkflowState


class CodingAgent(BaseAgent):
    """根据需求生成代码的 Agent。"""

    name = "coding_agent"

    def run(self, task: str, language: str, state: WorkflowState) -> str:
        """返回可运行的代码字符串。"""
        retry_note = ""
        last_error = "未知错误"

        for attempt in range(1, 3):
            raw = self.ask(
                state,
                CODING_SYSTEM_PROMPT,
                build_coding_prompt(task, language, retry_note),
                label=f"coding_attempt_{attempt}",
            )
            code = extract_code_block(raw)
            if code is None:
                last_error = "回复中没有找到 ```python 代码块"
                retry_note = last_error
                continue

            error = syntax_error(code, language)
            if error is None:
                return code

            last_error = f"语法错误：{error}"
            retry_note = last_error

        raise AgentError(f"编码 Agent 未能产出合格代码：{last_error}")


def code_stats(code: str) -> str:
    """生成一句便于日志展示的代码摘要。"""
    lines = len(code.splitlines())
    funcs = len(re.findall(r"^\s*def\s+\w+", code, re.MULTILINE))
    return f"{lines} 行，{funcs} 个函数"

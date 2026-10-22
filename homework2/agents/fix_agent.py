"""
fix_agent.py —— 修复 Agent（Workflow 第 3 个节点）
====================================================
职责：根据审查问题清单修改代码，输出完整修复版本。
同样有语法门禁：修复后的代码必须能 ast.parse，否则重试一次。
"""
from __future__ import annotations

from agents.base import AgentError, BaseAgent
from code_utils import extract_code_block, syntax_error
from prompts import FIX_SYSTEM_PROMPT, build_fix_prompt
from state import ReviewResult, WorkflowState


class FixAgent(BaseAgent):
    """根据审查结果修复代码的 Agent。"""

    name = "fix_agent"

    def run(
        self,
        *,
        task: str,
        code: str,
        language: str,
        review: ReviewResult,
        round_no: int,
        state: WorkflowState,
    ) -> str:
        retry_note = ""
        last_error = "未知错误"

        for attempt in range(1, 3):
            raw = self.ask(
                state,
                FIX_SYSTEM_PROMPT,
                build_fix_prompt(
                    task=task,
                    code=code,
                    language=language,
                    review=review,
                    evidence=review.get("evidence", {}),
                )
                + (f"\n\n上一次输出不合格：{retry_note}，请重新输出完整代码块。" if retry_note else ""),
                label=f"fix_round_{round_no}_attempt_{attempt}",
            )
            fixed = extract_code_block(raw)
            if fixed is None:
                last_error = "回复中没有找到代码块"
                retry_note = last_error
                continue

            error = syntax_error(fixed, language)
            if error is None:
                return fixed

            last_error = f"语法错误：{error}"
            retry_note = last_error

        raise AgentError(f"修复 Agent 未能产出合格代码：{last_error}")

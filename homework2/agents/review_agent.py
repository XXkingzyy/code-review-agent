"""
review_agent.py —— 审查 Agent（Workflow 第 2 个节点）
=====================================================
复用作 Homework 1 的 4 个工具中的 3 个：
  - check_python_syntax：语法门禁 + ruff
  - analyze_complexity：复杂度量化
  - run_python_code：实际执行复现运行时 Bug
三个分析互不依赖，用线程池并行执行，缩短审查耗时。

Agent 拿到“源码 + 工具证据”后，由 LLM 输出 Markdown 报告 + JSON 结论，
JSON 里的 score / issues 直接驱动 Workflow 的条件分支。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from agents.base import AgentError, BaseAgent
from prompts import REVIEW_SYSTEM_PROMPT, build_review_prompt
from review_parser import ReviewParseError, parse_review
from state import ReviewResult, WorkflowState
from tools import analyze_complexity, check_python_syntax, run_python_code
from workflow.trace import TraceLogger


class ReviewAgent(BaseAgent):
    """基于工具证据做代码审查的 Agent。"""

    name = "review_agent"

    def run(
        self,
        *,
        task: str,
        code: str,
        language: str,
        round_no: int,
        state: WorkflowState,
    ) -> ReviewResult:
        evidence = self._collect_evidence(code, round_no, state)
        raw = ""
        last_error = "未知错误"

        for attempt in range(1, 3):
            raw = self.ask(
                state,
                REVIEW_SYSTEM_PROMPT,
                build_review_prompt(
                    task=task,
                    code=code,
                    language=language,
                    threshold=self.settings.pass_threshold,
                    evidence=evidence,
                ),
                label=f"review_round_{round_no}_attempt_{attempt}",
            )
            try:
                review = parse_review(raw, self.settings.pass_threshold)
            except ReviewParseError as exc:
                last_error = str(exc)
                continue
            review["evidence"] = evidence
            return review

        raise AgentError(f"审查 Agent 输出无法解析：{last_error}")

    def _collect_evidence(self, code: str, round_no: int, state: WorkflowState) -> dict[str, str]:
        """并行执行三个静态/动态分析工具（复用作业1工具）。"""
        logger = TraceLogger(state["run_dir"])
        logger.event("tool_batch_start", node=self.name, round=round_no)
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {
                "syntax": pool.submit(check_python_syntax.invoke, {"code": code}),
                "complexity": pool.submit(analyze_complexity.invoke, {"code": code}),
                "execution": pool.submit(run_python_code.invoke, {"code": code}),
            }
            evidence: dict[str, str] = {}
            for key, future in futures.items():
                try:
                    evidence[key] = str(future.result())
                except Exception as exc:  # 单个工具失败不影响整体审查
                    evidence[key] = f"[工具执行失败] {exc}"
                logger.event(
                    "tool_result",
                    node=self.name,
                    tool=key,
                    chars=len(evidence[key]),
                    preview=evidence[key][:200],
                )
        logger.event("tool_batch_end", node=self.name, round=round_no)
        return evidence


def summarize_review(review: ReviewResult) -> str:
    """一句话摘要，用于 Agent 消息与日志。"""
    critical = sum(1 for issue in review["issues"] if issue["severity"] == "critical")
    major = sum(1 for issue in review["issues"] if issue["severity"] == "major")
    verdict = "通过" if review["passed"] else "未通过"
    return (
        f"评分 {review['score']:.1f}/10（阈值 {review['threshold']:.1f}），"
        f"{verdict}；严重问题 {critical} 个，改进建议 {major} 个。"
    )


def review_to_record(round_no: int, review: ReviewResult) -> dict[str, Any]:
    """抽取轻量记录，供报告展示评分轨迹。"""
    return {
        "round": round_no,
        "score": review["score"],
        "passed": review["passed"],
        "critical": sum(1 for issue in review["issues"] if issue["severity"] == "critical"),
        "major": sum(1 for issue in review["issues"] if issue["severity"] == "major"),
        "summary": review["summary"],
    }

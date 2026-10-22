"""
test_workflow_offline.py —— 离线端到端测试
============================================
不依赖真实 LLM/API Key，用 MockLLM 验证：
  - 编码 → 审查 → 修复 → 复审 → 通过的完整循环；
  - 从已有代码进入时跳过编码 Agent（条件分支）；
  - 达到最大轮数后正确终止（防止死循环）；
  - LLM 失败时进入 error 状态并生成报告（错误恢复）；
  - 审查 JSON 解析、代码块提取、语法门禁等基础能力。
"""
from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from code_utils import extract_code_block, extract_json_object, syntax_error
from config import load_settings
from review_parser import ReviewParseError, parse_review
from workflow.graph import resume_workflow, run_workflow
from workflow.nodes import route_after_review, route_entry
from workflow.trace import executed_nodes, read_trace


def _settings(tmp_dir: str, *, max_rounds: int = 3, threshold: float = 8.0):
    return load_settings(
        offline=True,
        runs_root=Path(tmp_dir),
        max_rounds=max_rounds,
        pass_threshold=threshold,
    )


class BrokenModel:
    """模拟网络故障的模型：每次调用都抛异常。"""

    def invoke(self, messages):
        raise RuntimeError("模拟网络中断")


class WorkflowOfflineTest(unittest.TestCase):
    def test_full_loop_passes_after_fix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = run_workflow(
                task="实现成绩统计函数",
                language="python",
                code="",
                code_source="task",
                settings=_settings(tmp),
            )
            run_dir = Path(state["run_dir"])

            self.assertEqual(state["status"], "passed")
            self.assertEqual(state["round"], 2)
            self.assertNotIn("cache=[]", state["code"])
            self.assertTrue((run_dir / "90_final_code.py").is_file())
            self.assertTrue((run_dir / "90_final_report.md").is_file())
            self.assertTrue((run_dir / "trace.jsonl").is_file())
            self.assertTrue((run_dir / "31_diff_v1.txt").is_file())
            self.assertTrue(state["diffs"])
            report = (run_dir / "90_final_report.md").read_text(encoding="utf-8")
            self.assertIn("## 4. 代码变更摘要", report)

            senders = {message["sender"] for message in state["messages"]}
            self.assertLessEqual({"coding_agent", "review_agent", "fix_agent", "workflow"}, senders)

            nodes = executed_nodes(run_dir)
            self.assertEqual(nodes[0], "prepare")
            self.assertIn("coding", nodes)
            self.assertIn("fix", nodes)

            trace = read_trace(run_dir)
            review_starts = [
                record for record in trace if record["event"] == "node_start" and record["node"] == "review"
            ]
            self.assertEqual(len(review_starts), 2)
            self.assertTrue(any(record["event"] == "workflow_end" for record in trace))

    def test_existing_code_skips_coding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code = "def add(a, b):\n    return a - b\n"
            state = run_workflow(
                task="审查已有代码",
                language="python",
                code=code,
                code_source="file",
                settings=_settings(tmp),
            )
            nodes = executed_nodes(state["run_dir"])
            self.assertEqual(nodes, ["prepare", "review", "finalize"])
            self.assertEqual(state["status"], "passed")
            self.assertNotIn("coding_agent", {message["sender"] for message in state["messages"]})

    def test_max_rounds_stops_loop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = run_workflow(
                task="实现成绩统计函数",
                language="python",
                code="",
                code_source="task",
                settings=_settings(tmp, max_rounds=2, threshold=10.0),
            )
            self.assertEqual(state["round"], 2)
            self.assertEqual(state["status"], "failed")

    def test_llm_failure_becomes_error_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = replace(_settings(tmp), llm_retries=1)
            state = run_workflow(
                task="实现一个函数",
                language="python",
                code="",
                code_source="task",
                settings=settings,
                model=BrokenModel(),
            )
            self.assertEqual(state["status"], "error")
            self.assertTrue(state["errors"])
            self.assertTrue((Path(state["run_dir"]) / "90_final_report.md").is_file())
            self.assertEqual(executed_nodes(state["run_dir"]), ["prepare", "coding", "finalize"])

    def test_pause_and_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = _settings(tmp)
            state = run_workflow(
                task="实现成绩统计函数",
                language="python",
                code="",
                code_source="task",
                settings=settings,
                pause_before_fix=True,
            )
            run_dir = Path(state["run_dir"])

            self.assertEqual(state["status"], "awaiting_confirmation")
            self.assertEqual(state["round"], 1)
            self.assertTrue((run_dir / "checkpoints.sqlite").is_file())
            self.assertTrue((run_dir / "99_state.json").is_file())
            self.assertEqual(executed_nodes(run_dir), ["prepare", "coding", "review"])

            resumed = resume_workflow(run_dir=str(run_dir), settings=settings)
            self.assertEqual(resumed["status"], "passed")
            self.assertEqual(resumed["round"], 2)
            self.assertTrue(resumed["diffs"])
            self.assertTrue((run_dir / "31_diff_v1.txt").is_file())
            self.assertIn("## 4. 代码变更摘要", (run_dir / "90_final_report.md").read_text(encoding="utf-8"))

    def test_conditional_routing(self) -> None:
        self.assertEqual(route_entry({"status": "running", "code_source": "file", "code": "x"}), "review")
        self.assertEqual(route_entry({"status": "running", "code_source": "task", "code": ""}), "coding")
        self.assertEqual(route_entry({"status": "error"}), "finalize")

        passed = {"status": "reviewing", "round": 1, "max_rounds": 3, "review": {"passed": True}}
        failed = {"status": "reviewing", "round": 1, "max_rounds": 3, "review": {"passed": False}}
        exhausted = {"status": "reviewing", "round": 3, "max_rounds": 3, "review": {"passed": False}}
        self.assertEqual(route_after_review(passed), "finalize")
        self.assertEqual(route_after_review(failed), "fix")
        self.assertEqual(route_after_review(exhausted), "finalize")


class ParsingTest(unittest.TestCase):
    def test_extract_code_block(self) -> None:
        text = "说明\n```python\nprint(1)\n```\n"
        self.assertEqual(extract_code_block(text), "print(1)")
        self.assertIsNone(extract_code_block("没有代码"))

    def test_syntax_gate(self) -> None:
        self.assertIsNone(syntax_error("x = 1\n"))
        self.assertIsNotNone(syntax_error("def f(:\n"))
        self.assertIsNone(syntax_error("def f(:\n", language="java"))

    def test_parse_review_json(self) -> None:
        raw = (
            "## 代码审查报告\n...\n"
            "```json\n"
            '{"score": 7.5, "summary": "有严重问题", '
            '"issues": [{"severity": "critical", "line": "12", "title": "除零", '
            '"detail": "空列表", "suggestion": "加保护"}], '
            '"strengths": ["结构清晰"], "dimensions": {"correctness": 7}}\n'
            "```"
        )
        review = parse_review(raw, 8.0)
        self.assertEqual(review["score"], 7.5)
        self.assertFalse(review["passed"])
        self.assertEqual(review["issues"][0]["line"], 12)
        self.assertEqual(review["issues"][0]["severity"], "critical")
        self.assertIn("代码审查报告", review["markdown"])

    def test_parse_review_without_json_raises(self) -> None:
        with self.assertRaises(ReviewParseError):
            parse_review("只有一段自然语言，没有 JSON", 8.0)

    def test_extract_json_object(self) -> None:
        payload = extract_json_object('前缀 ```json\n{"a": 1, "b": {"c": 2}}\n``` 后缀')
        self.assertEqual(payload, {"a": 1, "b": {"c": 2}})


if __name__ == "__main__":
    unittest.main()

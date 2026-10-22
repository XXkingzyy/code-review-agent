"""
cli.py —— 命令行入口
======================
用法：
    python main.py demo                      # 离线演示（无需 API Key）
    python main.py run -t "实现一个..."       # 从需求开始：编码 → 审查 → 修复
    python main.py run -f examples/bad_code.py   # 从已有代码开始：审查 → 修复
    python main.py run -t "..." --offline    # 离线 Mock 模式
    python main.py run -t "..." --pause      # 每轮修复前暂停，等待人工确认
    python main.py resume runs/<run_id>      # 从暂停点继续执行（断点恢复）
    python main.py web                       # 启动 Web 界面
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from config import Settings, load_settings
from state import WorkflowState
from tools import read_text_file
from workflow import resume_workflow, run_workflow

DEMO_TASK = (
    "实现一个成绩统计函数：输入学生分数列表，计算及格（>=60）成绩的平均分；"
    "要求处理空列表、忽略非数字或超出 0~100 的非法值，并打印示例结果。"
)

_STATUS_TEXT = {
    "passed": "✅ 通过",
    "failed": "❌ 未通过",
    "error": "⚠️ 异常终止",
    "awaiting_confirmation": "⏸ 已暂停（等待人工确认）",
}


def _print_step(node: str, state: WorkflowState) -> None:
    """每个节点结束后打印一行进度。"""
    messages = state.get("messages", [])
    content = messages[-1]["content"] if messages else ""
    round_no = state.get("round", 0)
    prefix = f"[{node}]"
    if node == "review":
        prefix += f" 第 {round_no} 轮"
    print(f"  {prefix} {content}")


def _describe(settings: Settings) -> str:
    mode = "离线 Mock" if settings.offline else f"{settings.llm_model} @ {settings.llm_base_url}"
    return (
        f"模型：{mode}\n"
        f"最大审查轮数：{settings.max_rounds}　通过阈值：{settings.pass_threshold:.1f}/10"
        f"　修复前人工确认：{'开启' if settings.pause_before_fix else '关闭'}"
    )


def _print_result(state: WorkflowState, show_report: bool) -> None:
    """打印一次运行（或恢复）的结果摘要。"""
    status = state.get("status", "")
    status_text = _STATUS_TEXT.get(status, status)
    review = state.get("review") or {}
    run_dir = Path(state.get("run_dir", ""))
    print("-" * 64)
    print(f"最终状态：{status_text}")
    if review:
        print(f"最终评分：{review.get('score', 0):.1f}/10（阈值 {review.get('threshold', 0):.1f}）")
    print(f"审查轮数：{state.get('round', 0)}/{state.get('max_rounds', 0)}")
    if status == "awaiting_confirmation":
        print("最终代码/最终报告：恢复执行结束后生成")
    else:
        print(f"最终代码：{run_dir / '90_final_code.py'}")
        print(f"最终报告：{run_dir / '90_final_report.md'}")
    print(f"执行日志：{run_dir / 'trace.jsonl'}")
    diffs = state.get("diffs", [])
    if diffs:
        for diff in diffs:
            print(f"代码 diff：{run_dir / diff['path']}（+{diff['added']}/-{diff['removed']} 行）")

    if status == "awaiting_confirmation":
        print("\n已暂停在修复前。确认修复方案后，执行以下命令继续：")
        print(f'  python main.py resume "{run_dir}"')

    if show_report and state.get("final_report"):
        print("\n" + state["final_report"])


def _execute(
    task: str,
    code: str,
    code_source: str,
    language: str,
    settings: Settings,
    show_report: bool,
    pause_before_fix: bool | None = None,
) -> int:
    """执行一次 Workflow 并打印结果。"""
    print("=" * 64)
    print("  代码审查 Workflow（编码 → 审查 → 修复）")
    print("=" * 64)
    print(_describe(settings))
    print("-" * 64)

    try:
        state = run_workflow(
            task=task,
            language=language,
            code=code,
            code_source=code_source,
            settings=settings,
            on_node=_print_step,
            pause_before_fix=pause_before_fix,
        )
    except Exception as exc:
        print(f"\n运行失败：{exc}")
        return 1

    _print_result(state, show_report)
    return 0


def _snapshot_offline(run_dir: str) -> bool:
    """读取状态快照，判断该次运行是否使用离线 Mock 模型。"""
    snapshot = Path(run_dir) / "99_state.json"
    try:
        payload = json.loads(snapshot.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(payload.get("offline", False))


def _resume(run_dir: str, offline: bool, show_report: bool) -> int:
    """从暂停点恢复执行。"""
    run_path = Path(run_dir).expanduser().resolve()
    print("=" * 64)
    print("  代码审查 Workflow（从暂停点恢复）")
    print("=" * 64)
    print(f"运行目录：{run_path}")
    try:
        settings = load_settings(offline=offline or _snapshot_offline(str(run_path)))
        state = resume_workflow(
            run_dir=str(run_path),
            settings=settings,
            on_node=_print_step,
        )
    except Exception as exc:
        print(f"\n恢复失败：{exc}")
        return 1

    _print_result(state, show_report)
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(description="代码审查 Workflow（Homework 2）")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="执行一次 Workflow")
    run_parser.add_argument("-t", "--task", default="", help="自然语言需求")
    run_parser.add_argument("-f", "--file", default="", help="已有代码文件（提供后跳过编码 Agent）")
    run_parser.add_argument("--language", default="python", help="代码语言，默认 python")
    run_parser.add_argument("--rounds", type=int, default=None, help="最大审查轮数")
    run_parser.add_argument("--threshold", type=float, default=None, help="通过阈值（0~10）")
    run_parser.add_argument("--offline", action="store_true", help="使用离线 Mock 模型（无需 API Key）")
    run_parser.add_argument("--pause", action="store_true", help="每轮修复前暂停，等待人工确认")
    run_parser.add_argument("--report", action="store_true", help="运行结束后打印完整报告")

    demo_parser = sub.add_parser("demo", help="离线演示：跑通编码→审查→修复循环")
    demo_parser.add_argument("--rounds", type=int, default=3, help="最大审查轮数")
    demo_parser.add_argument("--threshold", type=float, default=8.0, help="通过阈值")
    demo_parser.add_argument("--pause", action="store_true", help="每轮修复前暂停，等待人工确认")
    demo_parser.add_argument("--report", action="store_true", help="打印完整报告")

    resume_parser = sub.add_parser("resume", help="从暂停点恢复执行")
    resume_parser.add_argument("run_dir", help="暂停运行的目录（runs/<run_id>）")
    resume_parser.add_argument("--offline", action="store_true", help="强制离线 Mock 模型")
    resume_parser.add_argument("--report", action="store_true", help="运行结束后打印完整报告")

    web_parser = sub.add_parser("web", help="启动 Web 界面")
    web_parser.add_argument("--offline", action="store_true", help="强制离线 Mock 模式")
    web_parser.add_argument("--port", type=int, default=7860, help="端口，默认 7860")

    args = parser.parse_args(argv)

    if args.command == "web":
        from ui.web import main as web_main  # noqa: PLC0415

        return web_main(offline_default=args.offline, port=args.port)

    if args.command == "resume":
        return _resume(args.run_dir, args.offline, args.report)

    if args.command == "demo":
        settings = load_settings(
            offline=True,
            max_rounds=args.rounds,
            pass_threshold=args.threshold,
            pause_before_fix=args.pause or None,
        )
        return _execute(DEMO_TASK, "", "task", "python", settings, args.report, args.pause or None)

    # run
    task = args.task.strip()
    file_path = args.file.strip()
    code = ""
    code_source = "task"
    if file_path:
        try:
            code = read_text_file(file_path)
        except Exception as exc:
            print(f"读取代码文件失败：{exc}")
            return 1
        code_source = "file"
        task = task or f"审查并修复已有代码：{file_path}"
    if not task:
        parser.error("run 至少需要 -t/--task 或 -f/--file 之一")

    try:
        settings = load_settings(
            offline=args.offline,
            max_rounds=args.rounds,
            pass_threshold=args.threshold,
            pause_before_fix=args.pause or None,
        )
    except RuntimeError as exc:
        print(f"配置错误：{exc}")
        return 1
    return _execute(task, code, code_source, args.language, settings, args.report, args.pause or None)


if __name__ == "__main__":
    sys.exit(main())

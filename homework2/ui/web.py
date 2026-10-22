"""
web.py —— Gradio Web 界面
===========================
一个页面完成：
  1. 输入需求或指定已有代码文件；
  2. 一键执行 Workflow，进度条实时提示当前节点；
  3. 查看流程图、最终报告、最终代码、执行日志、Agent 间消息；
  4. 下载本次运行的全部产物。
"""
from __future__ import annotations

import json
from pathlib import Path

import gradio as gr

from config import has_real_api_key, load_settings
from state import WorkflowState
from tools import read_text_file
from ui.svg import render_workflow_html
from workflow import read_trace, run_workflow

DEMO_TASK = (
    "实现一个成绩统计函数：输入学生分数列表，计算及格（>=60）成绩的平均分；"
    "要求处理空列表、忽略非数字或超出 0~100 的非法值，并打印示例结果。"
)

CSS = """
.gradio-container {max-width: 1280px !important;}
#wf-status {min-height: 120px;}
footer {visibility: hidden;}
"""


def _artifact_files(run_dir: str) -> list[str]:
    """列出本次运行生成的可下载文件。"""
    root = Path(run_dir)
    if not root.is_dir():
        return []
    preferred = [
        "90_final_report.md",
        "90_final_code.py",
        "20_review_v1.md",
        "20_review_v2.md",
        "20_review_v3.md",
        "trace.jsonl",
        "99_state.json",
    ]
    files = [root / name for name in preferred if (root / name).is_file()]
    return [str(path) for path in files]


def _trace_rows(run_dir: str) -> list[list[str]]:
    """把 JSONL 日志转成表格行。"""
    rows: list[list[str]] = []
    for record in read_trace(run_dir):
        extra = {
            key: value
            for key, value in record.items()
            if key not in ("time", "event", "node", "level")
        }
        summary = json.dumps(extra, ensure_ascii=False) if extra else ""
        rows.append(
            [
                str(record.get("time", "")),
                str(record.get("node") or "-"),
                str(record.get("event", "")),
                str(record.get("level", "info")),
                summary[:180],
            ]
        )
    return rows[-200:]


def _run_click(
    task: str,
    file_path: str,
    language: str,
    rounds: int,
    threshold: float,
    offline: bool,
    progress: gr.Progress = gr.Progress(),  # noqa: B008  Gradio 依赖此默认值注入进度条
):
    """Web 端“运行”按钮的回调。"""
    task = (task or "").strip()
    file_path = (file_path or "").strip()
    if not task and not file_path:
        raise gr.Error("请填写需求描述，或指定一个已有代码文件")

    try:
        settings = load_settings(
            offline=bool(offline),
            max_rounds=int(rounds),
            pass_threshold=float(threshold),
        )
    except RuntimeError as exc:
        raise gr.Error(str(exc)) from exc

    code = ""
    code_source = "task"
    if file_path:
        try:
            code = read_text_file(file_path)
        except Exception as exc:
            raise gr.Error(f"读取文件失败：{exc}") from exc
        code_source = "file"
        task = task or f"审查并修复已有代码：{file_path}"

    progress(0.05, desc="启动 Workflow")
    step = {"count": 0}

    def on_node(node: str, state: WorkflowState) -> None:
        step["count"] += 1
        progress(min(0.95, 0.08 + 0.09 * step["count"]), desc=f"{node} 完成")

    try:
        state = run_workflow(
            task=task,
            language=language,
            code=code,
            code_source=code_source,
            settings=settings,
            on_node=on_node,
        )
    except Exception as exc:
        raise gr.Error(f"Workflow 运行失败：{exc}") from exc

    status_html = render_workflow_html(state)
    review = state.get("review") or {}
    if review:
        status_html += (
            f'<div style="margin-top:8px;font-size:13px;color:#595959">'
            f"最终评分：<b>{review.get('score', 0):.1f}/10</b>　"
            f"审查轮数：{state.get('round', 0)}/{state.get('max_rounds', 0)}　"
            f"运行目录：<code>{state.get('run_dir', '')}</code></div>"
        )

    return (
        status_html,
        state.get("final_report", ""),
        state.get("code", ""),
        _trace_rows(state["run_dir"]),
        state.get("messages", []),
        _artifact_files(state["run_dir"]),
    )


def main(offline_default: bool = False, port: int = 7860) -> int:
    """启动 Gradio 应用。"""
    default_offline = offline_default or not has_real_api_key()

    with gr.Blocks(title="代码审查 Workflow") as demo:
        gr.Markdown(
            "## 🔁 代码审查 Workflow\n"
            "三个 Agent 协作：**编码 Agent → 审查 Agent → 修复 Agent**；"
            "审查未通过会自动进入修复循环，直到通过或达到最大轮数。"
        )
        with gr.Row():
            with gr.Column(scale=4):
                task_input = gr.Textbox(
                    label="需求描述（从需求开始时填写）",
                    value=DEMO_TASK,
                    lines=5,
                    placeholder="例如：实现一个带边界检查的 LRU 缓存",
                )
                file_input = gr.Textbox(
                    label="已有代码文件路径（可选，填写后跳过编码 Agent）",
                    value="",
                    placeholder=r"例如：examples/bad_code.py",
                )
                language_input = gr.Dropdown(
                    label="目标语言",
                    choices=["python", "java", "javascript", "go"],
                    value="python",
                )
                with gr.Row():
                    rounds_input = gr.Slider(1, 5, value=3, step=1, label="最大审查轮数")
                    threshold_input = gr.Slider(0, 10, value=8.0, step=0.5, label="通过阈值")
                offline_input = gr.Checkbox(
                    value=default_offline,
                    label="离线 Mock 模式（无需 API Key，仅用于流程自测）",
                )
                run_button = gr.Button("▶ 运行 Workflow", variant="primary")
                gr.Markdown(
                    "<small>真实模式请配置 `.env`（参考 `.env.example`）。"
                    "离线模式仅用确定性规则模拟 LLM，便于验证流程本身。</small>"
                )

            with gr.Column(scale=7):
                status_output = gr.HTML(elem_id="wf-status")
                with gr.Tabs():
                    with gr.Tab("最终报告"):
                        report_output = gr.Markdown()
                    with gr.Tab("最终代码"):
                        code_output = gr.Code(language="python", lines=22, label="最终代码")
                    with gr.Tab("执行日志"):
                        trace_output = gr.Dataframe(
                            headers=["时间", "节点", "事件", "级别", "摘要"],
                            datatype=["str", "str", "str", "str", "str"],
                            value=[],
                            interactive=False,
                            wrap=True,
                        )
                    with gr.Tab("Agent 消息"):
                        messages_output = gr.JSON(label="Agent 间传递的结构化消息")
                    with gr.Tab("产物下载"):
                        files_output = gr.File(file_count="multiple", label="本次运行产物")

        run_button.click(
            fn=_run_click,
            inputs=[task_input, file_input, language_input, rounds_input, threshold_input, offline_input],
            outputs=[
                status_output,
                report_output,
                code_output,
                trace_output,
                messages_output,
                files_output,
            ],
        )

    demo.launch(server_name="127.0.0.1", server_port=port, share=False)
    return 0

"""
svg.py —— Workflow 可视化（内联 SVG，无需前端依赖）
======================================================
把 LangGraph 的节点执行情况画成一张流程图：
  - 已执行节点显示绿色，出错的节点显示红色，未执行显示灰色；
  - 箭头标注条件分支（仅需求 / 已有代码 / 未通过 / 通过）；
  - 底部显示实际执行顺序，例如 prepare → coding → review → fix → review → finalize。
"""
from __future__ import annotations

import html

from state import WorkflowState
from workflow.trace import executed_nodes, read_trace

# 画布尺寸与节点坐标
_WIDTH = 700
_HEIGHT = 330
_BOXES = {
    "prepare": (20, 120, 120, 60),
    "coding": (180, 120, 120, 60),
    "review": (340, 120, 120, 60),
    "fix": (340, 240, 120, 60),
    "finalize": (540, 120, 120, 60),
}
_LABELS = {
    "prepare": "准备",
    "coding": "编码 Agent",
    "review": "审查 Agent",
    "fix": "修复 Agent",
    "finalize": "收尾",
}


def _box_style(node: str, executed: set[str], errored: set[str], final_status: str) -> tuple[str, str]:
    """返回节点的填充色与描边色。"""
    if node in errored:
        return "#fff1f0", "#cf1322"
    if node == "finalize" and final_status in ("passed", "failed", "error"):
        return ("#f6ffed", "#52c41a") if final_status == "passed" else ("#fff1f0", "#cf1322")
    if node in executed:
        return "#f6ffed", "#52c41a"
    return "#fafafa", "#bfbfbf"


def _box(node: str, executed: set[str], errored: set[str], final_status: str) -> str:
    x, y, w, h = _BOXES[node]
    fill, stroke = _box_style(node, executed, errored, final_status)
    status = "未执行"
    if node in errored:
        status = "出错"
    elif node in executed:
        status = "已执行"
    label = html.escape(_LABELS[node])
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="2"/>'
        f'<text x="{x + w / 2}" y="{y + 26}" text-anchor="middle" font-size="15" '
        f'font-weight="600" fill="#262626">{label}</text>'
        f'<text x="{x + w / 2}" y="{y + 45}" text-anchor="middle" font-size="11" '
        f'fill="#8c8c8c">{status}</text>'
    )


def _arrow(x1: int, y1: int, x2: int, y2: int, label: str = "", color: str = "#8c8c8c") -> str:
    """带箭头的直线。"""
    mid_x = (x1 + x2) / 2
    mid_y = (y1 + y2) / 2
    text = (
        f'<text x="{mid_x}" y="{mid_y - 6}" text-anchor="middle" font-size="11" fill="{color}">'
        f"{html.escape(label)}</text>"
        if label
        else ""
    )
    return (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="1.6" '
        f'marker-end="url(#arrow)"/>'
        f"{text}"
    )


def _path(d: str, label: str = "", label_x: int = 0, label_y: int = 0) -> str:
    """带箭头的折线路径。"""
    text = (
        f'<text x="{label_x}" y="{label_y}" text-anchor="middle" font-size="11" fill="#8c8c8c">'
        f"{html.escape(label)}</text>"
        if label
        else ""
    )
    return f'<path d="{d}" fill="none" stroke="#8c8c8c" stroke-width="1.6" marker-end="url(#arrow)"/>{text}'


def render_workflow_html(state: WorkflowState) -> str:
    """生成可直接放进 Gradio gr.HTML 的 HTML 片段。"""
    trace = read_trace(state["run_dir"])
    executed = set(executed_nodes(state["run_dir"]))
    errored = {
        record.get("node", "")
        for record in trace
        if record.get("level") == "error" and record.get("node")
    }
    final_status = state.get("status", "running")

    boxes = "".join(_box(node, executed, errored, final_status) for node in _BOXES)
    arrows = "".join(
        [
            _arrow(140, 150, 180, 150, "仅需求"),
            _path("M 80 120 L 80 70 L 400 70 L 400 116", "已有代码", 240, 62),
            _arrow(300, 150, 340, 150),
            _arrow(400, 180, 400, 240, "未通过"),
            _arrow(460, 150, 540, 150, "通过 / 达上限"),
            _path("M 340 270 L 300 270 L 300 200 L 336 200", "复审", 300, 288),
        ]
    )
    order = " → ".join(executed_nodes(state["run_dir"])) or "（尚未执行）"
    status_text = {
        "passed": "✅ 最终状态：通过",
        "failed": "❌ 最终状态：未通过",
        "error": "⚠️ 最终状态：流程异常",
    }.get(final_status, "⏳ 运行中/待运行")

    svg = (
        f'<svg viewBox="0 0 {_WIDTH} {_HEIGHT}" width="100%" style="max-width:760px" '
        f'xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Workflow 流程图">'
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" '
        'markerHeight="6" orient="auto-start-reverse">'
        '<path d="M 0 0 L 10 5 L 0 10 z" fill="#8c8c8c"/></marker></defs>'
        f"{arrows}{boxes}"
        f'<text x="20" y="315" font-size="12" fill="#595959">执行顺序：{html.escape(order)}</text>'
        f"</svg>"
    )
    return (
        '<div style="font-family: \'Microsoft YaHei\', \'PingFang SC\', sans-serif; '
        'background:#ffffff;border:1px solid #f0f0f0;border-radius:12px;padding:14px;">'
        f'<div style="font-size:15px;font-weight:600;color:#262626;margin-bottom:6px">'
        f"Workflow 执行状态　{html.escape(status_text)}</div>"
        f"{svg}</div>"
    )

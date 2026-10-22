"""
trace.py —— 执行日志与状态追踪
================================
每次运行都会在 runs/<run_id>/trace.jsonl 中追加一条结构化事件：
    节点开始/结束、LLM 调用、工具调用、错误、最终状态。

设计动机：
  - Workflow 是黑盒，出问题时需要知道“卡在哪个节点、用了多久、报了什么错”；
  - JSONL 逐行追加，天然支持运行中实时查看，也方便后续做可视化。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from state import now_iso


class TraceLogger:
    """往指定运行目录的 trace.jsonl 追加事件。"""

    def __init__(self, run_dir: str | Path) -> None:
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.run_dir / "trace.jsonl"

    def event(
        self,
        event: str,
        *,
        node: str | None = None,
        level: str = "info",
        **data: Any,
    ) -> dict[str, Any]:
        """写入一条事件，返回该事件（方便调用方复用）。"""
        record: dict[str, Any] = {
            "time": now_iso(),
            "event": event,
            "node": node,
            "level": level,
            **data,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        return record


def read_trace(run_dir: str | Path) -> list[dict[str, Any]]:
    """读取一次运行的全部事件；文件不存在时返回空列表。"""
    path = Path(run_dir) / "trace.jsonl"
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                # 单行损坏不应影响整体日志读取
                continue
    return records


def executed_nodes(run_dir: str | Path) -> list[str]:
    """从日志中提取实际执行过的节点顺序（按首次出现去重）。"""
    order: list[str] = []
    for record in read_trace(run_dir):
        node = record.get("node")
        if record.get("event") == "node_start" and node and node not in order:
            order.append(node)
    return order

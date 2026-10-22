"""
main.py —— 项目统一入口
=========================
用法：
    python main.py demo                         # 离线演示（无需 Key）
    python main.py run -t "需求描述"             # 真实 LLM：编码→审查→修复
    python main.py run -f examples/bad_code.py  # 审查已有代码
    python main.py web                          # Web 界面
"""
from __future__ import annotations

import sys

from ui.cli import main

if __name__ == "__main__":
    sys.exit(main())

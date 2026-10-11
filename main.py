"""
main.py —— 项目统一入口
=========================
用法：
    python main.py            # 启动命令行交互（默认）
    python main.py web        # 启动 Gradio Web 界面
"""
import sys  # 读命令行参数


def main():                                         # 入口函数
    # 根据命令行第二个参数决定走 CLI 还是 Web
    mode = sys.argv[1] if len(sys.argv) > 1 else "cli"  # 默认 cli
    if mode == "web":                               # 用户要 Web
        from ui.web import main as web_main  # noqa: PLC0415 —— 延迟导入：纯 CLI 用户不想加载 gradio
        web_main()                                  # 启动 Web
    else:                                           # 默认走 CLI
        from ui.cli import main as cli_main  # noqa: PLC0415 —— 延迟导入：仅在运行时按需加载
        cli_main()                                  # 启动命令行


if __name__ == "__main__":                          # 直接运行本文件
    main()

"""
cli.py —— 命令行交互入口
==========================
直接在终端里和 Agent 聊天，输入文件路径即可触发审查。
"""
from agent.code_review_agent import CodeReviewAgent  # 导入主 Agent 类


def main():                                        # 命令行主函数
    print("=" * 60)                               # 分隔线
    print("  代码审查 Agent（输入 exit 退出，reset 清空记忆）")  # 欢迎语
    print("=" * 60)                               # 分隔线
    agent = CodeReviewAgent()                      # 初始化 Agent（会读 .env）
    while True:                                    # 死循环直到用户退出
        try:
            user = input("\n你 > ").strip()        # 读一行用户输入
        except (EOFError, KeyboardInterrupt):      # Ctrl+C / Ctrl+D
            print("\n再见！")                      # 告别
            break                                  # 退出循环
        if not user:                              # 空输入
            continue                              # 跳过
        if user.lower() in ("exit", "quit"):      # 退出命令
            print("再见！")
            break
        if user.lower() == "reset":               # 重置命令
            agent.reset()                          # 清空记忆
            print("[已清空上下文记忆]")
            continue
        # 调用 Agent 并打印结果
        print("\nAgent 正在审查中...\n")            # 提示
        reply = agent.chat(user)                  # 调 Agent
        print("Agent > " + reply)                 # 打印回复


if __name__ == "__main__":                          # 直接运行本文件时启动 CLI
    main()

"""
web.py —— Gradio Web 界面入口
================================
起一个本地网页，浏览器里就能和 Agent 对话，方便演示。
"""
import gradio as gr  # Gradio Web UI 框架

from agent.code_review_agent import CodeReviewAgent  # 导入主 Agent

# 模块级单例：整个 Web 应用共用一个 Agent 实例（保留上下文记忆）
_agent = None                                       # 懒加载：第一次对话时才初始化


def _get_agent():                                  # 懒加载工厂
    global _agent  # noqa: PLW0603 —— 故意用模块级 global 实现单例：Web 服务整个生命周期只建一个 Agent
    if _agent is None:                             # 还没初始化
        _agent = CodeReviewAgent()                # 新建 Agent
    return _agent                                  # 返回单例


def respond(message, history):                     # Gradio 回调：用户发消息时调用
    """把 Gradio 的对话格式转成 Agent 调用，并把完整对话返回网页。

    注意：Gradio 6 的 Chatbot 强制 messages 格式且 postprocess 只接受
    **消息列表**（list[{"role","content"}]）。必须把用户消息 + 助手回复
    拼成列表整体返回，单条 dict 或纯字符串都会被拒绝。
    """
    agent = _get_agent()                          # 拿到 Agent 单例
    reply = agent.chat(message)                   # 调 Agent（同步、一次性返回）
    history = (history or []) + [                 # 现有历史 + 本轮两条新消息
        {"role": "user", "content": message},     # 用户提问
        {"role": "assistant", "content": reply},  # Agent 回复
    ]
    return history                                # 返回完整消息列表


def reset_chat():                                  # "清空对话"按钮回调
    _get_agent().reset()                           # 清 Agent 记忆
    return []                                      # 同时清空 Gradio 界面


def main():                                        # 启动 Web 服务
    # 用 Gradio Blocks 自定义界面布局
    with gr.Blocks(title="代码审查 Agent") as demo:
        gr.Markdown("## 🔍 代码审查 Agent\n输入文件路径（如 `examples/bad_code.py`）即可开始审查。")  # 标题
        chatbot = gr.Chatbot(height=500)  # 聊天窗口（Gradio 6 默认即 messages 消息格式）
        msg = gr.Textbox(placeholder="说点什么，例如：帮我审查 examples/bad_code.py")  # 输入框
        clear = gr.Button("清空对话")               # 清空按钮
        # 绑定事件：用户按回车 → respond → 追加到聊天
        msg.submit(respond, [msg, chatbot], [chatbot]).then(lambda: "", None, msg)
        # 绑定事件：点清空按钮 → 重置 Agent + 清空界面
        clear.click(reset_chat, None, chatbot)
    # 起本地服务：share=False 只本机访问；想要公网链接改 True
    demo.launch(server_name="127.0.0.1", server_port=7860, share=False)


if __name__ == "__main__":                          # 直接运行本文件时启动 Web
    main()

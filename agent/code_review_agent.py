"""
code_review_agent.py —— 代码审查 Agent 主类
==============================================
职责：
  1. 从环境变量加载 LLM 配置；
  2. 装配所有工具（读文件 / 语法检查 / 执行 / 复杂度）；
  3. 用 LangChain 1.x 的 create_agent（基于 LangGraph）跑 Agent 循环；
  4. 用消息列表实现上下文记忆，外加指数退避重试；
  5. 对外暴露 chat() / reset() 两个方法给 CLI / Web 调用。
"""
import os  # 读环境变量
import time  # 指数退避重试时暂停等待

from dotenv import load_dotenv  # 从 .env 加载环境变量
from langchain.agents import create_agent  # LangChain 1.x 的 Agent 工厂（内部是 LangGraph）
from langchain_core.messages import HumanMessage  # 消息类型：用户提问

# === LangChain 组件 ===
from langchain_openai import ChatOpenAI  # OpenAI 兼容聊天模型

from agent.prompts import SYSTEM_PROMPT  # 系统提示词（Agent 人设与工作流程）

# === 本项目内部模块 ===
from tools.code_executor import run_python_code  # 工具3：执行代码
from tools.complexity_analyzer import analyze_complexity  # 工具4：复杂度
from tools.file_reader import read_code_file  # 工具1：读文件
from tools.syntax_checker import check_python_syntax  # 工具2：语法检查


class CodeReviewAgent:  # 封装成一个类，方便 CLI/Web 共用
    """代码审查 Agent：对外暴露 chat() 与 reset() 两个方法。"""

    def __init__(self):  # 构造函数：初始化 LLM、工具、Agent 图、记忆
        load_dotenv()  # 先加载项目根目录下的 .env
        # --- 0. 校验 API Key 是否仍是占位符（未填写时提前给出明确提示）---
        api_key = os.environ.get("LLM_API_KEY", "")  # 读取 Key
        if not api_key or "在这里填" in api_key or api_key.startswith("sk-在这里"):  # 占位特征
            raise RuntimeError(
                "❌ 尚未配置真实的 LLM_API_KEY。\n"
                "请复制 .env.example 为 .env，填入你的 DeepSeek/OpenAI/通义 Key，例如：\n"
                "LLM_API_KEY=sk-你的真实Key"
            )  # 直接抛出，让 CLI/Web 启动时一眼看到
        # --- 1. 构造 LLM 客户端（OpenAI 兼容协议，可接 DeepSeek/通义/Ollama）---
        self.llm = ChatOpenAI(
            base_url=os.environ["LLM_BASE_URL"],  # 服务地址（从 .env 读）
            api_key=os.environ["LLM_API_KEY"],  # API Key
            model=os.environ["LLM_MODEL"],  # 模型名
            temperature=0.2,  # 低温：代码审查要稳定、少发挥
            timeout=30,  # 单次请求 30s 超时
        )
        # --- 2. 把所有工具装进一个列表 ---
        self.tools = [
            read_code_file,  # 读文件
            check_python_syntax,  # 语法检查
            run_python_code,  # 执行代码
            analyze_complexity,  # 复杂度分析
        ]
        # --- 3. 用 create_agent 创建"工具调用型 Agent"（LangGraph 图）---
        #    它自动实现"推理 → 调工具 → 再推理"循环，直到模型认为信息足够
        self.agent = create_agent(
            model=self.llm,  # 用哪个模型推理
            tools=self.tools,  # 可以调哪些工具
            system_prompt=SYSTEM_PROMPT,  # 系统提示词（人设 + 流程 + 输出格式）
            name="code_review_agent",  # 图的名字（仅用于日志/追踪）
        )
        # --- 4. 上下文记忆：用消息列表保存对话历史 ---
        #    create_agent 每次 invoke 都接收"到目前为止的全部消息"，
        #    我们把历史消息累加在 self.messages 里，天然实现多轮记忆
        self.messages: list = []  # 消息历史：交替存放 HumanMessage / AIMessage

    def chat(self, user_input: str) -> str:  # 对外：发一句话，拿一段回复
        """与 Agent 对话；内部自动跑 Agent 循环（最多 MAX_ITERATIONS 轮）。

        参数：
            user_input：用户输入，例如 "帮我审查 examples/bad_code.py"
        返回：
            Agent 最终的文本结论（审查报告）
        """
        # 1. 把用户提问追加进历史（模拟 Agent 循环的"输入"环节）
        self.messages.append(HumanMessage(content=user_input))
        # 2. 读配置：最大循环轮数 / 重试次数（默认 8 轮、3 次）
        max_iter = int(os.environ.get("MAX_ITERATIONS", "8"))  # LangGraph 递归上限
        max_retry = int(os.environ.get("MAX_RETRIES", "3"))  # 网络重试次数
        # 3. 带重试地跑 Agent：网络抖动/限流时自动重试
        last_err = None  # 记录最后一次错误
        for attempt in range(1, max_retry + 1):  # 尝试 1..N 次
            try:
                # invoke：传入全部历史消息；recursion_limit 控制工具调用轮数上限
                result = self.agent.invoke(
                    {"messages": self.messages},  # 输入：整个对话历史
                    config={"recursion_limit": max_iter},  # 最多循环 max_iter 轮防死循环
                )
                # 结果里最后一条消息就是 Agent 的最终回复
                final_msg = result["messages"][-1]  # AIMessage
                self.messages.append(final_msg)  # 4. 把回复存进历史（实现"上下文记忆"）
                return final_msg.content  # 返回纯文本回复
            except Exception as ex:  # 捕获任何异常（网络/限流/解析）
                last_err = ex  # 记下来
                if attempt < max_retry:  # 还有重试机会
                    time.sleep(1.5 * attempt)  # 指数退避：1.5s, 3s, 4.5s
                    continue
        # 4. 重试用尽还失败：把刚才那条提问弹出历史（避免污染记忆），返回友好错误
        self.messages.pop()  # 移除失败的 HumanMessage
        return f"[Agent 暂时不可用] 连续 {max_retry} 次调用失败：{last_err}\n请检查网络/API Key 是否正确。"

    def reset(self):  # 对外：清空记忆，重新开始
        """清空当前会话的上下文记忆。"""
        self.messages = []  # 直接把消息历史置空

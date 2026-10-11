# 代码审查 Agent（Code Review Agent）

> 课程作业 Homework 1 —— 一个会自己读文件、跑语法检查、执行代码、分析复杂度，然后给出审查报告的智能代码助手。

---

## 1. 它能干什么

你用自然语言说一句「帮我审查 `examples/bad_code.py`」，Agent 会自动：

1. **读文件**：用 `read_code_file` 工具把源码连同行号读进来；
2. **查语法**：用 `check_python_syntax` 工具跑 AST 解析 + ruff 静态检查；
3. **量复杂度**：用 `analyze_complexity` 工具统计函数数、圈复杂度、最长函数；
4. **跑一下**：必要时用 `run_python_code` 工具在子进程里执行，复现运行时 Bug；
5. **出报告**：按「严重问题 / 改进建议 / 优点 / 评分」四段式输出中文审查报告。

它不是一次性把 prompt 发给 LLM 就完事，而是真正体现 **输入 → 推理 → 工具调用 → 再推理 → 输出** 的 Agent 循环。

---

## 2. 快速开始

### 2.1 安装依赖

建议 Python 3.10+：

```bash
pip install -r requirements.txt
```

### 2.2 配置 LLM

复制 `.env.example` 为 `.env`，填入你的 LLM 配置：

```env
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=sk-你的Key
LLM_MODEL=deepseek-chat
```

兼容任何 OpenAI 协议的服务：DeepSeek、通义千问（DashScope 兼容模式）、OpenAI、本地 Ollama（`http://localhost:11434/v1`）都行。

### 2.3 启动

```bash
# 命令行模式（默认）
python main.py

# Web 界面模式（浏览器打开 http://127.0.0.1:7860）
python main.py web
```

### 2.4 试一下

```
你 > 帮我审查 examples/bad_code.py
```

Agent 会自动跑一整套工具，最后输出结构化审查报告。也可以继续追问：

```
你 > 那个除零风险具体在第几行？怎么改？
```

（因为开了上下文记忆，它记得你刚才审的是哪个文件。）

---

## 3. 项目结构

```
code-review-agent/
├── main.py                     # 统一入口：python main.py [web]
├── requirements.txt            # 依赖清单
├── .env.example                # 环境变量模板
├── README.md                   # 本文件
├── Design.md                   # 设计文档（架构、Prompt、工具设计）
├── agent/                      # Agent 核心
│   ├── code_review_agent.py   #   主类：装配 LLM / 工具 / 记忆 / 重试
│   ├── prompts.py              #   系统提示词（角色、流程、输出格式）
│   └── memory（已内置）        #   上下文记忆：消息列表累加实现
├── tools/                      # 工具集（Agent 可调用的"手"）
│   ├── file_reader.py          #   读代码文件（带行号、大小截断）
│   ├── syntax_checker.py      #   AST 语法检查 + ruff
│   ├── code_executor.py        #   子进程执行（带超时）
│   └── complexity_analyzer.py  #   静态复杂度/结构分析
├── ui/                         # 交互层
│   ├── cli.py                  #   命令行聊天
│   └── web.py                  #   Gradio Web 聊天
└── examples/
    └── bad_code.py             # 一段故意写得很差的示例代码
```

---

## 4. 已实现的作业要求对照

| 作业要求 | 本项目对应实现 |
|---|---|
| 基本 Agent 循环：输入→推理→工具调用→输出 | `create_agent`（LangGraph）驱动，`recursion_limit` 限制最多 8 轮 |
| 至少一种工具 | 4 种工具：读文件 / 语法检查 / 执行代码 / 复杂度分析 |
| 命令行或 Web 交互 | 两者都有：`python main.py`（CLI）、`python main.py web`（Gradio） |
| 主流 Agent 框架 | LangChain 1.x（`langchain.agents.create_agent`，内部为 LangGraph 图） |
| LLM 原生 API | `ChatOpenAI`，OpenAI 兼容协议，可切任意厂商 |
| 上下文记忆 | 消息列表（HumanMessage/AIMessage）累加，每轮全量注入 |
| 错误处理与重试 | 主类 `chat()` 里指数退避重试 3 次；invoke 异常有兜底 |
| 功能完整 + 边界处理 | 文件不存在/超大、语法错、执行超时、API 失败均有兜底 |
| 代码质量 | 模块化分层、每个工具独立、逐行中文注释、ruff 全绿 |
| 文档 | README.md + Design.md |

---

## 5. 常见问题

**Q：报 `APIConnectionError`？**
A：检查 `.env` 里的 `LLM_BASE_URL` 是否能连通，公司网络/代理可能需要单独配置。

**Q：想换成本地模型？**
A：把 `LLM_BASE_URL` 改成 `http://localhost:11434/v1`，`LLM_MODEL` 改成你 `ollama list` 里的模型名，`LLM_API_KEY` 随便填。

**Q：执行代码安全吗？**
A：作业演示用的是子进程 + 超时，不是真正的容器沙箱，**只跑你自己信任的代码**。

# Design.md —— 代码审查 Agent 设计文档

> 课程：Agent 开发基础 · 作业 1
> 方向：**代码审查 Agent**（分析代码质量、发现潜在 Bug、给出改进建议）

---

## 1. 设计目标

做一个「能像真正的高级工程师那样 Review 代码」的 Agent，而不是把整份代码直接塞进 prompt 让 LLM 一次性看完。核心区别在于：

- **会用工具**：LLM 自己决定要不要读文件、要不要跑一下、要不要量复杂度；
- **有记忆**：记得上一轮在审哪个文件、用户追问的是哪一行；
- **可恢复**：API 抖动、解析失败能自动重试，不会整个崩掉；
- **可演示**：CLI 和 Web 两种入口都能跑。

---

## 2. 整体架构

```
┌─────────────┐    用户输入     ┌──────────────────┐
│   CLI / Web │ ─────────────▶ │  CodeReviewAgent │
└─────────────┘                 │  (AgentExecutor) │
                                └────────┬─────────┘
                                         │ 推理决定调哪个工具
              ┌──────────────┬───────────┼───────────┬──────────────┐
              ▼              ▼           ▼           ▼              ▼
        read_code_file  check_syntax  run_python  analyze_complexity  (LLM 总结)
              │              │           │           │
              ▼              ▼           ▼           ▼
          文件内容        AST/ruff    stdout/err   复杂度指标
              └──────────────┴───────────┴───────────┘
                                         │
                                         ▼
                                 结构化审查报告（中文）
```

技术选型：

| 层 | 选型 | 理由 |
|---|---|---|
| Agent 框架 | **LangChain 1.x** `langchain.agents.create_agent`（内部是 LangGraph 图） | 作业推荐项；原生支持"推理→调工具"循环 |
| LLM | `ChatOpenAI`（OpenAI 兼容协议） | 一套接口可接 DeepSeek/通义/OpenAI/Ollama，灵活 |
| 记忆 | 消息列表（HumanMessage/AIMessage）累加，每轮全量注入 | create_agent 以 messages 为输入，天然支持多轮上下文 |
| UI | CLI（标准库 `input`） + Gradio | 零成本起一个能演示的网页 |
| 静态分析 | `ast` 标准库 + 可选 `ruff` | ast 零依赖；ruff 是现代 Python 事实标准 linter |

---

## 3. Agent 循环

每一次 `agent.chat(user_input)` 内部都跑这样一个循环（由 LangGraph 图驱动）：

```
用户输入
   │
   ▼
追加为 HumanMessage 到消息历史
   │
   ▼
LLM 推理（系统提示词 + 全部历史消息 + 工具描述）
   │
   ├── 觉得该调工具？──▶ 调用对应工具 ──▶ 把工具结果作为 ToolMessage 追加 ──▶ 回到 LLM 推理
   │
   └── 觉得信息够了？──▶ 输出最终自然语言报告 ──▶ 存为 AIMessage 返回给用户
```

关键参数：

- `recursion_limit=8`（从环境变量 `MAX_ITERATIONS` 读取）：限制"调工具→再推理"的最大轮数，防止死循环；
- `create_agent` 的 system_prompt：把工作流程和输出格式写死在系统提示词里，模型每轮都遵守；
- 重试与失败兜底在 `chat()` 外层实现（见第 7 节）。

---

## 4. 工具设计

四个工具都用 `@tool` 装饰器声明，**docstring 就是给 LLM 看的工具说明书**，所以写得很具体。

### 4.1 `read_code_file(file_path)`
- **作用**：读本地代码文件，返回带行号的内容。
- **边界**：
  - 文件不存在 → 返回明确错误串（让 Agent 知道路径错了）；
  - 超过 200KB → 拒绝读，防上下文爆炸；
  - utf-8 解码失败 → 回退 gbk（Windows 中文文件常见）。

### 4.2 `check_python_syntax(code)`
- **作用**：`ast.parse` 做语法校验；有 ruff 就顺便跑一遍。
- **为什么把"源码"而不是"路径"当入参**：上一步已经读过文件了，避免重复读盘；也方便用户直接贴一段代码审。

### 4.3 `run_python_code(code)`
- **作用**：把源码写到临时 `.py`，用当前解释器子进程跑，捕获 stdout/stderr/退出码。
- **安全**：5 秒超时（死循环直接杀）；最小化环境变量；用完即删临时文件。
- **局限**：作业演示用，不是真沙箱，不能跑不可信代码（README 里已写明）。

### 4.4 `analyze_complexity(code)`
- **作用**：遍历 AST，统计函数数、类数、每个函数的行数和圈复杂度。
- **圈复杂度口径**：基础 1，每出现 `if/for/while/except/with/布尔运算符/三元表达式` +1。
- **阈值**：圈复杂度 > 10、函数 > 50 行自动标 ⚠️，给 Agent 一个客观的"坏味道"证据，而不是纯靠 LLM 主观感觉。

---

## 5. Prompt 设计（Prompt Engineering）

`agent/prompts.py` 里的系统提示词做了几件事：

1. **角色设定**：「资深 Python 代码审查专家」，让模型代入专业身份；
2. **强制工作流**：明确告诉它"先读文件→再查语法→再量复杂度→必要时跑一下→最后出报告"，避免它偷懒直接编；
3. **审查维度清单**：正确性 Bug / 可读性 / 性能 / 安全性 / Python 最佳实践，五条全列出来，逼它逐条覆盖；
4. **固定输出格式**：用 Markdown 模板规定「严重问题 / 改进建议 / 优点 / 评分」四段，让最终报告结构稳定，方便用户看；
5. **纪律条款**：「不要编造没读到的内容」「工具报错就换工具或直说」，防止幻觉。

`temperature=0.2`：代码审查要稳定、保守，不要让模型自由发挥。

---

## 6. 记忆与会话

- `CodeReviewAgent` 内部维护 `self.messages` 消息列表：每轮把用户的 `HumanMessage` 和 Agent 的 `AIMessage` 依次累加；
- `create_agent` 每次 `invoke({"messages": 全量历史})`，模型天然能看到之前审过哪个文件、用户追问的是哪一行；
- 调用失败时会把刚追加的提问弹出历史，避免"坏消息"污染后续对话；
- 暴露 `reset()` 方法：CLI 里输入 `reset`、Web 里点「清空对话」，都会把消息列表置空，重新开始。

---

## 7. 错误处理与重试

`CodeReviewAgent.chat()` 里做了三层防御：

1. **工具层**：每个工具内部都 try/except，错误以字符串形式返回给 LLM（而不是抛出来崩掉整个循环）；
2. **循环层**：LangGraph 图在模型输出异常时自行处理；`recursion_limit` 防止无限循环；
3. **网络层**：外层 for 循环最多重试 3 次，退避时间 1.5s / 3s / 4.5s，处理网络抖动和限流；
4. **兜底**：重试用尽还失败，弹出该轮提问、返回一句友好错误，而不是让用户看到 traceback。

---

## 8. 评审标准自评

| 维度 | 权重 | 本项目如何满足 |
|---|---|---|
| 功能完整性 | 40% | 4 个工具全可用；文件不存在/超大/语法错/超时/API 失败都有兜底；双 UI |
| Agent 架构 | 30% | 严格走 LangChain 1.x create_agent（LangGraph）循环；模块化分层（agent/tools/ui）；Prompt 独立；记忆内置 |
| 代码质量 | 20% | 每个文件有模块 docstring；逐行中文注释；类型提示；无全局副作用；依赖最小 |
| 文档 | 10% | README（使用）+ Design.md（设计）双文档，结构清晰 |

---

## 9. 后续可改进方向

- 接入 `ast` 更细的规则（如未使用的 import、变量遮蔽）；
- 把执行代码放到 Docker / 子用户隔离；
- 支持多文件 diff 审查（读 git diff）；
- 把审查报告导出为 Markdown / HTML；
- 用 LangGraph 的 checkpointer（MemorySaver）把记忆持久化到磁盘/数据库。

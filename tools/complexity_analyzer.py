"""
complexity_analyzer.py —— 代码复杂度/结构分析工具
===================================================
功能：静态扫描源码 AST，统计函数数、类数、圈复杂度（粗略）、
     最长函数行数、嵌套深度等指标，给 Agent 提供量化的"坏味道"证据。
"""
import ast  # 抽象语法树

from langchain_core.tools import tool  # 工具装饰器

# 圈复杂度增量映射：这些语法节点每出现一次就 +1 复杂度
_COMPLEXITY_NODES = (
    ast.If, ast.For, ast.While, ast.ExceptHandler, ast.With,
    ast.BoolOp, ast.IfExp,
)
# 复杂度阈值：圈复杂度超过该值判定为"高复杂度，建议重构"
HIGH_COMPLEXITY_THRESHOLD = 10
# 行数阈值：函数体超过该行数判定为"过长，建议拆分"
LONG_FUNC_THRESHOLD = 50


@tool                                              # 注册工具
def analyze_complexity(code: str) -> str:          # 入参源码，返回结构分析报告
    """静态分析 Python 源码的结构指标（函数数、类数、各函数复杂度、最大嵌套深度等）。
    用于评估代码是否过长/过深/圈复杂度过高。

    Args:
        code: 要分析的 Python 源码字符串
    """
    try:
        tree = ast.parse(code)                     # 先解析 AST；语法错就别分析了
    except SyntaxError as e:                       # 语法错误
        return f"[错误] 代码有语法错误，无法做复杂度分析：{e}"

    funcs = []                                     # 存放每个函数的统计信息
    class FuncsVisitor(ast.NodeVisitor):           # 自定义 AST 遍历器
        def visit_FunctionDef(self, node):         # 遇到函数定义节点
            # 计算该函数的圈复杂度：基础分 1 + 每个分支节点 +1
            complexity = 1                         # 圈复杂度起始值
            # 遍历函数内部所有节点
            for child in ast.walk(node):
                if isinstance(child, _COMPLEXITY_NODES):  # 命中分支类节点
                    complexity += 1                # 复杂度+1
            # 计算函数行数（end_lineno - lineno + 1）
            length = (node.end_lineno or node.lineno) - node.lineno + 1
            funcs.append({                         # 记录这个函数
                "name": node.name,                 # 函数名
                "lineno": node.lineno,             # 起始行
                "lines": length,                   # 行数
                "complexity": complexity,          # 圈复杂度
            })
            self.generic_visit(node)               # 继续递归遍历子节点

    FuncsVisitor().visit(tree)                     # 启动遍历
    # 统计顶层类数量
    class_count = sum(1 for n in ast.walk(tree) if isinstance(n, ast.ClassDef))

    # 组装报告
    lines_out = [
        f"函数总数：{len(funcs)}",
        f"类总数：{class_count}",
        "各函数指标：",
    ]
    for f in sorted(funcs, key=lambda x: -x["complexity"]):  # 按复杂度降序
        # 标记高复杂度函数（超过阈值就该重构）
        flag = " ⚠️高复杂度" if f["complexity"] > HIGH_COMPLEXITY_THRESHOLD else ""
        lines_out.append(
            f"  - {f['name']}() @行{f['lineno']}："
            f"{f['lines']} 行，圈复杂度={f['complexity']}{flag}"
        )
    # 找出最长的函数
    if funcs:
        longest = max(funcs, key=lambda x: x["lines"])
        lines_out.append(
            f"最长函数：{longest['name']}()，{longest['lines']} 行"
            + (" ⚠️超过 50 行建议拆分" if longest["lines"] > LONG_FUNC_THRESHOLD else "")
        )
    return "\n".join(lines_out)                    # 返回完整报告

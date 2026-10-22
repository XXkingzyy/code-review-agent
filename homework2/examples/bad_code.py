"""
bad_code.py —— 一段故意写得很差的示例代码（复用自 Homework 1）
================================================================
用于演示“从已有代码开始”的分支：跳过编码 Agent，直接审查 → 修复。
里面埋了：除零风险、可变默认参数、命名不规范、过长函数、
嵌套过深、硬编码密钥、未关闭文件、O(n²) 循环等问题。
"""
import os                                          # 导入 os（其实没用上）


# 全局变量：到处乱改
g = 0                                              # 一个语义不明的全局计数器


def calc(data, result=[]):                         # ❌ 坑1：可变默认参数 list，跨调用会累积
    """计算列表里正数的平均值。"""
    s = 0                                          # 求和
    cnt = 0                                        # 计数
    for i in range(len(data)):                     # ❌ 坑2：写成 C 风格循环，Python 应直接 for x in data
        if data[i] > 0:                            # 判断正数
            s = s + data[i]                        # 累加
            cnt = cnt + 1                          # 计数+1
            if cnt == 100:                         # ❌ 坑3：魔数
                g = g + 1                          # ❌ 坑4：在函数里偷偷改全局变量
    avg = s / cnt                                  # ❌ 坑5：data 全非正数时 cnt=0 → ZeroDivisionError
    result.append(avg)                             # ❌ 坑6：副作用改默认参数
    return avg                                     # 返回平均值


def login(user, pwd):                              # 登录函数
    # ❌ 坑7：硬编码密钥（真实项目里绝对不能写死）
    SECRET = "sk-1234567890abcdef"                # 假的密钥，仅演示
    if user == "admin" and pwd == "123456":       # ❌ 坑8：硬编码弱口令
        f = open("log.txt", "a")                  # ❌ 坑9：打开文件没关闭，也没用 with
        f.write("login ok\n")                      # 写日志
        return True                                # 登录成功
    else:
        return False                               # 登录失败


def deep_nest(x):                                  # ❌ 坑10：嵌套过深 + 函数太长
    if x > 0:                                      # 第一层
        if x > 10:                                 # 第二层
            if x > 100:                            # 第三层
                if x > 1000:                       # 第四层
                    for i in range(x):             # 第五层：循环
                        if i % 2 == 0:             # 第六层：判断
                            for j in range(i):     # 第七层：嵌套循环 O(n²)
                                if j % 3 == 0:     # 第八层
                                    print(j)       # 打印
                else:                           # x<=100
                    print("small")               # 小
            else:                               # x<=10
                print("tiny")                    # 很小
        else:                                   # x<=0 分支
            if x < -100:                         # 又一层
                print("very negative")           # 很负
            else:
                print("slightly negative")       # 略负
    return x                                      # 返回


def slow_sum(a, b):                               # ❌ 坑11：O(n²) 本可以 O(n)
    total = 0                                     # 总和
    for i in range(a):                             # 外层 a 次
        for j in range(b):                         # 内层 b 次
            total += 1                              # 每次+1 → 其实就是 a*b
    return total                                   # 返回

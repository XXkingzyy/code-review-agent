"""
config.py —— 全局配置与运行参数
================================
职责：
  1. 从项目根目录的 .env 读取 LLM 配置；
  2. 提供工作流参数（最大审查轮数、通过阈值、执行超时等）；
  3. 支持命令行/Web 传入参数覆盖默认值；
  4. 提供“离线 Mock 模式”，在没有 API Key 时也能跑通整条 Workflow（用于自测/演示）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

from dotenv import load_dotenv

# 项目根目录：所有相对路径（.env、runs/、examples/）都以它为基准
PROJECT_ROOT = Path(__file__).resolve().parent
# 显式加载项目根目录的 .env，避免从其他工作目录启动时读不到
load_dotenv(PROJECT_ROOT / ".env")


def _env_int(name: str, default: int) -> int:
    """读取整型环境变量，非法值回退默认值。"""
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    """读取浮点型环境变量，非法值回退默认值。"""
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


def has_real_api_key() -> bool:
    """判断 .env 中是否填写了看起来真实的 API Key（而非占位符）。"""
    key = os.environ.get("LLM_API_KEY", "").strip()
    if not key:
        return False
    # 模板里的占位符特征：sk-在这里填你的Key
    return not (key.startswith("sk-在这里") or "在这里填" in key)


@dataclass(frozen=True)
class Settings:
    """一次工作流运行所需的全部配置（不可变，便于安全传递）。"""

    llm_base_url: str
    llm_api_key: str
    llm_model: str
    temperature: float
    llm_timeout: int
    llm_retries: int
    max_rounds: int
    pass_threshold: float
    code_exec_timeout: int
    runs_root: Path
    offline: bool

    @property
    def has_api_key(self) -> bool:
        """当前配置是否具备可用的 API Key。"""
        key = self.llm_api_key.strip()
        return bool(key) and not (key.startswith("sk-在这里") or "在这里填" in key)


def load_settings(
    *,
    offline: bool = False,
    max_rounds: int | None = None,
    pass_threshold: float | None = None,
    runs_root: Path | None = None,
) -> Settings:
    """构造运行配置；命令行/Web 的参数优先于 .env。

    参数：
        offline：是否强制使用离线 Mock 模型（无需 API Key）。
        max_rounds：最多审查轮数（含首轮），至少为 1。
        pass_threshold：评分通过阈值（0~10）。
        runs_root：运行产物根目录，默认项目下的 runs/。
    """
    settings = Settings(
        llm_base_url=os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1"),
        llm_api_key=os.environ.get("LLM_API_KEY", ""),
        llm_model=os.environ.get("LLM_MODEL", "deepseek-chat"),
        temperature=_env_float("LLM_TEMPERATURE", 0.2),
        llm_timeout=_env_int("LLM_TIMEOUT", 60),
        llm_retries=_env_int("LLM_RETRIES", 3),
        max_rounds=_env_int("MAX_ROUNDS", 3),
        pass_threshold=_env_float("PASS_THRESHOLD", 8.0),
        code_exec_timeout=_env_int("CODE_EXEC_TIMEOUT", 5),
        runs_root=runs_root or (PROJECT_ROOT / "runs"),
        offline=offline,
    )
    # 命令行/Web 覆盖
    if max_rounds is not None:
        settings = replace(settings, max_rounds=max(1, max_rounds))
    if pass_threshold is not None:
        settings = replace(settings, pass_threshold=min(10.0, max(0.0, pass_threshold)))
    # 工具（复用作Homework1的 code_executor）通过环境变量读取执行超时
    os.environ["CODE_EXEC_TIMEOUT"] = str(settings.code_exec_timeout)
    # 真实模式必须有 Key，提前给出明确提示，避免跑到一半才失败
    if not settings.offline and not settings.has_api_key:
        raise RuntimeError(
            "未配置 LLM_API_KEY。\n"
            "请复制 .env.example 为 .env 并填写真实 Key；"
            "或加 --offline 使用离线 Mock 模式先跑通流程。"
        )
    return settings

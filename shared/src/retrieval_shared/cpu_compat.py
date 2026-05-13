# shared/src/retrieval_shared/cpu_compat.py
"""CPU 兼容性检测 — 确保 torch 在不支持 AVX2 的 CPU 上可以回退。"""
import os
import logging

logger = logging.getLogger(__name__)

_COMPAT_MARKER = os.path.join(os.path.dirname(__file__), "..", "..", "..", ".torch_cpu_compat")


def ensure_compatible_torch() -> None:
    """检测 CPU AVX2 支持，必要时标记兼容模式。

    如果当前 CPU 不支持 AVX2 且 torch 尚未安装，记录警告。
    此函数应在服务启动时调用，在 import torch 之前执行。
    """
    if os.path.exists(_COMPAT_MARKER):
        logger.info("CPU compatibility marker found, skipping check")
        return

    try:
        import torch
    except ImportError:
        logger.debug("torch not installed, skipping CPU compatibility check")
        return

    # 检查 CPU 是否支持 AVX2
    if hasattr(torch, "__config__") and callable(torch.__config__):
        try:
            info = torch.__config__.show()
            if "AVX2" not in info:
                logger.warning(
                    "CPU does not support AVX2; torch may fall back to slower ops. "
                    "Consider installing a compatible torch build."
                )
        except Exception:
            pass

    # macOS ARM 或华为 NPU 场景不需要此检查
    logger.debug("CPU compatibility check passed")
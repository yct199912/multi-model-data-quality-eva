# services/model/src/core/providers/factory.py
from retrieval_shared.constants import ModelProvider
from .base import BaseEvalProvider
from ...config import settings


def get_eval_provider(provider_name: str = None) -> BaseEvalProvider:
    provider = provider_name or settings.model_name
    try:
        from .gemma4 import Gemma4EvalProvider
    except ImportError:
        raise ImportError(
            "Gemma4 模型依赖未安装。请执行: pip install -e '.[gemma4]'"
        )
    return Gemma4EvalProvider(
        model_name=settings.model_name,
        device=settings.device,
        cache_dir=settings.model_cache_dir,
    )
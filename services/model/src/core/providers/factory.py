# services/model/src/core/providers/factory.py
from retrieval_shared.constants import ModelProvider
from .base import BaseEvalProvider
from ...config import settings


def get_eval_provider(provider_name: str = None) -> BaseEvalProvider:
    provider = provider_name or settings.model_name

    if "OpenVINO" in provider or "openvino" in provider:
        try:
            from .openvino_gemma import OpenVINOGemmaEvalProvider
            return OpenVINOGemmaEvalProvider(
                model_name=settings.model_name,
                device=settings.device,
                cache_dir=settings.model_cache_dir,
            )
        except ImportError as e:
            raise ImportError(
                f"OpenVINO 依赖未安装或版本不匹配 ({e})。请执行: pip install optimum[openvino]"
            )

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
# services/model/src/main.py
import sys
from types import ModuleType
from enum import Enum
from ctypes import c_float, sizeof

# Monkey-patch transformers.onnx for transformers 5.x compatibility with optimum-intel
if "transformers.onnx" not in sys.modules:
    onnx_utils = ModuleType("transformers.onnx.utils")
    class ParameterFormat(Enum):
        Float = c_float
        @property
        def size(self):
            return sizeof(self.value)
    onnx_utils.ParameterFormat = ParameterFormat
    def compute_serialized_parameters_size(num_parameters, dtype):
        return num_parameters * (dtype.size if hasattr(dtype, 'size') else 4)
    onnx_utils.compute_serialized_parameters_size = compute_serialized_parameters_size
    
    onnx = ModuleType("transformers.onnx")
    onnx.utils = onnx_utils
    sys.modules["transformers.onnx"] = onnx
    sys.modules["transformers.onnx.utils"] = onnx_utils

# Monkey-patch transformers.utils for is_offline_mode
import transformers
if not hasattr(transformers.utils, "is_offline_mode"):
    import huggingface_hub
    transformers.utils.is_offline_mode = huggingface_hub.is_offline_mode

# Patch transformers.models.mamba.modeling_mamba for MambaCache
try:
    import transformers.models.mamba.modeling_mamba
    if not hasattr(transformers.models.mamba.modeling_mamba, "MambaCache"):
        class MambaCache: pass
        transformers.models.mamba.modeling_mamba.MambaCache = MambaCache
except ImportError:
    pass

# Patch transformers.utils.generic for _CAN_RECORD_REGISTRY and OutputRecorder
import transformers.utils.generic
if not hasattr(transformers.utils.generic, "_CAN_RECORD_REGISTRY"):
    transformers.utils.generic._CAN_RECORD_REGISTRY = False
if not hasattr(transformers.utils.generic, "OutputRecorder"):
    class OutputRecorder:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
    transformers.utils.generic.OutputRecorder = OutputRecorder

# Patch transformers for AutoModelForVision2Seq and AutoModelForVisionSeq2Seq
if not hasattr(transformers, "AutoModelForVision2Seq"):
    transformers.AutoModelForVision2Seq = getattr(transformers, "AutoModelForMultimodalLM", None)
if not hasattr(transformers, "AutoModelForVisionSeq2Seq"):
    transformers.AutoModelForVisionSeq2Seq = getattr(transformers, "AutoModelForMultimodalLM", None)

# Patch transformers.modeling_utils for unwrap_model
import transformers.modeling_utils
if not hasattr(transformers.modeling_utils, "unwrap_model"):
    def unwrap_model(model): return model
    transformers.modeling_utils.unwrap_model = unwrap_model

# Patch transformers.PretrainedConfig for _get_non_default_generation_parameters
if hasattr(transformers.PretrainedConfig, "_get_generation_parameters") and not hasattr(transformers.PretrainedConfig, "_get_non_default_generation_parameters"):
    transformers.PretrainedConfig._get_non_default_generation_parameters = transformers.PretrainedConfig._get_generation_parameters

# Patch optimum-intel for gemma4 support
try:
    import optimum.intel.openvino.modeling_visual_language as mvl
    if "gemma4" not in mvl.MODEL_TYPE_TO_CLS_MAPPING:
        if hasattr(mvl, "_OVGemma3ForCausalLM"):
            mvl.MODEL_TYPE_TO_CLS_MAPPING["gemma4"] = mvl._OVGemma3ForCausalLM
        elif hasattr(mvl, "_OVLlama4ForCausalLM"):
            # Llama 4 might be similar too, but let's try to find a good fallback
            mvl.MODEL_TYPE_TO_CLS_MAPPING["gemma4"] = mvl._OVLlama4ForCausalLM
except ImportError:
    pass

# Patch huggingface_hub for HfFolder
import huggingface_hub
if not hasattr(huggingface_hub, "HfFolder"):
    class HfFolder:
        @staticmethod
        def get_token(): return os.environ.get("HUGGING_FACE_HUB_TOKEN")
        @staticmethod
        def save_token(token): pass
        @staticmethod
        def delete_token(): pass
    huggingface_hub.HfFolder = HfFolder

import logging
import asyncio
import os
from contextlib import asynccontextmanager

from .config import settings

# CPU feature pre-flight check
from retrieval_shared.cpu_compat import ensure_compatible_torch
ensure_compatible_torch()

# NPU init
if settings.device == "npu":
    try:
        os.environ["USE_NNPACK"] = "0"
        os.environ["OMP_NUM_THREADS"] = "1"
        os.environ["NNPACK_DISABLE"] = "1"
        os.environ["ATEN_CPU_CAPABILITY"] = "default"
        import torch_npu
        import torch
        torch.npu.set_device(0)
        logging.info("NPU (Huawei Ascend) initialization successful")
    except ImportError:
        logging.error("torch_npu not found, but DEVICE=npu. Falling back to CPU.")
    except Exception as e:
        logging.error(f"NPU initialization failed: {e}")

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from .api import evaluate
from .core import state
from .core.providers.factory import get_eval_provider
from retrieval_shared.logging_config import configure_logging
from retrieval_shared.middleware import RequestIDMiddleware
from retrieval_shared.exception_handlers import setup_exception_handlers
from retrieval_shared.response_wrapper import CodeWrapperMiddleware

configure_logging("model-service", settings.log_level)


async def background_initialization():
    """后台异步初始化模型。"""
    try:
        logging.info(f"Initializing eval provider: {settings.model_name}")
        new_provider = get_eval_provider()
        # 在后台线程中完成模型加载，避免阻塞事件循环
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, new_provider._init_model)
        state.provider = new_provider
        state.is_ready = True
        state.init_error = None
        logging.info(f"Model {settings.model_name} initialized successfully.")
    except Exception as e:
        state.is_ready = False
        state.init_error = str(e)
        logging.error(f"Failed to initialize model: {e}", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    state.is_ready = False
    state.init_error = None
    app.state.init_task = asyncio.create_task(background_initialization())
    yield


app = FastAPI(title="Model Evaluation Server", version="1.0.0", lifespan=lifespan)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(CodeWrapperMiddleware)
setup_exception_handlers(app)

app.include_router(evaluate.router)


@app.get("/health")
async def health():
    if state.init_error:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "error": state.init_error, "model": settings.model_name},
        )
    if not state.is_ready:
        return JSONResponse(status_code=503, content={"status": "starting", "model": settings.model_name})
    return {"status": "up", "model": settings.model_name}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.host, port=settings.port)
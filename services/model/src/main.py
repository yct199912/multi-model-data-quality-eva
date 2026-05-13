# services/model/src/main.py
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

configure_logging("model-service", settings.log_level)


async def background_initialization():
    """后台异步初始化模型。"""
    try:
        logging.info(f"Initializing eval provider: {settings.model_name}")
        new_provider = get_eval_provider()
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
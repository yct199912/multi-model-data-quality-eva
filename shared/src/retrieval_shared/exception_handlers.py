# shared/src/retrieval_shared/exception_handlers.py
"""FastAPI 全局异常处理器注册。"""
import logging
import traceback
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AppException(Exception):
    """业务异常基类。"""

    def __init__(self, status_code: int = 500, detail: str = "Internal Server Error"):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def setup_exception_handlers(app: FastAPI) -> None:
    """为 FastAPI 应用注册全局异常处理器。"""

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled exception: {exc}\n{traceback.format_exc()}")
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal Server Error"},
        )
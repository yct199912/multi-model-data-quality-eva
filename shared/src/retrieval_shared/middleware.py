# shared/src/retrieval_shared/middleware.py
import uuid
import structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

log = structlog.get_logger()

class RequestIDMiddleware(BaseHTTPMiddleware):
    """为每个请求添加/传播 X-Request-ID。"""
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        # 绑定到 structlog context
        with structlog.contextvars.bound_contextvars(request_id=request_id):
            response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

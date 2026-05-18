# shared/src/retrieval_shared/response_wrapper.py
"""FastAPI 中间件：统一为所有成功响应添加 code=200 字段。"""
import json
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)


class CodeWrapperMiddleware(BaseHTTPMiddleware):
    """对所有 2xx JSON 响应统一包装为 {"code": 200, "data": ...} 结构。"""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # 只处理 2xx 成功响应
        if response.status_code < 200 or response.status_code >= 300:
            return response

        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return response

        # 读取原始响应体
        body = b""
        async for chunk in response.body_iterator:
            if isinstance(chunk, str):
                body += chunk.encode("utf-8")
            else:
                body += chunk

        try:
            original = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return Response(content=body, status_code=response.status_code, media_type=content_type)

        # 已经是 {code, data} 结构则不再嵌套
        if isinstance(original, dict) and "code" in original and "data" in original:
            return JSONResponse(content=original, status_code=response.status_code)

        return JSONResponse(
            content={"code": 200, "data": original},
            status_code=response.status_code,
        )
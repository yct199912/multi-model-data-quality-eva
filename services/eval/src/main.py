# services/eval/src/main.py
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from .api import evaluate
from .dependencies import db
from .config import settings
from retrieval_shared.logging_config import configure_logging
from retrieval_shared.middleware import RequestIDMiddleware
from retrieval_shared.exception_handlers import setup_exception_handlers

configure_logging("eval-service", settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    yield
    await db.disconnect()


app = FastAPI(title="Evaluation Service", version="1.0.0", lifespan=lifespan)
app.add_middleware(RequestIDMiddleware)
setup_exception_handlers(app)

app.include_router(evaluate.router)


@app.get("/health")
async def health():
    return {"status": "up"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.host, port=settings.port)
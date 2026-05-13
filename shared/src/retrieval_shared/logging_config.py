# shared/src/retrieval_shared/logging_config.py
import structlog
import logging
import sys

def configure_logging(service_name: str, log_level: str = "INFO") -> None:
    """初始化 structlog，生产环境输出 JSON，开发环境输出彩色文本。"""
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.dict_tracebacks,
    ]
    
    # 简单的控制台渲染或 JSON 渲染判断
    if sys.stdout.isatty():
        processors = shared_processors + [structlog.dev.ConsoleRenderer()]
    else:
        processors = shared_processors + [structlog.processors.JSONRenderer()]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(message)s",
        stream=sys.stdout,
    )

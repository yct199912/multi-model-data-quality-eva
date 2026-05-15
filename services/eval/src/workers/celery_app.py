# services/eval/src/workers/celery_app.py
from celery import Celery
from ..config import settings

celery_app = Celery(
    "eval_worker",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["services.eval.src.workers.tasks"],
)

celery_app.conf.update(
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    visibility_timeout=7200,
    task_serializer="json",
    result_serializer="json",
    worker_concurrency=1,
)
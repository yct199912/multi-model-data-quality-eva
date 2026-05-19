# services/eval/src/dependencies.py
from retrieval_shared.database import Database
from retrieval_shared.redis import RedisClient
from .config import settings

db = Database(settings.postgres_dsn)
redis_client = RedisClient(settings.redis_url)
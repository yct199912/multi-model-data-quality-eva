# services/eval/src/dependencies.py
from retrieval_shared.database import Database
from .config import settings

db = Database(settings.postgres_dsn)
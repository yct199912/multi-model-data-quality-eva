# services/eval/src/config.py
import os
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # App auth
    app_key: str = Field("default_app_key", alias="APP_KEY")
    app_secret: str = Field("default_app_secret", alias="APP_SECRET")

    # Gitea
    gitea_base_url: str = Field("http://localhost:3000", alias="GITEA_BASE_URL")
    gitea_token: str = Field("", alias="GITEA_TOKEN")
    gitea_file_ob: str = Field(
        "/api/v1/repos/{owner}/{repo}/contents/{filepath}",
        alias="GITEA_FILE_OB",
    )

    # Database
    postgres_dsn: str = Field(
        "postgresql+asyncpg://retrieval:retrieval@localhost:5432/retrieval_db",
        alias="POSTGRES_DSN",
    )
    redis_url: str = Field("redis://localhost:6379/0", alias="REDIS_URL")

    # Model server
    model_server_url: str = Field("http://localhost:18100", alias="MODEL_SERVER_URL")

    # Callback (RECALL)
    recall_ip: str = Field("", alias="RECALL_IP")
    recall_port: str = Field("", alias="RECALL_PORT")
    recall_api: str = Field("", alias="RECALL_API")

    # Celery
    celery_worker_concurrency: int = Field(4, alias="CELERY_WORKER_CONCURRENCY")

    log_level: str = Field("INFO", alias="LOG_LEVEL")
    host: str = Field("0.0.0.0", alias="HOST")
    port: int = Field(18080, alias="PORT")

    model_config = {
        "env_file": os.getenv("ENV_FILE", ".env"),
        "extra": "ignore",
        "populate_by_name": True,
        "protected_namespaces": (),
    }


settings = Settings()
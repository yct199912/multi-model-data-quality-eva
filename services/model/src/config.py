# services/model/src/config.py
import os
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    model_name: str = Field("google/gemma-4-e4b", alias="MODEL_NAME")
    model_cache_dir: str = Field("/models", alias="MODEL_CACHE_DIR")
    device: str = Field("cpu", alias="DEVICE")
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    gpu_concurrency: int = Field(1, alias="GPU_CONCURRENCY")
    use_openvino: bool = Field(False, alias="USE_OPENVINO")
    max_text_chars: int = Field(8000, alias="MAX_TEXT_CHARS")
    max_image_size: int = Field(384, alias="MAX_IMAGE_SIZE")
    host: str = Field("0.0.0.0", alias="HOST")
    port: int = Field(18100, alias="PORT")

    model_config = {
        "env_file": os.getenv("ENV_FILE", ".env"),
        "extra": "ignore",
        "populate_by_name": True,
        "protected_namespaces": (),
    }


settings = Settings()
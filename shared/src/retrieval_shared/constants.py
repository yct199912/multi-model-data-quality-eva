# shared/src/retrieval_shared/constants.py
from enum import Enum
import os


class FileType(str, Enum):
    IMAGE = "image"
    TEXT = "text"
    VIDEO = "video"
    UNKNOWN = "unknown"


class EvalStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class ModelProvider(str, Enum):
    GEMMA4 = "gemma4"


# Model
MODEL_NAME_DEFAULT = os.getenv("MODEL_NAME", "google/gemma-4-e4b")
MODEL_CACHE_DIR = os.getenv("MODEL_CACHE_DIR", "/models")
DEVICE_DEFAULT = os.getenv("DEVICE", "cpu")

# Redis key templates
REDIS_EVAL_LOCK_KEY = "eval:lock:{task_id}"
REDIS_EVAL_PROGRESS = "eval:progress:{task_id}"

# Max file size for evaluation (100 MB)
MAX_EVAL_FILE_BYTES = 100 * 1024 * 1024

# MIME type → FileType classification
MIME_TO_FILE_TYPE = {
    # Images
    "image/jpeg":      FileType.IMAGE,
    "image/png":       FileType.IMAGE,
    "image/webp":      FileType.IMAGE,
    "image/gif":       FileType.IMAGE,
    "image/bmp":       FileType.IMAGE,
    "image/tiff":      FileType.IMAGE,
    "image/svg+xml":   FileType.IMAGE,
    # Text
    "text/plain":      FileType.TEXT,
    "text/markdown":   FileType.TEXT,
    "text/csv":        FileType.TEXT,
    "text/html":       FileType.TEXT,
    "text/xml":        FileType.TEXT,
    "application/json": FileType.TEXT,
    "application/xml": FileType.TEXT,
    # Documents - will be extracted as text
    "application/pdf": FileType.TEXT,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": FileType.TEXT,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": FileType.TEXT,
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": FileType.TEXT,
    # Video
    "video/mp4":       FileType.VIDEO,
    "video/x-msvideo": FileType.VIDEO,
    "video/quicktime": FileType.VIDEO,
    "video/x-matroska": FileType.VIDEO,
    }

    # File extension → FileType (fallback when MIME not available)
    EXT_TO_FILE_TYPE = {
    ".jpg":  FileType.IMAGE, ".jpeg": FileType.IMAGE, ".png": FileType.IMAGE,
    ".webp": FileType.IMAGE, ".gif":  FileType.IMAGE, ".bmp":  FileType.IMAGE,
    ".tiff": FileType.IMAGE, ".tif":  FileType.IMAGE, ".svg":  FileType.IMAGE,
    ".txt":  FileType.TEXT,  ".md":   FileType.TEXT,  ".csv":  FileType.TEXT,
    ".html": FileType.TEXT, ".htm":  FileType.TEXT,  ".xml":  FileType.TEXT,
    ".json": FileType.TEXT, ".py":   FileType.TEXT,  ".java": FileType.TEXT,
    ".js":   FileType.TEXT, ".ts":   FileType.TEXT,  ".c":    FileType.TEXT,
    ".cpp":  FileType.TEXT, ".h":    FileType.TEXT,  ".go":   FileType.TEXT,
    ".rs":   FileType.TEXT, ".rb":   FileType.TEXT,  ".php":  FileType.TEXT,
    ".pdf":  FileType.TEXT, ".docx": FileType.TEXT,  ".xlsx": FileType.TEXT,
    ".pptx": FileType.TEXT, ".doc":  FileType.TEXT,
    ".mp4":  FileType.VIDEO, ".avi": FileType.VIDEO, ".mov": FileType.VIDEO,
    ".mkv":  FileType.VIDEO, ".wmv": FileType.VIDEO, ".flv": FileType.VIDEO,
    ".webm": FileType.VIDEO,
    }


# Evaluation dimension types (eva_type values)
# Accuracy
EVA_TYPE_IMAGE_CONTENT_ACCURACY = "image-content"
EVA_TYPE_TEXT_FORMAT_ACCURACY = "text-format"
EVA_TYPE_TEXT_CONTENT_ACCURACY = "text-content"
# Consistency (完整性)
EVA_TYPE_IMAGE_NOINFO = "image-noinfo"
EVA_TYPE_IMAGE_NOISE = "image-noise"
EVA_TYPE_TEXT_NOINFO = "text-noinfo"
EVA_TYPE_TEXT_DESC = "text-desc"
# Uniqueness (唯一性)
EVA_TYPE_IMAGE_CONTENT_UNIQUENESS = "image-content"
EVA_TYPE_TEXT_CONTENT_UNIQUENESS = "text-content"
# Integrity (一致性)
EVA_TYPE_IMAGE_CONTENT_INTEGRITY = "image-content"
EVA_TYPE_TEXT_CONTENT_INTEGRITY = "text-content"

# Repository-level evaluation types (repo-level)
EVA_TYPE_REPO_EFFECTIVENESS = "repo-effectiveness"
EVA_TYPE_REPO_TIMELINESS = "repo-timeliness"
EVA_TYPE_REPO_INTER_IMAGE_UNQ = "inter-image-unq"
EVA_TYPE_REPO_INTER_IMAGE_INTEGRITY = "inter-image-integrity"
EVA_TYPE_REPO_INTER_TEXT_UNQ = "inter-text-unq"
EVA_TYPE_REPO_INTER_TEXT_INTEGRITY = "inter-text-integrity"

# Score table names
SCORE_TABLE_ACCURACY = "content_accuracy_score"
SCORE_TABLE_CONSISTENCY = "content_consistency_score"
SCORE_TABLE_UNIQUENESS = "content_unq_score"
SCORE_TABLE_INTEGRITY = "content_integrity_score"

# Repository-level score table names
SCORE_TABLE_REPO_EFFECTIVENESS = "repo_effectiveness_score"
SCORE_TABLE_REPO_TIMELINESS = "repo_timeliness_score"
SCORE_TABLE_REPO_UNIQUENESS = "repo_unq_score"
SCORE_TABLE_REPO_INTEGRITY = "repo_integrity_score"
SCORE_TABLE_REPO_ACCURACY = "repo_accuracy_score"
SCORE_TABLE_REPO_CONSISTENCY = "repo_consistency_score"
# services/eval/src/core/evaluator.py
"""评价分数聚合逻辑。"""
import hashlib
import logging
from retrieval_shared.constants import (
    SCORE_TABLE_ACCURACY, SCORE_TABLE_CONSISTENCY,
    SCORE_TABLE_UNIQUENESS, SCORE_TABLE_INTEGRITY,
    EVA_TYPE_IMAGE_NOINFO, EVA_TYPE_IMAGE_NOISE,
    EVA_TYPE_TEXT_NOINFO, EVA_TYPE_TEXT_DESC,
    EVA_TYPE_IMAGE_CONTENT_ACCURACY,
    EVA_TYPE_TEXT_FORMAT_ACCURACY, EVA_TYPE_TEXT_CONTENT_ACCURACY,
    EVA_TYPE_IMAGE_CONTENT_UNIQUENESS, EVA_TYPE_TEXT_CONTENT_UNIQUENESS,
    EVA_TYPE_IMAGE_CONTENT_INTEGRITY, EVA_TYPE_TEXT_CONTENT_INTEGRITY,
)

logger = logging.getLogger(__name__)


def compute_content_hash(content: str) -> str:
    """计算内容的 SHA256 hash，用于去重。"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def compute_dataset_uniqueness(hashes: list[str]) -> float:
    """数据集内唯一性得分 = 非冗余数量 / 总数量 × 100。"""
    if not hashes:
        return 0.0
    unique_count = len(set(hashes))
    return round(unique_count / len(hashes) * 100, 2)


def compute_image_uniqueness_score(info_scores: list[float], dataset_uniqueness: float) -> float:
    """图像唯一性 = 图内信息唯一性 × 0.3 + 数据集内唯一性 × 0.7。"""
    if not info_scores:
        return 0.0
    info_avg = sum(info_scores) / len(info_scores)
    return round(info_avg * 0.3 + dataset_uniqueness * 0.7, 2)


def compute_image_completeness_score(
    solid_scores: list[float], noise_scores: list[float], object_scores: list[float],
) -> float:
    """图像完整性 = 无信息区域 × 0.5 + 无信息噪声 × 0.3 + 描述对象完整性 × 0.2。"""
    if not solid_scores:
        return 0.0
    solid_avg = sum(solid_scores) / len(solid_scores)
    noise_avg = sum(noise_scores) / len(noise_scores) if noise_scores else 0.0
    object_avg = sum(object_scores) / len(object_scores) if object_scores else 0.0
    return round(solid_avg * 0.5 + noise_avg * 0.3 + object_avg * 0.2, 2)


def compute_text_uniqueness_score(info_scores: list[float], dataset_uniqueness: float) -> float:
    """文本唯一性 = 文本信息唯一性 × 0.3 + 数据集内唯一性 × 0.7。"""
    if not info_scores:
        return 0.0
    info_avg = sum(info_scores) / len(info_scores)
    return round(info_avg * 0.3 + dataset_uniqueness * 0.7, 2)


def compute_text_completeness_score(junk_scores: list[float], desc_scores: list[float]) -> float:
    """文本完整性 = 无信息文本检测 × 0.6 + 描述完整性 × 0.4。"""
    if not junk_scores:
        return 0.0
    junk_avg = sum(junk_scores) / len(junk_scores)
    desc_avg = sum(desc_scores) / len(desc_scores) if desc_scores else 0.0
    return round(junk_avg * 0.6 + desc_avg * 0.4, 2)


def get_score_table_and_eva_type(dimension: str, file_type: str) -> tuple[str, str]:
    """根据评价维度和文件类型返回对应的数据库表名和 eva_type。

    dimension: accuracy / consistency / uniqueness / integrity
    file_type: image / text
    sub_key: 依赖于具体子维度
    """
    mapping = {
        ("accuracy", "image"): (SCORE_TABLE_ACCURACY, EVA_TYPE_IMAGE_CONTENT_ACCURACY),
        ("accuracy", "text_format"): (SCORE_TABLE_ACCURACY, EVA_TYPE_TEXT_FORMAT_ACCURACY),
        ("accuracy", "text_content"): (SCORE_TABLE_ACCURACY, EVA_TYPE_TEXT_CONTENT_ACCURACY),
        ("consistency", "image-noinfo"): (SCORE_TABLE_CONSISTENCY, EVA_TYPE_IMAGE_NOINFO),
        ("consistency", "image-noise"): (SCORE_TABLE_CONSISTENCY, EVA_TYPE_IMAGE_NOISE),
        ("consistency", "text-noinfo"): (SCORE_TABLE_CONSISTENCY, EVA_TYPE_TEXT_NOINFO),
        ("consistency", "text-desc"): (SCORE_TABLE_CONSISTENCY, EVA_TYPE_TEXT_DESC),
        ("uniqueness", "image"): (SCORE_TABLE_UNIQUENESS, EVA_TYPE_IMAGE_CONTENT_UNIQUENESS),
        ("uniqueness", "text"): (SCORE_TABLE_UNIQUENESS, EVA_TYPE_TEXT_CONTENT_UNIQUENESS),
        ("integrity", "image"): (SCORE_TABLE_INTEGRITY, EVA_TYPE_IMAGE_CONTENT_INTEGRITY),
        ("integrity", "text"): (SCORE_TABLE_INTEGRITY, EVA_TYPE_TEXT_CONTENT_INTEGRITY),
    }
    return mapping.get((dimension, file_type), (None, None))
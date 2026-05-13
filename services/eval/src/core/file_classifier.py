# services/eval/src/core/file_classifier.py
"""根据文件扩展名和 MIME 类型将文件分类为 image / text / unknown。"""
import os
from retrieval_shared.constants import EXT_TO_FILE_TYPE, FileType

# 支持 base64 内联获取内容的文件后缀
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".tif", ".svg"}
TEXT_EXTENSIONS = {
    ".txt", ".md", ".csv", ".html", ".htm", ".xml", ".json",
    ".py", ".java", ".js", ".ts", ".c", ".cpp", ".h", ".go", ".rs", ".rb", ".php",
    ".pdf", ".docx", ".xlsx", ".pptx", ".doc",
}


def classify_file(filepath: str) -> FileType:
    """根据文件路径后缀判断文件类型。"""
    _, ext = os.path.splitext(filepath.lower())
    return EXT_TO_FILE_TYPE.get(ext, FileType.UNKNOWN)


def is_image_file(filepath: str) -> bool:
    return classify_file(filepath) == FileType.IMAGE


def is_text_file(filepath: str) -> bool:
    return classify_file(filepath) == FileType.TEXT
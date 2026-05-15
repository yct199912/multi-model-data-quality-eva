"""Office 和 PDF 文件文本提取工具。"""
import io
import logging
from typing import Optional

logger = logging.getLogger(__name__)

def extract_text_from_docx(content_bytes: bytes) -> str:
    """从 .docx 文件提取文本。"""
    try:
        from docx import Document
        doc = Document(io.BytesIO(content_bytes))
        return "\n".join([p.text for p in doc.paragraphs])
    except Exception as e:
        logger.error(f"Failed to extract text from DOCX: {e}")
        return ""

def extract_text_from_xlsx(content_bytes: bytes) -> str:
    """从 .xlsx 文件提取文本（所有工作表）。"""
    try:
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(content_bytes), data_only=True)
        text_parts = []
        for sheet in wb.worksheets:
            text_parts.append(f"Sheet: {sheet.title}")
            for row in sheet.iter_rows(values_only=True):
                text_parts.append(" ".join([str(cell) for cell in row if cell is not None]))
        return "\n".join(text_parts)
    except Exception as e:
        logger.error(f"Failed to extract text from XLSX: {e}")
        return ""

def extract_text_from_pptx(content_bytes: bytes) -> str:
    """从 .pptx 文件提取文本。"""
    try:
        from pptx import Presentation
        prs = Presentation(io.BytesIO(content_bytes))
        text_parts = []
        for i, slide in enumerate(prs.slides):
            text_parts.append(f"Slide {i+1}:")
            for shape in slide.shapes:
                if hasattr(shape, "text"):
                    text_parts.append(shape.text)
        return "\n".join(text_parts)
    except Exception as e:
        logger.error(f"Failed to extract text from PPTX: {e}")
        return ""

def extract_text_from_pdf(content_bytes: bytes) -> str:
    """从 .pdf 文件提取文本。"""
    try:
        from pypdf import PdfReader
        reader = pypdf.PdfReader(io.BytesIO(content_bytes))
        text_parts = []
        for page in reader.pages:
            text_parts.append(page.extract_text())
        return "\n".join(text_parts)
    except Exception as e:
        logger.error(f"Failed to extract text from PDF: {e}")
        return ""

def extract_text_by_extension(extension: str, content_bytes: bytes) -> Optional[str]:
    """根据扩展名选择合适的提取方法。"""
    ext = extension.lower()
    if ext == ".docx":
        return extract_text_from_docx(content_bytes)
    elif ext == ".xlsx":
        return extract_text_from_xlsx(content_bytes)
    elif ext == ".pptx":
        return extract_text_from_pptx(content_bytes)
    elif ext in (".pdf"):
        return extract_text_from_pdf(content_bytes)
    return None

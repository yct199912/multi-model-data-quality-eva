# services/model/tests/test_model_service.py
"""Tests for model service provider logic."""
import pytest


class TestJsonParsing:
    def test_parse_combined_image_json(self):
        from services.model.src.core.providers.gemma4 import Gemma4EvalProvider
        text = """
        分析结果如下：
        {
          "accuracy": {"score": 90, "eva_content": "准确"},
          "noinfo": {"score": 85, "eva_content": "无纯色"},
          "noise": {"score": 80, "eva_content": "低噪声"},
          "uniqueness": {"score": 75, "eva_content": "内容独特"},
          "consistency": {"score": 95, "eva_content": "逻辑一致"}
        }
        以上是全部评价。
        """
        result = Gemma4EvalProvider._parse_json_response(text)
        assert result["accuracy"]["score"] == 90
        assert result["noise"]["eva_content"] == "低噪声"

    def test_parse_combined_text_json_with_unescaped_newline(self):
        from services.model.src.core.providers.gemma4 import Gemma4EvalProvider
        # Raw newline inside eva_content should be handled by fix_control_chars
        text = '{"format_accuracy": {"score": 100, "eva_content": "包含\n换行符"}}'
        result = Gemma4EvalProvider._parse_json_response(text)
        assert result["format_accuracy"]["score"] == 100
        # If successfully parsed, it will be "包含 换行符" due to re.sub
        assert "换行符" in result["format_accuracy"]["eva_content"]

    def test_parse_json_with_chinese_quotes_and_colon(self):
        from services.model.src.core.providers.gemma4 import Gemma4EvalProvider
        text = '{“accuracy”：{“score”：90，“eva_content”：“好”}}'
        result = Gemma4EvalProvider._parse_json_response(text)
        assert result["accuracy"]["score"] == 90

    def test_parse_json_invalid(self):
        from services.model.src.core.providers.gemma4 import Gemma4EvalProvider
        result = Gemma4EvalProvider._parse_json_response("not json at all")
        assert result == {}
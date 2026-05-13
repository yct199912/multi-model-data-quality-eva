# services/model/tests/test_model_service.py
"""Tests for model service provider logic."""
import pytest


class TestJsonParsing:
    def test_parse_json_with_code_block(self):
        from services.model.src.core.providers.gemma4 import Gemma4EvalProvider
        text = '```json\n{"image_info_uniqueness": 85.0, "solid_region_score": 90.0}\n```'
        result = Gemma4EvalProvider._parse_json_response(text)
        assert result["image_info_uniqueness"] == 85.0
        assert result["solid_region_score"] == 90.0

    def test_parse_json_direct(self):
        from services.model.src.core.providers.gemma4 import Gemma4EvalProvider
        text = '{"text_info_uniqueness": 70.5, "junk_score": 88.2}'
        result = Gemma4EvalProvider._parse_json_response(text)
        assert result["text_info_uniqueness"] == 70.5
        assert result["junk_score"] == 88.2

    def test_parse_json_with_surrounding_text(self):
        from services.model.src.core.providers.gemma4 import Gemma4EvalProvider
        text = 'Here is the result: {"object_completeness": 92.0, "noise_score": 85.0} end'
        result = Gemma4EvalProvider._parse_json_response(text)
        assert result["object_completeness"] == 92.0

    def test_parse_json_invalid(self):
        from services.model.src.core.providers.gemma4 import Gemma4EvalProvider
        result = Gemma4EvalProvider._parse_json_response("not json at all")
        assert result == {}
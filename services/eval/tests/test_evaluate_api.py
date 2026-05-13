# services/eval/tests/test_evaluate_api.py
"""Tests for the evaluate API endpoint."""
import pytest
from retrieval_shared.schemas import EvaluateRequest, EvaluateResponse
from retrieval_shared.constants import EvalStatus, FileType
from services.eval.src.core.evaluator import (
    compute_content_hash,
    compute_dataset_uniqueness,
    compute_image_uniqueness_score,
    compute_image_completeness_score,
    compute_text_uniqueness_score,
    compute_text_completeness_score,
)
from services.eval.src.core.file_classifier import classify_file, is_image_file, is_text_file


class TestEvaluateRequest:
    def test_default_branch(self):
        req = EvaluateRequest(userName="owner", repoName="repo")
        assert req.branchName == "master"

    def test_custom_branch(self):
        req = EvaluateRequest(userName="owner", repoName="repo", branchName="dev")
        assert req.branchName == "dev"


class TestFileClassifier:
    def test_image_extensions(self):
        assert classify_file("photo.jpg") == FileType.IMAGE
        assert classify_file("photo.png") == FileType.IMAGE
        assert classify_file("photo.webp") == FileType.IMAGE
        assert is_image_file("photo.jpg") is True
        assert is_text_file("photo.jpg") is False

    def test_text_extensions(self):
        assert classify_file("readme.md") == FileType.TEXT
        assert classify_file("data.csv") == FileType.TEXT
        assert classify_file("report.pdf") == FileType.TEXT
        assert is_text_file("readme.md") is True
        assert is_image_file("readme.md") is False

    def test_unknown_extension(self):
        assert classify_file("archive.zip") == FileType.UNKNOWN
        assert is_image_file("archive.zip") is False
        assert is_text_file("archive.zip") is False


class TestEvaluatorFormulas:
    def test_content_hash_deterministic(self):
        h1 = compute_content_hash("abc123")
        h2 = compute_content_hash("abc123")
        assert h1 == h2

    def test_content_hash_different(self):
        h1 = compute_content_hash("abc")
        h2 = compute_content_hash("def")
        assert h1 != h2

    def test_dataset_uniqueness_all_unique(self):
        hashes = ["a", "b", "c"]
        assert compute_dataset_uniqueness(hashes) == 100.0

    def test_dataset_uniqueness_all_same(self):
        hashes = ["a", "a", "a"]
        assert compute_dataset_uniqueness(hashes) == pytest.approx(33.33, rel=0.01)

    def test_dataset_uniqueness_empty(self):
        assert compute_dataset_uniqueness([]) == 0.0

    def test_image_uniqueness_score(self):
        # info_avg=80 * 0.3 + dataset=90 * 0.7 = 24 + 63 = 87
        score = compute_image_uniqueness_score([80.0], 90.0)
        assert score == pytest.approx(87.0)

    def test_image_uniqueness_empty(self):
        assert compute_image_uniqueness_score([], 90.0) == 0.0

    def test_image_completeness_score(self):
        # solid=90*0.5 + noise=80*0.3 + object=70*0.2 = 45+24+14 = 83
        score = compute_image_completeness_score([90.0], [80.0], [70.0])
        assert score == pytest.approx(83.0)

    def test_text_uniqueness_score(self):
        # info=70*0.3 + dataset=80*0.7 = 21+56 = 77
        score = compute_text_uniqueness_score([70.0], 80.0)
        assert score == pytest.approx(77.0)

    def test_text_completeness_score(self):
        # junk=85*0.6 + desc=75*0.4 = 51+30 = 81
        score = compute_text_completeness_score([85.0], [75.0])
        assert score == pytest.approx(81.0)
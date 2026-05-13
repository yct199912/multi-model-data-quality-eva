# conftest.py
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from retrieval_shared.schemas import EvaluateRequest
from retrieval_shared.constants import FileType, EvalStatus


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def valid_evaluate_request() -> EvaluateRequest:
    return EvaluateRequest(userName="test_owner", repoName="test_repo", branchName="master")


@pytest.fixture
def mock_gitea_client():
    client = MagicMock()
    client.dfs_traverse_repo.return_value = [
        {"name": "image1.jpg", "path": "image1.jpg", "sha": "abc123", "size": 1024, "type": "file"},
        {"name": "data", "path": "data", "sha": "dir123", "size": 0, "type": "dir"},
    ]
    client.download_file.return_value = "base64_encoded_content"
    client.get_file_content.return_value = {
        "name": "test.txt",
        "path": "test.txt",
        "content": "dGVzdCBjb250ZW50",
        "size": 12,
        "type": "file",
    }
    return client


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.connect = AsyncMock()
    db.disconnect = AsyncMock()
    db.execute = AsyncMock()
    db.fetchrow = AsyncMock(return_value=None)
    db.fetch = AsyncMock(return_value=[])
    return db
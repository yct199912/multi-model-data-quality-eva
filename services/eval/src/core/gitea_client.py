# services/eval/src/core/gitea_client.py
"""Gitea API client for fetching repository contents via DFS traversal."""
import logging
import urllib.parse
from typing import Optional
import httpx
from ..config import settings

logger = logging.getLogger(__name__)


class GiteaClient:
    """同步 Gitea API 客户端，用于递归获取仓库文件内容。"""

    def __init__(self):
        self.base_url = settings.gitea_base_url.rstrip("/")
        self.token = settings.gitea_token
        self.file_ob_template = settings.gitea_file_ob
        self._headers = {"Authorization": f"token {self.token}"} if self.token else {}

    def _build_contents_url(self, owner: str, repo: str, filepath: str, ref: str) -> str:
        """构建 Gitea Contents API URL。"""
        # 替换模板中的占位符
        path = self.file_ob_template.replace("{owner}", owner).replace("{repo}", repo)
        if filepath:
            # 替换 {filepath}
            encoded_path = urllib.parse.quote(filepath, safe="/")
            path = path.replace("{filepath}", encoded_path)
        else:
            # 空路径：去掉 {filepath} 部分
            path = path.replace("/{filepath}", "").replace("{filepath}", "")

        url = f"{self.base_url}{path}"
        params = {"ref": ref}
        return url, params

    def list_directory(self, owner: str, repo: str, filepath: str, ref: str) -> list[dict]:
        """获取指定目录下的文件和文件夹列表。"""
        url, params = self._build_contents_url(owner, repo, filepath, ref)
        logger.info(f"Fetching directory listing: {url} ref={ref}")

        with httpx.Client(timeout=60) as client:
            resp = client.get(url, headers=self._headers, params=params)
            resp.raise_for_status()
            data = resp.json()
            # 单个文件返回 dict，目录返回 list
            if isinstance(data, dict):
                return [data]
            return data

    def get_file_content(self, owner: str, repo: str, filepath: str, ref: str) -> Optional[dict]:
        """获取单个文件的内容（含 base64 编码的 content 字段）。"""
        url, params = self._build_contents_url(owner, repo, filepath, ref)
        logger.info(f"Fetching file content: {url} ref={ref}")

        with httpx.Client(timeout=120) as client:
            resp = client.get(url, headers=self._headers, params=params)
            if resp.status_code == 404:
                logger.warning(f"File not found: {filepath}")
                return None
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                # 目录而非文件
                return None
            return data

    def dfs_traverse_repo(self, owner: str, repo: str, ref: str) -> list[dict]:
        """深度优先遍历仓库目录结构，返回所有文件信息。

        返回格式: [{"name": ..., "path": ..., "type": "file", "size": ..., "sha": ...}, ...]
        """
        all_files: list[dict] = []
        visited_dirs = set()

        def _dfs(dirpath: str):
            if dirpath in visited_dirs:
                return
            visited_dirs.add(dirpath)

            try:
                items = self.list_directory(owner, repo, dirpath, ref)
            except Exception as e:
                logger.error(f"Failed to list directory {dirpath}: {e}")
                return

            for item in items:
                item_type = item.get("type", "file")
                if item_type == "dir":
                    _dfs(item["path"])
                elif item_type == "file":
                    all_files.append({
                        "name": item.get("name", ""),
                        "path": item.get("path", ""),
                        "sha": item.get("sha", ""),
                        "size": item.get("size", 0),
                        "type": "file",
                    })

        _dfs("")
        logger.info(f"DFS traversal complete: {len(all_files)} files found in {owner}/{repo}@{ref}")
        return all_files

    def download_file(self, owner: str, repo: str, filepath: str, ref: str) -> Optional[str]:
        """下载单个文件的内容（base64 编码）。"""
        file_info = self.get_file_content(owner, repo, filepath, ref)
        if file_info is None:
            return None
        return file_info.get("content")


# Module-level singleton
gitea_client = GiteaClient()
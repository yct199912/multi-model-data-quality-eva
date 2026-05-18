import asyncio
import base64
import logging
import os
import uuid
import httpx
from typing import List, Dict

from retrieval_shared.constants import (
    FileType, EvalStatus,
    SCORE_TABLE_ACCURACY, SCORE_TABLE_CONSISTENCY,
    SCORE_TABLE_UNIQUENESS, SCORE_TABLE_INTEGRITY,
    SCORE_TABLE_REPO_EFFECTIVENESS, SCORE_TABLE_REPO_TIMELINESS,
    SCORE_TABLE_REPO_UNIQUENESS, SCORE_TABLE_REPO_INTEGRITY,
    SCORE_TABLE_REPO_ACCURACY, SCORE_TABLE_REPO_CONSISTENCY,
)
from retrieval_shared.database import Database
from ..config import settings
from .gitea_client import GiteaClient
from .file_classifier import is_image_file, is_text_file, is_video_file
from .document_processor import prepare_text_content, prepare_video_frames
from .ledger import QualityLedger
from ..prompts.eval_prompts import (
    OUTPUT_FORMAT_PROMPT,
    COMBINED_IMAGE_EVAL_PROMPT,
    COMBINED_TEXT_EVAL_PROMPT,
    COMBINED_VIDEO_EVAL_PROMPT,
    REPO_EFFECTIVENESS_PROMPT,
    REPO_TIMELINESS_PROMPT,
    REPO_INTER_IMAGE_UNIQUENESS_PROMPT,
    REPO_INTER_IMAGE_CONSISTENCY_PROMPT,
    REPO_INTER_TEXT_UNIQUENESS_PROMPT,
    REPO_INTER_TEXT_CONSISTENCY_PROMPT,
    REPO_IMGSELF_ACCURACY_PROMPT,
    REPO_IMGSELF_CONSISTENCY_REGION_PROMPT,
    REPO_IMGSELF_CONSISTENCY_NOISE_PROMPT,
    REPO_IMGSELF_UNIQUENESS_PROMPT,
    REPO_IMGSELF_INTEGRITY_PROMPT,
    REPO_TEXTSELF_ACCURACY_FORMAT_PROMPT,
    REPO_TEXTSELF_ACCURACY_CONTENT_PROMPT,
    REPO_TEXTSELF_CONSISTENCY_NOINFO_PROMPT,
    REPO_TEXTSELF_CONSISTENCY_DESC_PROMPT,
    REPO_TEXTSELF_UNIQUENESS_PROMPT,
    REPO_TEXTSELF_INTEGRITY_PROMPT,
)

logger = logging.getLogger(__name__)

class EvaluationCoordinator:
    """
    Coordinates the multi-dimensional evaluation of a repository.
    Provides a deep interface for file discovery, multimodal analysis, and database persistence.
    """
    def __init__(self, db: Database, loop: asyncio.AbstractEventLoop):
        self.db = db
        self.loop = loop
        self.gitea = GiteaClient()
        self.ledger = QualityLedger(db, loop)
        self.evaluated_count = 0

    def evaluate_resource(self, task_id: str, user_name: str, repo_name: str, branch_name: str, repo_introduction: str):
        repo = f"{user_name}/{repo_name}"
        
        self.ledger.clear_repo_history(user_name, repo_name)

        all_files = self.gitea.dfs_traverse_repo(user_name, repo_name, branch_name)
        if not all_files:
            logger.warning(f"No files found in {repo}@{branch_name}")
            self._update_task_progress(task_id, 0, 0)
            return

        image_files = [f for f in all_files if is_image_file(f["path"])]
        text_files = [f for f in all_files if is_text_file(f["path"])]
        video_files = [f for f in all_files if is_video_file(f["path"])]
        
        total_count = len(image_files) + len(text_files) + len(video_files)
        self._update_task_progress(task_id, total_count, 0)

        self._process_images(task_id, user_name, repo_name, branch_name, image_files)
        self._process_texts(task_id, user_name, repo_name, branch_name, text_files)
        self._process_videos(task_id, user_name, repo_name, branch_name, video_files)

        self._do_repo_evaluation(repo, repo_introduction, image_files, text_files, video_files)

        logger.info(f"Evaluation task {task_id} completed: {len(image_files)} images, {len(text_files)} texts, {len(video_files)} videos")

    def _update_task_progress(self, task_id: str, total: int = None, evaluated: int = None):
        if total is not None and evaluated is not None:
            self.loop.run_until_complete(self.db.execute("UPDATE eval_tasks SET total_files=$1, evaluated_files=$2 WHERE task_id=$3", total, evaluated, task_id))
        elif evaluated is not None:
            self.loop.run_until_complete(self.db.execute("UPDATE eval_tasks SET evaluated_files=$1 WHERE task_id=$2", evaluated, task_id))

    def _increment_progress(self, task_id: str):
        self.evaluated_count += 1
        self._update_task_progress(task_id, evaluated=self.evaluated_count)

    def _call_model(self, rule_prompt: str, image_base64: str = None, text_content: str = None, video_frames: list = None) -> dict:
        url = f"{settings.model_server_url}/api/v1/evaluate"
        payload = {
            "rule_prompt": rule_prompt,
            "output_format_prompt": OUTPUT_FORMAT_PROMPT,
        }
        if image_base64:
            payload["image_base64"] = image_base64
        elif text_content:
            payload["text_content"] = text_content
        elif video_frames:
            payload["video_frames"] = video_frames

        with httpx.Client(timeout=httpx.Timeout(connect=30, read=1200, write=30, pool=30)) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            # 兼容 CodeWrapperMiddleware 包裹的 {"code": 200, "data": {...}} 格式
            if isinstance(data, dict) and "code" in data and "data" in data:
                data = data["data"]
            return data

    def _process_images(self, task_id, user_name, repo_name, branch_name, files):
        repo = f"{user_name}/{repo_name}"
        for f in files:
            file_path = f["path"]
            try:
                content_b64 = self.gitea.download_file(user_name, repo_name, file_path, branch_name)
                if not content_b64:
                    self._increment_progress(task_id)
                    continue

                model_resp = self._call_model(COMBINED_IMAGE_EVAL_PROMPT, image_base64=content_b64)
                result = model_resp.get("raw_result") or model_resp
                
                dims = [
                    ("accuracy", SCORE_TABLE_ACCURACY, "image-content"),
                    ("noinfo", SCORE_TABLE_CONSISTENCY, "image-noinfo"),
                    ("noise", SCORE_TABLE_CONSISTENCY, "image-noise"),
                    ("uniqueness", SCORE_TABLE_UNIQUENESS, "image-content"),
                    ("consistency", SCORE_TABLE_INTEGRITY, "image-content"),
                ]
                scores_map = {}
                fallback_score = result.get("score", 0)
                if isinstance(fallback_score, dict): fallback_score = fallback_score.get("score", 0)
                
                for key, table, eva_type in dims:
                    data = result.get(key, {})
                    val = data.get("score", fallback_score if fallback_score > 0 else 0)
                    scores_map[key] = val
                    self.ledger.record_file_score(table, repo, file_path, val, "image", eva_type, data.get("eva_content", ""))
                
                description = result.get("accuracy", {}).get("eva_content", "")
                if not description and isinstance(result.get("eva_content"), str): description = result.get("eva_content")
                    
                self.ledger.record_file_summary(task_id, user_name, repo_name, file_path, "image", scores_map, description)
            except Exception as e:
                logger.error(f"Image combined eval failed for {file_path}: {e}")
            self._increment_progress(task_id)

    def _process_texts(self, task_id, user_name, repo_name, branch_name, files):
        repo = f"{user_name}/{repo_name}"
        for f in files:
            file_path = f["path"]
            try:
                file_info = self.gitea.get_file_content(user_name, repo_name, file_path, branch_name)
                if not file_info or not file_info.get("content"):
                    self._increment_progress(task_id)
                    continue
                content_b64 = file_info["content"]
                
                text_content = prepare_text_content(content_b64, file_path)

                model_resp = self._call_model(COMBINED_TEXT_EVAL_PROMPT, text_content=text_content)
                result = model_resp.get("raw_result") or model_resp
                
                dims = [
                    ("format_accuracy", SCORE_TABLE_ACCURACY, "text-format"),
                    ("content_accuracy", SCORE_TABLE_ACCURACY, "text-content"),
                    ("noinfo", SCORE_TABLE_CONSISTENCY, "text-noinfo"),
                    ("desc_completeness", SCORE_TABLE_CONSISTENCY, "text-desc"),
                    ("uniqueness", SCORE_TABLE_UNIQUENESS, "text-content"),
                    ("consistency", SCORE_TABLE_INTEGRITY, "text-content"),
                ]
                scores_map = {}
                fallback_score = result.get("score", 0)
                if isinstance(fallback_score, dict): fallback_score = fallback_score.get("score", 0)
                
                for key, table, eva_type in dims:
                    data = result.get(key, {})
                    val = data.get("score", fallback_score if fallback_score > 0 else 0)
                    scores_map[key] = val
                    self.ledger.record_file_score(table, repo, file_path, val, "text", eva_type, data.get("eva_content", ""))
                
                description = result.get("content_accuracy", {}).get("eva_content", "")
                if not description and isinstance(result.get("eva_content"), str): description = result.get("eva_content")
                    
                self.ledger.record_file_summary(task_id, user_name, repo_name, file_path, "text", scores_map, description)
            except Exception as e:
                logger.error(f"Text combined eval failed for {file_path}: {e}")
            self._increment_progress(task_id)

    def _process_videos(self, task_id, user_name, repo_name, branch_name, files):
        repo = f"{user_name}/{repo_name}"
        for f in files:
            file_path = f["path"]
            try:
                content_b64 = self.gitea.download_file(user_name, repo_name, file_path, branch_name)
                if not content_b64:
                    self._increment_progress(task_id)
                    continue
                
                frames = prepare_video_frames(content_b64)
                if not frames:
                    self._increment_progress(task_id)
                    continue

                model_resp = self._call_model(COMBINED_VIDEO_EVAL_PROMPT, video_frames=frames)
                result = model_resp.get("raw_result") or model_resp
                
                dims = [
                    ("temporal_consistency", SCORE_TABLE_CONSISTENCY, "video-temporal"),
                    ("visual_quality", SCORE_TABLE_CONSISTENCY, "video-visual"),
                    ("content_accuracy", SCORE_TABLE_ACCURACY, "video-content"),
                    ("redundancy", SCORE_TABLE_UNIQUENESS, "video-content"),
                ]
                scores_map = {}
                fallback_score = result.get("score", 0)
                if isinstance(fallback_score, dict): fallback_score = fallback_score.get("score", 0)

                for key, table, eva_type in dims:
                    data = result.get(key, {})
                    val = data.get("score", fallback_score if fallback_score > 0 else 0)
                    scores_map[key] = val
                    self.ledger.record_file_score(table, repo, file_path, val, "video", eva_type, data.get("eva_content", ""))
                
                description = result.get("content_accuracy", {}).get("eva_content", "")
                if not description and isinstance(result.get("eva_content"), str): description = result.get("eva_content")

                self.ledger.record_file_summary(task_id, user_name, repo_name, file_path, "video", scores_map, description)
            except Exception as e:
                logger.error(f"Video combined eval failed for {file_path}: {e}")
            self._increment_progress(task_id)

    def _do_repo_evaluation(self, repo, repo_introduction, image_files, text_files, video_files):
        if repo_introduction:
            try:
                res = self._call_model(REPO_EFFECTIVENESS_PROMPT, text_content=repo_introduction)
                logger.info(f"模型分析结果:{res}")
                self.ledger.record_repo_score(SCORE_TABLE_REPO_EFFECTIVENESS, repo, res.get("score", 0), res.get("eva_content", ""))
            except Exception as e: logger.error(f"Repo eval err: {e}")
            
            try:
                res = self._call_model(REPO_TIMELINESS_PROMPT, text_content=repo_introduction)
                logger.info(f"模型分析结果:{res}")
                self.ledger.record_repo_score(SCORE_TABLE_REPO_TIMELINESS, repo, res.get("score", 0), res.get("eva_content", ""))
            except Exception as e: logger.error(f"Repo eval err: {e}")

        if image_files:
            try:
                res = self._call_model(REPO_INTER_IMAGE_UNIQUENESS_PROMPT, text_content=f"Images: {len(image_files)}")
                logger.info(f"模型分析结果:{res}")
                self.ledger.update_or_insert_repo_self_score(SCORE_TABLE_REPO_UNIQUENESS, repo, res.get("score", 0), res.get("eva_content", ""), "inter-image-unq")
            except: pass
            try:
                res = self._call_model(REPO_INTER_IMAGE_CONSISTENCY_PROMPT, text_content=f"Images: {len(image_files)}")
                logger.info(f"模型分析结果:{res}")
                self.ledger.update_or_insert_repo_self_score(SCORE_TABLE_REPO_INTEGRITY, repo, res.get("score", 0), res.get("eva_content", ""), "inter-image-integrity")
            except: pass
            
        if text_files:
            try:
                res = self._call_model(REPO_INTER_TEXT_UNIQUENESS_PROMPT, text_content=f"Texts: {len(text_files)}")
                logger.info(f"模型分析结果:{res}")
                self.ledger.update_or_insert_repo_self_score(SCORE_TABLE_REPO_UNIQUENESS, repo, res.get("score", 0), res.get("eva_content", ""), "inter-text-unq")
            except: pass
            try:
                res = self._call_model(REPO_INTER_TEXT_CONSISTENCY_PROMPT, text_content=f"Texts: {len(text_files)}")
                logger.info(f"模型分析结果:{res}")
                self.ledger.update_or_insert_repo_self_score(SCORE_TABLE_REPO_INTEGRITY, repo, res.get("score", 0), res.get("eva_content", ""), "inter-text-integrity")
            except: pass

        self._do_repo_self_evaluation(repo, image_files, text_files)

    def _do_repo_self_evaluation(self, repo, image_files, text_files):
        if image_files:
            try:
                score_avg = self.loop.run_until_complete(self.ledger.get_avg_score(SCORE_TABLE_ACCURACY, repo, "image-content", "image"))
                res = self._call_model(REPO_IMGSELF_ACCURACY_PROMPT, text_content="Images evaluated")
                self.ledger.update_or_insert_repo_self_score(SCORE_TABLE_REPO_ACCURACY, repo, res.get("score", 0), res.get("eva_content", ""), "imgself-accuracy", score_avg, score_avg * 0.5 + res.get("score", 0) * 0.5)
            except: pass
            try:
                score_avg = self.loop.run_until_complete(self.ledger.get_avg_score(SCORE_TABLE_CONSISTENCY, repo, "image-noinfo", "image"))
                res = self._call_model(REPO_IMGSELF_CONSISTENCY_REGION_PROMPT, text_content="Images evaluated")
                self.ledger.update_or_insert_repo_self_score(SCORE_TABLE_REPO_CONSISTENCY, repo, res.get("score", 0), res.get("eva_content", ""), "imgself-consistency-region", score_avg, score_avg * 0.5 + res.get("score", 0) * 0.5)
            except: pass
            try:
                score_avg = self.loop.run_until_complete(self.ledger.get_avg_score(SCORE_TABLE_CONSISTENCY, repo, "image-noise", "image"))
                res = self._call_model(REPO_IMGSELF_CONSISTENCY_NOISE_PROMPT, text_content="Images evaluated")
                self.ledger.update_or_insert_repo_self_score(SCORE_TABLE_REPO_CONSISTENCY, repo, res.get("score", 0), res.get("eva_content", ""), "imgself-consistency-noise", score_avg, score_avg * 0.5 + res.get("score", 0) * 0.5)
            except: pass
            try:
                score_avg = self.loop.run_until_complete(self.ledger.get_avg_score(SCORE_TABLE_UNIQUENESS, repo, "image-content", "image"))
                res = self._call_model(REPO_IMGSELF_UNIQUENESS_PROMPT, text_content="Images evaluated")
                self.ledger.update_or_insert_repo_self_score(SCORE_TABLE_REPO_UNIQUENESS, repo, res.get("score", 0), res.get("eva_content", ""), "imgself-unq", score_avg, score_avg * 0.5 + res.get("score", 0) * 0.5)
            except: pass
            try:
                score_avg = self.loop.run_until_complete(self.ledger.get_avg_score(SCORE_TABLE_INTEGRITY, repo, "image-content", "image"))
                res = self._call_model(REPO_IMGSELF_INTEGRITY_PROMPT, text_content="Images evaluated")
                self.ledger.update_or_insert_repo_self_score(SCORE_TABLE_REPO_INTEGRITY, repo, res.get("score", 0), res.get("eva_content", ""), "imgself-integrity", score_avg, score_avg * 0.5 + res.get("score", 0) * 0.5)
            except: pass

        if text_files:
            try:
                score_avg = self.loop.run_until_complete(self.ledger.get_avg_score(SCORE_TABLE_ACCURACY, repo, "text-format", "text"))
                res = self._call_model(REPO_TEXTSELF_ACCURACY_FORMAT_PROMPT, text_content="Texts evaluated")
                self.ledger.update_or_insert_repo_self_score(SCORE_TABLE_REPO_ACCURACY, repo, res.get("score", 0), res.get("eva_content", ""), "textself-accuracy-format", score_avg, score_avg * 0.5 + res.get("score", 0) * 0.5)
            except: pass
            try:
                score_avg = self.loop.run_until_complete(self.ledger.get_avg_score(SCORE_TABLE_ACCURACY, repo, "text-content", "text"))
                res = self._call_model(REPO_TEXTSELF_ACCURACY_CONTENT_PROMPT, text_content="Texts evaluated")
                self.ledger.update_or_insert_repo_self_score(SCORE_TABLE_REPO_ACCURACY, repo, res.get("score", 0), res.get("eva_content", ""), "textself-accuracy-content", score_avg, score_avg * 0.5 + res.get("score", 0) * 0.5)
            except: pass
            try:
                score_avg = self.loop.run_until_complete(self.ledger.get_avg_score(SCORE_TABLE_CONSISTENCY, repo, "text-noinfo", "text"))
                res = self._call_model(REPO_TEXTSELF_CONSISTENCY_NOINFO_PROMPT, text_content="Texts evaluated")
                self.ledger.update_or_insert_repo_self_score(SCORE_TABLE_REPO_CONSISTENCY, repo, res.get("score", 0), res.get("eva_content", ""), "textself-consistency-noinfo", score_avg, score_avg * 0.5 + res.get("score", 0) * 0.5)
            except: pass
            try:
                score_avg = self.loop.run_until_complete(self.ledger.get_avg_score(SCORE_TABLE_CONSISTENCY, repo, "text-desc", "text"))
                res = self._call_model(REPO_TEXTSELF_CONSISTENCY_DESC_PROMPT, text_content="Texts evaluated")
                self.ledger.update_or_insert_repo_self_score(SCORE_TABLE_REPO_CONSISTENCY, repo, res.get("score", 0), res.get("eva_content", ""), "textself-consistency-content", score_avg, score_avg * 0.5 + res.get("score", 0) * 0.5)
            except: pass
            try:
                score_avg = self.loop.run_until_complete(self.ledger.get_avg_score(SCORE_TABLE_UNIQUENESS, repo, "text-content", "text"))
                res = self._call_model(REPO_TEXTSELF_UNIQUENESS_PROMPT, text_content="Texts evaluated")
                self.ledger.update_or_insert_repo_self_score(SCORE_TABLE_REPO_UNIQUENESS, repo, res.get("score", 0), res.get("eva_content", ""), "textself-unq", score_avg, score_avg * 0.5 + res.get("score", 0) * 0.5)
            except: pass
            try:
                score_avg = self.loop.run_until_complete(self.ledger.get_avg_score(SCORE_TABLE_INTEGRITY, repo, "text-content", "text"))
                res = self._call_model(REPO_TEXTSELF_INTEGRITY_PROMPT, text_content="Texts evaluated")
                self.ledger.update_or_insert_repo_self_score(SCORE_TABLE_REPO_INTEGRITY, repo, res.get("score", 0), res.get("eva_content", ""), "textself-integrity", score_avg, score_avg * 0.5 + res.get("score", 0) * 0.5)
            except: pass

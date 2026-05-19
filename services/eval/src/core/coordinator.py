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
from .evaluator import (
    compute_dataset_uniqueness,
    compute_image_uniqueness_score,
    compute_image_completeness_score,
    compute_text_uniqueness_score,
    compute_text_completeness_score,
)
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
    def __init__(self, db: Database, redis_client: any, loop: asyncio.AbstractEventLoop):
        self.db = db
        self.redis = redis_client
        self.loop = loop
        self.gitea = GiteaClient()
        self.ledger = QualityLedger(db, loop)
        self.evaluated_count = 0
        
        # Intermediate results for aggregation
        self.image_results = []
        self.text_results = []
        self.video_results = []
        self.image_shas = []
        self.text_shas = []
        self.img_dataset_unq = 0.0
        self.txt_dataset_unq = 0.0

    async def evaluate_resource(self, task_id: str, user_name: str, repo_name: str, branch_name: str, repo_introduction: str):
        repo = f"{user_name}/{repo_name}"
        lock_key = f"lock:eval:{repo}"
        
        # Acquire distributed lock
        redis = await self.redis.get_client()
        # Set lock with 1 hour timeout as safeguard
        if not await redis.set(lock_key, task_id, ex=3600, nx=True):
            logger.warning(f"Task {task_id} skipped: Repo {repo} is already being evaluated by another task.")
            await self.db.execute("UPDATE eval_tasks SET status=$1, error_message=$2 WHERE task_id=$3", 
                                 EvalStatus.FAILED.value, "Repo already being evaluated by another task.", task_id)
            return

        try:
            await self.ledger.clear_repo_history(user_name, repo_name)

            all_files = self.gitea.dfs_traverse_repo(user_name, repo_name, branch_name)
            if not all_files:
                logger.warning(f"No files found in {repo}@{branch_name}")
                await self._update_task_progress(task_id, 0, 0)
                return

            image_files = [f for f in all_files if is_image_file(f["path"])]
            text_files = [f for f in all_files if is_text_file(f["path"])]
            video_files = [f for f in all_files if is_video_file(f["path"])]
            
            self.image_shas = [f["sha"] for f in image_files if f.get("sha")]
            self.text_shas = [f["sha"] for f in text_files if f.get("sha")]
            
            total_count = len(image_files) + len(text_files) + len(video_files)
            await self._update_task_progress(task_id, total_count, 0)

            # Compute dataset-wide uniqueness scores early
            self.img_dataset_unq = compute_dataset_uniqueness(self.image_shas)
            self.txt_dataset_unq = compute_dataset_uniqueness(self.text_shas)

            await self._process_images(task_id, user_name, repo_name, branch_name, image_files)
            await self._process_texts(task_id, user_name, repo_name, branch_name, text_files)
            await self._process_videos(task_id, user_name, repo_name, branch_name, video_files)

            try:
                await self._do_repo_evaluation(repo, repo_introduction, image_files, text_files, video_files)
                await self._finalize_aggregation(task_id, user_name, repo_name, branch_name)
            except Exception as e:
                logger.error(f"Repo evaluation/aggregation failed: {e}")

            logger.info(f"Evaluation task {task_id} completed: {len(image_files)} images, {len(text_files)} texts, {len(video_files)} videos")
        finally:
            # Release lock only if we own it
            current_task = await redis.get(lock_key)
            if current_task and current_task.decode() == task_id:
                await redis.delete(lock_key)

    async def _finalize_aggregation(self, task_id, user_name, repo_name, branch_name):
        """汇总全数据集指标并存入 eval_aggregate_results。"""
        # Calculate image aggregate scores
        img_unq_score = 0.0
        img_comp_score = 0.0
        img_unq_desc = ""
        if self.image_results:
            info_unqs = [r.get("uniqueness", 0) for r in self.image_results]
            img_unq_score = compute_image_uniqueness_score(info_unqs, self.img_dataset_unq)
            
            solids = [r.get("noinfo", 0) for r in self.image_results]
            noises = [r.get("noise", 0) for r in self.image_results]
            objs = [r.get("consistency", 0) for r in self.image_results]
            img_comp_score = compute_image_completeness_score(solids, noises, objs)
            img_unq_desc = f"数据集唯一性分: {self.img_dataset_unq}, 样本平均图内唯一性: {round(sum(info_unqs)/len(info_unqs), 2) if info_unqs else 0}"

        # Calculate text aggregate scores
        txt_unq_score = 0.0
        txt_comp_score = 0.0
        txt_unq_desc = ""
        if self.text_results:
            info_unqs = [r.get("uniqueness", 0) for r in self.text_results]
            txt_unq_score = compute_text_uniqueness_score(info_unqs, self.txt_dataset_unq)
            
            junks = [r.get("noinfo", 0) for r in self.text_results]
            descs = [r.get("desc_completeness", 0) for r in self.text_results]
            txt_comp_score = compute_text_completeness_score(junks, descs)
            txt_unq_desc = f"数据集唯一性分: {self.txt_dataset_unq}, 样本平均文内唯一性: {round(sum(info_unqs)/len(info_unqs), 2) if info_unqs else 0}"

        agg_data = {
            "total_image_count": len(self.image_shas),
            "total_text_count": len(self.text_shas),
            "unique_image_count": len(set(self.image_shas)),
            "unique_text_count": len(set(self.text_shas)),
            "image_uniqueness_score": img_unq_score,
            "image_completeness_score": img_comp_score,
            "text_uniqueness_score": txt_unq_score,
            "text_completeness_score": txt_comp_score,
            "image_uniqueness_description": img_unq_desc,
            "text_uniqueness_description": txt_unq_desc,
        }
        await self.ledger.record_aggregate_results(task_id, user_name, repo_name, branch_name, agg_data)

    async def _update_task_progress(self, task_id: str, total: int = None, evaluated: int = None):
        if total is not None and evaluated is not None:
            await self.db.execute("UPDATE eval_tasks SET total_files=$1, evaluated_files=$2 WHERE task_id=$3", total, evaluated, task_id)
        elif evaluated is not None:
            await self.db.execute("UPDATE eval_tasks SET evaluated_files=$1 WHERE task_id=$2", evaluated, task_id)

    async def _increment_progress(self, task_id: str):
        self.evaluated_count += 1
        await self._update_task_progress(task_id, evaluated=self.evaluated_count)

    async def _call_model(self, rule_prompt: str, image_base64: str = None, text_content: str = None, video_frames: list = None) -> dict:
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

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=30, read=1200, write=30, pool=30)) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, dict) and "code" in data and "data" in data:
                    data = data["data"]
                return data
        except Exception as e:
            logger.error(f"Model call failed: {e}")
            return {"score": 0.0, "eva_content": f"Error: {str(e)}"}

    async def _process_images(self, task_id, user_name, repo_name, branch_name, files):
        repo = f"{user_name}/{repo_name}"
        for f in files:
            file_path = f["path"]
            try:
                content_b64 = self.gitea.download_file(user_name, repo_name, file_path, branch_name)
                if not content_b64:
                    await self._increment_progress(task_id)
                    continue

                model_resp = await self._call_model(COMBINED_IMAGE_EVAL_PROMPT, image_base64=content_b64)
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
                    await self.ledger.record_file_score(table, repo, file_path, val, "image", eva_type, data.get("eva_content", ""))
                
                scores_map["dataset_uniqueness"] = self.img_dataset_unq
                self.image_results.append(scores_map)

                description = result.get("accuracy", {}).get("eva_content", "")
                if not description and isinstance(result.get("eva_content"), str): description = result.get("eva_content")
                    
                await self.ledger.record_file_summary(task_id, user_name, repo_name, file_path, "image", scores_map, description)
            except Exception as e:
                logger.error(f"Image combined eval failed for {file_path}: {e}")
            await self._increment_progress(task_id)

    async def _process_texts(self, task_id, user_name, repo_name, branch_name, files):
        repo = f"{user_name}/{repo_name}"
        for f in files:
            file_path = f["path"]
            try:
                file_info = self.gitea.get_file_content(user_name, repo_name, file_path, branch_name)
                if not file_info or not file_info.get("content"):
                    await self._increment_progress(task_id)
                    continue
                content_b64 = file_info["content"]
                
                text_content = prepare_text_content(content_b64, file_path)

                model_resp = await self._call_model(COMBINED_TEXT_EVAL_PROMPT, text_content=text_content)
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
                    await self.ledger.record_file_score(table, repo, file_path, val, "text", eva_type, data.get("eva_content", ""))
                
                scores_map["dataset_uniqueness"] = self.txt_dataset_unq
                self.text_results.append(scores_map)

                description = result.get("content_accuracy", {}).get("eva_content", "")
                if not description and isinstance(result.get("eva_content"), str): description = result.get("eva_content")
                    
                await self.ledger.record_file_summary(task_id, user_name, repo_name, file_path, "text", scores_map, description)
            except Exception as e:
                logger.error(f"Text combined eval failed for {file_path}: {e}")
            await self._increment_progress(task_id)

    async def _process_videos(self, task_id, user_name, repo_name, branch_name, files):
        repo = f"{user_name}/{repo_name}"
        for f in files:
            file_path = f["path"]
            try:
                content_b64 = self.gitea.download_file(user_name, repo_name, file_path, branch_name)
                if not content_b64:
                    await self._increment_progress(task_id)
                    continue
                
                frames = prepare_video_frames(content_b64)
                if not frames:
                    await self._increment_progress(task_id)
                    continue

                model_resp = await self._call_model(COMBINED_VIDEO_EVAL_PROMPT, video_frames=frames)
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
                    await self.ledger.record_file_score(table, repo, file_path, val, "video", eva_type, data.get("eva_content", ""))
                
                self.video_results.append(scores_map)
                description = result.get("content_accuracy", {}).get("eva_content", "")
                if not description and isinstance(result.get("eva_content"), str): description = result.get("eva_content")

                await self.ledger.record_file_summary(task_id, user_name, repo_name, file_path, "video", scores_map, description)
            except Exception as e:
                logger.error(f"Video combined eval failed for {file_path}: {e}")
            await self._increment_progress(task_id)

    async def _do_repo_evaluation(self, repo, repo_introduction, image_files, text_files, video_files):
        # Build contextual context for repo-level eval
        image_summary = ""
        if self.image_results:
            avg_acc = sum(r.get("accuracy", 0) for r in self.image_results) / len(self.image_results)
            image_summary = f"Evaluated {len(self.image_results)} images. Average accuracy: {avg_acc:.2f}. Dataset uniqueness: {self.img_dataset_unq}%."
            
        text_summary = ""
        if self.text_results:
            avg_acc = sum(r.get("content_accuracy", 0) for r in self.text_results) / len(self.text_results)
            text_summary = f"Evaluated {len(self.text_results)} texts. Average content accuracy: {avg_acc:.2f}. Dataset uniqueness: {self.txt_dataset_unq}%."

        if repo_introduction:
            context = f"Repo Intro: {repo_introduction}\n{image_summary}\n{text_summary}"
            try:
                res = await self._call_model(REPO_EFFECTIVENESS_PROMPT, text_content=context)
                await self.ledger.record_repo_score(SCORE_TABLE_REPO_EFFECTIVENESS, repo, res.get("score", 0), res.get("eva_content", ""))
            except: pass
            
            try:
                res = await self._call_model(REPO_TIMELINESS_PROMPT, text_content=context)
                await self.ledger.record_repo_score(SCORE_TABLE_REPO_TIMELINESS, repo, res.get("score", 0), res.get("eva_content", ""))
            except: pass

        if image_files:
            try:
                res = await self._call_model(REPO_INTER_IMAGE_UNIQUENESS_PROMPT, text_content=image_summary)
                await self.ledger.update_or_insert_repo_self_score(SCORE_TABLE_REPO_UNIQUENESS, repo, res.get("score", 0), res.get("eva_content", ""), "inter-image-unq")
            except: pass
            try:
                res = await self._call_model(REPO_INTER_IMAGE_CONSISTENCY_PROMPT, text_content=image_summary)
                await self.ledger.update_or_insert_repo_self_score(SCORE_TABLE_REPO_INTEGRITY, repo, res.get("score", 0), res.get("eva_content", ""), "inter-image-integrity")
            except: pass
            
        if text_files:
            try:
                res = await self._call_model(REPO_INTER_TEXT_UNIQUENESS_PROMPT, text_content=text_summary)
                await self.ledger.update_or_insert_repo_self_score(SCORE_TABLE_REPO_UNIQUENESS, repo, res.get("score", 0), res.get("eva_content", ""), "inter-text-unq")
            except: pass
            try:
                res = await self._call_model(REPO_INTER_TEXT_CONSISTENCY_PROMPT, text_content=text_summary)
                await self.ledger.update_or_insert_repo_self_score(SCORE_TABLE_REPO_INTEGRITY, repo, res.get("score", 0), res.get("eva_content", ""), "inter-text-integrity")
            except: pass

        await self._do_repo_self_evaluation(repo, image_files, text_files, image_summary, text_summary)

    async def _do_repo_self_evaluation(self, repo, image_files, text_files, image_summary, text_summary):
        if image_files:
            # imgself-accuracy
            try:
                score_avg = await self.ledger.get_avg_score(SCORE_TABLE_ACCURACY, repo, "image-content", "image")
                res = await self._call_model(REPO_IMGSELF_ACCURACY_PROMPT, text_content=image_summary)
                await self.ledger.update_or_insert_repo_self_score(SCORE_TABLE_REPO_ACCURACY, repo, res.get("score", 0), res.get("eva_content", ""), "imgself-accuracy", score_avg, score_avg * 0.3 + res.get("score", 0) * 0.7)
            except: pass
            # imgself-consistency-region
            try:
                score_avg = await self.ledger.get_avg_score(SCORE_TABLE_CONSISTENCY, repo, "image-noinfo", "image")
                res = await self._call_model(REPO_IMGSELF_CONSISTENCY_REGION_PROMPT, text_content=image_summary)
                await self.ledger.update_or_insert_repo_self_score(SCORE_TABLE_REPO_CONSISTENCY, repo, res.get("score", 0), res.get("eva_content", ""), "imgself-consistency-region", score_avg, score_avg * 0.5 + res.get("score", 0) * 0.5)
            except: pass
            # imgself-consistency-noise
            try:
                score_avg = await self.ledger.get_avg_score(SCORE_TABLE_CONSISTENCY, repo, "image-noise", "image")
                res = await self._call_model(REPO_IMGSELF_CONSISTENCY_NOISE_PROMPT, text_content=image_summary)
                await self.ledger.update_or_insert_repo_self_score(SCORE_TABLE_REPO_CONSISTENCY, repo, res.get("score", 0), res.get("eva_content", ""), "imgself-consistency-noise", score_avg, score_avg * 0.5 + res.get("score", 0) * 0.5)
            except: pass
            # imgself-unq
            try:
                score_avg = await self.ledger.get_avg_score(SCORE_TABLE_UNIQUENESS, repo, "image-content", "image")
                res = await self._call_model(REPO_IMGSELF_UNIQUENESS_PROMPT, text_content=image_summary)
                # 使用 CLAUDE.md 定义的 0.3/0.7 权重
                await self.ledger.update_or_insert_repo_self_score(SCORE_TABLE_REPO_UNIQUENESS, repo, res.get("score", 0), res.get("eva_content", ""), "imgself-unq", score_avg, score_avg * 0.3 + self.img_dataset_unq * 0.7)
            except: pass
            # imgself-integrity
            try:
                score_avg = await self.ledger.get_avg_score(SCORE_TABLE_INTEGRITY, repo, "image-content", "image")
                res = await self._call_model(REPO_IMGSELF_INTEGRITY_PROMPT, text_content=image_summary)
                await self.ledger.update_or_insert_repo_self_score(SCORE_TABLE_REPO_INTEGRITY, repo, res.get("score", 0), res.get("eva_content", ""), "imgself-integrity", score_avg, score_avg * 0.5 + res.get("score", 0) * 0.5)
            except: pass

        if text_files:
            # textself-accuracy-format
            try:
                score_avg = await self.ledger.get_avg_score(SCORE_TABLE_ACCURACY, repo, "text-format", "text")
                res = await self._call_model(REPO_TEXTSELF_ACCURACY_FORMAT_PROMPT, text_content=text_summary)
                await self.ledger.update_or_insert_repo_self_score(SCORE_TABLE_REPO_ACCURACY, repo, res.get("score", 0), res.get("eva_content", ""), "textself-accuracy-format", score_avg, score_avg * 0.5 + res.get("score", 0) * 0.5)
            except: pass
            # textself-accuracy-content
            try:
                score_avg = await self.ledger.get_avg_score(SCORE_TABLE_ACCURACY, repo, "text-content", "text")
                res = await self._call_model(REPO_TEXTSELF_ACCURACY_CONTENT_PROMPT, text_content=text_summary)
                await self.ledger.update_or_insert_repo_self_score(SCORE_TABLE_REPO_ACCURACY, repo, res.get("score", 0), res.get("eva_content", ""), "textself-accuracy-content", score_avg, score_avg * 0.5 + res.get("score", 0) * 0.5)
            except: pass
            # textself-consistency-noinfo
            try:
                score_avg = await self.ledger.get_avg_score(SCORE_TABLE_CONSISTENCY, repo, "text-noinfo", "text")
                res = await self._call_model(REPO_TEXTSELF_CONSISTENCY_NOINFO_PROMPT, text_content=text_summary)
                await self.ledger.update_or_insert_repo_self_score(SCORE_TABLE_REPO_CONSISTENCY, repo, res.get("score", 0), res.get("eva_content", ""), "textself-consistency-noinfo", score_avg, score_avg * 0.5 + res.get("score", 0) * 0.5)
            except: pass
            # textself-consistency-content
            try:
                score_avg = await self.ledger.get_avg_score(SCORE_TABLE_CONSISTENCY, repo, "text-desc", "text")
                res = await self._call_model(REPO_TEXTSELF_CONSISTENCY_DESC_PROMPT, text_content=text_summary)
                await self.ledger.update_or_insert_repo_self_score(SCORE_TABLE_REPO_CONSISTENCY, repo, res.get("score", 0), res.get("eva_content", ""), "textself-consistency-content", score_avg, score_avg * 0.5 + res.get("score", 0) * 0.5)
            except: pass
            # textself-unq
            try:
                score_avg = await self.ledger.get_avg_score(SCORE_TABLE_UNIQUENESS, repo, "text-content", "text")
                res = await self._call_model(REPO_TEXTSELF_UNIQUENESS_PROMPT, text_content=text_summary)
                await self.ledger.update_or_insert_repo_self_score(SCORE_TABLE_REPO_UNIQUENESS, repo, res.get("score", 0), res.get("eva_content", ""), "textself-unq", score_avg, score_avg * 0.3 + self.txt_dataset_unq * 0.7)
            except: pass
            # textself-integrity
            try:
                score_avg = await self.ledger.get_avg_score(SCORE_TABLE_INTEGRITY, repo, "text-content", "text")
                res = await self._call_model(REPO_TEXTSELF_INTEGRITY_PROMPT, text_content=text_summary)
                await self.ledger.update_or_insert_repo_self_score(SCORE_TABLE_REPO_INTEGRITY, repo, res.get("score", 0), res.get("eva_content", ""), "textself-integrity", score_avg, score_avg * 0.5 + res.get("score", 0) * 0.5)
            except: pass

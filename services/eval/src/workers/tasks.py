import uuid
# services/eval/src/workers/tasks.py
"""Celery 任务 — 数据质量评价核心流程。"""
import asyncio
import base64
import logging
import os
import httpx
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
from ..core.gitea_client import GiteaClient
from ..core.file_classifier import classify_file, is_image_file, is_text_file, is_video_file
from ..core.document_processor import extract_text_by_extension, extract_frames_from_video
from ..prompts.eval_prompts import (
    OUTPUT_FORMAT_PROMPT,
    COMBINED_IMAGE_EVAL_PROMPT,
    COMBINED_TEXT_EVAL_PROMPT,
    COMBINED_VIDEO_EVAL_PROMPT,
    # image prompts
    IMAGE_ACCURACY_PROMPT,
    IMAGE_NOINFO_REGION_PROMPT,
    IMAGE_NOISE_PROMPT,
    IMAGE_UNIQUENESS_PROMPT,
    IMAGE_CONSISTENCY_PROMPT,
    # text prompts
    TEXT_FORMAT_ACCURACY_PROMPT,
    TEXT_CONTENT_ACCURACY_PROMPT,
    TEXT_NOINFO_PROMPT,
    TEXT_DESC_COMPLETENESS_PROMPT,
    TEXT_UNIQUENESS_PROMPT,
    TEXT_CONSISTENCY_PROMPT,
    # repo-level prompts
    REPO_EFFECTIVENESS_PROMPT,
    REPO_TIMELINESS_PROMPT,
    REPO_INTER_IMAGE_UNIQUENESS_PROMPT,
    REPO_INTER_IMAGE_CONSISTENCY_PROMPT,
    REPO_INTER_TEXT_UNIQUENESS_PROMPT,
    REPO_INTER_TEXT_CONSISTENCY_PROMPT,
    # repo-level self-evaluation prompts
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
from .celery_app import celery_app

logger = logging.getLogger(__name__)


def _get_db():
    return Database(settings.postgres_dsn)


def _call_model(rule_prompt: str, image_base64: str = None, text_content: str = None, video_frames: list = None) -> dict:
    """调用模型服务进行单维度评价。"""
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
        return resp.json()


def _decode_gitea_content(content_base64: str) -> str:
    """解码 Gitea 返回的 base64 文件内容。"""
    return base64.b64decode(content_base64).decode("utf-8", errors="replace")


@celery_app.task(bind=True, max_retries=1, default_retry_delay=30)
def run_evaluation(self, task_id: str, user_name: str, repo_name: str,
                   branch_name: str, repo_introduction: str):
    """核心评价任务。"""
    db = _get_db()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(db.connect())
        loop.run_until_complete(
            db.execute(
                "UPDATE eval_tasks SET status=$1, started_at=NOW() WHERE task_id=$2",
                EvalStatus.RUNNING.value, task_id,
            )
        )
        _do_evaluation(db, task_id, user_name, repo_name, branch_name, repo_introduction)

        # 评价完成后构建 JSON 并发送回调
        repo = f"{user_name}/{repo_name}"
        callback_json = loop.run_until_complete(_build_callback_json(db, task_id, repo))
        _do_callback(task_id, callback_json)

        loop.run_until_complete(
            db.execute(
                "UPDATE eval_tasks SET status=$1, finished_at=NOW() WHERE task_id=$2",
                EvalStatus.DONE.value, task_id,
            )
        )
    except Exception as e:
        logger.error(f"Evaluation task {task_id} failed: {e}", exc_info=True)
        loop.run_until_complete(
            db.execute(
                "UPDATE eval_tasks SET status=$1, error_message=$2, finished_at=NOW() WHERE task_id=$3",
                EvalStatus.FAILED.value, str(e)[:2000], task_id,
            )
        )
        raise self.retry(exc=e, countdown=30 * (self.request.retries + 1))
    finally:
        loop.run_until_complete(db.disconnect())
        loop.close()


def _insert_score(db, loop, table: str, repo: str, file_path: str,
                  score: float, file_type: str, eva_type: str, eva_dsc: str):
    """向评分表插入一条记录。"""
    loop.run_until_complete(
        db.execute(
            f"""INSERT INTO {table} (repo, file_path, score, file_type, eva_dsc, eva_type)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            repo, file_path, round(score, 2), file_type, eva_dsc, eva_type,
        )
    )


def _insert_repo_score(db, loop, table: str, repo: str,
                       score: float, eva_dsc: str, eva_type: str = None):
    """向仓库级评分表插入一条记录。"""
    if eva_type:
        loop.run_until_complete(
            db.execute(
                f"""INSERT INTO {table} (repo, score, eva_dsc, eva_type)
                   VALUES ($1, $2, $3, $4)""",
                repo, round(score, 2), eva_dsc, eva_type,
            )
        )
    else:
        loop.run_until_complete(
            db.execute(
                f"""INSERT INTO {table} (repo, score, eva_dsc)
                   VALUES ($1, $2, $3)""",
                repo, round(score, 2), eva_dsc,
            )
        )


def _delete_existing_scores(db, loop, repo: str):
    """评价前清除该仓库在所有评分表中的历史记录。"""
    tables = [
        SCORE_TABLE_ACCURACY, SCORE_TABLE_CONSISTENCY,
        SCORE_TABLE_UNIQUENESS, SCORE_TABLE_INTEGRITY,
        SCORE_TABLE_REPO_ACCURACY, SCORE_TABLE_REPO_CONSISTENCY,
        SCORE_TABLE_REPO_EFFECTIVENESS, SCORE_TABLE_REPO_INTEGRITY,
        SCORE_TABLE_REPO_TIMELINESS, SCORE_TABLE_REPO_UNIQUENESS,
    ]
    for table in tables:
        loop.run_until_complete(
            db.execute(f"DELETE FROM {table} WHERE repo=$1", repo)
        )
    logger.info(f"Cleared existing scores for repo={repo}")


def _do_evaluation(db, task_id, user_name, repo_name, branch_name, repo_introduction):
    """执行评价流程。"""
    gitea = GiteaClient()
    repo = f"{user_name}/{repo_name}"
    loop = asyncio.get_event_loop()

    # 0. 清除该仓库的历史评分记录
    _delete_existing_scores(db, loop, repo)

    # 1. DFS 遍历获取所有文件
    all_files = gitea.dfs_traverse_repo(user_name, repo_name, branch_name)
    if not all_files:
        logger.warning(f"No files found in {repo}@{branch_name}")
        loop.run_until_complete(
            db.execute("UPDATE eval_tasks SET total_files=0, evaluated_files=0 WHERE task_id=$1", task_id)
        )
        return

    # 2. 按类型分类
    image_files = [f for f in all_files if is_image_file(f["path"])]
    text_files = [f for f in all_files if is_text_file(f["path"])]
    video_files = [f for f in all_files if is_video_file(f["path"])]
    total_count = len(image_files) + len(text_files) + len(video_files)
    loop.run_until_complete(
        db.execute("UPDATE eval_tasks SET total_files=$1 WHERE task_id=$2", total_count, task_id)
    )

    evaluated_count = 0

    # 3. 评价图像文件
    # ... (rest of image processing)
    for f in image_files:
        try:
            content_b64 = gitea.download_file(user_name, repo_name, f["path"], branch_name)
            if not content_b64:
                continue

            file_path = f["path"]

            # 一键综合评价：将原本 5 次调用合并为 1 次
            try:
                result = _call_model(COMBINED_IMAGE_EVAL_PROMPT, image_base64=content_b64)
                logger.debug(f"Combined image result for {file_path}: {result}")
                
                # 分维度解析并插入数据库
                dims = [
                    ("accuracy", SCORE_TABLE_ACCURACY, "image-content"),
                    ("noinfo", SCORE_TABLE_CONSISTENCY, "image-noinfo"),
                    ("noise", SCORE_TABLE_CONSISTENCY, "image-noise"),
                    ("uniqueness", SCORE_TABLE_UNIQUENESS, "image-content"),
                    ("consistency", SCORE_TABLE_INTEGRITY, "image-content"),
                ]
                # 提取分数用于汇总表
                scores_map = {}
                for key, table, eva_type in dims:
                    data = result.get(key, {})
                    val = data.get("score", 0)
                    scores_map[key] = val
                    _insert_score(db, loop, table, repo, file_path,
                                  val, "image", eva_type, data.get("eva_content", ""))
                
                # 插入汇总表 (eval_file_results)
                loop.run_until_complete(
                    db.execute(
                        """INSERT INTO eval_file_results (task_id, user_name, repo_name, file_path, file_type, 
                           image_info_uniqueness, solid_region_score, noise_score, object_completeness, description)
                           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)""",
                        uuid.UUID(task_id), user_name, repo_name, file_path, "image",
                        round(scores_map.get("uniqueness", 0), 2),
                        round(scores_map.get("noinfo", 0), 2),
                        round(scores_map.get("noise", 0), 2),
                        round(scores_map.get("consistency", 0), 2),
                        result.get("accuracy", {}).get("eva_content", "")
                    )
                )
            except Exception as e:
                logger.error(f"Image combined eval failed for {file_path}: {e}")

            evaluated_count += 1
            loop.run_until_complete(
                db.execute("UPDATE eval_tasks SET evaluated_files=$1 WHERE task_id=$2", evaluated_count, task_id)
            )
        except Exception as e:
            logger.error(f"Error processing image {f['path']}: {e}")

    # 4. 评价文本文件
    for f in text_files:
        try:
            file_info = gitea.get_file_content(user_name, repo_name, f["path"], branch_name)
            if not file_info or not file_info.get("content"):
                continue
            content_b64 = file_info["content"]
            file_path = f["path"]
            _, ext = os.path.splitext(file_path.lower())
            
            # 尝试使用文档处理器提取文本 (docx, xlsx, pptx, pdf)
            text_content = extract_text_by_extension(ext, base64.b64decode(content_b64))
            
            # 如果不是 Office/PDF，则尝试作为纯文本解码
            if text_content is None:
                try:
                    text_content = _decode_gitea_content(content_b64)
                except Exception:
                    text_content = base64.b64decode(content_b64).decode("utf-8", errors="replace")

            # 一键综合评价：将原本 6 次调用合并为 1 次
            try:
                result = _call_model(COMBINED_TEXT_EVAL_PROMPT, text_content=text_content)
                logger.debug(f"Combined text result for {file_path}: {result}")
                
                dims = [
                    ("format_accuracy", SCORE_TABLE_ACCURACY, "text-format"),
                    ("content_accuracy", SCORE_TABLE_ACCURACY, "text-content"),
                    ("noinfo", SCORE_TABLE_CONSISTENCY, "text-noinfo"),
                    ("desc_completeness", SCORE_TABLE_CONSISTENCY, "text-desc"),
                    ("uniqueness", SCORE_TABLE_UNIQUENESS, "text-content"),
                    ("consistency", SCORE_TABLE_INTEGRITY, "text-content"),
                ]
                scores_map = {}
                for key, table, eva_type in dims:
                    data = result.get(key, {})
                    val = data.get("score", 0)
                    scores_map[key] = val
                    _insert_score(db, loop, table, repo, file_path,
                                  val, "text", eva_type, data.get("eva_content", ""))
                
                # 插入汇总表 (eval_file_results)
                loop.run_until_complete(
                    db.execute(
                        """INSERT INTO eval_file_results (task_id, user_name, repo_name, file_path, file_type, 
                           text_info_uniqueness, junk_score, desc_completeness, description)
                           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
                        uuid.UUID(task_id), user_name, repo_name, file_path, "text",
                        round(scores_map.get("uniqueness", 0), 2),
                        round(scores_map.get("noinfo", 0), 2),
                        round(scores_map.get("desc_completeness", 0), 2),
                        result.get("content_accuracy", {}).get("eva_content", "")
                    )
                )
            except Exception as e:
                logger.error(f"Text combined eval failed for {file_path}: {e}")

            evaluated_count += 1
            loop.run_until_complete(
                db.execute("UPDATE eval_tasks SET evaluated_files=$1 WHERE task_id=$2", evaluated_count, task_id)
            )
        except Exception as e:
            logger.error(f"Error processing text {f['path']}: {e}")

    # 5. 评价视频文件
    for f in video_files:
        try:
            content_b64 = gitea.download_file(user_name, repo_name, f["path"], branch_name)
            if not content_b64:
                continue
            
            file_path = f["path"]
            # 抽帧 (默认 8 帧)
            frames = extract_frames_from_video(base64.b64decode(content_b64))
            if not frames:
                logger.warning(f"No frames extracted for video {file_path}")
                continue

            # 一键综合评价
            try:
                result = _call_model(COMBINED_VIDEO_EVAL_PROMPT, video_frames=frames)
                logger.debug(f"Combined video result for {file_path}: {result}")
                
                dims = [
                    ("temporal_consistency", SCORE_TABLE_CONSISTENCY, "video-temporal"),
                    ("visual_quality", SCORE_TABLE_CONSISTENCY, "video-visual"),
                    ("content_accuracy", SCORE_TABLE_ACCURACY, "video-content"),
                    ("redundancy", SCORE_TABLE_UNIQUENESS, "video-content"),
                ]
                scores_map = {}
                for key, table, eva_type in dims:
                    data = result.get(key, {})
                    val = data.get("score", 0)
                    scores_map[key] = val
                    _insert_score(db, loop, table, repo, file_path,
                                  val, "video", eva_type, data.get("eva_content", ""))
                
                # 插入汇总表 (eval_file_results) - 复用部分列
                loop.run_until_complete(
                    db.execute(
                        """INSERT INTO eval_file_results (task_id, user_name, repo_name, file_path, file_type, 
                           solid_region_score, noise_score, object_completeness, description)
                           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
                        uuid.UUID(task_id), user_name, repo_name, file_path, "video",
                        round(scores_map.get("redundancy", 0), 2),
                        round(scores_map.get("visual_quality", 0), 2),
                        round(scores_map.get("temporal_consistency", 0), 2),
                        result.get("content_accuracy", {}).get("eva_content", "")
                    )
                )
            except Exception as e:
                logger.error(f"Video combined eval failed for {file_path}: {e}")

            evaluated_count += 1
            loop.run_until_complete(
                db.execute("UPDATE eval_tasks SET evaluated_files=$1 WHERE task_id=$2", evaluated_count, task_id)
            )
        except Exception as e:
            logger.error(f"Error processing video {f['path']}: {e}")

    # 6. 仓库级评价
    _do_repo_evaluation(db, loop, repo, repo_introduction, image_files, text_files)

    logger.info(f"Evaluation task {task_id} completed: {len(image_files)} images, {len(text_files)} texts, {len(video_files)} videos")


def _do_repo_evaluation(db, loop, repo, repo_introduction, image_files, text_files):
    """仓库级评价：在所有文件评价完成后，对整个数据仓库进行宏观评价。"""

    # --- 有效性 ---
    if repo_introduction:
        try:
            result = _call_model(REPO_EFFECTIVENESS_PROMPT, text_content=repo_introduction)
            _insert_repo_score(db, loop, SCORE_TABLE_REPO_EFFECTIVENESS, repo,
                               result.get("score", 0), result.get("eva_content", ""))
        except Exception as e:
            logger.error(f"Repo effectiveness eval failed: {e}")

    # --- 及时性 ---
    try:
        result = _call_model(REPO_TIMELINESS_PROMPT, text_content=repo_introduction or "无数据仓库简介")
        _insert_repo_score(db, loop, SCORE_TABLE_REPO_TIMELINESS, repo,
                           result.get("score", 0), result.get("eva_content", ""))
    except Exception as e:
        logger.error(f"Repo timeliness eval failed: {e}")

    # --- 图间唯一性 ---
    if image_files:
        try:
            image_summary = f"本次评价的图像文件共 {len(image_files)} 个。"
            result = _call_model(REPO_INTER_IMAGE_UNIQUENESS_PROMPT, text_content=image_summary)
            _insert_repo_self_score(db, loop, SCORE_TABLE_REPO_UNIQUENESS, repo,
                                    score_model=result.get("score", 0), eva_dsc=result.get("eva_content", ""),
                                    eva_rule_type="inter-image-unq", score_avg=None, score=None)
        except Exception as e:
            logger.error(f"Inter-image uniqueness eval failed: {e}")

    # --- 图间一致性 ---
    if image_files:
        try:
            image_summary = f"本次评价的图像文件共 {len(image_files)} 个。"
            result = _call_model(REPO_INTER_IMAGE_CONSISTENCY_PROMPT, text_content=image_summary)
            _insert_repo_self_score(db, loop, SCORE_TABLE_REPO_INTEGRITY, repo,
                                    score_model=result.get("score", 0), eva_dsc=result.get("eva_content", ""),
                                    eva_rule_type="inter-image-integrity", score_avg=None, score=None)
        except Exception as e:
            logger.error(f"Inter-image consistency eval failed: {e}")

    # --- 文本间唯一性 ---
    if text_files:
        try:
            text_summary = f"本次评价的文本文件共 {len(text_files)} 个。"
            result = _call_model(REPO_INTER_TEXT_UNIQUENESS_PROMPT, text_content=text_summary)
            _insert_repo_self_score(db, loop, SCORE_TABLE_REPO_UNIQUENESS, repo,
                                    score_model=result.get("score", 0), eva_dsc=result.get("eva_content", ""),
                                    eva_rule_type="inter-text-unq", score_avg=None, score=None)
        except Exception as e:
            logger.error(f"Inter-text uniqueness eval failed: {e}")

    # --- 文本间一致性 ---
    if text_files:
        try:
            text_summary = f"本次评价的文本文件共 {len(text_files)} 个。"
            result = _call_model(REPO_INTER_TEXT_CONSISTENCY_PROMPT, text_content=text_summary)
            _insert_repo_self_score(db, loop, SCORE_TABLE_REPO_INTEGRITY, repo,
                                    score_model=result.get("score", 0), eva_dsc=result.get("eva_content", ""),
                                    eva_rule_type="inter-text-integrity", score_avg=None, score=None)
        except Exception as e:
            logger.error(f"Inter-text consistency eval failed: {e}")

    # 6. 仓库级综合评价（对同类文件各维度的整体打分）
    _do_repo_self_evaluation(db, loop, repo, image_files, text_files)


def _insert_repo_self_score(db, loop, table: str, repo: str,
                            score_model: float, eva_dsc: str,
                            eva_rule_type: str, score_avg: float = None, score: float = None):
    """向仓库级综合评分表写入一条记录（UPSERT: 先尝试更新，无则插入）。

    匹配条件: repo = $1 AND eva_rule_type = $2
    """
    # 先尝试更新已有记录
    status = loop.run_until_complete(
        db.execute(
            f"""UPDATE {table}
               SET score_model=$1, eva_dsc=$2, score_avg=$3, score=$4
               WHERE repo=$5 AND eva_rule_type=$6""",
            round(score_model, 2), eva_dsc,
            round(score_avg, 2) if score_avg is not None else None,
            round(score, 2) if score is not None else None,
            repo, eva_rule_type,
        )
    )
    # asyncpg execute 返回 "UPDATE N" 格式，N=0 表示无匹配行
    if status and status.startswith("UPDATE 0"):
        loop.run_until_complete(
            db.execute(
                f"""INSERT INTO {table} (repo, score_model, eva_dsc, eva_rule_type, score_avg, score)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                repo, round(score_model, 2), eva_dsc, eva_rule_type,
                round(score_avg, 2) if score_avg is not None else None,
                round(score, 2) if score is not None else None,
            )
        )


async def _query_avg_score(db, table: str, repo: str, eva_type: str, file_type: str = None) -> float:
    """从文件级评分表中查询某 repo 某维度的平均分（仅未删除记录）。

    当 file_type 不为 None 时，额外加 file_type 条件。
    """
    if file_type:
        row = await db.fetchrow(
            f"SELECT AVG(score) as avg_score FROM {table} WHERE repo=$1 AND eva_type=$2 AND file_type=$3 AND deleted=0",
            repo, eva_type, file_type,
        )
    else:
        row = await db.fetchrow(
            f"SELECT AVG(score) as avg_score FROM {table} WHERE repo=$1 AND eva_type=$2 AND deleted=0",
            repo, eva_type,
        )
    if row and row["avg_score"] is not None:
        return float(row["avg_score"])
    return 0.0


def _do_repo_self_evaluation(db, loop, repo, image_files, text_files):
    """仓库级综合评价：对全部图像/文本各维度进行综合打分。

    每个维度:
    - score_model: 模型综合评价得分
    - score_avg: 所有文件该维度平均分
    - score: 加权得分 = score_avg * 0.5 + score_model * 0.5
    """

    has_images = len(image_files) > 0
    has_texts = len(text_files) > 0

    # --- 图像综合评价 ---
    if has_images:
        image_summary = f"本次评价的图像文件共 {len(image_files)} 个。"

        # 图像准确性 imgself-accuracy
        try:
            score_avg = loop.run_until_complete(
                _query_avg_score(db, SCORE_TABLE_ACCURACY, repo, "image-content", "image")
            )
            result = _call_model(REPO_IMGSELF_ACCURACY_PROMPT, text_content=image_summary)
            score_model = result.get("score", 0)
            score = score_avg * 0.5 + score_model * 0.5
            _insert_repo_self_score(db, loop, SCORE_TABLE_REPO_ACCURACY, repo,
                                    score_model, result.get("eva_content", ""),
                                    "imgself-accuracy", score_avg, score)
        except Exception as e:
            logger.error(f"Repo imgself-accuracy eval failed: {e}")

        # 图像完整性-无信息区域 imgself-consistency-region
        try:
            score_avg = loop.run_until_complete(
                _query_avg_score(db, SCORE_TABLE_CONSISTENCY, repo, "image-noinfo", "image")
            )
            result = _call_model(REPO_IMGSELF_CONSISTENCY_REGION_PROMPT, text_content=image_summary)
            score_model = result.get("score", 0)
            score = score_avg * 0.5 + score_model * 0.5
            _insert_repo_self_score(db, loop, SCORE_TABLE_REPO_CONSISTENCY, repo,
                                    score_model, result.get("eva_content", ""),
                                    "imgself-consistency-region", score_avg, score)
        except Exception as e:
            logger.error(f"Repo imgself-consistency-region eval failed: {e}")

        # 图像完整性-噪声 imgself-consistency-noise
        try:
            score_avg = loop.run_until_complete(
                _query_avg_score(db, SCORE_TABLE_CONSISTENCY, repo, "image-noise", "image")
            )
            result = _call_model(REPO_IMGSELF_CONSISTENCY_NOISE_PROMPT, text_content=image_summary)
            score_model = result.get("score", 0)
            score = score_avg * 0.5 + score_model * 0.5
            _insert_repo_self_score(db, loop, SCORE_TABLE_REPO_CONSISTENCY, repo,
                                    score_model, result.get("eva_content", ""),
                                    "imgself-consistency-noise", score_avg, score)
        except Exception as e:
            logger.error(f"Repo imgself-consistency-noise eval failed: {e}")

        # 图像唯一性 imgself-unq
        try:
            score_avg = loop.run_until_complete(
                _query_avg_score(db, SCORE_TABLE_UNIQUENESS, repo, "image-content", "image")
            )
            result = _call_model(REPO_IMGSELF_UNIQUENESS_PROMPT, text_content=image_summary)
            score_model = result.get("score", 0)
            score = score_avg * 0.5 + score_model * 0.5
            _insert_repo_self_score(db, loop, SCORE_TABLE_REPO_UNIQUENESS, repo,
                                    score_model, result.get("eva_content", ""),
                                    "imgself-unq", score_avg, score)
        except Exception as e:
            logger.error(f"Repo imgself-unq eval failed: {e}")

        # 图像一致性 imgself-integrity
        try:
            score_avg = loop.run_until_complete(
                _query_avg_score(db, SCORE_TABLE_INTEGRITY, repo, "image-content", "image")
            )
            result = _call_model(REPO_IMGSELF_INTEGRITY_PROMPT, text_content=image_summary)
            score_model = result.get("score", 0)
            score = score_avg * 0.5 + score_model * 0.5
            _insert_repo_self_score(db, loop, SCORE_TABLE_REPO_INTEGRITY, repo,
                                    score_model, result.get("eva_content", ""),
                                    "imgself-integrity", score_avg, score)
        except Exception as e:
            logger.error(f"Repo imgself-integrity eval failed: {e}")

    # --- 文本综合评价 ---
    if has_texts:
        text_summary = f"本次评价的文本文件共 {len(text_files)} 个。"

        # 文本格式准确性 textself-accuracy-format
        try:
            score_avg = loop.run_until_complete(
                _query_avg_score(db, SCORE_TABLE_ACCURACY, repo, "text-format", "text")
            )
            result = _call_model(REPO_TEXTSELF_ACCURACY_FORMAT_PROMPT, text_content=text_summary)
            score_model = result.get("score", 0)
            score = score_avg * 0.5 + score_model * 0.5
            _insert_repo_self_score(db, loop, SCORE_TABLE_REPO_ACCURACY, repo,
                                    score_model, result.get("eva_content", ""),
                                    "textself-accuracy-format", score_avg, score)
        except Exception as e:
            logger.error(f"Repo textself-accuracy-format eval failed: {e}")

        # 文本内容准确性 textself-accuracy-content
        try:
            score_avg = loop.run_until_complete(
                _query_avg_score(db, SCORE_TABLE_ACCURACY, repo, "text-content", "text")
            )
            result = _call_model(REPO_TEXTSELF_ACCURACY_CONTENT_PROMPT, text_content=text_summary)
            score_model = result.get("score", 0)
            score = score_avg * 0.5 + score_model * 0.5
            _insert_repo_self_score(db, loop, SCORE_TABLE_REPO_ACCURACY, repo,
                                    score_model, result.get("eva_content", ""),
                                    "textself-accuracy-content", score_avg, score)
        except Exception as e:
            logger.error(f"Repo textself-accuracy-content eval failed: {e}")

        # 文本完整性-无信息文本 textself-consistency-noinfo
        try:
            score_avg = loop.run_until_complete(
                _query_avg_score(db, SCORE_TABLE_CONSISTENCY, repo, "text-noinfo", "text")
            )
            result = _call_model(REPO_TEXTSELF_CONSISTENCY_NOINFO_PROMPT, text_content=text_summary)
            score_model = result.get("score", 0)
            score = score_avg * 0.5 + score_model * 0.5
            _insert_repo_self_score(db, loop, SCORE_TABLE_REPO_CONSISTENCY, repo,
                                    score_model, result.get("eva_content", ""),
                                    "textself-consistency-noinfo", score_avg, score)
        except Exception as e:
            logger.error(f"Repo textself-consistency-noinfo eval failed: {e}")

        # 文本完整性-描述完整性 textself-consistency-content
        try:
            score_avg = loop.run_until_complete(
                _query_avg_score(db, SCORE_TABLE_CONSISTENCY, repo, "text-desc", "text")
            )
            result = _call_model(REPO_TEXTSELF_CONSISTENCY_DESC_PROMPT, text_content=text_summary)
            score_model = result.get("score", 0)
            score = score_avg * 0.5 + score_model * 0.5
            _insert_repo_self_score(db, loop, SCORE_TABLE_REPO_CONSISTENCY, repo,
                                    score_model, result.get("eva_content", ""),
                                    "textself-consistency-content", score_avg, score)
        except Exception as e:
            logger.error(f"Repo textself-consistency-content eval failed: {e}")

        # 文本唯一性 textself-unq
        try:
            score_avg = loop.run_until_complete(
                _query_avg_score(db, SCORE_TABLE_UNIQUENESS, repo, "text-content", "text")
            )
            result = _call_model(REPO_TEXTSELF_UNIQUENESS_PROMPT, text_content=text_summary)
            score_model = result.get("score", 0)
            score = score_avg * 0.5 + score_model * 0.5
            _insert_repo_self_score(db, loop, SCORE_TABLE_REPO_UNIQUENESS, repo,
                                    score_model, result.get("eva_content", ""),
                                    "textself-unq", score_avg, score)
        except Exception as e:
            logger.error(f"Repo textself-unq eval failed: {e}")

        # 文本一致性 textself-integrity
        try:
            score_avg = loop.run_until_complete(
                _query_avg_score(db, SCORE_TABLE_INTEGRITY, repo, "text-content", "text")
            )
            result = _call_model(REPO_TEXTSELF_INTEGRITY_PROMPT, text_content=text_summary)
            score_model = result.get("score", 0)
            score = score_avg * 0.5 + score_model * 0.5
            _insert_repo_self_score(db, loop, SCORE_TABLE_REPO_INTEGRITY, repo,
                                    score_model, result.get("eva_content", ""),
                                    "textself-integrity", score_avg, score)
        except Exception as e:
            logger.error(f"Repo textself-integrity eval failed: {e}")


async def _build_callback_json(db, task_id: str, repo: str) -> dict:
    """从数据库查询所有仓库级评分，构建回调 JSON。"""
    def _float_or_none(val):
        return float(val) if val is not None else None

    def _str_or_empty(val):
        return val or ""

    def _row_to_dict(row, has_avg=True):
        """将 repo 级综合评价行转为 {modelScore, avgScore, eva} 字典。"""
        if not row:
            return None
        d = {
            "modelScore": _float_or_none(row.get("score_model")),
            "eva": _str_or_empty(row.get("eva_dsc")),
        }
        if has_avg:
            d["avgScore"] = _float_or_none(row.get("score_avg"))
        return d

    def _row_to_simple_dict(row):
        """将 effectiveness / timeliness 行转为 {modelScore, eva} 字典。"""
        if not row:
            return None
        return {
            "modelScore": _float_or_none(row.get("score")),
            "eva": _str_or_empty(row.get("eva_dsc")),
        }

    cond = "repo=$1 AND deleted=0"

    # accuracy (repo_accuracy_score)
    img_content_acc = await db.fetchrow(
        f"SELECT score_model, score_avg, eva_dsc FROM repo_accuracy_score WHERE eva_rule_type='imgself-accuracy' AND {cond}", repo)
    text_content_acc = await db.fetchrow(
        f"SELECT score_model, score_avg, eva_dsc FROM repo_accuracy_score WHERE eva_rule_type='textself-accuracy-content' AND {cond}", repo)
    text_format_acc = await db.fetchrow(
        f"SELECT score_model, score_avg, eva_dsc FROM repo_accuracy_score WHERE eva_rule_type='textself-accuracy-format' AND {cond}", repo)

    # consistency (repo_consistency_score)
    img_noinfo_con = await db.fetchrow(
        f"SELECT score_model, score_avg, eva_dsc FROM repo_consistency_score WHERE eva_rule_type='imgself-consistency-region' AND {cond}", repo)
    img_noise_con = await db.fetchrow(
        f"SELECT score_model, score_avg, eva_dsc FROM repo_consistency_score WHERE eva_rule_type='imgself-consistency-noise' AND {cond}", repo)
    text_noinfo_con = await db.fetchrow(
        f"SELECT score_model, score_avg, eva_dsc FROM repo_consistency_score WHERE eva_rule_type='textself-consistency-noinfo' AND {cond}", repo)
    text_desc_con = await db.fetchrow(
        f"SELECT score_model, score_avg, eva_dsc FROM repo_consistency_score WHERE eva_rule_type='textself-consistency-content' AND {cond}", repo)

    # uniqueness (repo_unq_score) — imgself/textself have avgScore, inter- ones don't
    inner_img_unq = await db.fetchrow(
        f"SELECT score_model, score_avg, eva_dsc FROM repo_unq_score WHERE eva_rule_type='imgself-unq' AND {cond}", repo)
    inner_text_unq = await db.fetchrow(
        f"SELECT score_model, score_avg, eva_dsc FROM repo_unq_score WHERE eva_rule_type='textself-unq' AND {cond}", repo)
    inter_img_unq = await db.fetchrow(
        f"SELECT score_model, eva_dsc FROM repo_unq_score WHERE eva_rule_type='inter-image-unq' AND {cond}", repo)
    inter_text_unq = await db.fetchrow(
        f"SELECT score_model, eva_dsc FROM repo_unq_score WHERE eva_rule_type='inter-text-unq' AND {cond}", repo)

    # integrity (repo_integrity_score) — imgself/textself have avgScore, inter- ones don't
    inner_img_int = await db.fetchrow(
        f"SELECT score_model, score_avg, eva_dsc FROM repo_integrity_score WHERE eva_rule_type='imgself-integrity' AND {cond}", repo)
    inner_text_int = await db.fetchrow(
        f"SELECT score_model, score_avg, eva_dsc FROM repo_integrity_score WHERE eva_rule_type='textself-integrity' AND {cond}", repo)
    inter_img_int = await db.fetchrow(
        f"SELECT score_model, eva_dsc FROM repo_integrity_score WHERE eva_rule_type='inter-image-integrity' AND {cond}", repo)
    inter_text_int = await db.fetchrow(
        f"SELECT score_model, eva_dsc FROM repo_integrity_score WHERE eva_rule_type='inter-text-integrity' AND {cond}", repo)

    # effectiveness & timeliness (only score + eva_dsc)
    eff_row = await db.fetchrow(
        f"SELECT score, eva_dsc FROM repo_effectiveness_score WHERE {cond} ORDER BY id DESC LIMIT 1", repo)
    time_row = await db.fetchrow(
        f"SELECT score, eva_dsc FROM repo_timeliness_score WHERE {cond} ORDER BY id DESC LIMIT 1", repo)

    result = {
        "taskId": task_id,
        "accuracy": {
            "imgContent": _row_to_dict(img_content_acc) or {"modelScore": None, "avgScore": None, "eva": ""},
            "textContent": _row_to_dict(text_content_acc) or {"modelScore": None, "avgScore": None, "eva": ""},
            "textFormat": _row_to_dict(text_format_acc) or {"modelScore": None, "avgScore": None, "eva": ""},
        },
        "consistency": {
            "imgNoInfoRegion": _row_to_dict(img_noinfo_con) or {"modelScore": None, "avgScore": None, "eva": ""},
            "imgNoise": _row_to_dict(img_noise_con) or {"modelScore": None, "avgScore": None, "eva": ""},
            "textInfo": _row_to_dict(text_noinfo_con) or {"modelScore": None, "avgScore": None, "eva": ""},
            "textDesc": _row_to_dict(text_desc_con) or {"modelScore": None, "avgScore": None, "eva": ""},
        },
        "unique": {
            "innerImage": _row_to_dict(inner_img_unq) or {"modelScore": None, "avgScore": None, "eva": ""},
            "interImage": _row_to_dict(inter_img_unq, has_avg=False) or {"modelScore": None, "eva": ""},
            "innerText": _row_to_dict(inner_text_unq) or {"modelScore": None, "avgScore": None, "eva": ""},
            "interText": _row_to_dict(inter_text_unq, has_avg=False) or {"modelScore": None, "eva": ""},
        },
        "integrity": {
            "innerImage": _row_to_dict(inner_img_int) or {"modelScore": None, "avgScore": None, "eva": ""},
            "innerText": _row_to_dict(inner_text_int) or {"modelScore": None, "avgScore": None, "eva": ""},
            "interImage": _row_to_dict(inter_img_int, has_avg=False) or {"modelScore": None, "eva": ""},
            "interText": _row_to_dict(inter_text_int, has_avg=False) or {"modelScore": None, "eva": ""},
        },
        "time": _row_to_simple_dict(time_row) or {"modelScore": None, "eva": ""},
        "effictive": _row_to_simple_dict(eff_row) or {"modelScore": None, "eva": ""},
    }
    return result


def _do_callback(task_id: str, callback_json: dict):
    """将评价结果 JSON POST 到回调接口。"""
    recall_ip = settings.recall_ip
    recall_port = settings.recall_port
    recall_api = settings.recall_api
    if not recall_ip or not recall_port or not recall_api:
        logger.info(f"Callback not configured, skipping for task {task_id}")
        return
    url = f"http://{recall_ip}:{recall_port}{recall_api}"
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(url, json=callback_json)
            logger.info(f"Callback POST {url} for task {task_id}: status={resp.status_code}")
    except Exception as e:
        logger.error(f"Callback POST failed for task {task_id}: {e}")
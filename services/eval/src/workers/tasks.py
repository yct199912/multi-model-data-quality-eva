import uuid
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
from .celery_app import celery_app
from ..core.coordinator import EvaluationCoordinator

logger = logging.getLogger(__name__)


def _get_db():
    return Database(settings.postgres_dsn)


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
        
        coordinator = EvaluationCoordinator(db, loop)
        coordinator.evaluate_resource(task_id, user_name, repo_name, branch_name, repo_introduction)

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

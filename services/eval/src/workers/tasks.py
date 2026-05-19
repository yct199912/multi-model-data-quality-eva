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
from ..dependencies import db, redis_client
from ..core.coordinator import EvaluationCoordinator

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=1, default_retry_delay=30)
def run_evaluation(self, evaluate_id: int, task_id: str, user_name: str, repo_name: str,
                   branch_name: str, repo_introduction: str):
    """核心评价任务。"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(db.connect())
        loop.run_until_complete(redis_client.connect())
        loop.run_until_complete(
            db.execute(
                "UPDATE eval_tasks SET status=$1, started_at=NOW() WHERE task_id=$2",
                EvalStatus.RUNNING.value, task_id,
            )
        )

        coordinator = EvaluationCoordinator(db, redis_client, loop)
        loop.run_until_complete(coordinator.evaluate_resource(task_id, user_name, repo_name, branch_name, repo_introduction))


        # 评价完成后构建 JSON 并发送回调
        repo = f"{user_name}/{repo_name}"
        callback_json = loop.run_until_complete(_build_callback_json(db, task_id, evaluate_id, repo))
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
        loop.run_until_complete(redis_client.disconnect())
        loop.close()


async def _build_callback_json(db, task_id: str, eva_id: int, repo: str) -> dict:
    """从数据库查询所有仓库级评分，构建回调 JSON。"""
    def _float_or_none(val):
        return float(val) if val is not None else None

    def _str_or_empty(val):
        return val or ""

    def _rule_entry(rule_name, rule_detail, rule_desc, row, has_avg=True):
        """将 repo 级综合评价行转为 ruleScore 条目。"""
        entry = {
            "ruleName": rule_name,
            "ruleDetail": rule_detail,
            "ruleDesc": rule_desc,
        }
        if row:
            entry["modelScore"] = _float_or_none(row.get("score_model"))
            entry["eva"] = _str_or_empty(row.get("eva_dsc"))
            if has_avg:
                entry["avgScore"] = _float_or_none(row.get("score_avg"))
        else:
            entry["modelScore"] = None
            entry["eva"] = ""
            if has_avg:
                entry["avgScore"] = None
        return entry

    def _simple_rule_entry(rule_name, rule_detail, rule_desc, row):
        """将 effectiveness / timeliness 行转为 ruleScore 条目。"""
        if row:
            return {
                "ruleName": rule_name,
                "ruleDetail": rule_detail,
                "ruleDesc": rule_desc,
                "modelScore": _float_or_none(row.get("score")),
                "eva": _str_or_empty(row.get("eva_dsc")),
            }
        return {
            "ruleName": rule_name,
            "ruleDetail": rule_detail,
            "ruleDesc": rule_desc,
            "modelScore": None,
            "eva": "",
        }

    cond = "repo=$1 AND deleted=0"

    # Fetch aggregate result for the task
    agg_row = await db.fetchrow("SELECT * FROM eval_aggregate_results WHERE task_id=$1", uuid.UUID(task_id))

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

    # uniqueness (repo_unq_score)
    inner_img_unq = await db.fetchrow(
        f"SELECT score_model, score_avg, eva_dsc FROM repo_unq_score WHERE eva_rule_type='imgself-unq' AND {cond}", repo)
    inner_text_unq = await db.fetchrow(
        f"SELECT score_model, score_avg, eva_dsc FROM repo_unq_score WHERE eva_rule_type='textself-unq' AND {cond}", repo)
    inter_img_unq = await db.fetchrow(
        f"SELECT score_model, eva_dsc FROM repo_unq_score WHERE eva_rule_type='inter-image-unq' AND {cond}", repo)
    inter_text_unq = await db.fetchrow(
        f"SELECT score_model, eva_dsc FROM repo_unq_score WHERE eva_rule_type='inter-text-unq' AND {cond}", repo)

    # integrity (repo_integrity_score)
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

    # Use aggregated scores from eval_aggregate_results if available
    img_unq_final = inner_img_unq
    if agg_row and agg_row["image_uniqueness_score"] is not None:
        img_unq_final = {"score_model": float(agg_row["image_uniqueness_score"]), "eva_dsc": agg_row["image_uniqueness_description"]}
    
    text_unq_final = inner_text_unq
    if agg_row and agg_row["text_uniqueness_score"] is not None:
        text_unq_final = {"score_model": float(agg_row["text_uniqueness_score"]), "eva_dsc": agg_row["text_uniqueness_description"]}

    img_int_final = inner_img_int
    if agg_row and agg_row["image_completeness_score"] is not None:
        img_int_final = {"score_model": float(agg_row["image_completeness_score"]), "eva_dsc": "综合完整性评分"}

    text_int_final = inner_text_int
    if agg_row and agg_row["text_completeness_score"] is not None:
        text_int_final = {"score_model": float(agg_row["text_completeness_score"]), "eva_dsc": "综合完整性评分"}

    rule_score = [
        # accuracy
        _rule_entry("accurate", "imgContent", "准确性-图像内容准确性检测", img_content_acc),
        _rule_entry("accurate", "textContent", "准确性-文本内容准确性检测", text_content_acc),
        _rule_entry("accurate", "textFormat", "准确性-文本格式准确性检测", text_format_acc),
        # consistency
        _rule_entry("integrity", "imgNoInfoRegion", "完整性-图像无信息区域检测", img_noinfo_con),
        _rule_entry("integrity", "imgNoise", "完整性-图像无信息噪声检测", img_noise_con),
        _rule_entry("integrity", "textInfo", "完整性-无信息文本检测", text_noinfo_con),
        _rule_entry("integrity", "textDesc", "完整性-文本描述完整性检测", text_desc_con),
        # unique
        _rule_entry("unique", "innerImage", "唯一性-图内信息唯一性检测", img_unq_final),
        _rule_entry("unique", "interImage", "唯一性-图间信息唯一性检测", inter_img_unq, has_avg=False),
        _rule_entry("unique", "innerText", "唯一性-文本内容唯一性检测", text_unq_final),
        _rule_entry("unique", "interText", "唯一性-文本间唯一性检测", inter_text_unq, has_avg=False),
        # integrity
        _rule_entry("consistent", "innerImage", "一致性-图像中内容一致性检测", img_int_final),
        _rule_entry("consistent", "innerText", "一致性-文本内容描述一致性检测", text_int_final),
        _rule_entry("consistent", "interImage", "一致性-图像间一致性检测", inter_img_int, has_avg=False),
        _rule_entry("consistent", "interText", "一致性-文本文件之间一致性检测", inter_text_int, has_avg=False),
        # time & effective
        _simple_rule_entry("timely", "timely", "及时性检测", time_row),
        _simple_rule_entry("effective", "effictive", "有效性检测", eff_row),
    ]

    return {
        "taskId": task_id,
        "evaluateId": eva_id,
        "ruleScore": rule_score,
    }


def _do_callback(task_id: str, callback_json: dict):
    """将评价结果 JSON POST 到回调接口，并在 callback_json 中记录回调状态码。"""
    recall_ip = settings.recall_ip
    recall_port = settings.recall_port
    recall_api = settings.recall_api
    if not recall_ip or not recall_port or not recall_api:
        logger.info(f"Callback not configured, skipping for task {task_id}")
        return
    url = f"http://{recall_ip}:{recall_port}{recall_api}"
    try:
        with httpx.Client(timeout=30) as client:
            callback_json["code"] = 200
            resp = client.post(url, json=callback_json)
            logger.info(f"Callback POST {url} for task {task_id}: status={resp.status_code}")
    except Exception as e:
        callback_json["code"] = -1
        logger.error(f"Callback POST failed for task {task_id}: {e}")

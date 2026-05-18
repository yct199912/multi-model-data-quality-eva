# services/eval/src/api/evaluate.py
"""POST /api/v1/evaluate 端点 — 创建数据质量评价任务。"""
import logging
import uuid
from fastapi import APIRouter, HTTPException, Header, Depends
from retrieval_shared.schemas import EvaluateRequest, EvaluateResponse
from retrieval_shared.constants import EvalStatus
from ..config import settings
from ..dependencies import db
from ..workers.tasks import run_evaluation

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["evaluate"])


def verify_app_key(
    x_app_key: str = Header(..., alias="appKey"),
    x_app_secret: str = Header(..., alias="appSecret"),
):
    """验证 appKey / appSecret。"""
    if x_app_key != settings.app_key or x_app_secret != settings.app_secret:
        raise HTTPException(status_code=401, detail="Invalid app key or secret")


@router.post("/evaluate", response_model=EvaluateResponse)
async def create_evaluation(
    req: EvaluateRequest,
    _: None = Depends(verify_app_key),
):
    """创建数据质量评价任务。

    1. 创建 eval_task 记录
    2. 异步派发 Celery 任务
    3. 返回 task_id 供查询
    """
    # 优先使用请求中的 taskId，如果未提供则自动生成
    task_id = str(uuid.uuid4())
    branch = req.branchName or "master"

    try:
        await db.execute(
            """INSERT INTO eval_tasks (task_id, user_name, repo_name, branch_name, status, evaluate_id)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            task_id, req.userName, req.repoName, branch, EvalStatus.PENDING.value, req.evaluateId
        )
    except Exception as e:
        logger.error(f"Failed to create eval task: {e}")
        raise HTTPException(status_code=500, detail="Failed to create evaluation task")

    # 派发 Celery 异步任务
    try:
        run_evaluation.apply_async(args=(req.evaluateId, task_id, req.userName, req.repoName, branch, req.repoIntroduction), queue="eval")
        logger.info(f"Dispatched eval task {task_id} for {req.userName}/{req.repoName}@{branch}")
    except Exception as e:
        logger.error(f"Failed to dispatch Celery task: {e}")
        # Celery 不可用时仍然返回 task_id，前端可轮询
        await db.execute(
            "UPDATE eval_tasks SET status=$1, error_message=$2 WHERE task_id=$3",
            EvalStatus.FAILED.value, f"Celery dispatch failed: {e}", task_id,
        )

    return EvaluateResponse(task_id=task_id, status=EvalStatus.PENDING, message="Evaluation task created")


@router.get("/evaluate/{task_id}")
async def get_evaluation_result(
    task_id: str,
    _: None = Depends(verify_app_key),
):
    """查询评价任务结果。"""
    from retrieval_shared.schemas import (
        EvalTask, EvalFileResult, EvalAggregateResult, EvaluateResultResponse,
        RepoScoreRecord, RepoSelfScoreRecord, RepoEvaluationResult,
    )

    task_row = await db.fetchrow(
        "SELECT * FROM eval_tasks WHERE task_id=$1", task_id
    )
    if not task_row:
        raise HTTPException(status_code=404, detail="Task not found")

    task = EvalTask(
        task_id=str(task_row["task_id"]),
        user_name=task_row["user_name"],
        repo_name=task_row["repo_name"],
        branch_name=task_row["branch_name"],
        status=task_row["status"],
        total_files=task_row["total_files"],
        evaluated_files=task_row["evaluated_files"],
        error_message=task_row.get("error_message"),
        created_at=str(task_row["created_at"]) if task_row.get("created_at") else None,
        finished_at=str(task_row["finished_at"]) if task_row.get("finished_at") else None,
    )

    file_rows = await db.fetch(
        "SELECT * FROM eval_file_results WHERE task_id=$1 ORDER BY id", task_id
    )
    file_results = []
    for r in file_rows:
        file_results.append(EvalFileResult(
            id=r["id"],
            task_id=str(r["task_id"]),
            user_name=r["user_name"],
            repo_name=r["repo_name"],
            file_path=r["file_path"],
            file_type=r["file_type"],
            file_size=r["file_size"],
            image_info_uniqueness=float(r["image_info_uniqueness"]) if r.get("image_info_uniqueness") is not None else None,
            solid_region_score=float(r["solid_region_score"]) if r.get("solid_region_score") is not None else None,
            noise_score=float(r["noise_score"]) if r.get("noise_score") is not None else None,
            object_completeness=float(r["object_completeness"]) if r.get("object_completeness") is not None else None,
            text_info_uniqueness=float(r["text_info_uniqueness"]) if r.get("text_info_uniqueness") is not None else None,
            junk_score=float(r["junk_score"]) if r.get("junk_score") is not None else None,
            desc_completeness=float(r["desc_completeness"]) if r.get("desc_completeness") is not None else None,
            dataset_uniqueness=float(r["dataset_uniqueness"]) if r.get("dataset_uniqueness") is not None else None,
            description=r.get("description"),
        ))

    agg_row = await db.fetchrow(
        "SELECT * FROM eval_aggregate_results WHERE task_id=$1", task_id
    )
    aggregate = None
    if agg_row:
        aggregate = EvalAggregateResult(
            id=agg_row["id"],
            task_id=str(agg_row["task_id"]),
            user_name=agg_row["user_name"],
            repo_name=agg_row["repo_name"],
            branch_name=agg_row["branch_name"],
            total_image_count=agg_row["total_image_count"],
            total_text_count=agg_row["total_text_count"],
            unique_image_count=agg_row["unique_image_count"],
            unique_text_count=agg_row["unique_text_count"],
            image_uniqueness_score=float(agg_row["image_uniqueness_score"]) if agg_row.get("image_uniqueness_score") is not None else None,
            image_completeness_score=float(agg_row["image_completeness_score"]) if agg_row.get("image_completeness_score") is not None else None,
            text_uniqueness_score=float(agg_row["text_uniqueness_score"]) if agg_row.get("text_uniqueness_score") is not None else None,
            text_completeness_score=float(agg_row["text_completeness_score"]) if agg_row.get("text_completeness_score") is not None else None,
            image_uniqueness_description=agg_row.get("image_uniqueness_description"),
            text_uniqueness_description=agg_row.get("text_uniqueness_description"),
        )

    # 仓库级评价结果
    repo_eval = None
    repo_str = f"{task_row['user_name']}/{task_row['repo_name']}"

    eff_row = await db.fetchrow(
        "SELECT * FROM repo_effectiveness_score WHERE repo=$1 ORDER BY id DESC LIMIT 1", repo_str
    )
    time_row = await db.fetchrow(
        "SELECT * FROM repo_timeliness_score WHERE repo=$1 ORDER BY id DESC LIMIT 1", repo_str
    )
    img_unq_row = await db.fetchrow(
        "SELECT * FROM repo_unq_score WHERE repo=$1 AND eva_rule_type='inter-image-unq' ORDER BY id DESC LIMIT 1", repo_str
    )
    img_int_row = await db.fetchrow(
        "SELECT * FROM repo_integrity_score WHERE repo=$1 AND eva_rule_type='inter-image-integrity' ORDER BY id DESC LIMIT 1", repo_str
    )
    txt_unq_row = await db.fetchrow(
        "SELECT * FROM repo_unq_score WHERE repo=$1 AND eva_rule_type='inter-text-unq' ORDER BY id DESC LIMIT 1", repo_str
    )
    txt_int_row = await db.fetchrow(
        "SELECT * FROM repo_integrity_score WHERE repo=$1 AND eva_rule_type='inter-text-integrity' ORDER BY id DESC LIMIT 1", repo_str
    )

    def _to_repo_score(row) -> RepoScoreRecord | None:
        if not row:
            return None
        return RepoScoreRecord(
            id=row["id"],
            repo=row["repo"],
            score=float(row["score"]) if row.get("score") is not None else 0.0,
            eva_dsc=row.get("eva_dsc") or "",
            eva_type=row.get("eva_type"),
        )

    def _to_self_score(row) -> RepoSelfScoreRecord | None:
        if not row:
            return None
        return RepoSelfScoreRecord(
            id=row["id"],
            repo=row["repo"],
            score_model=float(row["score_model"]) if row.get("score_model") is not None else None,
            eva_dsc=row.get("eva_dsc") or "",
            eva_rule_type=row.get("eva_rule_type", ""),
            score_avg=float(row["score_avg"]) if row.get("score_avg") is not None else None,
            score=float(row["score"]) if row.get("score") is not None else None,
        )

    repo_eval = RepoEvaluationResult(
        effectiveness=_to_repo_score(eff_row),
        timeliness=_to_repo_score(time_row),
        inter_image_uniqueness=_to_self_score(img_unq_row),
        inter_image_consistency=_to_self_score(img_int_row),
        inter_text_uniqueness=_to_self_score(txt_unq_row),
        inter_text_consistency=_to_self_score(txt_int_row),
    )

    # 仓库级综合评价结果
    imgself_acc = await db.fetchrow(
        "SELECT * FROM repo_accuracy_score WHERE repo=$1 AND eva_rule_type='imgself-accuracy' ORDER BY id DESC LIMIT 1", repo_str
    )
    imgself_con_region = await db.fetchrow(
        "SELECT * FROM repo_consistency_score WHERE repo=$1 AND eva_rule_type='imgself-consistency-region' ORDER BY id DESC LIMIT 1", repo_str
    )
    imgself_con_noise = await db.fetchrow(
        "SELECT * FROM repo_consistency_score WHERE repo=$1 AND eva_rule_type='imgself-consistency-noise' ORDER BY id DESC LIMIT 1", repo_str
    )
    imgself_unq = await db.fetchrow(
        "SELECT * FROM repo_unq_score WHERE repo=$1 AND eva_rule_type='imgself-unq' ORDER BY id DESC LIMIT 1", repo_str
    )
    imgself_int = await db.fetchrow(
        "SELECT * FROM repo_integrity_score WHERE repo=$1 AND eva_rule_type='imgself-integrity' ORDER BY id DESC LIMIT 1", repo_str
    )
    txtself_acc_fmt = await db.fetchrow(
        "SELECT * FROM repo_accuracy_score WHERE repo=$1 AND eva_rule_type='textself-accuracy-format' ORDER BY id DESC LIMIT 1", repo_str
    )
    txtself_acc_cont = await db.fetchrow(
        "SELECT * FROM repo_accuracy_score WHERE repo=$1 AND eva_rule_type='textself-accuracy-content' ORDER BY id DESC LIMIT 1", repo_str
    )
    txtself_con_noinfo = await db.fetchrow(
        "SELECT * FROM repo_consistency_score WHERE repo=$1 AND eva_rule_type='textself-consistency-noinfo' ORDER BY id DESC LIMIT 1", repo_str
    )
    txtself_con_desc = await db.fetchrow(
        "SELECT * FROM repo_consistency_score WHERE repo=$1 AND eva_rule_type='textself-consistency-content' ORDER BY id DESC LIMIT 1", repo_str
    )
    txtself_unq = await db.fetchrow(
        "SELECT * FROM repo_unq_score WHERE repo=$1 AND eva_rule_type='textself-unq' ORDER BY id DESC LIMIT 1", repo_str
    )
    txtself_int = await db.fetchrow(
        "SELECT * FROM repo_integrity_score WHERE repo=$1 AND eva_rule_type='textself-integrity' ORDER BY id DESC LIMIT 1", repo_str
    )

    repo_eval.imgself_accuracy = _to_self_score(imgself_acc)
    repo_eval.imgself_consistency_region = _to_self_score(imgself_con_region)
    repo_eval.imgself_consistency_noise = _to_self_score(imgself_con_noise)
    repo_eval.imgself_uniqueness = _to_self_score(imgself_unq)
    repo_eval.imgself_integrity = _to_self_score(imgself_int)
    repo_eval.textself_accuracy_format = _to_self_score(txtself_acc_fmt)
    repo_eval.textself_accuracy_content = _to_self_score(txtself_acc_cont)
    repo_eval.textself_consistency_noinfo = _to_self_score(txtself_con_noinfo)
    repo_eval.textself_consistency_desc = _to_self_score(txtself_con_desc)
    repo_eval.textself_uniqueness = _to_self_score(txtself_unq)
    repo_eval.textself_integrity = _to_self_score(txtself_int)

    return EvaluateResultResponse(task=task, aggregate=aggregate, file_results=file_results, repo_evaluation=repo_eval)
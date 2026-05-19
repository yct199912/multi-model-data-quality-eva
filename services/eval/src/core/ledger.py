import asyncio
import logging
import uuid
from typing import Optional

from retrieval_shared.constants import (
    SCORE_TABLE_ACCURACY, SCORE_TABLE_CONSISTENCY,
    SCORE_TABLE_UNIQUENESS, SCORE_TABLE_INTEGRITY,
    SCORE_TABLE_REPO_EFFECTIVENESS, SCORE_TABLE_REPO_TIMELINESS,
    SCORE_TABLE_REPO_UNIQUENESS, SCORE_TABLE_REPO_INTEGRITY,
    SCORE_TABLE_REPO_ACCURACY, SCORE_TABLE_REPO_CONSISTENCY,
)
from retrieval_shared.database import Database

logger = logging.getLogger(__name__)

class QualityLedger:
    """
    Result Persistence Module.
    Abstracts the database schema and provides a deep interface for recording evaluation results.
    """
    def __init__(self, db: Database, loop: asyncio.AbstractEventLoop):
        self.db = db
        self.loop = loop

    async def clear_repo_history(self, user_name: str, repo_name: str):
        repo = f"{user_name}/{repo_name}"
        tables = [
            SCORE_TABLE_ACCURACY, SCORE_TABLE_CONSISTENCY,
            SCORE_TABLE_UNIQUENESS, SCORE_TABLE_INTEGRITY,
            SCORE_TABLE_REPO_ACCURACY, SCORE_TABLE_REPO_CONSISTENCY,
            SCORE_TABLE_REPO_EFFECTIVENESS, SCORE_TABLE_REPO_INTEGRITY,
            SCORE_TABLE_REPO_TIMELINESS, SCORE_TABLE_REPO_UNIQUENESS,
        ]
        logger.info(f"Clearing history for repo={repo}")
        for t in tables:
            await self.db.execute(f"DELETE FROM {t} WHERE repo=$1", repo)
        
        await self.db.execute("DELETE FROM eval_file_results WHERE user_name=$1 AND repo_name=$2", user_name, repo_name)
        await self.db.execute("DELETE FROM eval_aggregate_results WHERE user_name=$1 AND repo_name=$2", user_name, repo_name)
        logger.info(f"Cleared existing scores for repo={repo}")

    async def record_aggregate_results(self, task_id: str, user_name: str, repo_name: str, branch_name: str, data: dict):
        logger.info(f"Recording aggregate results for task {task_id}")
        query = """INSERT INTO eval_aggregate_results (task_id, user_name, repo_name, branch_name, 
                   total_image_count, total_text_count, unique_image_count, unique_text_count,
                   image_uniqueness_score, image_completeness_score, text_uniqueness_score, text_completeness_score,
                   image_uniqueness_description, text_uniqueness_description)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                   ON CONFLICT (task_id) DO UPDATE SET
                   total_image_count=EXCLUDED.total_image_count, total_text_count=EXCLUDED.total_text_count,
                   unique_image_count=EXCLUDED.unique_image_count, unique_text_count=EXCLUDED.unique_text_count,
                   image_uniqueness_score=EXCLUDED.image_uniqueness_score, image_completeness_score=EXCLUDED.image_completeness_score,
                   text_uniqueness_score=EXCLUDED.text_uniqueness_score, text_completeness_score=EXCLUDED.text_completeness_score,
                   image_uniqueness_description=EXCLUDED.image_uniqueness_description, text_uniqueness_description=EXCLUDED.text_uniqueness_description
                """
        try:
            await self.db.execute(
                query, uuid.UUID(task_id), user_name, repo_name, branch_name,
                data.get("total_image_count", 0), data.get("total_text_count", 0),
                data.get("unique_image_count", 0), data.get("unique_text_count", 0),
                round(data.get("image_uniqueness_score", 0), 2), round(data.get("image_completeness_score", 0), 2),
                round(data.get("text_uniqueness_score", 0), 2), round(data.get("text_completeness_score", 0), 2),
                data.get("image_uniqueness_description", ""), data.get("text_uniqueness_description", "")
            )
            logger.info(f"Successfully recorded aggregate results for task {task_id}")
        except Exception as e:
            logger.error(f"Failed to record aggregate results for task {task_id}: {e}")
            raise

    async def record_file_score(self, table: str, repo: str, file_path: str, score: float, file_type: str, eva_type: str, eva_dsc: str):
        await self.db.execute(
            f"INSERT INTO {table} (repo, file_path, score, file_type, eva_dsc, eva_type) VALUES ($1, $2, $3, $4, $5, $6)",
            repo, file_path, round(score, 2), file_type, eva_dsc, eva_type,
        )

    async def record_repo_score(self, table: str, repo: str, score: float, eva_dsc: str, eva_type: str = None):
        if eva_type:
            await self.db.execute(f"INSERT INTO {table} (repo, score, eva_dsc, eva_type) VALUES ($1, $2, $3, $4)", repo, round(score, 2), eva_dsc, eva_type)
        else:
            await self.db.execute(f"INSERT INTO {table} (repo, score, eva_dsc) VALUES ($1, $2, $3)", repo, round(score, 2), eva_dsc)

    async def update_or_insert_repo_self_score(self, table: str, repo: str, score_model: float, eva_dsc: str, eva_rule_type: str, score_avg: Optional[float] = None, score: Optional[float] = None):
        status = await self.db.execute(
            f"UPDATE {table} SET score_model=$1, eva_dsc=$2, score_avg=$3, score=$4 WHERE repo=$5 AND eva_rule_type=$6",
            round(score_model, 2), eva_dsc, round(score_avg, 2) if score_avg is not None else None, round(score, 2) if score is not None else None, repo, eva_rule_type,
        )
        if status and status.startswith("UPDATE 0"):
            await self.db.execute(
                f"INSERT INTO {table} (repo, score_model, eva_dsc, eva_rule_type, score_avg, score) VALUES ($1, $2, $3, $4, $5, $6)",
                repo, round(score_model, 2), eva_dsc, eva_rule_type, round(score_avg, 2) if score_avg is not None else None, round(score, 2) if score is not None else None,
            )

    async def get_avg_score(self, table: str, repo: str, eva_type: str, file_type: str = None) -> float:
        if file_type:
            row = await self.db.fetchrow(f"SELECT AVG(score) as avg_score FROM {table} WHERE repo=$1 AND eva_type=$2 AND file_type=$3 AND deleted=0", repo, eva_type, file_type)
        else:
            row = await self.db.fetchrow(f"SELECT AVG(score) as avg_score FROM {table} WHERE repo=$1 AND eva_type=$2 AND deleted=0", repo, eva_type)
        return float(row["avg_score"]) if row and row["avg_score"] is not None else 0.0

    async def record_file_summary(self, task_id: str, user_name: str, repo_name: str, file_path: str, file_type: str, scores_map: dict, description: str):
        if file_type == "image":
            query = """INSERT INTO eval_file_results (task_id, user_name, repo_name, file_path, file_type, 
                       image_info_uniqueness, solid_region_score, noise_score, object_completeness, description)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)"""
            args = (round(scores_map.get("uniqueness", 0), 2), round(scores_map.get("noinfo", 0), 2), round(scores_map.get("noise", 0), 2), round(scores_map.get("consistency", 0), 2))
        elif file_type == "text":
            query = """INSERT INTO eval_file_results (task_id, user_name, repo_name, file_path, file_type, 
                       text_info_uniqueness, junk_score, desc_completeness, description)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)"""
            args = (round(scores_map.get("uniqueness", 0), 2), round(scores_map.get("noinfo", 0), 2), round(scores_map.get("desc_completeness", 0), 2))
        elif file_type == "video":
            query = """INSERT INTO eval_file_results (task_id, user_name, repo_name, file_path, file_type, 
                       solid_region_score, noise_score, object_completeness, description)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)"""
            args = (round(scores_map.get("redundancy", 0), 2), round(scores_map.get("visual_quality", 0), 2), round(scores_map.get("temporal_consistency", 0), 2))
        else:
            return

        await self.db.execute(query, uuid.UUID(task_id), user_name, repo_name, file_path, file_type, *args, description)

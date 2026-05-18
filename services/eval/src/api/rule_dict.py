# services/eval/src/api/rule_dict.py
"""GET /api/v1/ruleDict 端点 — 查询评价规则字典。"""
import logging
from fastapi import APIRouter, Query, Depends, Header, HTTPException
from ..config import settings
from ..dependencies import db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["ruleDict"])


def verify_app_key(
    x_app_key: str = Header(..., alias="X-App-Key"),
    x_app_secret: str = Header(..., alias="X-App-Secret"),
):
    """验证 appKey / appSecret。"""
    if x_app_key != settings.app_key or x_app_secret != settings.app_secret:
        raise HTTPException(status_code=401, detail="Invalid app key or secret")


@router.get("/ruleDict")
async def get_rule_dict(
    ruleName: str = Query(default="", alias="ruleName"),
    _: None = Depends(verify_app_key),
):
    """查询评价规则字典。

    - ruleName 为空时返回全部规则
    - ruleName 有值时按 rule_name 过滤
    - 特殊处理: ruleName=time 或 effictive 时同时返回两者
    """
    if ruleName:
        if ruleName in ("time", "effictive"):
            rows = await db.fetch(
                "SELECT rule_name, rule_detail, rule_desc FROM rule_dict WHERE rule_name IN ('time', 'effictive') ORDER BY id"
            )
        else:
            rows = await db.fetch(
                "SELECT rule_name, rule_detail, rule_desc FROM rule_dict WHERE rule_name = $1 ORDER BY id",
                ruleName,
            )
    else:
        rows = await db.fetch(
            "SELECT rule_name, rule_detail, rule_desc FROM rule_dict ORDER BY id"
        )

    return {
        "rule": [
            {
                "ruleName": row["rule_name"],
                "ruleDetail": row["rule_detail"],
                "ruleDesc": row["rule_desc"],
            }
            for row in rows
        ]
    }
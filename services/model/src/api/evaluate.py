# services/model/src/api/evaluate.py
import asyncio
import logging
from fastapi import APIRouter, HTTPException
from retrieval_shared.schemas import ModelEvalRequest, ModelEvalResponse
from ..core import state
from ..config import settings

router = APIRouter(prefix="/api/v1", tags=["evaluate"])

_semaphore = asyncio.Semaphore(settings.gpu_concurrency)


@router.post("/evaluate", response_model=ModelEvalResponse)
async def evaluate_single_dimension(req: ModelEvalRequest):
    """单维度评价接口 — 接收规则提示词 + 文件内容，返回 score + eva_content。"""
    if not state.is_ready or state.provider is None:
        raise HTTPException(status_code=503, detail="Model not ready")
    if not req.image_base64 and not req.text_content and not req.video_frames:
        raise HTTPException(status_code=400, detail="Must provide image_base64, text_content, or video_frames")
    async with _semaphore:
        try:
            result = await state.provider.evaluate(
                rule_prompt=req.rule_prompt,
                output_format_prompt=req.output_format_prompt,
                image_base64=req.image_base64,
                text_content=req.text_content,
                video_frames=req.video_frames,
            )
            # 兼容逻辑：处理经过 Super Parser 标准化的结果
            res_score = result.get("score", 0)
            if isinstance(res_score, dict):
                res_score = res_score.get("score", 0)
            
            res_eva = result.get("eva_content", "")
            if isinstance(res_eva, dict):
                res_eva = res_eva.get("eva_content", "")

            return ModelEvalResponse(
                score=float(res_score),
                eva_content=str(res_eva),
                raw_result=result
            )
        except Exception as e:
            logging.error(f"Evaluation failed: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
# shared/src/retrieval_shared/schemas.py
from pydantic import BaseModel, Field
from typing import Optional
from retrieval_shared.constants import EvalStatus, FileType


class EvaluateRequest(BaseModel):
    """POST /api/v1/evaluate 请求体"""
    evaluateId: int = Field(default=0, description="外部传入的任务ID")
    userName: str = Field(..., min_length=1, description="Gitea 仓库所有者用户名")
    repoName: str = Field(..., min_length=1, description="数据仓库名称")
    branchName: str = Field(default="master", description="评价分支名称，默认 master")
    repoIntroduction: str = Field(default="", description="数据库简介")


class EvalTask(BaseModel):
    """评价任务记录"""
    task_id: str
    user_name: str
    repo_name: str
    branch_name: str
    repo_introduction: str = ""
    status: EvalStatus = EvalStatus.PENDING
    total_files: int = 0
    evaluated_files: int = 0
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    finished_at: Optional[str] = None


class ScoreRecord(BaseModel):
    """单条得分记录（对应 4 张评分表的通用结构）"""
    id: Optional[int] = None
    repo: str
    file_path: str
    score: float
    file_type: str  # image / text
    eva_type: str   # 评价维度类型
    eva_dsc: str = ""


class EvaluateResponse(BaseModel):
    """POST /api/v1/evaluate 同步响应"""
    task_id: str
    status: EvalStatus
    message: str = "Evaluation task created"


class EvaluateResultResponse(BaseModel):
    """GET /api/v1/evaluate/{task_id} 结果响应"""
    task: EvalTask
    aggregate: Optional["EvalAggregateResult"] = None
    file_results: list["EvalFileResult"] = Field(default_factory=list)
    repo_evaluation: Optional["RepoEvaluationResult"] = None


class EvalFileResult(BaseModel):
    """单文件评价结果汇总"""
    id: Optional[int] = None
    task_id: str
    user_name: str
    repo_name: str
    file_path: str
    file_type: str
    file_size: int = 0
    image_info_uniqueness: Optional[float] = None
    solid_region_score: Optional[float] = None
    noise_score: Optional[float] = None
    object_completeness: Optional[float] = None
    text_info_uniqueness: Optional[float] = None
    junk_score: Optional[float] = None
    desc_completeness: Optional[float] = None
    dataset_uniqueness: Optional[float] = None
    description: Optional[str] = None


class EvalAggregateResult(BaseModel):
    """数据集级别聚合评价结果"""
    id: Optional[int] = None
    task_id: str
    user_name: str
    repo_name: str
    branch_name: str = "master"
    total_image_count: int = 0
    total_text_count: int = 0
    unique_image_count: int = 0
    unique_text_count: int = 0
    image_uniqueness_score: Optional[float] = None
    image_completeness_score: Optional[float] = None
    text_uniqueness_score: Optional[float] = None
    text_completeness_score: Optional[float] = None
    image_uniqueness_description: Optional[str] = None
    text_uniqueness_description: Optional[str] = None


class ModelEvalRequest(BaseModel):
    """模型服务评价请求"""
    rule_prompt: str = Field(..., description="规则提示词")
    output_format_prompt: str = Field(default="", description="输出格式提示词")
    image_base64: Optional[str] = Field(default=None, description="Base64 编码的图像数据")
    text_content: Optional[str] = Field(default=None, description="文本内容")
    video_frames: Optional[list[str]] = Field(default=None, description="Base64 编码的视频帧列表")


class ModelEvalResponse(BaseModel):
    """模型服务评价响应"""
    score: float = Field(0, description="评分 (0-100)")
    eva_content: str = Field("", description="评价内容")
    raw_result: Optional[dict] = Field(default=None, description="原始完整评价结果")


# ============================================================================
#  仓库级评价结果
# ============================================================================

class RepoScoreRecord(BaseModel):
    """仓库级单条得分记录（有效性/及时性等只有 score 的表）"""
    id: Optional[int] = None
    repo: str
    score: float
    eva_dsc: str = ""
    eva_type: Optional[str] = None


class RepoSelfScoreRecord(BaseModel):
    """仓库级综合评价得分记录（含 score_model / score_avg / score）"""
    id: Optional[int] = None
    repo: str
    score_model: Optional[float] = None
    eva_dsc: str = ""
    eva_rule_type: str
    score_avg: Optional[float] = None
    score: Optional[float] = None


class RepoEvaluationResult(BaseModel):
    """仓库级评价结果汇总"""
    effectiveness: Optional[RepoScoreRecord] = None
    timeliness: Optional[RepoScoreRecord] = None
    inter_image_uniqueness: Optional[RepoSelfScoreRecord] = None
    inter_image_consistency: Optional[RepoSelfScoreRecord] = None
    inter_text_uniqueness: Optional[RepoSelfScoreRecord] = None
    inter_text_consistency: Optional[RepoSelfScoreRecord] = None
    # 仓库级综合评价（含 score_model / score_avg / score）
    imgself_accuracy: Optional[RepoSelfScoreRecord] = None
    imgself_consistency_region: Optional[RepoSelfScoreRecord] = None
    imgself_consistency_noise: Optional[RepoSelfScoreRecord] = None
    imgself_uniqueness: Optional[RepoSelfScoreRecord] = None
    imgself_integrity: Optional[RepoSelfScoreRecord] = None
    textself_accuracy_format: Optional[RepoSelfScoreRecord] = None
    textself_accuracy_content: Optional[RepoSelfScoreRecord] = None
    textself_consistency_noinfo: Optional[RepoSelfScoreRecord] = None
    textself_consistency_desc: Optional[RepoSelfScoreRecord] = None
    textself_uniqueness: Optional[RepoSelfScoreRecord] = None
    textself_integrity: Optional[RepoSelfScoreRecord] = None
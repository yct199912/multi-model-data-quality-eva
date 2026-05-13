# 数据质量评价系统 — AI 编程上下文

> 本文档供 Claude Code / Cursor / GitHub Copilot 等 AI 编程工具自动加载。

---

## 项目一句话

**数据质量评价系统**：从 Gitea 仓库获取多模态数据集文件，使用 gemma-4-e4b 模型对图像和文本进行质量评价（唯一性、完整性），评价结果写入 PostgreSQL，对外提供 appKey/appSecret 认证的 REST API。

---

## 技术栈

| 层次 | 技术 | 版本 |
| --- | --- | --- |
| Web 框架 | FastAPI | 0.115+ |
| 异步任务 | Celery + Redis | 5.4+ |
| 关系型 DB | PostgreSQL | 16+ |
| 模型推理 | gemma-4-e4b (ModelScope) | transformers 4.40+ |
| 对象存储 | Gitea API (文件获取) | 1.21+ |
| ORM | asyncpg (原生 SQL) | 0.29+ |
| 配置 | pydantic-settings | 2.3+ |
| 日志 | structlog | 24+ |
| 硬件加速 | Huawei Ascend NPU (可选) | CANN 8.0+ / torch-npu |

---

## 服务架构

| 服务 | 端口    | 职责 |
| --- |-------| --- |
| eval-service | 18080 | POST API，Gitea 文件遍历，Celery 任务派发 |
| model-service | 18100 | gemma-4-e4b 模型服务，图/文质量评价 |
| eval-worker | —     | Celery Worker，异步评价执行 |
| PostgreSQL | 5432  | 评价结果持久化 |
| Redis | 6379  | Celery Broker |

---

## 绝对不能改变的规则

### 1. Gitea 文件获取路径模板

```python
# GITEA_FILE_OB = /api/v1/repos/{owner}/{repo}/contents/{filepath}
# {owner} → userName, {repo} → repoName, {filepath} → 文件路径
# branchName 放在 queryParams 的 "ref" 字段
```

### 2. appKey/appSecret 认证

```python
# Header: X-App-Key / X-App-Secret
# 配置在 .env 文件的 APP_KEY / APP_SECRET
```

### 3. 图像评价维度与权重

- **唯一性** = 图内信息唯一性 × 0.3 + 数据集内唯一性 × 0.7
- **完整性** = 无信息区域检测 × 0.5 + 无信息噪声检测 × 0.3 + 描述对象完整性 × 0.2

### 4. 文本评价维度与权重

- **唯一性** = 文本信息唯一性 × 0.3 + 数据集内唯一性 × 0.7
- **完整性** = 无信息文本检测 × 0.6 + 描述完整性 × 0.4

### 5. 数据集内唯一性计算

```
得分 = 非冗余数量 / 总数量 × 100
冗余 = 内容完全相同（hash 相同），不算文件名
```

### 6. 百分制，保留两位小数

所有评价分数均为百分制（0-100），保留两位小数。

---

## 服务职责速查

| 需要做… | 去哪里 |
| --- | --- |
| POST /api/v1/evaluate | `services/eval/src/api/evaluate.py` |
| Gitea 文件 DFS 遍历 | `services/eval/src/core/gitea_client.py` |
| 分数聚合计算 | `services/eval/src/core/evaluator.py` |
| 文件类型判断 | `services/eval/src/core/file_classifier.py` |
| Celery 任务定义 | `services/eval/src/workers/tasks.py` |
| 模型评价 API | `services/model/src/api/evaluate.py` |
| 模型加载 (ModelScope) | `services/model/src/core/providers/gemma4.py` |
| 评价维度定义 | `shared/src/retrieval_shared/constants.py` |
| Pydantic 模型 | `shared/src/retrieval_shared/schemas.py` |
| PostgreSQL DDL | `infra/docker/postgres/init.sql` |
| DB 连接池 | `shared/src/retrieval_shared/database.py` |

---

## 环境变量

```bash
# 应用认证
APP_KEY=
APP_SECRET=

# Gitea
GITEA_BASE_URL=http://localhost:3000
GITEA_TOKEN=
GITEA_FILE_OB=/api/v1/repos/{owner}/{repo}/contents/{filepath}

# PostgreSQL
POSTGRES_DSN=postgresql+asyncpg://retrieval:retrieval@localhost:5432/retrieval_db
REDIS_URL=redis://localhost:6379/0

# 模型服务
MODEL_NAME=google/gemma-4-e4b
MODEL_CACHE_DIR=/models
DEVICE=cpu
MODEL_SERVER_URL=http://localhost:8100

# 性能
CELERY_WORKER_CONCURRENCY=4
GPU_CONCURRENCY=2
MAX_TEXT_CHARS=8000

# 日志
LOG_LEVEL=INFO
```
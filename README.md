# 数据质量评价系统

本项目是一个数据质量评价系统，从 Gitea 仓库获取多模态数据集文件，使用 gemma-4-e4b 模型对图像和文本进行质量评价，评价结果写入 PostgreSQL。

## 核心特性

- **多模态支持**：图像（jpg/png/webp 等）和文本（txt/md/csv/pdf/docx 等）质量评价
- **模型驱动评价**：使用 gemma-4-e4b 通过 ModelScope 下载，支持 CPU/GPU/NPU
- **Gitea 仓库集成**：通过 Gitea API DFS 遍历仓库文件，获取 base64 内容
- **Celery 异步执行**：评价任务异步派发，支持大规模数据集
- **四维度评价**：图像/文本各两个维度（唯一性、完整性），百分制，保留两位小数

## 快速开始

```bash
# 1. 安装依赖
make install

# 2. 配置环境
cp .env.example .env
# 编辑 .env 填入 GITEA_TOKEN, APP_KEY, APP_SECRET 等

# 3. 启动基础设施 + 模型 + 服务
make dev

# 4. 调用评价接口
curl -X POST http://localhost:8080/api/v1/evaluate \
  -H "X-App-Key: your_key" \
  -H "X-App-Secret: your_secret" \
  -H "Content-Type: application/json" \
  -d '{"userName": "owner", "repoName": "dataset", "branchName": "master"}'

# 5. 查询评价结果
curl http://localhost:8080/api/v1/evaluate/{task_id} \
  -H "X-App-Key: your_key" \
  -H "X-App-Secret: your_secret"
```

## 评价维度

### 图像评价
| 指标 | 规则 | 权重 |
|------|------|------|
| 唯一性 | 图内信息唯一性 × 0.3 + 数据集内唯一性 × 0.7 | — |
| 完整性 | 无信息区域 × 0.5 + 噪声检测 × 0.3 + 对象完整性 × 0.2 | — |

### 文本评价
| 指标 | 规则 | 权重 |
|------|------|------|
| 唯一性 | 文本信息唯一性 × 0.3 + 数据集内唯一性 × 0.7 | — |
| 完整性 | 无信息文本检测 × 0.6 + 描述完整性 × 0.4 | — |

## 目录结构

- `shared/`: 核心基础包（Pydantic 模型、常量、数据库连接池、日志等）
- `services/eval/`: 评价服务（API + Gitea 遍历 + Celery 任务 + 分数聚合）
- `services/model/`: 模型服务（gemma-4-e4b 推理 + ModelScope 下载）
- `infra/`: 基础设施配置（PostgreSQL DDL 等）
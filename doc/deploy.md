# 麒麟 10 SP3 (x86_64) 部署指南

> 目标服务器：Linux Kylin 10 SP3 x86_64，已预装 `uv` 包管理器。

---

## 1. 系统依赖

项目需要以下系统级软件，请确认已安装：

| 依赖 | 版本要求 | 安装方式 |
|------|----------|----------|
| Python | 3.10 ~ 3.15 | `uv` 会自动管理，或 `sudo apt install python3.12` |
| PostgreSQL | 16+ | `sudo apt install postgresql-16` 或 Docker |
| Redis | 7+ | `sudo apt install redis` 或 Docker |
| git | 任意 | `sudo apt install git` |
| libpq-dev | — | `sudo apt install libpq-dev`（asyncpg 编译需要） |
| gcc | — | `sudo apt install gcc`（asyncpg 编译需要） |

> 麒麟系统可能使用 `yum` 或 `dnf` 替代 `apt`，请根据实际包管理器调整。

### 1.1 麒麟系统安装命令参考

```bash
# 麒麟系统通常使用 yum/dnf
sudo yum install -y python3-devel gcc libpq-devel redis

# PostgreSQL 16（如果仓库中没有，可用 Docker 部署，见下文）
sudo yum install -y postgresql-server postgresql-devel
```

---

## 2. 获取项目代码

```bash
# 克隆项目到目标目录
cd /opt
git clone <仓库地址> multimodal-eva
cd multimodal-eva
```

---

## 3. 环境配置

### 3.1 创建 .env 文件

```bash
cp .env.example .env
```

### 3.2 编辑 .env

```bash
vi .env
```

需要修改的关键配置：

```bash
# --- 应用认证（必改）---
APP_KEY=你的AppKey
APP_SECRET=你的AppSecret

# --- Gitea（必改）---
GITEA_BASE_URL=http://你的Gitea地址:3000
GITEA_TOKEN=你的GiteaToken
GITEA_FILE_OB=/api/v1/repos/{owner}/{repo}/contents/{filepath}

# --- PostgreSQL（必改）---
POSTGRES_DSN=postgresql+asyncpg://用户名:密码@数据库地址:5432/数据库名

# --- Redis（必改）---
REDIS_URL=redis://Redis地址:6379/2

# --- 模型配置 ---
MODEL_NAME=google/gemma-4-e4b
MODEL_CACHE_DIR=/opt/models    # 模型下载缓存目录，需有写权限
DEVICE=cpu                      # cpu / cuda / npu
GPU_CONCURRENCY=2

# --- 模型服务地址 ---
MODEL_SERVER_URL=http://127.0.0.1:18100

# --- 性能 ---
CELERY_WORKER_CONCURRENCY=4
MAX_TEXT_CHARS=8000

# --- 日志 ---
LOG_LEVEL=INFO

# --- 连接池 ---
DB_POOL_MIN_SIZE=2
DB_POOL_MAX_SIZE=10
```

---

## 4. PostgreSQL 数据库初始化

### 方式 A：使用已有的 PostgreSQL 实例

```bash
# 创建数据库和用户（在 PostgreSQL 服务器上执行）
psql -U postgres <<EOF
CREATE USER retrieval WITH PASSWORD '你的密码';
CREATE DATABASE data_quality_eva OWNER retrieval;
GRANT ALL PRIVILEGES ON DATABASE data_quality_eva TO retrieval;
EOF

# 初始化表结构
psql -U retrieval -d data_quality_eva -f infra/docker/postgres/init.sql
```

### 方式 B：使用 Docker 部署 PostgreSQL

```bash
docker run -d \
  --name postgres \
  --restart always \
  -e POSTGRES_DB=data_quality_eva \
  -e POSTGRES_USER=retrieval \
  -e POSTGRES_PASSWORD=你的密码 \
  -v $(pwd)/infra/docker/postgres/init.sql:/docker-entrypoint-initdb.d/init.sql:ro \
  -v postgres_data:/var/lib/postgresql/data \
  -p 5432:5432 \
  postgres:16-alpine
```

初始化完成后，更新 `.env` 中的 `POSTGRES_DSN`：

```
POSTGRES_DSN=postgresql+asyncpg://retrieval:你的密码@数据库地址:5432/data_quality_eva
```

---

## 5. Redis 部署

### 方式 A：使用已有的 Redis 实例

确认 Redis 可连接即可，更新 `.env` 中的 `REDIS_URL`。

### 方式 B：使用 Docker 部署 Redis

```bash
docker run -d \
  --name redis \
  --restart always \
  redis:7-alpine \
  redis-server --requirepass 你的密码 --maxmemory 4gb --maxmemory-policy allkeys-lru
```

更新 `.env`：

```
REDIS_URL=redis://:你的密码@Redis地址:6379/2
```

---

## 6. 安装 Python 依赖

```bash
cd /opt/multimodal-eva

# uv 自动创建 .venv 并安装全部依赖（包含 shared、eval-service、model-service）
uv sync --all-extras
```

> 此命令会根据 `pyproject.toml` 和 `uv.lock` 安装所有依赖，包括 torch、transformers、modelscope 等模型相关包。
> 首次安装 torch 体积较大（CPU 版约 200MB），模型下载（gemma-4-e4b）约需数 GB，请确保磁盘空间充足。

---

## 7. 启动服务

项目有 3 个需要手动启动的进程：**model-service**、**eval-service**、**eval-worker**。

### 7.1 启动模型服务 (model-service :18100)

```bash
cd /opt/multimodal-eva

# 激活虚拟环境
source .venv/bin/activate

# 设置 PYTHONPATH（确保 shared 包可被导入）
export PYTHONPATH=/opt/multimodal-eva/shared/src:$PYTHONPATH

# 前台运行（调试用）
python -m services.model.src.main
```

首次启动时，模型会从 ModelScope 自动下载到 `MODEL_CACHE_DIR` 指定的目录（默认 `./models`），根据网络情况可能需要 10~30 分钟。

模型加载完成后，访问健康检查确认服务就绪：

```bash
curl http://localhost:18100/health
# 返回 {"status":"up","model":"google/gemma-4-e4b"} 表示启动成功
```

### 7.2 启动评价 API 服务 (eval-service :18080)

```bash
cd /opt/multimodal-eva
source .venv/bin/activate
export PYTHONPATH=/opt/multimodal-eva/shared/src:$PYTHONPATH

python -m services.eval.src.main
```

确认健康检查：

```bash
curl http://localhost:18080/health
# 返回 {"status":"up"} 表示启动成功
```

### 7.3 启动 Celery Worker (eval-worker)

```bash
cd /opt/multimodal-eva
source .venv/bin/activate
export PYTHONPATH=/opt/multimodal-eva/shared/src:$PYTHONPATH

celery -A services.eval.src.workers.celery_app worker -Q eval --loglevel=info
```

---

## 8. 后台运行（生产环境）

推荐使用 `systemd` 管理三个服务进程。

### 8.1 model-service 服务

```bash
sudo vi /etc/systemd/system/model-service.service
```

写入：

```ini
[Unit]
Description=Model Evaluation Service (gemma-4-e4b)
After=network.target

[Service]
Type=simple
User=app
WorkingDirectory=/opt/multimodal-eva
Environment=PYTHONPATH=/opt/multimodal-eva/shared/src
ExecStart=/opt/multimodal-eva/.venv/bin/python -m services.model.src.main
Restart=always
RestartSec=10
EnvironmentFile=/opt/multimodal-eva/.env

[Install]
WantedBy=multi-user.target
```

### 8.2 eval-service 服务

```bash
sudo vi /etc/systemd/system/eval-service.service
```

写入：

```ini
[Unit]
Description=Evaluation API Service
After=network.target

[Service]
Type=simple
User=app
WorkingDirectory=/opt/multimodal-eva
Environment=PYTHONPATH=/opt/multimodal-eva/shared/src
ExecStart=/opt/multimodal-eva/.venv/bin/python -m services.eval.src.main
Restart=always
RestartSec=10
EnvironmentFile=/opt/multimodal-eva/.env

[Install]
WantedBy=multi-user.target
```

### 8.3 eval-worker 服务

```bash
sudo vi /etc/systemd/system/eval-worker.service
```

写入：

```ini
[Unit]
Description=Celery Evaluation Worker
After=network.target

[Service]
Type=simple
User=app
WorkingDirectory=/opt/multimodal-eva
Environment=PYTHONPATH=/opt/multimodal-eva/shared/src
ExecStart=/opt/multimodal-eva/.venv/bin/celery -A services.eval.src.workers.celery_app worker -Q eval --loglevel=info
Restart=always
RestartSec=10
EnvironmentFile=/opt/multimodal-eva/.env

[Install]
WantedBy=multi-user.target
```

### 8.4 启动并设置开机自启

```bash
# 创建运行用户（如不存在）
sudo useradd -r -m -d /opt/multimodal-eva app
sudo chown -R app:app /opt/multimodal-eva

# 重载 systemd 配置
sudo systemctl daemon-reload

# 按顺序启动服务
sudo systemctl enable --now model-service
sudo systemctl enable --now eval-service
sudo systemctl enable --now eval-worker

# 查看服务状态
sudo systemctl status model-service
sudo systemctl status eval-service
sudo systemctl status eval-worker

# 查看日志
sudo journalctl -u model-service -f
sudo journalctl -u eval-service -f
sudo journalctl -u eval-worker -f
```

---

## 9. 验证部署

### 9.1 健康检查

```bash
# 检查模型服务
curl http://localhost:18100/health

# 检查评价 API
curl http://localhost:18080/health
```

### 9.2 发起评价任务

```bash
curl -X POST http://localhost:18080/api/v1/evaluate \
  -H "X-App-Key: 你的APP_KEY" \
  -H "X-App-Secret: 你的APP_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "userName": "gitea用户名",
    "repoName": "仓库名",
    "branchName": "master",
    "repoIntroduction": "数据仓库简介"
  }'
```

返回示例：

```json
{
  "task_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "status": "pending",
  "message": "Evaluation task created"
}
```

### 9.3 查询评价结果

```bash
curl http://localhost:18080/api/v1/evaluate/{task_id} \
  -H "X-App-Key: 你的APP_KEY" \
  -H "X-App-Secret: 你的APP_SECRET"
```

---

## 10. NPU 加速部署（可选）

如服务器配备华为昇腾 NPU，可启用 NPU 加速推理：

### 10.1 安装 NPU 驱动

```bash
# 安装 CANN 8.0+ 工具包（从华为官方获取）
# 安装 torch-npu
pip install torch-npu
```

### 10.2 修改 .env 配置

```bash
DEVICE=npu
GPU_CONCURRENCY=2
```

### 10.3 重启 model-service

```bash
sudo systemctl restart model-service
```

启动日志中应出现 `NPU (Huawei Ascend) initialization successful` 表示 NPU 初始化成功。

---

## 11. 常用运维命令

```bash
# 查看服务状态
sudo systemctl status model-service eval-service eval-worker

# 重启服务
sudo systemctl restart model-service
sudo systemctl restart eval-service
sudo systemctl restart eval-worker

# 查看实时日志
sudo journalctl -u eval-worker -f

# 清理模型缓存（重新下载）
rm -rf /opt/multimodal-eva/models/*

# 更新代码后重新部署
cd /opt/multimodal-eva
git pull
uv sync --all-extras
sudo systemctl restart model-service eval-service eval-worker
```

---

## 12. 故障排查

| 问题 | 排查方法 |
|------|----------|
| 模型服务启动慢 | 首次需下载模型（约数 GB），查看 `MODEL_CACHE_DIR` 目录是否在写入 |
| 模型服务健康检查返回 503 | 模型仍在加载中，等待加载完成（`start_period: 180s`） |
| Celery Worker 无法连接 Redis | 检查 `REDIS_URL` 配置和 Redis 服务状态 |
| 评价任务状态为 `failed` | 查看 worker 日志：`journalctl -u eval-worker` |
| asyncpg 连接失败 | 检查 `POSTGRES_DSN` 格式，确保 `+asyncpg` 在 scheme 中但实际连接时会被去掉 |
| Gitea 文件获取 401 | 检查 `GITEA_TOKEN` 是否有效 |
| 评价结果全为 0 | model-service 未就绪时 worker 已开始评价，确认 model-service 健康后再发任务 |
| torch CPU 兼容性警告 | `cpu_compat.py` 会自动检测 AVX2，老 CPU 可能性能较慢但不影响功能 |

---

## 13. 端口总览

| 服务 | 默认端口 | 说明 |
|------|----------|------|
| eval-service | 18080 | 评价 API |
| model-service | 18100 | 模型推理 API |
| PostgreSQL | 5432 | 数据库（外部或 Docker） |
| Redis | 6379 | 消息队列（外部或 Docker） |
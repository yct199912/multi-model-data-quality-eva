.PHONY: infra infra-down db-init dev dev-local model test lint format logs clean bootstrap

PYTHON ?= .venv/bin/python
UV ?= uv

# ============================================================
#  依赖安装 & 项目初始化
# ============================================================

install:
	@echo "=== Creating venv and installing dependencies ==="
	$(UV) sync --all-extras
	@echo "=== Dependencies installed ==="

env:
	@if [ -f .env ]; then \
		echo ".env already exists, skipping. Delete it first to regenerate."; \
	else \
		cp .env.example .env; \
		echo "Created .env from .env.example — edit it with your real values."; \
	fi

bootstrap: install env infra db-init
	@echo ""
	@echo "============================================"
	@echo "  Project bootstrap complete!"
	@echo "  Next steps:"
	@echo "    1. Edit .env with your credentials"
	@echo "    2. make dev        # start all services"
	@echo "============================================"

clean:
	rm -rf .venv __pycache__ .pytest_cache htmlcov .ruff_cache
	find . -type d -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true

# --- 基础设施 ---
infra:
	docker compose --profile infra up -d

infra-down:
	docker compose down -v

db-init: infra
	docker compose exec postgres psql -U retrieval -d retrieval_db -f /docker-entrypoint-initdb.d/init.sql

# --- 一键部署 (Profiles) ---

# 开发环境（基础设施 + 业务 + 模型）
dev: infra
	docker compose --profile infra --profile ai-local --profile core up -d

# 仅基础设施（手动运行 eval 服务）
dev-local: infra
	@echo "Infrastructure started. Run eval service manually:"
	@echo "  cd services/eval && PYTHONPATH=../../shared/src:src python src/main.py"

# --- 模型服务 ---
model: infra
	docker compose --profile infra --profile ai-local up -d model-service

# --- 测试 ---
test:
	pytest services/ shared/ -v --cov=. --cov-report=html

lint:
	ruff check services/ shared/ scripts/

format:
	ruff format services/ shared/ scripts/

# --- 运维 ---
logs:
	docker compose --profile infra --profile core logs -f
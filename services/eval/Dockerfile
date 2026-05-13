FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for asyncpg
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy shared package
COPY shared/ /app/shared/

# Copy eval service
COPY services/eval/ /app/services/eval/

# Install shared + eval service
RUN pip install /app/shared/ && \
    pip install -e "/app/services/eval[dev]"

# Non-root user
RUN useradd -m appuser
USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s \
    CMD curl -f http://localhost:8080/health || exit 1

CMD ["python", "-m", "services.eval.src.main"]
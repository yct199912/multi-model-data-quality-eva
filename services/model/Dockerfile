FROM python:3.11-slim

ARG TORCH_INDEX_URL="https://download.pytorch.org/whl/cpu"
ARG TORCH_PIP_SPEC=""
ARG EXTRAS="cpu,gemma4"

WORKDIR /app

# Pre-install torch for CPU compatibility
RUN if [ -n "${TORCH_PIP_SPEC}" ]; then \
      pip install --extra-index-url "${TORCH_INDEX_URL}" ${TORCH_PIP_SPEC}; \
    elif [ "$(uname -m)" = "x86_64" ] && ! grep -q avx2 /proc/cpuinfo 2>/dev/null; then \
      pip install --extra-index-url "${TORCH_INDEX_URL}" torch==2.2.2 torchvision==0.17.2; \
    fi

# Copy shared package
COPY shared/ /app/shared/

# Copy model service
COPY services/model/ /app/services/model/

# Install shared + model service with extras
RUN pip install /app/shared/ && \
    pip install --extra-index-url "${TORCH_INDEX_URL}" -e "/app/services/model[${EXTRAS}]"

# Non-root user
RUN useradd -m appuser
USER appuser

EXPOSE 8100

HEALTHCHECK --interval=30s --timeout=10s --start-period=180s \
    CMD curl -f http://localhost:8100/health || exit 1

CMD ["python", "-m", "services.model.src.main"]
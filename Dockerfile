# syntax=docker/dockerfile:1

# --- build stage: install the app + deps into a venv -------------------------
FROM python:3.12-slim AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /src
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install .

# --- runtime stage: slim image with just the venv ---------------------------
FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    OUTPUT_DIR=/data/output \
    STATE_DB_PATH=/data/state.sqlite
COPY --from=builder /opt/venv /opt/venv
# Non-root user; /data holds the state DB + downloaded output (mount a volume).
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /data
WORKDIR /app
# Self-test helper (docs/deployment-docker.md §4). Runs inside the container so it
# shares the same env, /data state DB and OUTPUT_DIR as the service.
COPY scripts ./scripts
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import httpx,sys; sys.exit(0 if httpx.get('http://127.0.0.1:8000/healthz').status_code==200 else 1)"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

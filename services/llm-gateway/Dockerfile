FROM ghcr.io/astral-sh/uv:0.12.5 AS uv

FROM python:3.14.7-slim-bookworm@sha256:9ab8d9c8514b44f90cf0029dd42fdd7e9e211e639c8b995304cc04568dee900f AS builder

WORKDIR /app

COPY --from=uv /uv /uvx /bin/

# hadolint ignore=DL3008
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock README.md ./
COPY src/ src/
RUN uv sync --locked --no-dev

FROM python:3.14.7-slim-bookworm@sha256:9ab8d9c8514b44f90cf0029dd42fdd7e9e211e639c8b995304cc04568dee900f

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src

ENV PATH="/app/.venv/bin:$PATH"

RUN useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app
USER appuser

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/_liveness')" || exit 1

# --graceful-timeout bounds the drain on SIGTERM: gunicorn SIGKILLs the worker once it
# expires, cutting any stream still in flight. The 30s default is far shorter than a long
# streaming turn, so deploys and scale-downs sever live responses. 600s fits inside the pod's
# 660s terminationGracePeriodSeconds after the 15s preStop sleep (charts/llm-gateway).
CMD ["gunicorn", "llm_gateway.main:app", \
     "--bind", "0.0.0.0:8080", \
     "--workers", "1", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--graceful-timeout", "600", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]

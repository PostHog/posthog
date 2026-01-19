from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import asyncpg
import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp

from llm_gateway.api.health import health_router
from llm_gateway.api.routes import router
from llm_gateway.callbacks import init_callbacks
from llm_gateway.config import get_settings
from llm_gateway.db.postgres import close_db_pool, init_db_pool
from llm_gateway.metrics.prometheus import DB_POOL_SIZE, get_instrumentator
from llm_gateway.rate_limiting.model_throttles import (
    ProductModelInputTokenThrottle,
    ProductModelOutputTokenThrottle,
    UserModelInputTokenThrottle,
    UserModelOutputTokenThrottle,
)
from llm_gateway.rate_limiting.runner import ThrottleRunner
from llm_gateway.rate_limiting.tokenizer import TokenCounter
from llm_gateway.request_context import RequestContext, set_request_context


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


configure_logging()
logger = structlog.get_logger(__name__)


def update_db_pool_metrics(pool: asyncpg.Pool | None) -> None:
    if pool is None:
        return
    DB_POOL_SIZE.labels(state="idle").set(pool.get_idle_size())
    DB_POOL_SIZE.labels(state="active").set(pool.get_size() - pool.get_idle_size())


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())[:8]
        set_request_context(RequestContext(request_id=request_id))
        structlog.contextvars.bind_contextvars(request_id=request_id)

        start_time = time.monotonic()

        response = await call_next(request)
        response.headers["x-request-id"] = request_id

        duration_ms = (time.monotonic() - start_time) * 1000

        if request.url.path not in ("/_liveness", "/_readiness", "/metrics"):
            logger.info(
                "request",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round(duration_ms, 2),
            )

        if hasattr(request.app.state, "db_pool"):
            update_db_pool_metrics(request.app.state.db_pool)

        structlog.contextvars.unbind_contextvars("request_id")
        return response


async def init_redis(url: str | None) -> Redis[bytes] | None:
    if not url:
        return None
    try:
        redis: Redis[bytes] = Redis.from_url(url)
        await redis.ping()
        return redis
    except Exception:
        logger.warning("redis_connection_failed", url=url)
        return None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    import os

    settings = get_settings()

    if settings.anthropic_api_key:
        os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
    if settings.openai_api_key:
        os.environ["OPENAI_API_KEY"] = settings.openai_api_key
    if settings.openai_api_base_url:
        os.environ["OPENAI_BASE_URL"] = settings.openai_api_base_url
    if settings.gemini_api_key:
        os.environ["GEMINI_API_KEY"] = settings.gemini_api_key

    logger.info("Initializing database pool...")
    app.state.db_pool = await init_db_pool(
        settings.database_url,
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
    )
    logger.info("Database pool initialized")

    app.state.redis = await init_redis(settings.redis_url)
    if app.state.redis:
        logger.info("Redis connected")

    app.state.token_counter = TokenCounter()

    output_throttles = [
        ProductModelOutputTokenThrottle(redis=app.state.redis),
        UserModelOutputTokenThrottle(redis=app.state.redis),
    ]
    app.state.output_throttles = output_throttles

    app.state.throttle_runner = ThrottleRunner(
        throttles=[
            ProductModelInputTokenThrottle(redis=app.state.redis),
            UserModelInputTokenThrottle(redis=app.state.redis),
            *output_throttles,
        ]
    )
    logger.info("Throttle runner initialized")

    init_callbacks()

    yield

    if app.state.redis:
        await app.state.redis.aclose()
        logger.info("Redis closed")
    logger.info("Closing database pool...")
    await close_db_pool(app.state.db_pool)
    logger.info("Database pool closed")


class ContentSizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, max_content_size: int) -> None:
        super().__init__(app)
        self.max_content_size = max_content_size

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.max_content_size:
            return JSONResponse(
                status_code=413,
                content={"detail": "Request body too large"},
            )
        return await call_next(request)


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="LLM Gateway",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(ContentSizeLimitMiddleware, max_content_size=settings.max_request_body_size)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["POST", "GET", "OPTIONS"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(router)

    if settings.metrics_enabled:
        get_instrumentator().instrument(app).expose(app, endpoint="/metrics")

    return app


app = create_app()

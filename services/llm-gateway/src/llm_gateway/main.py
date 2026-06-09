from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import asyncpg
import httpx
import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp

from llm_gateway.api.health import health_router
from llm_gateway.api.routes import router
from llm_gateway.callbacks import init_callbacks
from llm_gateway.circuit_breaker import build_anthropic_circuit_breaker, publish_anthropic_breaker_gauges_loop
from llm_gateway.config import Settings, get_settings
from llm_gateway.db.postgres import close_db_pool, init_db_pool
from llm_gateway.metrics.prometheus import DB_POOL_SIZE, get_instrumentator
from llm_gateway.rate_limiting.billable_credits_throttle import BillableCreditThrottle
from llm_gateway.rate_limiting.cost_gauge_publisher import publish_product_cost_gauges_loop
from llm_gateway.rate_limiting.cost_refresh import ensure_costs_fresh
from llm_gateway.rate_limiting.cost_throttles import (
    ProductCostThrottle,
    UserCostBurstThrottle,
    UserCostSustainedThrottle,
)
from llm_gateway.rate_limiting.denial_event import PosthogDenialCapturer
from llm_gateway.rate_limiting.runner import ThrottleRunner
from llm_gateway.request_context import RequestContext, set_request_context
from llm_gateway.services.plan_resolver import PlanResolver
from llm_gateway.services.quota_resolver import QuotaResolver


def configure_logging(debug: bool = False) -> None:
    log_level = logging.DEBUG if debug else logging.INFO
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )


configure_logging(get_settings().debug)
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


def export_provider_credentials(settings: Settings) -> None:
    """Export provider credentials and routing config as process env vars.

    The OpenAI and Anthropic SDKs (and litellm, which uses them) read these
    env vars by default, so doing this at startup is enough to propagate the
    configured values to every outbound request without per-call wiring.
    """
    if settings.anthropic_api_key:
        os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
    if settings.bedrock_region_name:
        os.environ["AWS_REGION"] = settings.bedrock_region_name
    if settings.openai_api_key:
        os.environ["OPENAI_API_KEY"] = settings.openai_api_key
    if settings.openai_api_base_url:
        os.environ["OPENAI_BASE_URL"] = settings.openai_api_base_url
    if settings.openai_organization:
        os.environ["OPENAI_ORG_ID"] = settings.openai_organization
    if settings.openrouter_api_key:
        os.environ["OPENROUTER_API_KEY"] = settings.openrouter_api_key
    if settings.fireworks_api_key:
        os.environ["FIREWORKS_API_KEY"] = settings.fireworks_api_key


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    export_provider_credentials(settings)

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

    product_throttle = ProductCostThrottle(redis=app.state.redis)
    denial_capturer: PosthogDenialCapturer | None = None
    if settings.posthog_project_token:
        denial_capturer = PosthogDenialCapturer(
            api_key=settings.posthog_project_token,
            host=settings.posthog_host,
        )
    app.state.throttle_runner = ThrottleRunner(
        throttles=[
            BillableCreditThrottle(),
            product_throttle,
            UserCostBurstThrottle(redis=app.state.redis),
            UserCostSustainedThrottle(redis=app.state.redis),
        ],
        denial_capturer=denial_capturer,
    )
    logger.info("Throttle runner initialized", denial_capture_enabled=denial_capturer is not None)

    app.state.cost_gauge_task = asyncio.create_task(publish_product_cost_gauges_loop(product_throttle))

    app.state.anthropic_circuit_breaker = build_anthropic_circuit_breaker(app.state.redis)
    logger.info(
        "anthropic_circuit_breaker_initialized",
        enabled=settings.anthropic_circuit_breaker_enabled,
        failure_threshold=settings.anthropic_circuit_breaker_failure_threshold,
        window_seconds=settings.anthropic_circuit_breaker_window_seconds,
        bypass_probability=settings.anthropic_circuit_breaker_bypass_probability,
        min_requests=settings.anthropic_circuit_breaker_min_requests,
    )
    app.state.anthropic_breaker_gauge_task = asyncio.create_task(
        publish_anthropic_breaker_gauges_loop(app.state.anthropic_circuit_breaker)
    )

    app.state.http_client = httpx.AsyncClient()
    app.state.plan_resolver = PlanResolver(
        redis=app.state.redis,
        http_client=app.state.http_client,
    )
    app.state.quota_resolver = QuotaResolver(
        redis=app.state.redis,
        http_client=app.state.http_client,
    )
    logger.info("Plan resolver initialized", posthog_api_base_url=settings.posthog_api_base_url or "(not configured)")

    logger.info(
        "rate_limits_configured",
        product_cost_limits={
            k: {"limit_usd": v.limit_usd, "window_seconds": v.window_seconds}
            for k, v in settings.product_cost_limits.items()
        },
        user_cost_limits={
            k: {
                "burst_limit_usd": v.burst_limit_usd,
                "burst_window_seconds": v.burst_window_seconds,
                "sustained_limit_usd": v.sustained_limit_usd,
                "sustained_window_seconds": v.sustained_window_seconds,
            }
            for k, v in settings.user_cost_limits.items()
        },
        user_cost_limits_disabled=settings.user_cost_limits_disabled,
    )

    init_callbacks()

    ensure_costs_fresh()
    logger.info("Model costs initialized")

    yield

    cost_gauge_task = getattr(app.state, "cost_gauge_task", None)
    if cost_gauge_task is not None:
        cost_gauge_task.cancel()
        try:
            await cost_gauge_task
        except asyncio.CancelledError:
            pass
    breaker_gauge_task = getattr(app.state, "anthropic_breaker_gauge_task", None)
    if breaker_gauge_task is not None:
        breaker_gauge_task.cancel()
        try:
            await breaker_gauge_task
        except asyncio.CancelledError:
            pass
    if app.state.http_client:
        await app.state.http_client.aclose()
        logger.info("HTTP client closed")
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
                content={"error": {"message": "Request body too large", "type": "request_too_large"}},
            )
        return await call_next(request)


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    content = exc.detail
    if isinstance(content, dict) and "error" in content:
        return JSONResponse(
            status_code=exc.status_code,
            content=content,
            headers=exc.headers,
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": content},
        headers=exc.headers,
    )


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

    app.exception_handler(HTTPException)(http_exception_handler)

    app.include_router(health_router)
    app.include_router(router)

    if settings.metrics_enabled:
        get_instrumentator().instrument(app).expose(app, endpoint="/metrics")

    return app


app = create_app()

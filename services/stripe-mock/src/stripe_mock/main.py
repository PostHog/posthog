import time
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request

from stripe_mock.config import settings
from stripe_mock.data.store import store
from stripe_mock.routes.list_endpoints import router as list_router
from stripe_mock.routes.nested_endpoints import router as nested_router
from stripe_mock.routes.search_endpoints import router as search_router
from stripe_mock.routes.webhook_endpoints import router as webhook_router

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Loading scenario", scenario=settings.scenario)
    store.load_scenario(settings.scenario)
    summary = store.summary()
    log.info("Scenario loaded", **summary)
    yield


app = FastAPI(title="Stripe Mock", lifespan=lifespan)

# Search routes must be registered before list routes
# so /v1/{resource}/search matches before /v1/{resource}
app.include_router(search_router)
app.include_router(nested_router)
app.include_router(webhook_router)
app.include_router(list_router)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration_ms = (time.time() - start) * 1000
    log.info(
        "request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=round(duration_ms, 1),
    )
    return response


@app.get("/_health")
async def health():
    return {"status": "ok", "scenario": settings.scenario, "collections": store.summary()}

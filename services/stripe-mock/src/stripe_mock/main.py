import time
import random
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from stripe_mock.config import mock_config, reload_mock_config, settings
from stripe_mock.data.store import store
from stripe_mock.routes.list_endpoints import router as list_router
from stripe_mock.routes.nested_endpoints import router as nested_router
from stripe_mock.routes.search_endpoints import router as search_router
from stripe_mock.routes.webhook_endpoints import router as webhook_router

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    reload_mock_config()
    log.info(
        "Config loaded",
        start_date=str(mock_config.start_date),
        end_date=str(mock_config.end_date),
        seed=mock_config.seed,
        customer_types=mock_config.customer_types,
        customer_metadata=mock_config.customer_metadata or "(none)",
    )
    log.info("Loading scenario", scenario=settings.scenario)
    store.load_scenario(settings.scenario)
    summary = store.summary()
    log.info("Scenario loaded", **summary)
    if mock_config.errors:
        log.info("Error injection active", routes=list(mock_config.errors.keys()))
    yield


app = FastAPI(title="Stripe Mock", lifespan=lifespan)

app.include_router(search_router)
app.include_router(nested_router)
app.include_router(webhook_router)
app.include_router(list_router)


@app.middleware("http")
async def error_injection(request: Request, call_next):
    for pattern, err_config in mock_config.errors.items():
        if request.url.path.startswith(pattern):
            if random.random() < err_config.rate:
                log.warning("error_injected", path=request.url.path, status=err_config.status)
                return JSONResponse(
                    status_code=err_config.status,
                    content={"error": {"message": err_config.message, "type": "api_error"}},
                )
    return await call_next(request)


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

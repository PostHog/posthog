import logging

from fastapi import APIRouter, HTTPException, Request

from llm_gateway.db.postgres import acquire_connection

logger = logging.getLogger(__name__)

health_router = APIRouter()


@health_router.get("/")
async def root() -> dict[str, str]:
    return {"service": "llm-gateway", "status": "running"}


@health_router.get("/_readiness")
async def readiness(request: Request) -> dict[str, str]:
    try:
        async with acquire_connection(request.app.state.db_pool) as conn:
            await conn.fetchval("SELECT 1")
        return {"status": "ready"}
    except Exception:
        logger.exception("Readiness check failed: database connection error")
        raise HTTPException(status_code=503, detail="Database not ready") from None


@health_router.get("/_liveness")
async def liveness() -> dict[str, str]:
    return {"status": "alive"}

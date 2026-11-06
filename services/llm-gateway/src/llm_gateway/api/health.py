import logging

from fastapi import APIRouter, HTTPException, Request

from llm_gateway.db.postgres import acquire_connection, missing_table_privileges

logger = logging.getLogger(__name__)

health_router = APIRouter()


@health_router.get("/")
async def root() -> dict[str, str]:
    return {"service": "llm-gateway", "status": "running"}


@health_router.get("/_readiness")
async def readiness(request: Request) -> dict[str, str]:
    try:
        async with acquire_connection(request.app.state.db_pool) as conn:
            missing = await missing_table_privileges(conn)
    except Exception:
        logger.exception("Readiness check failed: database connection error")
        raise HTTPException(status_code=503, detail="Database not ready") from None
    if missing:
        # Runs on every probe: a revoked grant unreadies serving pods too,
        # deliberately, since every declared table is on the auth path. The
        # body matches the connection-failure branch (the probe may be
        # public); this log line carries the table names.
        logger.error(
            "Readiness check failed: role lacks SELECT on %s; grants are the users.tf allowlist in posthog-cloud-infra",
            ", ".join(missing),
        )
        raise HTTPException(status_code=503, detail="Database not ready")
    return {"status": "ready"}


@health_router.get("/_liveness")
async def liveness() -> dict[str, str]:
    return {"status": "alive"}

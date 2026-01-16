from __future__ import annotations

import json
from typing import Annotated, Any

import asyncpg
from fastapi import Depends, HTTPException, Request, status

from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.auth.service import AuthService, get_auth_service
from llm_gateway.products.config import check_product_access
from llm_gateway.rate_limiting.runner import ThrottleRunner
from llm_gateway.rate_limiting.throttles import ThrottleContext
from llm_gateway.request_context import get_request_id, set_throttle_context


async def get_db_pool(request: Request) -> "asyncpg.Pool[asyncpg.Record]":  # noqa: UP037
    pool: asyncpg.Pool[asyncpg.Record] = request.app.state.db_pool
    return pool


async def get_throttle_runner(request: Request) -> ThrottleRunner:
    return request.app.state.throttle_runner


async def get_authenticated_user(
    request: Request,
    db_pool: Annotated[asyncpg.Pool, Depends(get_db_pool)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthenticatedUser:
    user = await auth_service.authenticate_request(request, db_pool)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return user


def get_product_from_request(request: Request) -> str:
    path = request.url.path
    parts = path.strip("/").split("/")
    if parts and parts[0] in {"array", "wizard", "llm_gateway"}:
        return parts[0]
    return "llm_gateway"


async def get_cached_body(request: Request) -> bytes | None:
    """Get request body, caching it for reuse."""
    if not hasattr(request.state, "_cached_body"):
        try:
            request.state._cached_body = await request.body()
        except Exception:
            request.state._cached_body = None
    return request.state._cached_body


async def get_model_from_request(request: Request) -> str | None:
    """Extract model name from request body if present."""
    body = await get_cached_body(request)
    if not body:
        return None
    try:
        data: dict[str, Any] = json.loads(body)
        return data.get("model")
    except (json.JSONDecodeError, TypeError):
        return None


async def enforce_product_access(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
) -> AuthenticatedUser:
    """Check if user has access to the product."""
    product = get_product_from_request(request)
    model = await get_model_from_request(request)

    allowed, error = check_product_access(
        product=product,
        auth_method=user.auth_method,
        application_id=user.application_id,
        model=model,
    )

    if not allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=error)
    return user


async def enforce_throttles(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(enforce_product_access)],
    runner: Annotated[ThrottleRunner, Depends(get_throttle_runner)],
) -> AuthenticatedUser:
    product = get_product_from_request(request)

    context = ThrottleContext(
        user=user,
        product=product,
        request_id=get_request_id() or None,
    )
    request.state.throttle_context = context
    set_throttle_context(runner, context)
    result = await runner.check(context)

    if not result.allowed:
        headers = {"Retry-After": str(result.retry_after)} if result.retry_after is not None else None
        detail = {
            "error": {
                "message": "Rate limit exceeded",
                "type": "rate_limit_error",
                "reason": result.detail,
            }
        }
        raise HTTPException(status_code=result.status_code, detail=detail, headers=headers)
    return user


DBPool = Annotated[asyncpg.Pool, Depends(get_db_pool)]
CurrentUser = Annotated[AuthenticatedUser, Depends(get_authenticated_user)]
ProductAccessUser = Annotated[AuthenticatedUser, Depends(enforce_product_access)]
RateLimitedUser = Annotated[AuthenticatedUser, Depends(enforce_throttles)]

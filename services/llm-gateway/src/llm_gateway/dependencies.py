from __future__ import annotations

from typing import Annotated

import asyncpg
from fastapi import Depends, HTTPException, Request, status

from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.auth.service import AuthService, get_auth_service
from llm_gateway.rate_limiting.middleware import check_rate_limit
from llm_gateway.rate_limiting.redis_limiter import RateLimiter


async def get_db_pool(request: Request) -> "asyncpg.Pool[asyncpg.Record]":  # noqa: UP037
    pool: asyncpg.Pool[asyncpg.Record] = request.app.state.db_pool
    return pool


async def get_rate_limiter(request: Request) -> RateLimiter:
    limiter: RateLimiter = request.app.state.rate_limiter
    return limiter


async def get_authenticated_user(
    request: Request,
    db_pool: Annotated[asyncpg.Pool, Depends(get_db_pool)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthenticatedUser:
    user = await auth_service.authenticate_request(request, db_pool)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return user


async def enforce_rate_limit(
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> AuthenticatedUser:
    if not await check_rate_limit(user, limiter):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")
    return user


DBPool = Annotated[asyncpg.Pool, Depends(get_db_pool)]
CurrentUser = Annotated[AuthenticatedUser, Depends(get_authenticated_user)]
RateLimitedUser = Annotated[AuthenticatedUser, Depends(enforce_rate_limit)]

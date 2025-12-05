from typing import Annotated

import asyncpg
from fastapi import Depends, HTTPException, Request, status

from llm_gateway.auth.middleware import authenticate_request
from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.rate_limiting.middleware import check_rate_limit


async def get_db_pool(request: Request) -> asyncpg.Pool:
    return request.app.state.db_pool


async def get_authenticated_user(
    request: Request,
    db_pool: Annotated[asyncpg.Pool, Depends(get_db_pool)],
) -> AuthenticatedUser:
    user = await authenticate_request(request, db_pool)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return user


async def enforce_rate_limit(
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
) -> AuthenticatedUser:
    if not check_rate_limit(user):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")
    return user


DBPool = Annotated[asyncpg.Pool, Depends(get_db_pool)]
CurrentUser = Annotated[AuthenticatedUser, Depends(get_authenticated_user)]
RateLimitedUser = Annotated[AuthenticatedUser, Depends(enforce_rate_limit)]

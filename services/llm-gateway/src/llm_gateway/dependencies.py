from __future__ import annotations

import json
from typing import Annotated, Any

import asyncpg
import structlog
from fastapi import Depends, HTTPException, Request, status

from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.auth.service import AuthService, get_auth_service
from llm_gateway.products.config import ALLOWED_PRODUCTS, check_product_access, resolve_product_alias
from llm_gateway.rate_limiting.cost_refresh import ensure_costs_fresh
from llm_gateway.rate_limiting.runner import ThrottleRunner
from llm_gateway.rate_limiting.throttles import ThrottleContext
from llm_gateway.request_context import (
    InvalidBillingTeamIdError,
    extract_billing_team_id_from_headers,
    extract_posthog_provider_from_headers,
    get_request_id,
    set_billing_team_id,
    set_throttle_context,
)
from llm_gateway.services.plan_resolver import resolve_plan_info

logger = structlog.get_logger(__name__)


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


async def resolve_billing_team(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
) -> AuthenticatedUser:
    """Validate the client-provided `X-PostHog-Team-Id` header and stash it in the request context.

    The billing team id is used to attribute LLM generation events for billing. When the header
    is absent we leave it unset (None) — callers that want billing attribution must explicitly
    opt in. This intentionally avoids falling back to the user's `current_team_id`, which is
    server-side session state and can diverge from the team the client is actually working in.
    """
    try:
        team_id = extract_billing_team_id_from_headers(request, user)
    except InvalidBillingTeamIdError as exc:
        detail = {"error": {"message": str(exc), "type": "invalid_request_error"}}
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc
    set_billing_team_id(team_id)
    return user


def get_product_from_request(request: Request) -> str:
    path = request.url.path
    parts = path.strip("/").split("/")
    if parts:
        product = resolve_product_alias(parts[0])
        if product in ALLOWED_PRODUCTS:
            return product
    return "llm_gateway"


async def get_cached_body(request: Request) -> bytes | None:
    """Get request body, caching it for reuse."""
    if not hasattr(request.state, "_cached_body"):
        try:
            request.state._cached_body = await request.body()
        except Exception:
            request.state._cached_body = None
    return request.state._cached_body


async def get_request_json(request: Request) -> dict[str, Any] | None:
    body = await get_cached_body(request)
    if not body:
        return None
    try:
        data = json.loads(body)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


async def get_model_from_request(request: Request) -> str | None:
    """Extract model name from request body if present."""
    data = await get_request_json(request)
    if data is None:
        return None
    model = data.get("model")
    return model if isinstance(model, str) else None


async def get_provider_from_request(request: Request) -> str | None:
    try:
        return extract_posthog_provider_from_headers(request)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": {"message": str(exc), "type": "invalid_request_error"}},
        ) from exc


async def enforce_product_access(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(resolve_billing_team)],
) -> AuthenticatedUser:
    """Check if user has access to the product."""
    product = get_product_from_request(request)
    model = await get_model_from_request(request)
    provider = await get_provider_from_request(request)

    allowed, error = check_product_access(
        product=product,
        auth_method=user.auth_method,
        application_id=user.application_id,
        model=model,
        provider=provider,
    )

    if not allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=error)
    return user


async def _extract_end_user_id_from_body(request: Request) -> str | None:
    """Extract the client-provided user identifier from the request body.

    For OpenAI-compatible endpoints, this is the top-level `user` field.
    For Anthropic endpoints, this is `metadata.user_id`.
    """
    body = await get_cached_body(request)
    if not body:
        return None
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None

    user_id = data.get("user")
    if user_id and isinstance(user_id, str):
        return user_id

    metadata = data.get("metadata")
    if isinstance(metadata, dict):
        uid = metadata.get("user_id")
        if uid and isinstance(uid, str):
            return uid

    return None


async def enforce_throttles(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(enforce_product_access)],
    runner: Annotated[ThrottleRunner, Depends(get_throttle_runner)],
) -> AuthenticatedUser:
    ensure_costs_fresh()
    product = get_product_from_request(request)

    end_user_id: str | None
    if user.auth_method == "oauth_access_token":
        end_user_id = str(user.user_id)
    else:
        end_user_id = await _extract_end_user_id_from_body(request)

    plan_info = await resolve_plan_info(request, user.user_id, product)

    context = ThrottleContext(
        user=user,
        product=product,
        request_id=get_request_id() or None,
        end_user_id=end_user_id,
        plan_key=plan_info.plan_key,
        seat_created_at=plan_info.seat_created_at,
        billing_period_start=plan_info.billing_period.current_period_start if plan_info.billing_period else None,
    )
    request.state.throttle_context = context
    set_throttle_context(runner, context)
    result = await runner.check(context)

    if not result.allowed:
        logger.warning(
            "request_rate_limited",
            user_id=user.user_id,
            team_id=user.team_id,
            product=product,
            reason=result.detail,
            retry_after=result.retry_after,
            status_code=result.status_code,
        )
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

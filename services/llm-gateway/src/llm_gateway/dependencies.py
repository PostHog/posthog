from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any

import asyncpg
import structlog
from fastapi import Depends, HTTPException, Request, status

from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.auth.service import AuthService, get_auth_service
from llm_gateway.circuit_breaker import AnthropicCircuitBreaker
from llm_gateway.products.config import (
    ALLOWED_PRODUCTS,
    check_free_tier_model_access,
    check_product_access,
    get_product_config,
    resolve_product_alias,
)
from llm_gateway.rate_limiting.cost_refresh import ensure_costs_fresh
from llm_gateway.rate_limiting.runner import ThrottleRunner
from llm_gateway.rate_limiting.throttles import ThrottleContext, is_usage_unlimited
from llm_gateway.request_context import (
    extract_posthog_provider_from_headers,
    get_request_id,
    set_throttle_context,
)
from llm_gateway.services.plan_resolver import PlanInfo, resolve_plan_info
from llm_gateway.services.quota_resolver import QuotaResourceStatus, resolve_quota_status

logger = structlog.get_logger(__name__)


async def get_db_pool(request: Request) -> "asyncpg.Pool[asyncpg.Record]":  # noqa: UP037
    pool: asyncpg.Pool[asyncpg.Record] = request.app.state.db_pool
    return pool


async def get_throttle_runner(request: Request) -> ThrottleRunner:
    return request.app.state.throttle_runner


async def get_anthropic_circuit_breaker(request: Request) -> AnthropicCircuitBreaker | None:
    return getattr(request.app.state, "anthropic_circuit_breaker", None)


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
    """Parse the JSON body as a dict, caching the result for reuse — the
    access-check chain reads it several times per request."""
    if hasattr(request.state, "_cached_json"):
        return request.state._cached_json
    parsed: dict[str, Any] | None = None
    body = await get_cached_body(request)
    if body:
        try:
            data = json.loads(body)
            parsed = data if isinstance(data, dict) else None
        except (json.JSONDecodeError, TypeError):
            parsed = None
    request.state._cached_json = parsed
    return parsed


async def get_model_from_request(request: Request) -> str | None:
    """Extract the model from the request body (JSON, or form for the
    transcription routes). None is safe: every route requires a model at
    validation, so such a request never reaches an upstream."""
    content_type = request.headers.get("content-type", "").lower()
    if content_type.startswith(("multipart/form-data", "application/x-www-form-urlencoded")):
        try:
            form = await request.form()
        except Exception:
            # malformed forms fail the endpoint's own parsing too
            return None
        model = form.get("model")
        return model if isinstance(model, str) else None
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
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
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
        scopes=user.scopes,
    )

    if not allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=error)
    return user


async def _extract_end_user_id_from_body(request: Request) -> str | None:
    """Extract the client-provided user identifier from the request body.

    For OpenAI-compatible endpoints, this is the top-level `user` field.
    For Anthropic endpoints, this is `metadata.user_id`.
    """
    data = await get_request_json(request)
    if data is None:
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


async def resolve_plan_and_quota(
    request: Request,
    *,
    user_id: int,
    team_id: int | None,
    product: str,
) -> tuple[PlanInfo, QuotaResourceStatus]:
    """Fetch plan info and (for bucket-billed products) the bucket's quota in parallel.

    Both calls are independent Django roundtrips on cache miss, so for products
    billing into a credit bucket we overlap them. Unbilled products short-circuit
    the throttle stack regardless of quota state, so we skip the resolver entirely
    rather than paying for the Redis GET (and the HTTP fallback on cache miss).

    Caveat: ``code_usage_billing_active`` rides the quota fetch, so a product
    without a credit bucket always reads as unbilled — removing or repointing
    posthog_code's bucket would silently turn off the org-billed cap bypass.
    """
    product_config = get_product_config(product)
    if product_config and product_config.credit_bucket is not None:
        plan_info, quota_status = await asyncio.gather(
            resolve_plan_info(request, user_id, product),
            resolve_quota_status(request, team_id, product_config.credit_bucket.value),
        )
        return plan_info, quota_status
    plan_info = await resolve_plan_info(request, user_id, product)
    return plan_info, QuotaResourceStatus(limited=False)


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

    plan_info, quota_status = await resolve_plan_and_quota(
        request,
        user_id=user.user_id,
        team_id=user.team_id,
        product=product,
    )

    model_allowed, model_error = check_free_tier_model_access(
        product=product,
        model=await get_model_from_request(request),
        provider=await get_provider_from_request(request),
        code_usage_billed=quota_status.code_usage_billing_active,
        usage_unlimited=is_usage_unlimited(user),
    )
    if not model_allowed:
        logger.warning(
            "free_tier_model_blocked",
            user_id=user.user_id,
            team_id=user.team_id,
            product=product,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "message": f"{model_error} (rate_limit)",
                    "type": "permission_error",
                    "code": "model_gate",
                }
            },
        )

    context = ThrottleContext(
        user=user,
        product=product,
        request_id=get_request_id() or None,
        end_user_id=end_user_id,
        plan_key=plan_info.plan_key,
        seat_created_at=plan_info.seat_created_at,
        seat_missing=plan_info.seat_missing,
        code_usage_billed=quota_status.code_usage_billing_active,
        billing_period_start=plan_info.billing_period.current_period_start if plan_info.billing_period else None,
        credits_exhausted=quota_status.limited,
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
        reason = result.detail
        message = (
            f"Rate limit exceeded: {reason}" if reason and reason != "Rate limit exceeded" else "Rate limit exceeded"
        )
        detail = {
            "error": {
                "message": message,
                "type": "rate_limit_error",
                "reason": reason,
                **({"code": result.scope} if result.scope else {}),
            }
        }
        raise HTTPException(status_code=result.status_code, detail=detail, headers=headers)
    return user


DBPool = Annotated[asyncpg.Pool, Depends(get_db_pool)]
CurrentUser = Annotated[AuthenticatedUser, Depends(get_authenticated_user)]
ProductAccessUser = Annotated[AuthenticatedUser, Depends(enforce_product_access)]
RateLimitedUser = Annotated[AuthenticatedUser, Depends(enforce_throttles)]
AnthropicCircuitBreakerDep = Annotated[AnthropicCircuitBreaker | None, Depends(get_anthropic_circuit_breaker)]

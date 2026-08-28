from decimal import Decimal
from typing import Literal

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.auth.service import InvalidProjectScopeError, UnauthorizedProjectScopeError, get_auth_service
from llm_gateway.products.config import (
    FREE_TIER_RESTRICTION_REASON,
    CreditBucket,
    filter_to_free_tier_models,
    validate_product,
)
from llm_gateway.rate_limiting.model_cost_service import ModelCostService
from llm_gateway.rate_limiting.throttles import is_usage_unlimited
from llm_gateway.services.model_registry import get_available_models
from llm_gateway.services.quota_resolver import resolve_quota_status

logger = structlog.get_logger(__name__)

models_router = APIRouter(tags=["models"])

CREATED_TIMESTAMP = 1669766400  # Nov 30, 2022 - ChatGPT release date - we don't have data on this so just return a default for the field to match OpenAI's API


class TruncationPolicyConfig(BaseModel):
    # Truncation for tool outputs: "bytes" | "tokens". 0 means fully truncated.
    # Default: bytes(10_000), matches codex fallback. Override with tool_output_token_limit.
    mode: Literal["bytes", "tokens"] = "bytes"
    limit: int = 10_000


class ModelPricing(BaseModel):
    prompt: str
    completion: str
    input_cache_read: str | None = None
    input_cache_write: str | None = None


class ModelObject(BaseModel):
    id: str
    slug: str = ""  # codex-acp compatibility — mirrors `id`
    display_name: str = ""  # codex-acp required
    object: Literal["model"] = "model"
    created: int = CREATED_TIMESTAMP
    owned_by: str
    context_window: int
    supports_streaming: bool
    supports_vision: bool
    # codex-acp required fields (codex-core ModelInfo struct)
    supported_reasoning_levels: list[str] = []
    shell_type: str = "default"
    visibility: str = "list"  # codex-acp ModelVisibility: "list" | "hide" | "none"
    supported_in_api: bool = True
    priority: int = 0
    base_instructions: str = ""
    supports_reasoning_summaries: bool = False
    support_verbosity: bool = False
    truncation_policy: TruncationPolicyConfig = TruncationPolicyConfig()
    supports_parallel_tool_calls: bool = True
    experimental_supported_tools: list[str] = []
    pricing: ModelPricing | None = None
    # Free-tier gate (posthog_code): restricted models are marked, not omitted.
    allowed: bool = True
    restriction_reason: str | None = None


class ModelsResponse(BaseModel):
    object: Literal["list"] = "list"
    data: list[ModelObject]
    models: list[ModelObject] = []  # Alias for `data` — codex-acp expects this field


def _format_rate(rate: float) -> str:
    return format(Decimal(str(rate)), "f")


def _get_model_pricing(cost_model_id: str) -> ModelPricing | None:
    costs = ModelCostService.get_instance().get_costs(cost_model_id)
    if costs is None:
        return None

    input_cost = costs.get("input_cost_per_token")
    output_cost = costs.get("output_cost_per_token")
    if input_cost is None or output_cost is None:
        return None

    supports_prompt_caching = bool(costs.get("supports_prompt_caching", False))
    cache_read_cost = costs.get("cache_read_input_token_cost", input_cost) if supports_prompt_caching else None
    cache_write_cost = costs.get("cache_creation_input_token_cost", input_cost) if supports_prompt_caching else None
    return ModelPricing(
        prompt=_format_rate(input_cost),
        completion=_format_rate(output_cost),
        input_cache_read=_format_rate(cache_read_cost) if cache_read_cost is not None else None,
        input_cache_write=_format_rate(cache_write_cost) if cache_write_cost is not None else None,
    )


def _build_response(product: str) -> ModelsResponse:
    models = get_available_models(product)
    model_objects = [
        ModelObject(
            id=m.id,
            slug=m.id,
            display_name=m.id,
            owned_by=m.provider,
            context_window=m.context_window,
            supports_streaming=m.supports_streaming,
            supports_vision=m.supports_vision,
            pricing=_get_model_pricing(m.cost_model_id),
        )
        for m in models
    ]
    return ModelsResponse(data=model_objects, models=model_objects)


async def _authenticated_caller(request: Request) -> AuthenticatedUser | None:
    """Resolve the caller when credentials are present, translating
    project-scope errors into responses. Runs on every product listing,
    independent of the model gate: a caller that selected a project it cannot
    use must get an error, never a list it could read as valid for that
    project. Anonymous callers and auth failures resolve to None."""
    try:
        return await get_auth_service().authenticate_request(request, request.app.state.db_pool)
    except InvalidProjectScopeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid project scope") from exc
    except UnauthorizedProjectScopeError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Project access denied") from exc
    except Exception:
        logger.warning("models_caller_resolution_failed", exc_info=True)
        return None


async def _caller_confirmed_free_tier(request: Request, user: AuthenticatedUser | None) -> bool:
    """Caller is authenticated, non-staff, and their org isn't billed for Code
    usage. Unidentifiable callers (anonymous, auth failure) are never marked;
    quota-fetch failures read the same last-known billing bit as enforcement,
    so marks match what requests would do. Enforcement stays the gate."""
    if user is None:
        return False
    if is_usage_unlimited(user):
        return False
    if user.team_id is None:
        # no team to bill: enforcement reads this caller as unbilled too
        return True
    try:
        quota_status = await resolve_quota_status(request, user.team_id, CreditBucket.POSTHOG_CODE_CREDITS.value)
    except Exception:
        logger.warning("models_free_tier_resolution_failed", exc_info=True)
        return False
    return not quota_status.code_usage_billing_active


@models_router.get("/v1/models")
async def list_models(request: Request) -> ModelsResponse:
    await _authenticated_caller(request)
    return _build_response("llm_gateway")


@models_router.get("/{product}/v1/models")
async def list_models_for_product(product: str, request: Request) -> ModelsResponse:
    resolved = validate_product(product)
    response = _build_response(product)

    user = await _authenticated_caller(request)

    if resolved != "posthog_code":
        return response
    if not await _caller_confirmed_free_tier(request, user):
        return response

    free_ids = set(filter_to_free_tier_models([m.id for m in response.data]))
    annotated = [
        m
        if m.id in free_ids
        else m.model_copy(update={"allowed": False, "restriction_reason": FREE_TIER_RESTRICTION_REASON})
        for m in response.data
    ]
    return ModelsResponse(data=annotated, models=annotated)

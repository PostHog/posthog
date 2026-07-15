from typing import Literal

import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel

from llm_gateway.auth.service import get_auth_service
from llm_gateway.config import get_settings
from llm_gateway.products.config import (
    FREE_TIER_RESTRICTION_REASON,
    CreditBucket,
    filter_to_free_tier_models,
    validate_product,
)
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
    # Free-tier gate (posthog_code): restricted models are marked, not omitted.
    allowed: bool = True
    restriction_reason: str | None = None


class ModelsResponse(BaseModel):
    object: Literal["list"] = "list"
    data: list[ModelObject]
    models: list[ModelObject] = []  # Alias for `data` — codex-acp expects this field


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
        )
        for m in models
    ]
    return ModelsResponse(data=model_objects, models=model_objects)


async def _caller_confirmed_free_tier(request: Request) -> bool:
    """Caller is authenticated, non-staff, and their org isn't billed for Code
    usage. Unidentifiable callers (anonymous, auth failure) are never marked;
    quota-fetch failures read the same last-known billing bit as enforcement,
    so marks match what requests would do. Enforcement stays the gate."""
    try:
        user = await get_auth_service().authenticate_request(request, request.app.state.db_pool)
        if user is None:
            return False
        if is_usage_unlimited(user):
            return False
        if user.team_id is None:
            # no team to bill: enforcement reads this caller as unbilled too
            return True
        quota_status = await resolve_quota_status(request, user.team_id, CreditBucket.POSTHOG_CODE_CREDITS.value)
        return not quota_status.code_usage_billing_active
    except Exception:
        logger.warning("models_free_tier_resolution_failed", exc_info=True)
        return False


@models_router.get("/v1/models")
async def list_models() -> ModelsResponse:
    return _build_response("llm_gateway")


@models_router.get("/{product}/v1/models")
async def list_models_for_product(product: str, request: Request) -> ModelsResponse:
    resolved = validate_product(product)
    response = _build_response(product)

    if resolved != "posthog_code" or not get_settings().posthog_code_model_gate_enabled:
        return response
    if not await _caller_confirmed_free_tier(request):
        return response

    free_ids = set(filter_to_free_tier_models([m.id for m in response.data]))
    annotated = [
        m
        if m.id in free_ids
        else m.model_copy(update={"allowed": False, "restriction_reason": FREE_TIER_RESTRICTION_REASON})
        for m in response.data
    ]
    return ModelsResponse(data=annotated, models=annotated)

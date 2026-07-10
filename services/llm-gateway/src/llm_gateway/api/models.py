from typing import Literal

import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel

from llm_gateway.auth.service import get_auth_service
from llm_gateway.products.config import validate_product
from llm_gateway.services.model_registry import get_available_models
from llm_gateway.services.plan_resolver import resolve_plan_info
from llm_gateway.services.premium_model_policy import (
    is_model_allowed_by_premium_policy,
    is_premium_model_gate_active,
)

models_router = APIRouter(tags=["models"])
logger = structlog.get_logger(__name__)

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


class ModelsResponse(BaseModel):
    object: Literal["list"] = "list"
    data: list[ModelObject]
    models: list[ModelObject] = []  # Alias for `data` — codex-acp expects this field


async def _resolve_optional_plan_key(request: Request, product: str) -> str | None:
    try:
        user = await get_auth_service().authenticate_request(request, request.app.state.db_pool)
    except Exception:
        logger.warning("models_optional_auth_failed", product=product, exc_info=True)
        return None
    if user is None:
        return None
    plan_info = await resolve_plan_info(request, user.user_id, product)
    return plan_info.plan_key


async def _build_response(request: Request, product: str) -> ModelsResponse:
    models = get_available_models(product)
    if is_premium_model_gate_active(product):
        plan_key = await _resolve_optional_plan_key(request, product)
        models = [m for m in models if is_model_allowed_by_premium_policy(product, m.id, plan_key)]
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


@models_router.get("/v1/models")
async def list_models(request: Request) -> ModelsResponse:
    return await _build_response(request, "llm_gateway")


@models_router.get("/{product}/v1/models")
async def list_models_for_product(product: str, request: Request) -> ModelsResponse:
    resolved_product = validate_product(product)
    return await _build_response(request, resolved_product)

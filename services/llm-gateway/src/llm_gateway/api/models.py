from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from llm_gateway.products.config import validate_product
from llm_gateway.services.model_registry import get_available_models

models_router = APIRouter(tags=["models"])

CREATED_TIMESTAMP = 1669766400  # Nov 30, 2022 - ChatGPT release date - we don't have data on this so just return a default for the field to match OpenAI's API


class ModelObject(BaseModel):
    id: str
    object: Literal["model"] = "model"
    created: int = CREATED_TIMESTAMP
    owned_by: str
    context_window: int
    supports_streaming: bool
    supports_vision: bool


class ModelsResponse(BaseModel):
    object: Literal["list"] = "list"
    data: list[ModelObject]


def _build_response(product: str) -> ModelsResponse:
    models = get_available_models(product)
    return ModelsResponse(
        data=[
            ModelObject(
                id=m.id,
                owned_by=m.provider,
                context_window=m.context_window,
                supports_streaming=m.supports_streaming,
                supports_vision=m.supports_vision,
            )
            for m in models
        ]
    )


@models_router.get("/v1/models")
async def list_models() -> ModelsResponse:
    return _build_response("llm_gateway")


@models_router.get("/{product}/v1/models")
async def list_models_for_product(product: str) -> ModelsResponse:
    validate_product(product)
    return _build_response(product)

from typing import NoReturn

from fastapi import APIRouter, HTTPException

from llm_gateway.api.anthropic import anthropic_router
from llm_gateway.api.models import models_router
from llm_gateway.api.openai import openai_router
from llm_gateway.api.usage import usage_router

SLUGLESS_INFERENCE_PATHS = (
    "/v1/messages",
    "/v1/messages/count_tokens",
    "/v1/chat/completions",
    "/v1/responses",
    "/responses",
    "/v1/audio/transcriptions",
)


async def reject_slugless_inference() -> NoReturn:
    raise HTTPException(
        status_code=400,
        detail={
            "error": {
                "message": (
                    "A product is required in the URL path, for example /{product}/v1/messages. "
                    "This gateway is being retired. Move to the AI gateway at "
                    "https://ai-gateway.us.posthog.com or https://ai-gateway.eu.posthog.com."
                ),
                "type": "invalid_request_error",
            }
        },
    )


router = APIRouter()
for path in SLUGLESS_INFERENCE_PATHS:
    router.add_api_route(path, reject_slugless_inference, methods=["POST"], response_model=None)
router.include_router(anthropic_router, tags=["Anthropic"])
router.include_router(models_router, tags=["Models"])
router.include_router(openai_router, tags=["OpenAI"])
router.include_router(usage_router)

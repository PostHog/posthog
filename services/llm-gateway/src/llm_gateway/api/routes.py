from fastapi import APIRouter

from llm_gateway.api.anthropic import anthropic_router
from llm_gateway.api.models import models_router
from llm_gateway.api.openai import openai_router

router = APIRouter()
router.include_router(anthropic_router, tags=["Anthropic"])
router.include_router(models_router, tags=["Models"])
router.include_router(openai_router, tags=["OpenAI"])

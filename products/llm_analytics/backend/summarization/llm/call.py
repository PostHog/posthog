"""
LLM calling function for summarization supporting multiple providers.

Supports:
- OpenAI: Uses openai.AsyncOpenAI directly
- Gemini: Uses google.genai directly
"""

from typing import cast

from ..constants import DEFAULT_MODE, DEFAULT_MODEL_GEMINI, DEFAULT_MODEL_OPENAI, DEFAULT_PROVIDER
from ..models import GeminiModel, OpenAIModel, SummarizationMode, SummarizationProvider
from .gemini import summarize_with_gemini
from .openai import summarize_with_openai
from .schema import SummarizationResponse


async def summarize(
    text_repr: str,
    team_id: int,
    mode: SummarizationMode = DEFAULT_MODE,
    provider: SummarizationProvider = DEFAULT_PROVIDER,
    model: OpenAIModel | GeminiModel | None = None,
) -> SummarizationResponse:
    """
    Generate AI-powered summary from text representation.

    Args:
        text_repr: Line-numbered text representation to summarize
        team_id: Team ID for cost tracking and analytics
        mode: Summary detail level
        provider: LLM provider to use
        model: LLM model to use (defaults based on provider)

    Returns:
        Structured summarization response with flow diagram, bullets, and notes
    """
    if provider == SummarizationProvider.GEMINI:
        gemini_model = cast(GeminiModel, model) if model else DEFAULT_MODEL_GEMINI
        return await summarize_with_gemini(text_repr, team_id, mode, gemini_model)
    else:
        openai_model = cast(OpenAIModel, model) if model else DEFAULT_MODEL_OPENAI
        return await summarize_with_openai(text_repr, team_id, mode, openai_model)

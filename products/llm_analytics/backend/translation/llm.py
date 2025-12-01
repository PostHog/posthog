"""LLM-based translation using OpenAI."""

from django.conf import settings

import openai
import structlog

from .constants import SUPPORTED_LANGUAGES, TRANSLATION_MODEL

logger = structlog.get_logger(__name__)


def translate_text(text: str, target_language: str) -> str:
    """
    Translate text to target language using OpenAI's GPT model.

    Args:
        text: The text to translate
        target_language: Target language code (e.g., 'en', 'es', 'fr')

    Returns:
        Translated text
    """
    client = openai.OpenAI(api_key=settings.OPENAI_API_KEY, timeout=30.0)

    target_name = SUPPORTED_LANGUAGES.get(target_language, target_language)

    response = client.chat.completions.create(
        model=TRANSLATION_MODEL,
        messages=[
            {
                "role": "system",
                "content": f"You are a translator. Translate the following text to {target_name}. "
                "Only return the translation, nothing else. Preserve formatting and line breaks.",
            },
            {"role": "user", "content": text},
        ],
    )

    content = response.choices[0].message.content
    return content.strip() if content else ""

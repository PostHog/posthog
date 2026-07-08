"""Gemini API key resolution for Replay Vision."""

from django.conf import settings


def gemini_api_key() -> str:
    """Replay Vision's dedicated key (own GCP project), falling back to the shared key where unset."""
    return settings.REPLAY_VISION_GEMINI_API_KEY or settings.GEMINI_API_KEY

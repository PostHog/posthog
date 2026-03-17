import os
import logging
from pathlib import Path

import pytest
from unittest.mock import patch

from django.conf import settings

import posthoganalytics
from dotenv import load_dotenv
from posthoganalytics import Posthog
from posthoganalytics.ai.gemini import genai
from posthoganalytics.ai.openai import AsyncOpenAI

load_dotenv(Path(__file__).resolve().parents[3] / ".env")

logging.getLogger("google_genai").setLevel(logging.ERROR)
logging.getLogger("google.genai").setLevel(logging.ERROR)

# Initialize posthoganalytics default_client so the LLM wrapper (which requires it) works
posthoganalytics.default_client = Posthog(
    os.environ.get("POSTHOG_PROJECT_API_KEY", "phx_unused"),
    host=os.environ.get("POSTHOG_HOST", "http://localhost:8010"),
    disabled=True,
    debug=bool(os.environ.get("POSTHOG_DEBUG")),
)

# Django settings are loaded before conftest, so .env vars aren't picked up.
# Override settings that need to come from .env.
if not settings.ANTHROPIC_API_KEY:
    settings.ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
if not getattr(settings, "OPENAI_API_KEY", ""):
    settings.OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# Gemini client expects GOOGLE_API_KEY; alias from GEMINI_API_KEY if needed
if not os.environ.get("GOOGLE_API_KEY") and os.environ.get("GEMINI_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]


def pytest_addoption(parser):
    parser.addoption("--limit", default=None, type=int, help="Limit number of items to process (e.g. --limit 3)")
    parser.addoption("--no-capture", action="store_true", default=False, help="Skip emitting eval results to PostHog")
    parser.addoption("--online", action="store_true", default=False, help="Capture as online eval")


@pytest.fixture
def limit(request):
    return request.config.getoption("--limit")


@pytest.fixture
def no_capture(request):
    return request.config.getoption("--no-capture")


@pytest.fixture
def online(request):
    return request.config.getoption("--online")


@pytest.fixture
def posthog_client(no_capture):
    api_key = os.environ.get("POSTHOG_PROJECT_API_KEY", "")
    if not api_key and not no_capture:
        raise ValueError("POSTHOG_PROJECT_API_KEY needs to be set (or pass --no-capture).")
    host = os.environ.get("POSTHOG_HOST", "http://localhost:8010")
    client = Posthog(
        api_key or "phx_unused", host=host, disabled=no_capture, debug=bool(os.environ.get("POSTHOG_DEBUG"))
    )
    yield client
    client.shutdown()


@pytest.fixture
def openai_client(posthog_client):
    return AsyncOpenAI(posthog_client=posthog_client)


@pytest.fixture
def gemini_client():
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    return genai.AsyncClient(api_key=api_key)


@pytest.fixture
def mock_temporal():
    with patch("temporalio.activity.heartbeat"):
        yield

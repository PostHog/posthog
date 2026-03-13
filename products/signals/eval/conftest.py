import os
import logging
from pathlib import Path

import pytest

from django.conf import settings

import posthoganalytics
from dotenv import load_dotenv
from posthoganalytics import Posthog
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
    parser.addoption("--case-ids", default=None, help="Comma-separated ticket IDs to run (e.g. 00005,00010)")
    parser.addoption("--limit", default=None, type=int, help="Limit number of items to process (e.g. --limit 3)")
    parser.addoption("--no-capture", action="store_true", default=False, help="Skip emitting eval results to PostHog")


@pytest.fixture
def case_ids(request):
    raw = request.config.getoption("--case-ids")
    if raw is None:
        return None
    return {s.strip() for s in raw.split(",") if s.strip()}


@pytest.fixture
def limit(request):
    return request.config.getoption("--limit")


@pytest.fixture
def no_capture(request):
    return request.config.getoption("--no-capture")


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


# Re-export fixtures from mock.py so pytest auto-discovers them
from products.signals.eval.mock import mock_clickhouse, mock_temporal, team  # noqa: E402, F401

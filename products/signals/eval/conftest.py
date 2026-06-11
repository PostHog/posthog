import os
from pathlib import Path

import pytest
from unittest.mock import patch

from django.conf import settings

import posthoganalytics
from dotenv import load_dotenv
from posthoganalytics import Posthog
from posthoganalytics.ai.openai import AsyncOpenAI

from posthog.llm.gateway_client import get_async_anthropic_gateway_client
from posthog.models import Organization, Team

load_dotenv(Path(__file__).resolve().parents[3] / ".env")

# Initialize posthoganalytics default_client so the LLM wrapper (which requires it) works
posthoganalytics.default_client = Posthog(  # ty: ignore[invalid-assignment]
    os.environ.get("POSTHOG_PROJECT_API_KEY", "phx_unused"),
    host=os.environ.get("POSTHOG_HOST", "http://localhost:8010"),
    disabled=True,
    debug=bool(os.environ.get("POSTHOG_DEBUG")),
)

# Django settings are loaded before conftest, so .env vars aren't picked up.
# Override settings that need to come from .env.
if not getattr(settings, "OPENAI_API_KEY", ""):
    settings.OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
if not getattr(settings, "LLM_GATEWAY_URL", ""):
    settings.LLM_GATEWAY_URL = os.environ.get("LLM_GATEWAY_URL", "")
if not getattr(settings, "LLM_GATEWAY_API_KEY", ""):
    settings.LLM_GATEWAY_API_KEY = os.environ.get("LLM_GATEWAY_PERSONAL_API_KEY", "") or os.environ.get(
        "LLM_GATEWAY_API_KEY", ""
    )

# Team id used by the eval harness when attributing LLM cost via the gateway.
EVAL_TEAM_ID = int(os.environ.get("SIGNALS_EVAL_TEAM_ID", "1"))


def pytest_addoption(parser):
    parser.addoption("--limit", default=None, type=int, help="Limit number of items to process (e.g. --limit 3)")
    parser.addoption("--no-capture", action="store_true", default=False, help="Skip emitting eval results to PostHog")
    parser.addoption("--online", action="store_true", default=False, help="Capture as online eval")
    parser.addoption("--strategy", default="example_strategy", help="Strategy module name (default: example_strategy)")
    parser.addoption(
        "--safe", action="store_true", default=False, help="Filter to safe signals only, skip safety_filter step"
    )


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
def posthog_client(no_capture, db):
    api_key = os.environ.get("POSTHOG_PROJECT_API_KEY", "")
    if not api_key:
        last_team = Team.objects.order_by("-pk").first()
        if last_team:
            api_key = last_team.api_token
        elif not no_capture:
            org = Organization.objects.create(name="Eval Org", is_ai_data_processing_approved=True)
            team = Team.objects.create(organization=org, name="Eval Team")
            api_key = team.api_token
    if not api_key and not no_capture:
        raise ValueError("POSTHOG_PROJECT_API_KEY needs to be set (or pass --no-capture).")
    host = os.environ.get("POSTHOG_HOST", "http://localhost:8010")
    client = Posthog(
        api_key or "phx_unused", host=host, disabled=no_capture, debug=bool(os.environ.get("POSTHOG_DEBUG"))
    )
    yield client
    client.shutdown()


@pytest.fixture
async def openai_client(posthog_client):
    client = AsyncOpenAI(posthog_client=posthog_client)
    yield client
    await client.close()


@pytest.fixture
def gateway_client():
    """Async Anthropic client pointed at the internal LLM gateway's native Messages endpoint.

    Used by eval_grouping_e2e to drive the production signals pre-emit pipeline
    (`_check_actionability` etc.) through the gateway, attributing cost to EVAL_TEAM_ID.
    """
    return get_async_anthropic_gateway_client(product="signals", team_id=EVAL_TEAM_ID)


@pytest.fixture
def mock_temporal():
    with patch("temporalio.activity.heartbeat"):
        yield

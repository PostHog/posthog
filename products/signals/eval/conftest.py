import os
import subprocess
from pathlib import Path

import pytest
from unittest.mock import patch

from django.conf import settings

import posthoganalytics
from dotenv import load_dotenv
from posthoganalytics import Posthog
from posthoganalytics.ai.openai import AsyncOpenAI

from posthog.llm.gateway_client import build_async_anthropic_client

# This eval runs via bare pytest (no hogli), so the conftest owns loading repo-root .env.
load_dotenv(Path(__file__).resolve().parents[3] / ".env")

# Initialize posthoganalytics default_client so the LLM wrapper (which requires it) works
posthoganalytics.default_client = Posthog(
    os.environ.get("POSTHOG_PROJECT_API_KEY", "phx_unused"),
    host=os.environ.get("POSTHOG_HOST", "http://localhost:8010"),
    disabled=True,
    debug=bool(os.environ.get("POSTHOG_DEBUG")),
)

# Django settings are loaded before conftest, so .env vars aren't picked up.
# Override settings that need to come from .env.
if not getattr(settings, "OPENAI_API_KEY", ""):
    settings.OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
if not getattr(settings, "AI_GATEWAY_URL", ""):
    settings.AI_GATEWAY_URL = os.environ.get("AI_GATEWAY_URL", "")
if not getattr(settings, "AI_GATEWAY_API_KEY", ""):
    settings.AI_GATEWAY_API_KEY = os.environ.get("AI_GATEWAY_API_KEY", "")

# Team id used by the eval harness when attributing LLM cost via the gateway.
EVAL_TEAM_ID = int(os.environ.get("SIGNALS_EVAL_TEAM_ID", "1"))


def pytest_addoption(parser):
    parser.addoption("--limit", default=None, type=int, help="Limit number of items to process (e.g. --limit 3)")
    parser.addoption("--no-capture", action="store_true", default=False, help="Skip eval uploads and trace capture")
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
def posthog_client(no_capture):
    api_key = os.environ.get("POSTHOG_PROJECT_API_KEY", "")
    host = os.environ.get("POSTHOG_HOST", "http://localhost:8010")
    client = Posthog(
        api_key or "phx_unused",
        host=host,
        disabled=no_capture or not api_key,
        debug=bool(os.environ.get("POSTHOG_DEBUG")),
    )
    yield client
    client.shutdown()


@pytest.fixture
def eval_metadata(limit: int | None) -> dict[str, object]:
    metadata: dict[str, object] = {"limit": limit}
    root = Path(__file__).resolve().parents[3]
    try:
        metadata["git_sha"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL, timeout=5
        ).strip()
        metadata["git_dirty"] = bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=root, text=True, stderr=subprocess.DEVNULL, timeout=5
            ).strip()
        )
    except (OSError, subprocess.SubprocessError):
        pass
    return metadata


@pytest.fixture
async def openai_client(posthog_client):
    client = AsyncOpenAI(posthog_client=posthog_client)
    yield client
    await client.close()


@pytest.fixture
def gateway_client():
    """Async Anthropic client pointed at the Go ai-gateway's native Messages endpoint.

    Used by eval_grouping_e2e to drive the production signals pre-emit pipeline
    (`check_actionability` etc.) through the gateway, attributing cost to EVAL_TEAM_ID.
    """
    return build_async_anthropic_client(product="signals", ai_product="signals_eval", team_id=EVAL_TEAM_ID)


@pytest.fixture
def mock_temporal():
    with patch("temporalio.activity.heartbeat"):
        yield

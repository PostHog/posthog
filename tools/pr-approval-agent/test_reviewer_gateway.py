"""Routing-pin tests for the ai-gateway switch in reviewer.py."""

import os
import sys

import pytest
from unittest.mock import MagicMock

# reviewer.py's claude_agent_sdk dep is installed by `uv run`, not the test venv.
sys.modules.setdefault("claude_agent_sdk", MagicMock())
sys.modules.setdefault("claude_agent_sdk.types", MagicMock())

import reviewer  # noqa: E402
from reviewer import _apply_gateway_route  # noqa: E402

_ANTHROPIC_ENV_KEYS = ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_CUSTOM_HEADERS")


@pytest.fixture(autouse=True)
def _restore_anthropic_env():
    saved = {k: os.environ.get(k) for k in _ANTHROPIC_ENV_KEYS}
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def test_no_gateway_returns_none_and_leaves_env_untouched():
    before = {k: os.environ.get(k) for k in _ANTHROPIC_ENV_KEYS}
    assert _apply_gateway_route(None, {"stamphog_pr_number": 1}) is None
    assert {k: os.environ.get(k) for k in _ANTHROPIC_ENV_KEYS} == before


def test_gateway_mode_uses_plain_query_and_applies_env():
    active = _apply_gateway_route(("https://gateway.us.posthog.com", "phs_secret"), {"stamphog_pr_number": 7})
    # Plain query, not the traced wrapper (else the gateway's $ai_generation double-counts).
    assert active is reviewer.query
    assert os.environ["ANTHROPIC_BASE_URL"] == "https://gateway.us.posthog.com"
    assert os.environ["ANTHROPIC_AUTH_TOKEN"] == "phs_secret"
    assert os.environ["ANTHROPIC_API_KEY"] == "phs_secret"
    headers = os.environ["ANTHROPIC_CUSTOM_HEADERS"]
    assert "x-posthog-property-ai_product: aio_stamphog" in headers
    assert "x-posthog-property-stamphog_pr_number: 7" in headers

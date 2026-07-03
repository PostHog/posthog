"""Tests for ai-gateway routing in gateway.py."""

import pytest

from gateway import AI_PRODUCT, gateway_env, resolve_gateway_config


@pytest.fixture(autouse=True)
def _clear_gateway_env(monkeypatch):
    monkeypatch.delenv("AI_GATEWAY_URL", raising=False)
    monkeypatch.delenv("AI_GATEWAY_API_KEY", raising=False)


def test_unset_returns_none_direct_path(monkeypatch):
    assert resolve_gateway_config() is None


@pytest.mark.parametrize(
    "url,api_key",
    [
        pytest.param("https://gateway.us.posthog.com/v1", "", id="url-only"),
        pytest.param("", "phs_secret", id="key-only"),
    ],
)
def test_half_applied_config_falls_back(monkeypatch, url, api_key):
    monkeypatch.setenv("AI_GATEWAY_URL", url)
    monkeypatch.setenv("AI_GATEWAY_API_KEY", api_key)
    assert resolve_gateway_config() is None


def test_url_without_v1_falls_back(monkeypatch):
    monkeypatch.setenv("AI_GATEWAY_URL", "https://gateway.us.posthog.com")
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "phs_secret")
    assert resolve_gateway_config() is None


def test_schemeless_url_falls_back(monkeypatch):
    # Schemeless parses all into .path, so the /v1 check alone would pass.
    monkeypatch.setenv("AI_GATEWAY_URL", "gateway.us.posthog.com/v1")
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "phs_secret")
    assert resolve_gateway_config() is None


@pytest.mark.parametrize(
    "configured_url,expected_base",
    [
        pytest.param("https://gateway.us.posthog.com/v1", "https://gateway.us.posthog.com", id="strips-v1"),
        pytest.param(
            "https://gateway.us.posthog.com/v1/", "https://gateway.us.posthog.com", id="strips-v1-trailing-slash"
        ),
    ],
)
def test_resolves_and_strips_v1_for_anthropic_base(monkeypatch, configured_url, expected_base):
    # SDK re-appends /v1/messages, so resolve() returns the bare host.
    monkeypatch.setenv("AI_GATEWAY_URL", configured_url)
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "phs_secret")
    assert resolve_gateway_config() == (expected_base, "phs_secret")


def test_gateway_env_points_sdk_at_gateway():
    env = gateway_env("https://gateway.us.posthog.com", "phs_secret", {"stamphog_pr_number": 123})
    assert env["ANTHROPIC_BASE_URL"] == "https://gateway.us.posthog.com"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "phs_secret"
    assert env["ANTHROPIC_API_KEY"] == "phs_secret"


def test_gateway_env_tags_ai_product_and_attribution():
    env = gateway_env("https://host", "phs_secret", {"stamphog_pr_number": 123, "stamphog_repo": "PostHog/posthog"})
    headers = env["ANTHROPIC_CUSTOM_HEADERS"]
    assert f"x-posthog-property-ai_product: {AI_PRODUCT}" in headers
    assert "x-posthog-property-stamphog_pr_number: 123" in headers
    assert "x-posthog-property-stamphog_repo: PostHog/posthog" in headers


def test_ai_product_uses_aio_prefix_no_reserved_prefix():
    assert AI_PRODUCT == "aio_stamphog"
    assert not AI_PRODUCT.startswith("$")


def test_header_values_are_single_line():
    env = gateway_env("https://host", "phs_secret", {"stamphog_pr_title": "line one\nline two"})
    title_lines = [ln for ln in env["ANTHROPIC_CUSTOM_HEADERS"].split("\n") if "stamphog_pr_title" in ln]
    assert title_lines == ["x-posthog-property-stamphog_pr_title: line one line two"]


def test_none_attribution_values_dropped():
    env = gateway_env("https://host", "phs_secret", {"stamphog_commit_type": None})
    assert "stamphog_commit_type" not in env["ANTHROPIC_CUSTOM_HEADERS"]

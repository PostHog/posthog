from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from llm_gateway import flags
from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.config import DEFAULT_WIZARD_MODEL_ALLOWLIST, get_settings
from llm_gateway.dependencies import enforce_product_access
from llm_gateway.products.config import WIZARD_US_APP_ID
from llm_gateway.products.wizard_allowlist import (
    WIZARD_MODEL_ALLOWLIST_FLAG,
    check_wizard_model_access,
    parse_allowlist,
    request_efforts,
    resolve_allowlist,
)
from tests.test_dependencies import _make_request

DEFAULTS = parse_allowlist(DEFAULT_WIZARD_MODEL_ALLOWLIST)
assert DEFAULTS is not None


@pytest.fixture(autouse=True)
def clear_caches() -> None:
    flags._payload_cache.clear()
    flags._flag_unavailable_cache.clear()
    get_settings.cache_clear()


class TestParseAllowlist:
    def test_normalizes_models_and_efforts(self) -> None:
        parsed = parse_allowlist({" OpenAI/GPT-5.6-Terra ": ["Low", " medium "], "claude-haiku-4-5": ["none"]})
        assert parsed == {"gpt-5.6-terra": frozenset({"low", "medium"}), "claude-haiku-4-5": frozenset({"none"})}

    def test_accepts_json_string_payload(self) -> None:
        assert parse_allowlist('{"claude-sonnet-4-6": ["none"]}') == {"claude-sonnet-4-6": frozenset({"none"})}

    @pytest.mark.parametrize("raw", ["not json", ["claude-sonnet-4-6"], 42, None])
    def test_unusable_shapes_return_none(self, raw: object) -> None:
        assert parse_allowlist(raw) is None

    def test_bad_efforts_keep_the_model_with_nothing_allowed(self) -> None:
        # A typo must not widen access: the model stays listed but every effort is refused.
        parsed = parse_allowlist({"claude-sonnet-4-6": "high", "gpt-5.6-sol": [1, "medium"]})
        assert parsed == {"claude-sonnet-4-6": frozenset(), "gpt-5.6-sol": frozenset({"medium"})}


class TestRequestEfforts:
    def test_reads_every_api_shape(self) -> None:
        assert request_efforts({"output_config": {"effort": "High"}}) == frozenset({"high"})
        assert request_efforts({"reasoning_effort": "low"}) == frozenset({"low"})
        assert request_efforts({"reasoning": {"effort": "medium"}}) == frozenset({"medium"})

    def test_no_effort_is_empty(self) -> None:
        assert request_efforts({"model": "claude-haiku-4-5"}) == frozenset()
        assert request_efforts(None) == frozenset()


class TestCheckWizardModelAccess:
    @pytest.mark.parametrize(
        ("model", "efforts"),
        [
            ("claude-sonnet-4-6", frozenset()),
            ("claude-sonnet-4-6", frozenset({"high"})),
            ("claude-haiku-4-5-20251001", frozenset()),
            ("openai/gpt-5.6-terra", frozenset({"medium"})),
            ("gpt-5.6-luna", frozenset({"low"})),
        ],
    )
    def test_wizard_pairs_pass(self, model: str, efforts: frozenset[str]) -> None:
        assert check_wizard_model_access(model, efforts, DEFAULTS) == (True, None)

    @pytest.mark.parametrize(
        ("model", "efforts", "fragment"),
        [
            ("claude-opus-4-8", frozenset(), "Model 'claude-opus-4-8'"),
            ("claude-fable-5-1", frozenset({"high"}), "Model 'claude-fable-5-1'"),
            ("gpt-6-astra", frozenset(), "Model 'gpt-6-astra'"),
            # Exact, not prefix: a longer id sharing a listed prefix is a different model.
            ("claude-sonnet-4-6-pro", frozenset(), "Model 'claude-sonnet-4-6-pro'"),
            ("claude-haiku-4-5", frozenset({"high"}), "Effort 'high'"),
            ("gpt-5.6-luna", frozenset({"medium"}), "Effort 'medium'"),
            ("gpt-5.6-sol", frozenset(), "Effort 'none'"),
            # Two shapes declaring different efforts: both must be listed.
            ("gpt-5.6-terra", frozenset({"low", "xhigh"}), "Effort 'low, xhigh'"),
        ],
    )
    def test_everything_else_is_refused(self, model: str, efforts: frozenset[str], fragment: str) -> None:
        allowed, reason = check_wizard_model_access(model, efforts, DEFAULTS)
        assert allowed is False
        assert reason is not None and fragment in reason

    def test_bedrock_fallback_matches_the_anthropic_name(self) -> None:
        assert check_wizard_model_access("claude-sonnet-4-6", frozenset({"high"}), DEFAULTS, provider="bedrock") == (
            True,
            None,
        )

    def test_empty_allowlist_blocks_everything(self) -> None:
        allowed, _ = check_wizard_model_access("claude-sonnet-4-6", frozenset(), {})
        assert allowed is False


class TestResolveAllowlist:
    async def test_flag_payload_replaces_the_settings_table(self) -> None:
        client = MagicMock()
        client.get_feature_flag_payload.return_value = {"claude-opus-4-8": ["high"]}
        with patch("llm_gateway.flags._get_client", return_value=client):
            assert await resolve_allowlist() == {"claude-opus-4-8": frozenset({"high"})}
            assert await resolve_allowlist() == {"claude-opus-4-8": frozenset({"high"})}
        # Cached: one roundtrip per TTL for the whole gateway, not per request.
        client.get_feature_flag_payload.assert_called_once_with(
            WIZARD_MODEL_ALLOWLIST_FLAG, "llm-gateway", send_feature_flag_events=False
        )

    async def test_empty_payload_blocks_everything(self) -> None:
        client = MagicMock()
        client.get_feature_flag_payload.return_value = {}
        with patch("llm_gateway.flags._get_client", return_value=client):
            assert await resolve_allowlist() == {}

    @pytest.mark.parametrize("mode", ["off", "outage", "no_client", "unusable"])
    async def test_falls_back_to_settings(self, mode: str) -> None:
        client: MagicMock | None = MagicMock()
        assert client is not None
        if mode == "off":
            client.get_feature_flag_payload.return_value = None
        elif mode == "outage":
            client.get_feature_flag_payload.side_effect = RuntimeError("posthog down")
        elif mode == "unusable":
            client.get_feature_flag_payload.return_value = ["claude-sonnet-4-6"]
        else:
            client = None
        with patch("llm_gateway.flags._get_client", return_value=client):
            assert await resolve_allowlist() == DEFAULTS


class TestEnforceProductAccessForWizard:
    def _user(self) -> AuthenticatedUser:
        return AuthenticatedUser(
            user_id=7,
            team_id=1,
            auth_method="oauth_access_token",
            distinct_id="test-distinct-id-7",
            scopes=["llm_gateway:read"],
            application_id=WIZARD_US_APP_ID,
            is_staff=True,
        )

    def _request(self, body: dict, path: str = "/wizard/v1/messages"):
        request = _make_request(body, path=path)
        request.app.state.desktop_access_resolver = MagicMock()
        return request

    async def test_listed_pair_passes(self) -> None:
        request = self._request({"model": "claude-sonnet-4-6", "output_config": {"effort": "high"}, "messages": []})
        user = self._user()
        with patch("llm_gateway.flags._get_client", return_value=None):
            assert await enforce_product_access(request=request, user=user) is user

    async def test_unlisted_model_is_refused_even_for_staff(self) -> None:
        request = self._request({"model": "claude-opus-4-8", "messages": []})
        with patch("llm_gateway.flags._get_client", return_value=None), pytest.raises(HTTPException) as exc_info:
            await enforce_product_access(request=request, user=self._user())
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["error"]["reason"] == "wizard_model_not_allowed"

    async def test_unlisted_effort_is_refused(self) -> None:
        request = self._request(
            {"model": "openai/gpt-5.6-luna", "reasoning_effort": "high", "messages": []},
            path="/wizard/v1/chat/completions",
        )
        with patch("llm_gateway.flags._get_client", return_value=None), pytest.raises(HTTPException) as exc_info:
            await enforce_product_access(request=request, user=self._user())
        assert exc_info.value.status_code == 403
        assert "Effort 'high'" in exc_info.value.detail["error"]["message"]

    async def test_other_products_are_not_gated(self) -> None:
        request = self._request({"model": "claude-opus-4-8", "messages": []}, path="/llm_gateway/v1/messages")
        user = AuthenticatedUser(
            user_id=7, team_id=1, auth_method="personal_api_key", distinct_id="d", scopes=["llm_gateway:read"]
        )
        with patch("llm_gateway.flags._get_client", return_value=None):
            assert await enforce_product_access(request=request, user=user) is user

import re

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.buzzsprout.buzzsprout import (
    BUZZSPROUT_BASE_URL,
    USER_AGENT,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.buzzsprout.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.buzzsprout.source import BuzzsproutSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.buzzsprout import (
    BuzzsproutSourceConfig,
)


def _driver(api_token: str = "test-token", podcast_id: str = "123456") -> SourceDriver:
    return SourceDriver(BuzzsproutSource(), BuzzsproutSourceConfig(api_token=api_token, podcast_id=podcast_id))


class TestBuzzsproutRows:
    def test_podcasts_endpoint_omits_podcast_id(self) -> None:
        # The podcasts endpoint is account-scoped, so the podcast_id must not appear in the path.
        result = _driver().run("podcasts", [ScriptedResponse(json=[{"id": 9}])])

        assert result.rows == [{"id": 9}]
        assert result.urls == [f"{BUZZSPROUT_BASE_URL}/podcasts.json"]
        assert "123456" not in result.urls[0]

    def test_surrounding_whitespace_in_podcast_id_is_stripped(self) -> None:
        result = _driver(podcast_id="  123456  ").run("episodes", [ScriptedResponse(json=[{"id": 1}])])

        assert result.rows == [{"id": 1}]
        assert result.urls == [f"{BUZZSPROUT_BASE_URL}/123456/episodes.json"]

    def test_token_auth_scheme_and_user_agent(self) -> None:
        result = _driver(api_token="abc123").run("episodes", [ScriptedResponse(json=[{"id": 1}])])

        # Buzzsprout's documented auth scheme is a static account token in the Authorization header.
        assert result.requests[0].headers["authorization"] == "Token token=abc123"
        # A non-default User-Agent is mandatory or Buzzsprout may block the request.
        assert result.requests[0].headers["user-agent"] == USER_AGENT

    def test_token_is_redacted_in_tracked_session(self) -> None:
        result = _driver(api_token="secret-token").run("episodes", [ScriptedResponse(json=[{"id": 1}])])

        assert result.session_options[0]["redact_values"] == ("Token token=secret-token",)

    def test_non_list_body_raises_loudly(self) -> None:
        # Every documented endpoint returns a bare array; an object body means the response shape
        # changed (e.g. an error envelope on a 200) — fail loud rather than syncing it as a row.
        result = _driver().run("episodes", [ScriptedResponse(json={"unexpected": "object"})])

        assert isinstance(result.raised, ValueError)
        assert "list response body" in str(result.raised)

    @pytest.mark.parametrize("status", [401, 403])
    def test_auth_errors_raise_http_error_matching_non_retryable_keys(self, status: int) -> None:
        # The HTTPError message must keep the "<status> Client Error: <reason> for url: <host>" shape
        # so `get_non_retryable_errors` keys keep matching credential failures.
        result = _driver().run("episodes", [ScriptedResponse(status=status, json={})])

        assert isinstance(result.raised, requests.HTTPError)
        assert re.search(rf"{status} Client Error: .* for url: https://www\.buzzsprout\.com", str(result.raised))


class TestBuzzsproutSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_source_response_names_match_endpoints(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=[{"id": 1}])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, expected_valid",
        [
            (200, True),
            (401, False),
            (403, False),
            (404, False),
            (500, False),
        ],
    )
    def test_status_mapping(self, status: int, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status))):
            is_valid, _ = validate_credentials("test-token", "123456")

        assert is_valid is expected_valid

    def test_blank_podcast_id_is_invalid_without_request(self) -> None:
        with scripted_network([]) as network:
            is_valid, message = validate_credentials("test-token", "   ")

        assert is_valid is False
        assert message is not None
        assert network.requests_log == []

    def test_network_error_is_invalid(self) -> None:
        with scripted_network(always(ConnectionError("boom"))):
            is_valid, message = validate_credentials("test-token", "123456")

        assert is_valid is False
        assert message is not None
        assert "reach the Buzzsprout API" in message

    def test_probes_episodes_with_podcast_id_and_headers(self) -> None:
        with scripted_network([ScriptedResponse()]) as network:
            validate_credentials("test-token", "123456")

        assert network.requests_log[0].url == f"{BUZZSPROUT_BASE_URL}/123456/episodes.json"
        assert network.requests_log[0].headers["authorization"] == "Token token=test-token"
        assert network.requests_log[0].headers["user-agent"] == USER_AGENT

    @pytest.mark.parametrize(
        "status, message_fragment",
        [
            (401, "Invalid Buzzsprout API token"),
            (403, "Invalid Buzzsprout API token"),
            (404, "podcast not found"),
        ],
    )
    def test_credential_error_messages(self, status: int, message_fragment: str) -> None:
        with scripted_network([ScriptedResponse(status=status)]):
            is_valid, message = validate_credentials("test-token", "123456")

        assert is_valid is False
        assert message_fragment in (message or "")

    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_transient_status_is_distinguished_from_invalid_credentials(self, status: int) -> None:
        # A 429/5xx (after the session's own retries) is a temporary outage, not a credential problem,
        # so the message must steer the user to retry rather than recreate their token.
        with scripted_network(always(ScriptedResponse(status=status))):
            is_valid, message = validate_credentials("test-token", "123456")

        assert is_valid is False
        assert "temporarily unavailable" in (message or "")

    def test_unexpected_status_is_reported(self) -> None:
        with scripted_network([ScriptedResponse(status=418)]):
            is_valid, message = validate_credentials("test-token", "123456")

        assert is_valid is False
        assert "unexpected status code: 418" in (message or "")

    def test_token_is_redacted_in_tracked_session(self) -> None:
        with scripted_network([ScriptedResponse()]) as network:
            validate_credentials("secret-token", "123456")

        assert network.session_options[0]["redact_values"] == ("secret-token",)

import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.buzzsprout.buzzsprout import (
    BUZZSPROUT_BASE_URL,
    USER_AGENT,
    BuzzsproutDownloadsCursor,
    BuzzsproutResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.buzzsprout.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.buzzsprout.source import BuzzsproutSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.cursor import SourceCursorManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
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


def _yesterday() -> date:
    return datetime.now(UTC).date() - timedelta(days=1)


def _downloads_script(first_published_at: str) -> Callable[[RecordedRequest], ScriptedResponse]:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path.endswith("/episodes.json"):
            return ScriptedResponse(
                json=[{"id": 1, "published_at": first_published_at}, {"id": 2, "published_at": None}]
            )
        return ScriptedResponse(json=[{"episode_id": 1, "total": int((request.param("date") or "")[-2:])}])

    return respond


class TestBuzzsproutDownloads:
    def test_full_refresh_walks_each_day_from_first_episode_to_yesterday(self) -> None:
        yesterday = _yesterday()
        first_day = yesterday - timedelta(days=2)
        # The offset keeps the podcast-local publish day, rather than shifting it to UTC.
        result = _driver().run("downloads", _downloads_script(f"{first_day.isoformat()}T23:30:00.000-04:00"))

        days = [(first_day + timedelta(days=offset)).isoformat() for offset in range(3)]
        assert result.raised is None
        assert result.paths == ["/api/123456/episodes.json"] + ["/api/123456/downloads.json"] * 3
        assert result.params("date") == [None, *days]
        assert result.rows == [{"episode_id": 1, "total": int(day[-2:]), "date": day} for day in days]

    @pytest.mark.parametrize(
        "watermark_days_ago, cursor_days_ago, lookback_days, first_read_days_ago",
        [
            pytest.param(2, None, 0, 2, id="watermark_only"),
            # A quiet podcast has an old watermark, so the stored cursor decides where to start.
            pytest.param(30, 1, 0, 1, id="cursor_ahead_of_watermark"),
            pytest.param(30, 1, 1, 2, id="lookback_moves_the_cursor_back"),
        ],
    )
    def test_incremental_start_day(
        self,
        watermark_days_ago: int,
        cursor_days_ago: int | None,
        lookback_days: int,
        first_read_days_ago: int,
    ) -> None:
        yesterday = _yesterday()
        stored = (
            BuzzsproutDownloadsCursor(next_date=(yesterday - timedelta(days=cursor_days_ago)).isoformat())
            if cursor_days_ago is not None
            else None
        )
        cursor = SourceCursorManager(BuzzsproutDownloadsCursor, stored, BuzzsproutSource())
        watermark = yesterday - timedelta(days=watermark_days_ago)
        result = _driver().run(
            "downloads",
            _downloads_script("2019-01-01T00:00:00Z"),
            incremental_field="date",
            db_incremental_field_last_value=watermark.isoformat(),
            db_incremental_field_last_value_before_lookback=(watermark + timedelta(days=lookback_days)).isoformat(),
            source_cursor=cursor,
        )

        assert result.raised is None
        assert result.params("date") == [
            (yesterday - timedelta(days=offset)).isoformat() for offset in range(first_read_days_ago, -1, -1)
        ]
        assert cursor.staged == BuzzsproutDownloadsCursor(next_date=yesterday.isoformat())

    def test_non_list_episodes_body_fails_before_choosing_the_start_day(self) -> None:
        result = _driver().run("downloads", [ScriptedResponse(json={"unexpected": "object"})])

        assert isinstance(result.raised, ValueError)
        assert result.paths == ["/api/123456/episodes.json"]

    def test_resumes_from_saved_day(self) -> None:
        yesterday = _yesterday()
        result = _driver().run(
            "downloads",
            _downloads_script("2019-01-01T00:00:00Z"),
            resume_state=BuzzsproutResumeConfig(day_state={"date": yesterday.isoformat()}),
        )

        assert result.raised is None
        assert result.params("date") == [yesterday.isoformat()]


class TestBuzzsproutSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_source_response_names_match_endpoints(self, endpoint: str) -> None:
        result = _driver().run(endpoint, always(ScriptedResponse(json=[{"id": 1}])))

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, expected_valid",
        [
            (404, False),
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

    def test_probes_episodes_with_podcast_id_and_headers(self) -> None:
        with scripted_network([ScriptedResponse()]) as network:
            validate_credentials("test-token", "123456")

        assert network.requests_log[0].url == f"{BUZZSPROUT_BASE_URL}/123456/episodes.json"
        assert network.requests_log[0].headers["authorization"] == "Token token=test-token"
        assert network.requests_log[0].headers["user-agent"] == USER_AGENT

    @pytest.mark.parametrize(
        "status, message_fragment",
        [
            (404, "podcast not found"),
        ],
    )
    def test_credential_error_messages(self, status: int, message_fragment: str) -> None:
        with scripted_network([ScriptedResponse(status=status)]):
            is_valid, message = validate_credentials("test-token", "123456")

        assert is_valid is False
        assert message_fragment in (message or "")

    @pytest.mark.parametrize("status", [429, 503])
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

import json
from typing import Any, Optional

import pytest
from unittest import mock

import requests
import tenacity
import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.buzzsprout.buzzsprout import (
    BUZZSPROUT_BASE_URL,
    USER_AGENT,
    BuzzsproutRetryableError,
    _build_url,
    _fetch,
    _get_headers,
    buzzsprout_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.buzzsprout.settings import (
    BUZZSPROUT_ENDPOINTS,
    ENDPOINTS,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.buzzsprout.buzzsprout"


def _response(status: int = 200, body: Optional[Any] = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status
    resp.ok = 200 <= status < 300
    resp.json.return_value = body if body is not None else []
    resp.text = json.dumps(body if body is not None else [])
    if not resp.ok:
        reason = "Unauthorized" if status == 401 else "Forbidden" if status == 403 else "Error"
        resp.raise_for_status.side_effect = requests.HTTPError(
            f"{status} Client Error: {reason} for url: {BUZZSPROUT_BASE_URL}/123456/episodes.json",
            response=requests.Response(),
        )
    return resp


class TestGetHeaders:
    def test_token_and_user_agent(self):
        headers = _get_headers("abc123")

        # Buzzsprout's documented auth scheme is a static account token in the Authorization header.
        assert headers["Authorization"] == "Token token=abc123"
        # A non-default User-Agent is mandatory or Buzzsprout may block the request.
        assert headers["User-Agent"] == USER_AGENT


class TestBuildUrl:
    def test_podcast_scoped_includes_id(self):
        url = _build_url("123456", BUZZSPROUT_ENDPOINTS["episodes"])

        assert url == f"{BUZZSPROUT_BASE_URL}/123456/episodes.json"

    def test_account_scoped_omits_id(self):
        # The podcasts endpoint is account-scoped, so the podcast_id must not appear in the path.
        url = _build_url("123456", BUZZSPROUT_ENDPOINTS["podcasts"])

        assert url == f"{BUZZSPROUT_BASE_URL}/podcasts.json"
        assert "123456" not in url

    def test_surrounding_whitespace_is_stripped(self):
        url = _build_url("  123456  ", BUZZSPROUT_ENDPOINTS["episodes"])

        assert url == f"{BUZZSPROUT_BASE_URL}/123456/episodes.json"


# tenacity exposes the undecorated function via `__wrapped__`, so status classification can be
# asserted without waiting through retry backoff.
_fetch_once = _fetch.__wrapped__  # type: ignore[attr-defined]


class TestFetch:
    def test_ok_returns_array(self):
        session = mock.MagicMock()
        session.get.return_value = _response(200, [{"id": 1}, {"id": 2}])

        assert _fetch_once(session, "https://example.com", {}, structlog.get_logger()) == [{"id": 1}, {"id": 2}]

    def test_non_list_body_returns_empty(self):
        # Every documented endpoint returns a bare array; defend against an unexpected object body.
        session = mock.MagicMock()
        session.get.return_value = _response(200, {"unexpected": "object"})

        assert _fetch_once(session, "https://example.com", {}, structlog.get_logger()) == []

    @pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
    def test_retryable_statuses_raise_retryable(self, status):
        session = mock.MagicMock()
        session.get.return_value = _response(status)

        with pytest.raises(BuzzsproutRetryableError):
            _fetch_once(session, "https://example.com", {}, structlog.get_logger())

    @pytest.mark.parametrize("status", [400, 401, 403, 404])
    def test_client_errors_raise_for_status(self, status):
        session = mock.MagicMock()
        session.get.return_value = _response(status)

        with pytest.raises(requests.HTTPError):
            _fetch_once(session, "https://example.com", {}, structlog.get_logger())

    def test_retries_transient_status_then_succeeds(self):
        # Drive the real tenacity decorator (not `__wrapped__`) with no backoff to confirm a transient
        # error is retried rather than re-raised on the first attempt.
        fast_fetch = tenacity.retry(
            retry=tenacity.retry_if_exception_type(
                (BuzzsproutRetryableError, requests.ReadTimeout, requests.ConnectionError)
            ),
            stop=tenacity.stop_after_attempt(5),
            wait=tenacity.wait_none(),
            reraise=True,
        )(_fetch_once)

        session = mock.MagicMock()
        session.get.side_effect = [_response(500), _response(200, [{"id": 1}])]

        result = fast_fetch(session, "https://example.com", {}, structlog.get_logger())

        assert result == [{"id": 1}]
        assert session.get.call_count == 2


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
    def test_status_mapping(self, status, expected_valid):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(status)

            is_valid, _ = validate_credentials("test-token", "123456")

        assert is_valid is expected_valid

    def test_blank_podcast_id_is_invalid_without_request(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            is_valid, message = validate_credentials("test-token", "   ")

        assert is_valid is False
        assert message is not None
        mock_session.return_value.get.assert_not_called()

    def test_network_error_is_invalid(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = Exception("boom")

            is_valid, message = validate_credentials("test-token", "123456")

        assert is_valid is False
        assert message is not None

    def test_probes_episodes_with_podcast_id_and_headers(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(200)

            validate_credentials("test-token", "123456")

            call = mock_session.return_value.get.call_args

        assert call.args[0] == f"{BUZZSPROUT_BASE_URL}/123456/episodes.json"
        assert call.kwargs["headers"]["Authorization"] == "Token token=test-token"

    def test_surrounding_whitespace_in_podcast_id_is_stripped(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(200)

            validate_credentials("test-token", "  123456  ")

            call = mock_session.return_value.get.call_args

        assert call.args[0] == f"{BUZZSPROUT_BASE_URL}/123456/episodes.json"

    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_transient_status_is_distinguished_from_invalid_credentials(self, status):
        # A 429/5xx (after the session's own retries) is a temporary outage, not a credential problem,
        # so the message must steer the user to retry rather than recreate their token.
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(status)

            is_valid, message = validate_credentials("test-token", "123456")

        assert is_valid is False
        assert message is not None
        assert "temporarily unavailable" in message

    def test_token_is_redacted_in_tracked_session(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(200)

            validate_credentials("secret-token", "123456")

        assert mock_session.call_args.kwargs["redact_values"] == ("secret-token",)


class TestGetRows:
    def test_yields_single_batch_with_full_array(self):
        # Buzzsprout has no pagination, so a single fetch returns the whole table in one batch.
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(200, [{"id": 1}, {"id": 2}])

            batches = list(get_rows("test-token", "123456", "episodes", structlog.get_logger()))

            called_url = mock_session.return_value.get.call_args.args[0]

        assert batches == [[{"id": 1}, {"id": 2}]]
        assert called_url == f"{BUZZSPROUT_BASE_URL}/123456/episodes.json"

    def test_skips_empty_response(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(200, [])

            batches = list(get_rows("test-token", "123456", "episodes", structlog.get_logger()))

        assert batches == []

    def test_podcasts_endpoint_omits_podcast_id(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(200, [{"id": 9}])

            list(get_rows("test-token", "123456", "podcasts", structlog.get_logger()))

            called_url = mock_session.return_value.get.call_args.args[0]

        assert called_url == f"{BUZZSPROUT_BASE_URL}/podcasts.json"

    def test_token_is_redacted_in_tracked_session(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(200, [{"id": 1}])

            list(get_rows("secret-token", "123456", "episodes", structlog.get_logger()))

        assert mock_session.call_args.kwargs["redact_values"] == ("secret-token",)


class TestBuzzsproutSource:
    def test_episodes_partitions_on_stable_published_at(self):
        response = buzzsprout_source("test-token", "123456", "episodes", structlog.get_logger())

        assert response.name == "episodes"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["published_at"]
        assert response.sort_mode == "asc"

    def test_podcasts_is_unpartitioned(self):
        # Podcasts carry no stable datetime field, so no datetime partitioning is applied.
        response = buzzsprout_source("test-token", "123456", "podcasts", structlog.get_logger())

        assert response.name == "podcasts"
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        assert response.partition_keys is None

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_source_response_names_match_endpoints(self, endpoint):
        response = buzzsprout_source("test-token", "123456", endpoint, structlog.get_logger())

        assert response.name == endpoint

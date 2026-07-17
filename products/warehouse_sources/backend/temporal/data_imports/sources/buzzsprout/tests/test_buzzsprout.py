import json
from typing import Any

import pytest
from unittest import mock

import requests
from requests import PreparedRequest, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.buzzsprout.buzzsprout import (
    BUZZSPROUT_BASE_URL,
    USER_AGENT,
    buzzsprout_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.buzzsprout.settings import ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the buzzsprout module.
BUZZSPROUT_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.buzzsprout.buzzsprout.make_tracked_session"
)


def _response(body: Any, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    resp.url = f"{BUZZSPROUT_BASE_URL}/123456/episodes.json"
    resp.reason = {401: "Unauthorized", 403: "Forbidden"}.get(status, "Error" if status >= 400 else "OK")
    return resp


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return snapshots of each request captured AT PREPARE TIME.

    Request state is mutated in place across pages, so inspecting it after the run shows only the
    final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {}), "auth": request.auth})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _applied_auth_headers(auth: Any) -> dict[str, str]:
    prepared = PreparedRequest()
    prepared.prepare(method="GET", url="https://example.com")
    auth(prepared)
    return dict(prepared.headers)


class TestBuzzsproutRows:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_request_yields_full_array(self, MockSession) -> None:
        # Buzzsprout has no pagination, so a single fetch returns the whole table.
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": 1}, {"id": 2}])])

        rows = _rows(buzzsprout_source("test-token", "123456", "episodes", team_id=1, job_id="j"))

        assert rows == [{"id": 1}, {"id": 2}]
        assert session.send.call_count == 1
        assert snapshots[0]["url"] == f"{BUZZSPROUT_BASE_URL}/123456/episodes.json"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_response_yields_no_rows(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        assert _rows(buzzsprout_source("test-token", "123456", "episodes", team_id=1, job_id="j")) == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_podcasts_endpoint_omits_podcast_id(self, MockSession) -> None:
        # The podcasts endpoint is account-scoped, so the podcast_id must not appear in the path.
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": 9}])])

        _rows(buzzsprout_source("test-token", "123456", "podcasts", team_id=1, job_id="j"))

        assert snapshots[0]["url"] == f"{BUZZSPROUT_BASE_URL}/podcasts.json"
        assert "123456" not in snapshots[0]["url"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_surrounding_whitespace_in_podcast_id_is_stripped(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": 1}])])

        _rows(buzzsprout_source("test-token", "  123456  ", "episodes", team_id=1, job_id="j"))

        assert snapshots[0]["url"] == f"{BUZZSPROUT_BASE_URL}/123456/episodes.json"

    @pytest.mark.parametrize(
        "podcast_id",
        [
            "https://attacker.example/../../../123456",
            "http://attacker.example/123456",
            "123456/../../evil",
            "123456?x=1",
            "foo#bar",
            "foo\\bar",
        ],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retargeting_podcast_id_is_rejected_without_request(self, MockSession, podcast_id) -> None:
        # `podcast_id` is a non-secret editable field that becomes a REST path segment; a value that
        # could resolve to another origin must be rejected before any authenticated request is sent.
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}])])

        with pytest.raises(ValueError, match="Invalid Buzzsprout podcast ID"):
            _rows(buzzsprout_source("test-token", podcast_id, "episodes", team_id=1, job_id="j"))

        session.send.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_token_auth_scheme_and_user_agent(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": 1}])])

        _rows(buzzsprout_source("abc123", "123456", "episodes", team_id=1, job_id="j"))

        # Buzzsprout's documented auth scheme is a static account token in the Authorization header.
        assert _applied_auth_headers(snapshots[0]["auth"])["Authorization"] == "Token token=abc123"
        # A non-default User-Agent is mandatory or Buzzsprout may block the request.
        assert session.headers.get("User-Agent") == USER_AGENT

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_token_is_redacted_in_tracked_session(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}])])

        _rows(buzzsprout_source("secret-token", "123456", "episodes", team_id=1, job_id="j"))

        assert MockSession.call_args.kwargs["redact_values"] == ("Token token=secret-token",)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_body_raises_loudly(self, MockSession) -> None:
        # Every documented endpoint returns a bare array; an object body means the response shape
        # changed (e.g. an error envelope on a 200) — fail loud rather than syncing it as a row.
        session = MockSession.return_value
        _wire(session, [_response({"unexpected": "object"})])

        with pytest.raises(ValueError, match="list response body"):
            _rows(buzzsprout_source("test-token", "123456", "episodes", team_id=1, job_id="j"))

    @pytest.mark.parametrize("status", [401, 403])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_auth_errors_raise_http_error_matching_non_retryable_keys(self, MockSession, status) -> None:
        # The HTTPError message must keep the "<status> Client Error: <reason> for url: <host>" shape
        # so `get_non_retryable_errors` keys keep matching credential failures.
        session = MockSession.return_value
        _wire(session, [_response({}, status=status)])

        with pytest.raises(requests.HTTPError, match=f"{status} Client Error: .* for url: https://www.buzzsprout.com"):
            _rows(buzzsprout_source("test-token", "123456", "episodes", team_id=1, job_id="j"))


class TestBuzzsproutSourceResponse:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_episodes_partitions_on_stable_published_at(self, MockSession) -> None:
        response = buzzsprout_source("test-token", "123456", "episodes", team_id=1, job_id="j")

        assert response.name == "episodes"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"
        assert response.partition_keys == ["published_at"]
        assert response.sort_mode == "asc"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_podcasts_is_unpartitioned(self, MockSession) -> None:
        # Podcasts carry no stable datetime field, so no datetime partitioning is applied.
        response = buzzsprout_source("test-token", "123456", "podcasts", team_id=1, job_id="j")

        assert response.name == "podcasts"
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        assert response.partition_keys is None

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_names_match_endpoints(self, MockSession, endpoint) -> None:
        response = buzzsprout_source("test-token", "123456", endpoint, team_id=1, job_id="j")

        assert response.name == endpoint


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
    def test_status_mapping(self, status, expected_valid) -> None:
        with mock.patch(BUZZSPROUT_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)

            is_valid, _ = validate_credentials("test-token", "123456")

        assert is_valid is expected_valid

    def test_blank_podcast_id_is_invalid_without_request(self) -> None:
        with mock.patch(BUZZSPROUT_SESSION_PATCH) as mock_session:
            is_valid, message = validate_credentials("test-token", "   ")

        assert is_valid is False
        assert message is not None
        mock_session.return_value.get.assert_not_called()

    @pytest.mark.parametrize(
        "podcast_id",
        [
            "https://attacker.example/../../../123456",
            "123456/../../evil",
            "123456?x=1",
            "foo#bar",
        ],
    )
    def test_retargeting_podcast_id_is_invalid_without_request(self, podcast_id) -> None:
        # Validation must reject a retargeting podcast_id the same way the sync does, so the probe
        # and the sync can never disagree on the request destination.
        with mock.patch(BUZZSPROUT_SESSION_PATCH) as mock_session:
            is_valid, message = validate_credentials("test-token", podcast_id)

        assert is_valid is False
        assert message is not None
        mock_session.return_value.get.assert_not_called()

    def test_network_error_is_invalid(self) -> None:
        with mock.patch(BUZZSPROUT_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.side_effect = Exception("boom")

            is_valid, message = validate_credentials("test-token", "123456")

        assert is_valid is False
        assert message is not None
        assert "reach the Buzzsprout API" in message

    def test_probes_episodes_with_podcast_id_and_headers(self) -> None:
        with mock.patch(BUZZSPROUT_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)

            validate_credentials("test-token", "123456")

            call = mock_session.return_value.get.call_args

        assert call.args[0] == f"{BUZZSPROUT_BASE_URL}/123456/episodes.json"
        assert call.kwargs["headers"]["Authorization"] == "Token token=test-token"
        assert call.kwargs["headers"]["User-Agent"] == USER_AGENT

    def test_surrounding_whitespace_in_podcast_id_is_stripped(self) -> None:
        with mock.patch(BUZZSPROUT_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)

            validate_credentials("test-token", "  123456  ")

            call = mock_session.return_value.get.call_args

        assert call.args[0] == f"{BUZZSPROUT_BASE_URL}/123456/episodes.json"

    @pytest.mark.parametrize(
        "status, message_fragment",
        [
            (401, "Invalid Buzzsprout API token"),
            (403, "Invalid Buzzsprout API token"),
            (404, "podcast not found"),
        ],
    )
    def test_credential_error_messages(self, status: int, message_fragment: str) -> None:
        with mock.patch(BUZZSPROUT_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)

            is_valid, message = validate_credentials("test-token", "123456")

        assert is_valid is False
        assert message_fragment in (message or "")

    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_transient_status_is_distinguished_from_invalid_credentials(self, status) -> None:
        # A 429/5xx (after the session's own retries) is a temporary outage, not a credential problem,
        # so the message must steer the user to retry rather than recreate their token.
        with mock.patch(BUZZSPROUT_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)

            is_valid, message = validate_credentials("test-token", "123456")

        assert is_valid is False
        assert "temporarily unavailable" in (message or "")

    def test_unexpected_status_is_reported(self) -> None:
        with mock.patch(BUZZSPROUT_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.return_value = mock.MagicMock(status_code=418)

            is_valid, message = validate_credentials("test-token", "123456")

        assert is_valid is False
        assert "unexpected status code: 418" in (message or "")

    def test_token_is_redacted_in_tracked_session(self) -> None:
        with mock.patch(BUZZSPROUT_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)

            validate_credentials("secret-token", "123456")

        assert mock_session.call_args.kwargs["redact_values"] == ("secret-token",)

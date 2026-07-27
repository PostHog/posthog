import json
from typing import Any
from urllib.parse import urlparse

import pytest
from unittest import mock

from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    DEFAULT_RETRY_ATTEMPTS,
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.eventee.eventee import (
    EVENTEE_BASE_URL,
    eventee_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.eventee.settings import (
    ENDPOINTS,
    EVENTEE_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the eventee module.
EVENTEE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.eventee.eventee.make_tracked_session"
)


def _response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp.reason = "OK" if status_code == 200 else "Error"
    resp.url = f"{EVENTEE_BASE_URL}/content"
    resp._content = json.dumps(body).encode()
    return resp


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[str]:
    """Wire a mock session and capture each request's URL AT SEND TIME (prepare_request is mocked, so
    the real prepared URL isn't built — snapshot ``request.url`` when the request is prepared)."""
    session.headers = {}
    url_snapshots: list[str] = []

    def _prepare(request: Any) -> mock.MagicMock:
        url_snapshots.append(request.url)
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return url_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestRowExtraction:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_content_subresource_extracted_by_data_key(self, MockSession) -> None:
        # /content bundles several lists; the `halls` table reads its rows from the `halls` key and
        # must not pick up rows from sibling keys.
        session = MockSession.return_value
        content = {"halls": [{"id": 1, "name": "Main"}], "lectures": [{"id": 99, "name": "Keynote"}]}
        urls = _wire(session, [_response(content)])

        rows = _rows(eventee_source("tok", "halls", team_id=1, job_id="j"))

        assert rows == [{"id": 1, "name": "Main"}]
        assert urlparse(urls[0]).path == "/public/v1/content"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_standalone_array_endpoint(self, MockSession) -> None:
        session = MockSession.return_value
        urls = _wire(session, [_response([{"id": 7}, {"id": 8}])])

        rows = _rows(eventee_source("tok", "groups", team_id=1, job_id="j"))

        assert rows == [{"id": 7}, {"id": 8}]
        assert urlparse(urls[0]).path == "/public/v1/groups"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_object_response_wrapped_in_list(self, MockSession) -> None:
        # /registrations can return a bare object rather than an array.
        session = MockSession.return_value
        _wire(session, [_response({"id": 420, "email": "a@b.com"})])

        rows = _rows(eventee_source("tok", "registrations", team_id=1, job_id="j"))

        assert rows == [{"id": 420, "email": "a@b.com"}]

    @pytest.mark.parametrize(
        "endpoint, body",
        [
            ("halls", {"halls": []}),
            ("halls", {"lectures": [{"id": 1}]}),  # data_key missing entirely
            ("groups", []),
            ("groups", None),
        ],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_or_missing_data_yields_no_rows(self, MockSession, endpoint, body) -> None:
        session = MockSession.return_value
        _wire(session, [_response(body)])

        assert _rows(eventee_source("tok", endpoint, team_id=1, job_id="j")) == []


class TestRetries:
    @mock.patch("time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retries_retryable_status_then_succeeds(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_response({}, 500), _response({}, 429), _response([{"id": 1}])])

        rows = _rows(eventee_source("tok", "groups", team_id=1, job_id="j"))

        assert rows == [{"id": 1}]
        assert session.send.call_count == 3

    @mock.patch("time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retries_exhausted_raises(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        session.headers = {}
        session.prepare_request.return_value = mock.MagicMock()
        session.send.return_value = _response({}, 503)

        with pytest.raises(RESTClientRetryableError):
            _rows(eventee_source("tok", "groups", team_id=1, job_id="j"))

        assert session.send.call_count == DEFAULT_RETRY_ATTEMPTS

    @mock.patch("time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_raises_for_status_without_retry(self, MockSession, _sleep) -> None:
        # A 401 is not retryable — it must propagate via raise_for_status so the source can mark it
        # non-retryable rather than burning retries on a bad token.
        session = MockSession.return_value
        session.headers = {}
        session.prepare_request.return_value = mock.MagicMock()
        session.send.return_value = _response({"error": "token_invalid"}, 401)

        with pytest.raises(HTTPError):
            _rows(eventee_source("tok", "groups", team_id=1, job_id="j"))

        assert session.send.call_count == 1


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code, expected", [(200, True), (401, False), (403, False), (500, False)])
    @mock.patch(EVENTEE_SESSION_PATCH)
    def test_status_mapping(self, mock_session, status_code, expected) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("tok") is expected

    @mock.patch(EVENTEE_SESSION_PATCH)
    def test_sends_bearer_token(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        validate_credentials("tok")

        headers = mock_session.return_value.get.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer tok"

    @mock.patch(EVENTEE_SESSION_PATCH)
    def test_swallows_exceptions(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("tok") is False


class TestEventeeSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint) -> None:
        config = EVENTEE_ENDPOINTS[endpoint]
        response = eventee_source("tok", endpoint, team_id=1, job_id="j")

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"

        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "month"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_partition_keys_are_stable_creation_fields(self, endpoint) -> None:
        # Partitioning on a mutable field (updated_at / checked_at) rewrites partitions every sync.
        config = EVENTEE_ENDPOINTS[endpoint]
        if config.partition_key:
            assert config.partition_key in ("created_at", "registered_at")

    def test_base_url_is_fixed(self) -> None:
        assert EVENTEE_BASE_URL == "https://api.eventee.com/public/v1"

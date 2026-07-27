import json
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.cohere.cohere import (
    cohere_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cohere.settings import COHERE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the cohere module.
COHERE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.cohere.cohere.make_tracked_session"
)


def _response(
    data_key: str | None, items: list[dict[str, Any]] | None, extra: dict[str, Any] | None = None
) -> Response:
    body: dict[str, Any] = dict(extra or {})
    if data_key is not None:
        body[data_key] = items or []
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _error_response(status_code: int) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = b"{}"
    return resp


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list that captures each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when each
    request is prepared instead of inspecting the final state after the run.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestOffsetPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_and_progresses(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [{"id": f"d_{i}"} for i in range(100)]
        params = _wire(session, [_response("datasets", full_page), _response("datasets", [{"id": "d_last"}])])

        rows = _rows(cohere_source("key", "datasets", team_id=1, job_id="j"))

        assert [r["id"] for r in rows] == [*(f"d_{i}" for i in range(100)), "d_last"]
        assert params[0]["offset"] == 0
        assert params[0]["limit"] == 100
        # A full page advances the offset; the short second page ends pagination without a third request.
        assert params[1]["offset"] == 100
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_first_page_makes_one_request(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response("datasets", [{"id": "a"}, {"id": "b"}])])

        rows = _rows(cohere_source("key", "datasets", team_id=1, job_id="j"))

        assert [r["id"] for r in rows] == ["a", "b"]
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response("datasets", [])])

        assert _rows(cohere_source("key", "datasets", team_id=1, job_id="j")) == []
        assert session.send.call_count == 1


class TestPageTokenPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_next_page_token(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response("finetuned_models", [{"id": "a"}], extra={"next_page_token": "t2"}),
                _response("finetuned_models", [{"id": "b"}]),
            ],
        )

        rows = _rows(cohere_source("key", "finetuned_models", team_id=1, job_id="j"))

        assert [r["id"] for r in rows] == ["a", "b"]
        # First request carries the page size but no token; the second carries the token from the
        # first response. Absence of a token in the second response ends pagination.
        assert params[0]["page_size"] == 100
        assert "page_token" not in params[0]
        assert params[1]["page_token"] == "t2"
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_models_uses_large_page_size(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response("models", [{"name": "command"}])])

        rows = _rows(cohere_source("key", "models", team_id=1, job_id="j"))

        assert [r["name"] for r in rows] == ["command"]
        # /models caps page_size at 1000.
        assert params[0]["page_size"] == 1000


class TestSinglePage:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unpaginated_endpoint_makes_single_request(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response("embed_jobs", [{"job_id": "j1"}, {"job_id": "j2"}])])

        rows = _rows(cohere_source("key", "embed_jobs", team_id=1, job_id="j"))

        assert [r["job_id"] for r in rows] == ["j1", "j2"]
        assert session.send.call_count == 1


class TestFailLoud:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_envelope_key_raises_instead_of_emptying(self, MockSession) -> None:
        session = MockSession.return_value
        # A 200 body whose shape lacks the envelope key must fail loud, not be treated as an empty
        # page that clears the full-refresh table.
        _wire(session, [_response("unexpected", [])])

        with pytest.raises(ValueError, match="matched nothing"):
            _rows(cohere_source("key", "datasets", team_id=1, job_id="j"))


class TestRetry:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_is_retried_then_succeeds(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_error_response(429), _response("datasets", [{"id": "a"}])])

        with mock.patch.object(RESTClient._send_request.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            rows = _rows(cohere_source("key", "datasets", team_id=1, job_id="j"))

        assert [r["id"] for r in rows] == ["a"]
        assert session.send.call_count == 2


class TestSourceResponseShape:
    @pytest.mark.parametrize("endpoint", list(COHERE_ENDPOINTS))
    def test_source_response_shape(self, endpoint: str) -> None:
        config = COHERE_ENDPOINTS[endpoint]
        response = cohere_source(api_key="key", endpoint=endpoint, team_id=1, job_id="j")
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
            assert response.partition_count == 1
            assert response.partition_size == 1
        else:
            # The model catalog has no creation timestamp, so it must stay fully unpartitioned.
            # partition_count/size are left None too: a stray count makes the writer fall back to
            # primary_keys and md5-partition by name.
            assert response.partition_mode is None
            assert response.partition_keys is None
            assert response.partition_count is None
            assert response.partition_size is None

    def test_models_primary_key_is_name_not_id(self) -> None:
        # Model catalog rows are keyed by name; there is no id field to dedupe on.
        assert cohere_source(api_key="key", endpoint="models", team_id=1, job_id="j").primary_keys == ["name"]


class TestValidateCredentials:
    @mock.patch(COHERE_SESSION_PATCH)
    def test_ok(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials("key") is True

    @pytest.mark.parametrize("status_code", [401, 403])
    @mock.patch(COHERE_SESSION_PATCH)
    def test_non_200_is_false(self, mock_session, status_code: int) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("key") is False

    @mock.patch(COHERE_SESSION_PATCH)
    def test_network_error_is_false(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key") is False

    @mock.patch(COHERE_SESSION_PATCH)
    def test_session_redacts_api_key(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("secret-key")
        assert mock_session.call_args.kwargs["redact_values"] == ("secret-key",)

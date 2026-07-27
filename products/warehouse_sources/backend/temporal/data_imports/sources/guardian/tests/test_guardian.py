import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClient,
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.guardian.guardian import (
    GuardianResumeConfig,
    _format_from_date,
    guardian_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the guardian module.
GUARDIAN_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.guardian.guardian.make_tracked_session"
)

DEFAULT_URL = "https://content.guardianapis.com/search?api-key=k&page=1"


def _resp(
    results: list[dict[str, Any]] | None,
    *,
    pages: int | None = 1,
    current_page: int = 1,
    status: int = 200,
    reason: str = "",
    url: str = DEFAULT_URL,
    with_envelope: bool = True,
) -> Response:
    if with_envelope:
        inner: dict[str, Any] = {"status": "ok", "results": results or []}
        # sections/editions omit pagination metadata; content/tags report `pages`/`currentPage`.
        if pages is not None:
            inner["pages"] = pages
            inner["currentPage"] = current_page
        body: dict[str, Any] = {"response": inner}
    else:
        body = {}
    resp = Response()
    resp.status_code = status
    resp.reason = reason
    resp.url = url
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: GuardianResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list capturing each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
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


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return guardian_source(
        api_key=kwargs.pop("api_key", "k"),
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        **kwargs,
    )


class TestFormatFromDate:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04"),
            (date(2026, 3, 4), "2026-03-04"),
            ("2026-03-04T02:58:14Z", "2026-03-04"),
            ("", None),
            (None, None),
        ],
    )
    def test_format_from_date(self, value: Any, expected: str | None) -> None:
        assert _format_from_date(value) == expected


class TestRequestParams:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_content_incremental_sets_from_date_and_oldest_order(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_resp([{"id": "a"}], pages=1)])

        _rows(_source("content", _make_manager(), db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC)))

        assert params[0]["from-date"] == "2026-03-04"
        # Ascending order is what keeps the incremental watermark advancing correctly.
        assert params[0]["order-by"] == "oldest"
        assert params[0]["order-date"] == "published"
        assert params[0]["show-fields"] == "all"
        assert params[0]["page-size"] == 200
        assert params[0]["page"] == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_content_full_refresh_has_no_from_date(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_resp([{"id": "a"}], pages=1)])

        _rows(_source("content", _make_manager(), db_incremental_field_last_value=None))
        assert "from-date" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_incremental_endpoint_never_sets_from_date(self, MockSession) -> None:
        # tags advertises no incremental field, so even an accidental cursor value is ignored.
        session = MockSession.return_value
        params = _wire(session, [_resp([{"id": "a"}], pages=1)])

        _rows(_source("tags", _make_manager(), db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC)))
        assert "from-date" not in params[0]


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_last_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _resp([{"id": "a"}, {"id": "b"}], pages=2, current_page=1),
                _resp([{"id": "c"}], pages=2, current_page=2),
            ],
        )

        rows = _rows(_source("content", _make_manager()))
        assert [r["id"] for r in rows] == ["a", "b", "c"]
        assert params[0]["page"] == 1
        assert params[1]["page"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_next_page_after_yield(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _resp([{"id": "a"}], pages=2, current_page=1),
                _resp([{"id": "b"}], pages=2, current_page=2),
            ],
        )

        manager = _make_manager()
        _rows(_source("content", manager))
        # State is saved once (after page 1 yields), pointing at page 2. The final page saves nothing.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == GuardianResumeConfig(page=2)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_resp([{"id": "c"}], pages=3, current_page=3)])

        manager = _make_manager(GuardianResumeConfig(page=3))
        rows = _rows(_source("content", manager))
        # Resuming at page 3 skips the already-synced earlier pages.
        assert [r["id"] for r in rows] == ["c"]
        assert params[0]["page"] == 3

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_reference_endpoint_makes_one_request_and_no_checkpoint(self, MockSession) -> None:
        # /sections and /editions omit `pages`/`currentPage`; a single page ends the sync.
        session = MockSession.return_value
        _wire(session, [_resp([{"id": "uk"}, {"id": "us"}], pages=None)])

        manager = _make_manager()
        rows = _rows(_source("editions", manager))
        assert [r["id"] for r in rows] == ["uk", "us"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_response_envelope_raises_loudly(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_resp(None, with_envelope=False)])

        # A 200 body without the `response` envelope means the shape changed — fail loud, not 0 rows.
        with pytest.raises(ValueError, match="matched nothing"):
            _rows(_source("content", _make_manager()))


class TestRetries:
    @pytest.mark.parametrize("status_code", [429, 500, 503])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_is_retried_then_reraised(self, MockSession, status_code: int) -> None:
        session = MockSession.return_value
        _wire(session, [_resp([], status=status_code) for _ in range(5)])

        with mock.patch.object(RESTClient._send_request.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(RESTClientRetryableError):
                _rows(_source("content", _make_manager()))
        assert session.send.call_count == 5

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_transient_error_is_retried_then_succeeds(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_resp([], status=500), _resp([{"id": "a"}], pages=1)])

        with mock.patch.object(RESTClient._send_request.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            rows = _rows(_source("content", _make_manager()))
        assert [r["id"] for r in rows] == ["a"]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_auth_failure_raises_without_leaking_api_key(self, MockSession) -> None:
        # The api-key rides in the query string; a non-2xx must not surface it in the exception, but
        # the base host must survive so get_non_retryable_errors() can still match.
        session = MockSession.return_value
        _wire(
            session,
            [
                _resp(
                    [],
                    status=401,
                    reason="Unauthorized",
                    url="https://content.guardianapis.com/search?api-key=super-secret&page=1",
                )
            ],
        )

        with pytest.raises(HTTPError) as exc_info:
            _rows(_source("content", _make_manager(), api_key="super-secret"))
        message = str(exc_info.value)
        assert "super-secret" not in message
        assert "401 Client Error: Unauthorized for url: https://content.guardianapis.com/search" in message


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code,expected", [(200, True), (401, False), (403, False)])
    @mock.patch(GUARDIAN_SESSION_PATCH)
    def test_status_maps_to_bool(self, mock_session, status_code: int, expected: bool) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("some-key") is expected

    @mock.patch(GUARDIAN_SESSION_PATCH)
    def test_network_error_is_false(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("some-key") is False


class TestGuardianSourceResponse:
    def test_content_partitions_on_stable_publication_date(self) -> None:
        response = _source("content", _make_manager())
        assert response.primary_keys == ["id"]
        assert response.partition_keys == ["webPublicationDate"]
        assert response.partition_mode == "datetime"
        assert response.sort_mode == "asc"

    @pytest.mark.parametrize("endpoint", ["tags", "sections", "editions"])
    def test_reference_endpoints_are_unpartitioned(self, endpoint: str) -> None:
        response = _source(endpoint, _make_manager())
        assert response.primary_keys == ["id"]
        assert response.partition_keys is None
        assert response.partition_mode is None
        # Full-refresh endpoints carry no order-by, so their order is unspecified.
        assert response.sort_mode is None

import json
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.freshdesk.freshdesk import (
    FreshdeskResumeConfig,
    _format_updated_since,
    freshdesk_source,
    normalize_subdomain,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the freshdesk module.
FRESHDESK_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.freshdesk.freshdesk.make_tracked_session"
)


def _response(
    body: Any,
    *,
    next_url: Optional[str] = None,
    status_code: int = 200,
) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    if next_url is not None:
        resp.headers["Link"] = f'<{next_url}>; rel="next"'
    return resp


def _make_manager(resume_state: Optional[FreshdeskResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


class _Wired:
    def __init__(self, params: list[dict[str, Any]], urls: list[Optional[str]]) -> None:
        self.params = params
        self.urls = urls


def _wire(session: mock.MagicMock, responses: list[Response]) -> _Wired:
    """Wire a mock session and capture each request's params and URL AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when
    each request is prepared rather than inspecting the final state.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []
    url_snapshots: list[Optional[str]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        url_snapshots.append(request.url)
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return _Wired(param_snapshots, url_snapshots)


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str = "tickets", manager: Optional[mock.MagicMock] = None, **kwargs: Any):
    return freshdesk_source(
        api_key="key",
        subdomain="acme",
        endpoint=endpoint,
        team_id=1,
        job_id="job-1",
        resumable_source_manager=manager if manager is not None else _make_manager(),
        **kwargs,
    )


class TestNormalizeSubdomain:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("acme", "acme"),
            ("acme.freshdesk.com", "acme"),
            ("https://acme.freshdesk.com", "acme"),
            ("http://acme.freshdesk.com/", "acme"),
            ("  acme  ", "acme"),
            ("acme.freshdesk.com/a/tickets", "acme"),
        ],
    )
    def test_normalize_subdomain(self, raw: str, expected: str) -> None:
        assert normalize_subdomain(raw) == expected


class TestFormatUpdatedSince:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            (date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("some-cursor", "some-cursor"),
        ],
    )
    def test_format_updated_since(self, value: Any, expected: str) -> None:
        assert _format_updated_since(value) == expected

    def test_no_offset_suffix(self) -> None:
        assert "+00:00" not in _format_updated_since(datetime(2026, 3, 4, tzinfo=UTC))


class TestRequestParams:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_has_per_page_only(self, MockSession) -> None:
        session = MockSession.return_value
        wired = _wire(session, [_response([{"id": 1}])])

        _rows(_source("companies"))

        assert wired.params[0]["per_page"] == 100
        assert "updated_since" not in wired.params[0]
        assert "_updated_since" not in wired.params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_tickets_incremental_uses_updated_since_and_ordering(self, MockSession) -> None:
        session = MockSession.return_value
        wired = _wire(session, [_response([{"id": 1}])])

        _rows(
            _source(
                "tickets",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            )
        )

        assert wired.params[0]["updated_since"] == "2026-03-04T00:00:00Z"
        assert wired.params[0]["order_by"] == "updated_at"
        assert wired.params[0]["order_type"] == "asc"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_contacts_incremental_uses_underscore_param(self, MockSession) -> None:
        session = MockSession.return_value
        wired = _wire(session, [_response([{"id": 1}])])

        _rows(
            _source(
                "contacts",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            )
        )

        assert wired.params[0]["_updated_since"] == "2026-03-04T00:00:00Z"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_without_last_value_omits_filter(self, MockSession) -> None:
        session = MockSession.return_value
        wired = _wire(session, [_response([{"id": 1}])])

        _rows(_source("tickets", should_use_incremental_field=True, db_incremental_field_last_value=None))

        assert "updated_since" not in wired.params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_endpoint_ignores_incremental_flag(self, MockSession) -> None:
        # `companies` has no server-side filter, so it never gets an updated_since param.
        session = MockSession.return_value
        wired = _wire(session, [_response([{"id": 1}])])

        _rows(
            _source(
                "companies",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            )
        )

        assert "updated_since" not in wired.params[0]


class TestExtraction:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_bare_array_yields_rows(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}, {"id": 2}])])

        rows = _rows(_source("tickets"))

        assert [r["id"] for r in rows] == [1, 2]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_data_key_object_yields_rows(self, MockSession) -> None:
        # `skills` wraps its list under a "skills" key rather than returning a bare array.
        session = MockSession.return_value
        _wire(session, [_response({"skills": [{"id": 7}]})])

        rows = _rows(_source("skills"))

        assert [r["id"] for r in rows] == [7]


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_via_link_header_and_saves_state(self, MockSession) -> None:
        session = MockSession.return_value
        next_url = "https://acme.freshdesk.com/api/v2/tickets?per_page=100&page=2"
        _wire(
            session,
            [
                _response([{"id": 1}], next_url=next_url),
                _response([{"id": 2}]),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("tickets", manager=manager))

        assert [r["id"] for r in rows] == [1, 2]
        # State saved once, after the first (only non-terminal) page.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == FreshdeskResumeConfig(next_url=next_url)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_second_request_targets_the_next_link(self, MockSession) -> None:
        session = MockSession.return_value
        next_url = "https://acme.freshdesk.com/api/v2/tickets?per_page=100&page=2"
        wired = _wire(
            session,
            [
                _response([{"id": 1}], next_url=next_url),
                _response([{"id": 2}]),
            ],
        )

        _rows(_source("tickets"))

        assert wired.urls[1] == next_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_saves_no_state(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}])])

        manager = _make_manager()
        rows = _rows(_source("agents", manager=manager))

        assert [r["id"] for r in rows] == [1]
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state(self, MockSession) -> None:
        session = MockSession.return_value
        resume_url = "https://acme.freshdesk.com/api/v2/tickets?per_page=100&page=5"
        wired = _wire(session, [_response([{"id": 50}])])

        manager = _make_manager(FreshdeskResumeConfig(next_url=resume_url))
        rows = _rows(_source("tickets", manager=manager))

        assert [r["id"] for r in rows] == [50]
        # First request must target the resumed URL, not a freshly-built initial URL.
        assert wired.urls[0] == resume_url

    @pytest.mark.parametrize("status_code", [401, 403, 404])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_retryable_status_raises(self, MockSession, status_code: int) -> None:
        session = MockSession.return_value
        _wire(session, [_response({}, status_code=status_code)])

        with pytest.raises(requests.HTTPError):
            _rows(_source("tickets"))


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code", [200, 401, 403])
    @mock.patch(FRESHDESK_SESSION_PATCH)
    def test_returns_status_code(self, mock_session, status_code: int) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("acme", "key") == status_code

    @mock.patch(FRESHDESK_SESSION_PATCH)
    def test_connection_error_returns_none(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("nope")
        assert validate_credentials("acme", "key") is None

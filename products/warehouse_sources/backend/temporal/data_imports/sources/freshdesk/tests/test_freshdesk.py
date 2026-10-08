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
    def __init__(self, params: list[dict[str, Any]], urls: list[str]) -> None:
        self.params = params
        self.urls = urls


def _wire(session: mock.MagicMock, responses: list[Response]) -> _Wired:
    """Wire a mock session and capture each request's params and URL AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when
    each request is prepared rather than inspecting the final state.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []
    url_snapshots: list[str] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        url_snapshots.append(request.url or "")
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


class TestRequestParams:
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
    @mock.patch(FRESHDESK_SESSION_PATCH)
    def test_connection_error_returns_none(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("nope")
        assert validate_credentials("acme", "key") is None


class TestFanout:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_conversations_incremental_windows_the_parent_walk(self, MockSession) -> None:
        # The child endpoint takes no timestamp filter, so the watermark has to reach the
        # tickets request instead -- otherwise every sync re-walks every ticket.
        session = MockSession.return_value
        wired = _wire(session, [_response([{"id": 10}]), _response([{"id": 100}])])

        _rows(
            _source(
                "conversations",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            )
        )

        assert wired.params[0]["updated_since"] == "2026-03-04T00:00:00Z"
        assert wired.params[0]["order_type"] == "asc"
        # The child request carries no watermark param of its own.
        assert "updated_since" not in wired.params[1]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_canned_responses_fan_out_from_folders(self, MockSession) -> None:
        session = MockSession.return_value
        wired = _wire(session, [_response([{"id": 1}]), _response([{"id": 5, "folder_id": 1}])])

        rows = _rows(_source("canned_responses"))

        assert [r["id"] for r in rows] == [5]
        assert wired.urls[1].endswith("/api/v2/canned_response_folders/1/responses")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_solution_articles_walk_categories_then_folders(self, MockSession) -> None:
        session = MockSession.return_value
        wired = _wire(
            session,
            [
                _response([{"id": 3}]),
                _response([{"id": 4}]),
                _response([{"id": 1, "folder_id": 4, "category_id": 3}]),
            ],
        )

        rows = _rows(_source("solution_articles"))

        assert [r["id"] for r in rows] == [1]
        assert [u.rsplit("/api/v2", 1)[1] for u in wired.urls] == [
            "/solutions/categories",
            "/solutions/categories/3/folders",
            "/solutions/folders/4/articles",
        ]

import json
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.freshservice.freshservice import (
    FreshserviceResumeConfig,
    _format_updated_since,
    freshservice_source,
    normalize_domain,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the freshservice module.
FRESHSERVICE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.freshservice.freshservice.make_tracked_session"
)


def _response(body: Any, *, status: int = 200, next_url: Optional[str] = None) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    resp.url = "https://acme.freshservice.com/api/v2/tickets"
    if next_url:
        # RFC 5988 Link header — requests parses this into Response.links.
        resp.headers["Link"] = f'<{next_url}>; rel="next"'
    return resp


def _make_manager(resume_state: Optional[FreshserviceResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's url + params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so snapshot a copy when each
    request is prepared rather than inspecting the final state.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _run(
    endpoint: str,
    *,
    manager: Optional[mock.MagicMock] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> list[dict[str, Any]]:
    source_response = freshservice_source(
        api_key="key",
        domain="acme",
        endpoint=endpoint,
        team_id=1,
        job_id="job-1",
        resumable_source_manager=manager if manager is not None else _make_manager(),
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
    )
    return [row for page in source_response.items() for row in page]


class TestNormalizeDomain:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("acme", "acme"),
            ("acme.freshservice.com", "acme"),
            ("https://acme.freshservice.com", "acme"),
            ("http://acme.freshservice.com/", "acme"),
            ("  acme  ", "acme"),
            ("acme.freshservice.com/a/tickets", "acme"),
        ],
    )
    def test_normalize_domain(self, raw: str, expected: str) -> None:
        assert normalize_domain(raw) == expected


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
    def test_full_refresh_sends_per_page_only(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"agents": [{"id": 1}]})])

        _run("agents")

        assert snapshots[0]["params"]["per_page"] == 100
        assert "updated_since" not in snapshots[0]["params"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_tickets_incremental_sends_updated_since_and_ordering(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"tickets": [{"id": 1}]})])

        _run(
            "tickets",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )

        params = snapshots[0]["params"]
        assert params["updated_since"] == "2026-03-04T00:00:00Z"
        assert params["order_by"] == "updated_at"
        assert params["order_type"] == "asc"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_without_last_value_omits_filter(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"tickets": [{"id": 1}]})])

        _run("tickets", should_use_incremental_field=True, db_incremental_field_last_value=None)

        assert "updated_since" not in snapshots[0]["params"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_endpoint_ignores_incremental_flag(self, MockSession) -> None:
        # `problems` has no server-side filter, so it never gets an updated_since param even when
        # the pipeline requests incremental.
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"problems": [{"id": 1}]})])

        _run(
            "problems",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )

        assert "updated_since" not in snapshots[0]["params"]


class TestDataSelector:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unwraps_resource_envelope(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"tickets": [{"id": 1}, {"id": 2}]})])

        assert _run("tickets") == [{"id": 1}, {"id": 2}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_software_uses_applications_key(self, MockSession) -> None:
        # The software table maps to /api/v2/applications, which wraps rows under "applications".
        session = MockSession.return_value
        _wire(session, [_response({"applications": [{"id": 7}]})])

        assert _run("software") == [{"id": 7}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_agent_groups_uses_groups_key(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"groups": [{"id": 3}]})])

        assert _run("agent_groups") == [{"id": 3}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_wrong_key_yields_no_rows(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"problems": [{"id": 1}]})])

        assert _run("tickets") == []


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_via_link_header_and_saves_state(self, MockSession) -> None:
        session = MockSession.return_value
        next_url = "https://acme.freshservice.com/api/v2/tickets?per_page=100&page=2"
        snapshots = _wire(
            session,
            [
                _response({"tickets": [{"id": 1}]}, next_url=next_url),
                _response({"tickets": [{"id": 2}]}),
            ],
        )

        manager = _make_manager()
        rows = _run("tickets", manager=manager)

        assert rows == [{"id": 1}, {"id": 2}]
        # Second request follows the Link-header next URL.
        assert snapshots[1]["url"] == next_url
        # State saved once, after the first (only non-terminal) page.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == FreshserviceResumeConfig(next_url=next_url)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_saves_no_state(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"agents": [{"id": 1}]})])

        manager = _make_manager()
        rows = _run("agents", manager=manager)

        assert rows == [{"id": 1}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state(self, MockSession) -> None:
        session = MockSession.return_value
        resume_url = "https://acme.freshservice.com/api/v2/tickets?per_page=100&page=5"
        snapshots = _wire(session, [_response({"tickets": [{"id": 50}]})])

        manager = _make_manager(resume_state=FreshserviceResumeConfig(next_url=resume_url))
        rows = _run("tickets", manager=manager)

        assert rows == [{"id": 50}]
        # First request must hit the resumed URL, not a freshly-built initial URL.
        assert snapshots[0]["url"] == resume_url

    @pytest.mark.parametrize("status_code", [401, 403, 404])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_retryable_status_raises(self, MockSession, status_code: int) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"error": "boom"}, status=status_code)])

        with pytest.raises(requests.HTTPError):
            _run("tickets")


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code", [200, 401, 403])
    @mock.patch(FRESHSERVICE_SESSION_PATCH)
    def test_returns_status_code(self, mock_session, status_code: int) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("acme", "key") == status_code

    @mock.patch(FRESHSERVICE_SESSION_PATCH)
    def test_connection_error_returns_none(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("nope")
        assert validate_credentials("acme", "key") is None

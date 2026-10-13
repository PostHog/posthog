import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, Optional, cast

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.freshservice.freshservice import (
    FreshserviceResumeConfig,
    _format_updated_since,
    freshservice_source,
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
    return [row for page in cast("Iterable[Any]", source_response.items()) for row in page]


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


class TestFanout:
    @pytest.mark.parametrize(
        "endpoint, parent_key, child_key, parent_field, child_path",
        [
            ("software_users", "applications", "application_users", "application_id", "applications/{}/users"),
            (
                "software_installations",
                "applications",
                "installations",
                "application_id",
                "applications/{}/installations",
            ),
            ("ticket_time_entries", "tickets", "time_entries", "ticket_id", "tickets/{}/time_entries"),
            ("ticket_conversations", "tickets", "conversations", "ticket_id", "tickets/{}/conversations"),
            ("ticket_tasks", "tickets", "tasks", "ticket_id", "tickets/{}/tasks"),
            ("problem_tasks", "problems", "tasks", "problem_id", "problems/{}/tasks"),
            ("change_tasks", "changes", "tasks", "change_id", "changes/{}/tasks"),
            ("release_tasks", "releases", "tasks", "release_id", "releases/{}/tasks"),
        ],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_child_requests_and_parent_id_injection(
        self, MockSession, endpoint: str, parent_key: str, child_key: str, parent_field: str, child_path: str
    ) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response({parent_key: [{"id": 7}, {"id": 9}]}),
                _response({child_key: [{"id": 100}]}),
                _response({child_key: [{"id": 100}]}),
            ],
        )

        rows = _run(endpoint)

        assert [s["url"] for s in snapshots[1:]] == [
            f"https://acme.freshservice.com/api/v2/{child_path.format(7)}",
            f"https://acme.freshservice.com/api/v2/{child_path.format(9)}",
        ]
        # The child `id` repeats across parents, so the injected parent id is what makes the
        # composite primary key unique table-wide.
        assert rows == [{"id": 100, parent_field: 7}, {"id": 100, parent_field: 9}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_after_the_parents_already_swept(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response({"applications": [{"id": 7}, {"id": 9}]}),
                _response({"application_users": [{"id": 100}]}),
            ],
        )

        manager = _make_manager(
            resume_state=FreshserviceResumeConfig(completed=["/api/v2/applications/7/users"], current=None)
        )
        rows = _run("software_users", manager=manager)

        assert [s["url"] for s in snapshots[1:]] == ["https://acme.freshservice.com/api/v2/applications/9/users"]
        assert rows == [{"id": 100, "application_id": 9}]


class TestApprovals:
    @staticmethod
    def _slices(snapshots: list[dict[str, Any]]) -> list[tuple[str, str, int]]:
        return [(s["params"]["parent"], s["params"]["status"], s["params"]["page"]) for s in snapshots]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_at_the_saved_slice_and_page(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response({"approvals": [{"id": 5, "parent": "change"}]}),
                _response({"approvals": []}),
                _response({"approvals": []}),
                _response({"approvals": []}),
            ],
        )

        manager = _make_manager(
            resume_state=FreshserviceResumeConfig(
                completed=[
                    "ticket:requested",
                    "ticket:approved",
                    "ticket:rejected",
                    "ticket:cancelled",
                    "change:requested",
                ],
                current="change:approved",
                child_state={"page": 3},
            )
        )
        rows = _run("approvals", manager=manager)

        assert rows == [{"id": 5, "parent": "change"}]
        assert self._slices(snapshots) == [
            ("change", "approved", 3),
            ("change", "approved", 4),
            ("change", "rejected", 1),
            ("change", "cancelled", 1),
        ]


class TestValidateCredentials:
    @mock.patch(FRESHSERVICE_SESSION_PATCH)
    def test_connection_error_returns_none(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("nope")
        assert validate_credentials("acme", "key") is None

from datetime import UTC, date, datetime
from typing import Any

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.freshservice.freshservice import (
    FreshserviceResumeConfig,
    _format_updated_since,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.freshservice.source import FreshserviceSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.freshservice import (
    FreshserviceSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(FreshserviceSource(), FreshserviceSourceConfig(domain="acme", api_key="key"))


def _response(body: dict[str, Any], *, status: int = 200, next_url: str | None = None) -> ScriptedResponse:
    headers = {"Link": f'<{next_url}>; rel="next"'} if next_url else {}
    return ScriptedResponse(status=status, json=body, headers=headers)


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
    def test_tickets_incremental_sends_updated_since_and_ordering(self) -> None:
        result = _driver().run(
            "tickets",
            [_response({"tickets": [{"id": 1}]})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )

        assert result.raised is None
        request = result.requests[0]
        assert request.param("updated_since") == "2026-03-04T00:00:00Z"
        assert request.param("order_by") == "updated_at"
        assert request.param("order_type") == "asc"


class TestPagination:
    def test_paginates_via_link_header_and_saves_state(self) -> None:
        next_url = "https://acme.freshservice.com/api/v2/tickets?per_page=100&page=2"
        result = _driver().run(
            "tickets",
            [
                _response({"tickets": [{"id": 1}]}, next_url=next_url),
                _response({"tickets": [{"id": 2}]}),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"id": 1}, {"id": 2}]
        # Second request follows the Link-header next URL.
        assert result.urls[1] == next_url
        # State saved once, after the first (only non-terminal) page.
        assert result.saved_states == [FreshserviceResumeConfig(next_url=next_url)]

    def test_resumes_from_saved_state(self) -> None:
        resume_url = "https://acme.freshservice.com/api/v2/tickets?per_page=100&page=5"
        result = _driver().run(
            "tickets",
            [_response({"tickets": [{"id": 50}]})],
            resume_state=FreshserviceResumeConfig(next_url=resume_url),
        )

        assert result.raised is None
        assert result.rows == [{"id": 50}]
        # First request must hit the resumed URL, not a freshly-built initial URL.
        assert result.urls[0] == resume_url

    @pytest.mark.parametrize("status_code", [401, 403, 404])
    def test_non_retryable_status_raises(self, status_code: int) -> None:
        result = _driver().run("tickets", [_response({"error": "boom"}, status=status_code)])

        assert isinstance(result.raised, requests.HTTPError)


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
    def test_child_requests_and_parent_id_injection(
        self, endpoint: str, parent_key: str, child_key: str, parent_field: str, child_path: str
    ) -> None:
        result = _driver().run(
            endpoint,
            [
                _response({parent_key: [{"id": 7}, {"id": 9}]}),
                _response({child_key: [{"id": 100}]}),
                _response({child_key: [{"id": 100}]}),
            ],
        )

        assert result.raised is None
        assert [request.origin + request.path for request in result.requests[1:]] == [
            f"https://acme.freshservice.com/api/v2/{child_path.format(7)}",
            f"https://acme.freshservice.com/api/v2/{child_path.format(9)}",
        ]
        # The child `id` repeats across parents, so the injected parent id is what makes the
        # composite primary key unique table-wide.
        assert result.rows == [{"id": 100, parent_field: 7}, {"id": 100, parent_field: 9}]

    def test_resumes_after_the_parents_already_swept(self) -> None:
        result = _driver().run(
            "software_users",
            [
                _response({"applications": [{"id": 7}, {"id": 9}]}),
                _response({"application_users": [{"id": 100}]}),
            ],
            resume_state=FreshserviceResumeConfig(completed=["/api/v2/applications/7/users"], current=None),
        )

        assert result.raised is None
        assert [request.origin + request.path for request in result.requests[1:]] == [
            "https://acme.freshservice.com/api/v2/applications/9/users"
        ]
        assert result.rows == [{"id": 100, "application_id": 9}]


class TestApprovals:
    def test_resumes_at_the_saved_slice_and_page(self) -> None:
        result = _driver().run(
            "approvals",
            [
                _response({"approvals": [{"id": 5, "parent": "change"}]}),
                _response({"approvals": []}),
                _response({"approvals": []}),
                _response({"approvals": []}),
            ],
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
            ),
        )

        assert result.raised is None
        assert result.rows == [{"id": 5, "parent": "change"}]
        assert [
            (request.param("parent"), request.param("status"), request.param("page")) for request in result.requests
        ] == [
            ("change", "approved", "3"),
            ("change", "approved", "4"),
            ("change", "rejected", "1"),
            ("change", "cancelled", "1"),
        ]


class TestValidateCredentials:
    def test_connection_error_returns_none(self) -> None:
        with scripted_network(always(requests.ConnectionError("nope"))) as network:
            status = validate_credentials("acme", "key")

        assert status is None
        assert network.requests_log[0].path == "/api/v2/tickets"

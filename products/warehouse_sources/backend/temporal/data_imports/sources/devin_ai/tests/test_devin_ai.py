import json
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.devin_ai.devin_ai import (
    DevinAIResumeConfig,
    _endpoint_path,
    devin_ai_source,
    get_status_code,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.devin_ai.settings import (
    DEVIN_AI_ENDPOINTS,
    PAGE_SIZE,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# get_status_code builds its own tracked session in the devin_ai module.
DEVIN_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.devin_ai.devin_ai.make_tracked_session"
)


def _response(
    items: list[dict[str, Any]] | None, *, has_next_page: bool = False, end_cursor: str | None = None
) -> Response:
    body: dict[str, Any] = {"has_next_page": has_next_page, "end_cursor": end_cursor}
    if items is not None:
        body["items"] = items
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: DevinAIResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so snapshot a copy when each request
    is prepared rather than inspecting the final state after the run.
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


def _source(endpoint: str, manager: mock.MagicMock):
    return devin_ai_source(
        api_key="cog_test",
        org_id="org-abc",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


class TestEndpointPath:
    @parameterized.expand(
        [
            ("sessions", "/v3/organizations/org-abc/sessions"),
            ("playbooks", "/v3/organizations/org-abc/playbooks"),
            ("knowledge_notes", "/v3/organizations/org-abc/knowledge/notes"),
            ("secrets", "/v3/organizations/org-abc/secrets"),
            ("automations", "/v3/organizations/org-abc/automations"),
            ("session_insights", "/v3/organizations/org-abc/sessions/insights"),
            ("consumption_daily", "/v3/organizations/org-abc/consumption/daily"),
            # Members must stay on the org-scoped users listing: the v2 members endpoint only accepts
            # enterprise-admin personal API keys, which this source never stores.
            ("members", "/v3beta1/organizations/org-abc/members/users"),
        ]
    )
    def test_org_id_is_interpolated_into_path(self, endpoint: str, expected: str) -> None:
        assert _endpoint_path(endpoint, "org-abc") == expected

    @parameterized.expand(
        [
            ("path_traversal", "org-abc/../billing"),
            ("query_injection", "org-abc?first=1"),
            ("slash", "org/abc"),
            ("empty", ""),
            ("whitespace_only", "   "),
        ]
    )
    def test_malicious_org_id_is_rejected(self, _name: str, org_id: str) -> None:
        # A malformed org_id must not be able to inject `/` or `?` to route the stored key elsewhere.
        with pytest.raises(ValueError):
            _endpoint_path("sessions", org_id)


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"session_id": "s3"}])])

        _rows(_source("sessions", _make_manager(DevinAIResumeConfig(after="saved_cursor"))))
        assert params[0] == {"first": PAGE_SIZE, "after": "saved_cursor"}


class TestGetStatusCode:
    @parameterized.expand(
        [
            # A fan-out child's own path needs a parent id, so probing it directly would send a URL
            # with an unbound `{devin_id}` / `{user_id}` placeholder. Each delegates to the org-level
            # endpoint gated by the same permission instead.
            ("session_messages", "https://api.devin.ai/v3/organizations/org-abc/sessions", {"first": 1}),
            (
                "consumption_daily_users",
                "https://api.devin.ai/v3/organizations/org-abc/consumption/daily",
                {},
            ),
        ]
    )
    def test_fanout_child_probes_its_org_level_endpoint(
        self, endpoint: str, expected_url: str, expected_params: dict[str, Any]
    ) -> None:
        response = mock.MagicMock()
        response.status_code = 200
        session = mock.MagicMock()
        session.get.return_value = response

        with mock.patch(DEVIN_SESSION_PATCH, return_value=session):
            get_status_code("cog_test", "org-abc", endpoint)

        args, kwargs = session.get.call_args
        assert args[0] == expected_url
        assert kwargs["params"] == expected_params


class TestDevinAISource:
    @parameterized.expand(["sessions", "session_insights", "playbooks", "knowledge_notes", "secrets", "automations"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_uses_endpoint_primary_keys_and_stable_partition(self, endpoint: str, MockSession) -> None:
        response = _source(endpoint, _make_manager())
        cfg = DEVIN_AI_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == cfg.primary_keys
        # created_at is a stable field — never updated_at — so partitions don't rewrite each sync.
        assert response.partition_keys == ["created_at"]
        assert response.partition_mode == "datetime"

    @parameterized.expand(
        [
            ("session_messages", ["session_id", "event_id"]),
            ("consumption_daily", ["date"]),
            ("consumption_daily_users", ["user_id", "date"]),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fan_out_and_consumption_tables_keep_their_keys_and_partitioning(
        self, endpoint: str, expected_keys: list[str], MockSession
    ) -> None:
        # The fan-out and single-page branches build their SourceResponse separately from the
        # top-level one, so each has to carry the composite key that keeps rows from colliding
        # across parents, and a partition key that doesn't move once written.
        response = _source(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        assert response.partition_mode == "datetime"
        assert response.partition_keys == (["date"] if endpoint.startswith("consumption") else ["created_at"])


class TestMembersJoin:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_members_pagination_follows_cursor_so_later_pages_join(self, MockSession) -> None:
        session = MockSession.return_value
        # A member past the first page must still be synced, or their sessions stop resolving to an email.
        params = _wire(
            session,
            [
                _response(
                    [{"user_id": "email|aaa111", "email": "casey@example.com", "name": None, "role_assignments": []}],
                    has_next_page=True,
                    end_cursor="cur1",
                ),
                _response(
                    [{"user_id": "email|bbb222", "email": "riley@example.com", "name": None, "role_assignments": []}],
                    has_next_page=False,
                    end_cursor=None,
                ),
            ],
        )

        rows = _rows(_source("members", _make_manager()))

        assert params[1] == {"first": PAGE_SIZE, "after": "cur1"}
        email_by_user_id = {row["user_id"]: row["email"] for row in rows}
        assert email_by_user_id["email|bbb222"] == "riley@example.com"

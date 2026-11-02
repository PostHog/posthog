from typing import Any

import pytest

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.devin_ai.devin_ai import (
    DevinAIResumeConfig,
    _endpoint_path,
    get_status_code,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.devin_ai.settings import (
    DEVIN_AI_ENDPOINTS,
    PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.devin_ai.source import DevinAISource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.devinai import (
    DevinAISourceConfig,
)


def _page(
    items: list[dict[str, Any]] | None, *, has_next_page: bool = False, end_cursor: str | None = None
) -> ScriptedResponse:
    body: dict[str, Any] = {"has_next_page": has_next_page, "end_cursor": end_cursor}
    if items is not None:
        body["items"] = items
    return ScriptedResponse(json=body)


def _driver() -> SourceDriver:
    return SourceDriver(DevinAISource(), DevinAISourceConfig(api_key="cog_test", org_id="org-abc"))


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
    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "sessions", [_page([{"session_id": "s3"}])], resume_state=DevinAIResumeConfig(after="saved_cursor")
        )

        assert result.raised is None
        assert result.rows == [{"session_id": "s3"}]
        assert result.requests[0].param("first") == str(PAGE_SIZE)
        assert result.requests[0].param("after") == "saved_cursor"


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
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert get_status_code("cog_test", "org-abc", endpoint) == 200

        assert network.requests_log[0].url.split("?", 1)[0] == expected_url
        assert network.requests_log[0].query == {key: (str(value),) for key, value in expected_params.items()}


class TestDevinAISource:
    @parameterized.expand(["sessions", "session_insights", "playbooks", "knowledge_notes", "secrets", "automations"])
    def test_source_response_uses_endpoint_primary_keys_and_stable_partition(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_page([])])
        assert result.raised is None
        response = result.response
        assert response is not None
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
    def test_fan_out_and_consumption_tables_keep_their_keys_and_partitioning(
        self, endpoint: str, expected_keys: list[str]
    ) -> None:
        # The fan-out and single-page branches build their SourceResponse separately from the
        # top-level one, so each has to carry the composite key that keeps rows from colliding
        # across parents, and a partition key that doesn't move once written.
        answer = ScriptedResponse(json={"consumption_by_date": []}) if endpoint == "consumption_daily" else _page([])
        result = _driver().run(endpoint, [answer])
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        assert response.partition_mode == "datetime"
        assert response.partition_keys == (["date"] if endpoint.startswith("consumption") else ["created_at"])


class TestMembersJoin:
    def test_members_pagination_follows_cursor_so_later_pages_join(self) -> None:
        # A member past the first page must still be synced, or their sessions stop resolving to an email.
        result = _driver().run(
            "members",
            [
                _page(
                    [{"user_id": "email|aaa111", "email": "casey@example.com", "name": None, "role_assignments": []}],
                    has_next_page=True,
                    end_cursor="cur1",
                ),
                _page(
                    [{"user_id": "email|bbb222", "email": "riley@example.com", "name": None, "role_assignments": []}],
                    has_next_page=False,
                    end_cursor=None,
                ),
            ],
        )

        assert result.raised is None
        assert result.requests[1].param("first") == str(PAGE_SIZE)
        assert result.requests[1].param("after") == "cur1"
        email_by_user_id = {row["user_id"]: row["email"] for row in result.rows}
        assert email_by_user_id["email|bbb222"] == "riley@example.com"

import base64
from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine

from django.test import override_settings

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.listmonk import (
    ListmonkSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.listmonk.listmonk import (
    ListmonkResumeConfig,
    normalize_host,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.listmonk.source import ListmonkSource

HOST = "https://listmonk.example.com"
CONFIG = ListmonkSourceConfig(host=HOST, api_user="posthog", api_token="test-listmonk-token")
BASIC = "Basic " + base64.b64encode(b"posthog:test-listmonk-token").decode()


def _driver() -> SourceDriver:
    return SourceDriver(ListmonkSource(), CONFIG)


def _page(rows: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json={"data": {"results": rows, "total": 3, "per_page": 500, "page": 1}})


class TestListmonkLists:
    def test_walks_pages_until_an_empty_page(self) -> None:
        result = _driver().run("lists", [_page([{"id": 1}, {"id": 2}]), _page([{"id": 3}]), _page([])])

        assert result.raised is None
        assert result.paths == ["/api/lists"] * 3
        assert result.params("page") == ["1", "2", "3"]
        assert {r.headers.get("authorization") for r in result.requests} == {BASIC}
        assert [row["id"] for row in result.rows] == [1, 2, 3]
        assert result.saved_states == [ListmonkResumeConfig(next_page=2), ListmonkResumeConfig(next_page=3)]

    def test_resume_starts_from_the_saved_page(self) -> None:
        result = _driver().run("bounces", [_page([])], resume_state=ListmonkResumeConfig(next_page=5))

        assert result.params("page") == ["5"]

    @parameterized.expand(
        [
            (
                "incremental",
                {
                    "incremental_field": "updated_at",
                    "db_incremental_field_last_value": datetime(2026, 9, 30, 8, 15, tzinfo=UTC),
                },
                None,
                "(subscribers.updated_at >= '2026-09-30T08:15:00+00:00' OR subscribers.id IN "
                "(SELECT subscriber_id FROM subscriber_lists WHERE subscriber_lists.updated_at >= '2026-09-30T08:15:00+00:00'))",
            ),
            ("full_refresh", {}, None, None),
        ]
    )
    def test_subscriber_request_shaping(
        self, _name: str, inputs: dict[str, Any], order_by: str | None, query: str | None
    ) -> None:
        result = _driver().run("subscribers", [_page([])], **inputs)

        request = result.requests[0]
        assert request.param("order_by") == order_by
        assert request.param("order") == "asc"
        assert request.param("query") == query


class TestListmonkCampaignAnalytics:
    @staticmethod
    def _script(campaign_count: int) -> Any:
        campaigns = [{"id": i} for i in range(1, campaign_count + 1)]

        def answer(request: Any) -> ScriptedResponse:
            if request.path == "/api/campaigns":
                return _page(campaigns if request.param("page") == "1" else [])
            analytics_type = request.path.rsplit("/", 1)[1]
            first_id = int(request.query["id"][0])
            return ScriptedResponse(
                json={"data": [{"campaign_id": first_id, "count": 4, "timestamp": "2026-10-01T00:00:00Z"}]}
                if analytics_type != "bounces"
                else {"data": []}
            )

        return answer

    @time_machine.travel(datetime(2026, 10, 15, 12, tzinfo=UTC), tick=False)
    def test_requests_each_type_for_each_batch_of_campaigns(self) -> None:
        result = _driver().run("campaign_analytics", self._script(60))

        assert result.raised is None
        analytics = [r for r in result.requests if r.path.startswith("/api/campaigns/analytics/")]
        assert [(r.path.rsplit("/", 1)[1], len(r.query["id"])) for r in analytics] == [
            ("views", 50),
            ("views", 10),
            ("clicks", 50),
            ("clicks", 10),
            ("bounces", 50),
            ("bounces", 10),
        ]
        assert {(r.param("from"), r.param("to")) for r in analytics} == {("2019-01-01", "2026-10-16")}
        # Each request's position is staged before its rows are handed over.
        assert result.committed_states[0] == ListmonkResumeConfig(analytics_type="views", analytics_after_id=50)
        assert result.committed_states[-1] == ListmonkResumeConfig(analytics_type="bounces", analytics_after_id=60)
        assert [(row["type"], row["campaign_id"]) for row in result.rows] == [
            ("views", 1),
            ("views", 51),
            ("clicks", 1),
            ("clicks", 51),
        ]

    @parameterized.expand(
        [
            (
                "mid_type",
                ListmonkResumeConfig(analytics_type="clicks", analytics_after_id=50),
                60,
                ["clicks", "bounces", "bounces"],
            ),
            # A campaign deleted before the retry must not shift the position past unread work.
            ("after_deletion", ListmonkResumeConfig(analytics_type="bounces", analytics_after_id=50), 51, ["bounces"]),
        ]
    )
    def test_resume_continues_from_the_saved_type_and_campaign(
        self, _name: str, state: ListmonkResumeConfig, campaign_count: int, expected_types: list[str]
    ) -> None:
        result = _driver().run("campaign_analytics", self._script(campaign_count), resume_state=state)

        analytics = [r for r in result.requests if r.path.startswith("/api/campaigns/analytics/")]
        assert [r.path.rsplit("/", 1)[1] for r in analytics] == expected_types
        assert int(analytics[0].query["id"][0]) == 51


class TestListmonkHost:
    @parameterized.expand(
        [
            ("bare_host", "listmonk.example.com", False, "https://listmonk.example.com"),
            ("pasted_api_url", "https://listmonk.example.com/api/", False, "https://listmonk.example.com"),
            ("http_self_hosted", "http://10.0.0.5:9000", False, "http://10.0.0.5:9000"),
            ("http_on_cloud", "http://listmonk.example.com", True, None),
            ("userinfo", "https://evil.example.com@169.254.169.254", False, None),
            ("backslash", "http://127.0.0.1\\@listmonk.example.com", False, None),
            ("not_http", "ftp://listmonk.example.com", False, None),
        ]
    )
    def test_normalize_host(self, _name: str, host: str, cloud: bool, expected: str | None) -> None:
        with override_settings(CLOUD_DEPLOYMENT="US" if cloud else None):
            if expected is None:
                with pytest.raises(ValueError):
                    normalize_host(host)
            else:
                assert normalize_host(host) == expected

    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_validate_credentials_maps_probe_status(self, _name: str, status: int, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))) as network:
            valid, message = ListmonkSource().validate_credentials(CONFIG, team_id=1)

        assert valid is expected_valid
        assert (message is None) is expected_valid
        assert {r.path for r in network.requests_log} == {"/api/lists"}

    def test_sync_refuses_an_internal_host_before_any_request(self) -> None:
        config = ListmonkSourceConfig(host="https://169.254.169.254", api_user="posthog", api_token="t")
        with override_settings(CLOUD_DEPLOYMENT="US"):
            result = SourceDriver(ListmonkSource(), config).run("lists", route({}))

        assert "internal or private IP address" in str(result.raised)
        assert result.requests == []

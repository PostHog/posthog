from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from products.mcp_registry.backend.models import MCPMeasuredStats, MCPRegistryServer, MCPRegistryTool
from products.mcp_registry.backend.ranking import compute_ranking_run


def _only_mcp_registry_flag(flag_key: str, *args: object, **kwargs: object) -> bool:
    return flag_key == "mcp-registry"


class TestMCPRegistryAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        flag_patcher = patch("posthoganalytics.feature_enabled", side_effect=_only_mcp_registry_flag)
        flag_patcher.start()
        self.addCleanup(flag_patcher.stop)

    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/mcp_registry/servers/{suffix}"

    def _seed_index(self) -> dict[str, MCPRegistryServer]:
        measured = MCPRegistryServer.objects.create(
            registry_name="io.github.PostHog/mcp",
            display_name="PostHog MCP Server",
            listed_in_registry=True,
            is_measured=True,
            liveness="alive_auth",
            auth_method="oauth",
            canonical_url="https://mcp.example.com/mcp",
        )
        MCPMeasuredStats.objects.create(
            server=measured,
            team_id=self.team.id,
            server_name="PostHog",
            window_days=30,
            calls=50_000,
            errors=1_000,
            error_rate_pct=2.0,
            intent_coverage_pct=90.0,
            link_method="override",
            computed_at=timezone.now(),
        )
        unmeasured = MCPRegistryServer.objects.create(
            registry_name="io.example/analytics-helper",
            display_name="Analytics helper",
            listed_in_registry=True,
            repository_url="https://github.com/example/analytics-helper",
            liveness="alive_open",
            auth_method="none",
            canonical_url="https://helper.example.com/mcp",
        )
        MCPRegistryTool.objects.create(
            server=unmeasured,
            name="query_analytics",
            description="Run an analytics query",
            source="tools_list",
            last_seen_at=timezone.now(),
        )
        compute_ranking_run("v1_metadata_prior")
        compute_ranking_run("v2_measured_trust")
        return {"measured": measured, "unmeasured": unmeasured}

    def test_endpoints_require_the_feature_flag(self) -> None:
        with patch("posthoganalytics.feature_enabled", return_value=False):
            response = self.client.get(self._url())
        assert response.status_code == 403

    def test_requires_authentication(self) -> None:
        self.client.logout()
        assert self.client.get(self._url()).status_code == 401

    def test_list_orders_by_requested_ranking_version(self) -> None:
        servers = self._seed_index()

        default = self.client.get(self._url()).json()
        control = self.client.get(self._url(), {"version": "v1_metadata_prior"}).json()

        # The measured arm puts real usage first; the metadata-only arm inverts that.
        assert [row["id"] for row in default["results"]][:2] == [
            str(servers["measured"].id),
            str(servers["unmeasured"].id),
        ]
        assert [row["id"] for row in control["results"]][:2] == [
            str(servers["unmeasured"].id),
            str(servers["measured"].id),
        ]
        assert default["results"][0]["rank_score"] is not None

    def test_list_rejects_unknown_ranking_version(self) -> None:
        assert self.client.get(self._url(), {"version": "bogus"}).status_code == 400

    def test_search_matches_tool_names(self) -> None:
        servers = self._seed_index()

        response = self.client.get(self._url(), {"search": "query_analytics"}).json()

        assert [row["id"] for row in response["results"]] == [str(servers["unmeasured"].id)]

    def test_measured_only_filter(self) -> None:
        servers = self._seed_index()

        response = self.client.get(self._url(), {"measured_only": "true"}).json()

        assert [row["id"] for row in response["results"]] == [str(servers["measured"].id)]

    def test_retrieve_includes_scores_stats_and_connect_instructions(self) -> None:
        servers = self._seed_index()

        response = self.client.get(self._url(f"{servers['measured'].id}/"))

        assert response.status_code == 200
        data: dict[str, Any] = response.json()
        assert {score["version"] for score in data["scores"]} == {"v1_metadata_prior", "v2_measured_trust"}
        assert data["measured_stats"][0]["calls"] == 50_000
        assert data["connect"]["recommended"] == "remote_oauth"
        assert data["connect"]["methods"][-1]["method"] == "remote_api_key"

    def test_versions_endpoint_lists_runs_and_default(self) -> None:
        self._seed_index()

        payload = self.client.get(self._url("versions/")).json()

        by_version = {row["version"]: row for row in payload}
        assert by_version["v2_measured_trust"]["is_default"] is True
        assert by_version["v1_metadata_prior"]["latest_run"]["server_count"] == 2

    def test_compare_requires_two_known_versions(self) -> None:
        assert self.client.get(self._url("compare/")).status_code == 400
        assert self.client.get(self._url("compare/"), {"versions": "v1_metadata_prior,bogus"}).status_code == 400

    def test_compare_reports_rank_deltas_between_two_versions(self) -> None:
        servers = self._seed_index()

        response = self.client.get(self._url("compare/"), {"versions": "v1_metadata_prior,v2_measured_trust"}).json()

        assert set(response["versions"].keys()) == {"v1_metadata_prior", "v2_measured_trust"}
        # The measured server climbs from rank 2 to rank 1 when the measured arm is applied.
        assert response["rank_deltas"][str(servers["measured"].id)] == -1

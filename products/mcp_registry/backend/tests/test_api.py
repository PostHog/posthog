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
            display_name="Product analytics server",
            description="Product analytics, session replay, feature flags, and experiments.",
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
            display_name="Product analytics helper",
            description="Product analytics, session replay, feature flags, and experiments.",
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

    def test_discover_returns_ranked_candidates_with_connect_instructions(self) -> None:
        servers = self._seed_index()

        payload = self.client.get(self._url("discover/"), {"intent": "query my product analytics"}).json()

        assert payload["ranking_version"] == "v2_measured_trust"
        top = payload["candidates"][0]
        assert top["id"] == str(servers["measured"].id)
        assert top["rank"] == 1
        # The measured block is what no other registry can return.
        assert top["measured"]["calls"] == 50_000
        assert top["why"]["measured"] is True
        # Connect instructions ship in the same response, so one call is enough to act.
        assert top["connect"]["recommended"] == "remote_oauth"
        assert payload["candidates"][1]["measured"] is None

    def test_relevance_outranks_authority_when_the_text_match_is_better(self) -> None:
        # A live, well-documented server that is plainly about the thing must beat a
        # measured server that only matches on a tool name, or a high-traffic server
        # would win every unrelated query.
        self._seed_index()
        on_topic = MCPRegistryServer.objects.create(
            registry_name="io.example/webhook-relay",
            display_name="Webhook relay",
            description="Relay webhooks between services.",
            listed_in_registry=True,
            liveness="alive_open",
            auth_method="none",
            canonical_url="https://relay.example.com/mcp",
        )
        compute_ranking_run("v2_measured_trust")

        payload = self.client.get(self._url("discover/"), {"intent": "relay webhooks"}).json()

        assert payload["candidates"][0]["id"] == str(on_topic.id)

    def test_discover_returns_one_row_per_server(self) -> None:
        # Several tools matching one intent used to duplicate the server in the results.
        servers = self._seed_index()
        for name in ("query_analytics_daily", "query_analytics_hourly"):
            MCPRegistryTool.objects.create(
                server=servers["unmeasured"],
                name=name,
                description="Run an analytics query",
                source="tools_list",
                last_seen_at=timezone.now(),
            )

        payload = self.client.get(self._url("discover/"), {"intent": "query_analytics"}).json()

        ids = [candidate["id"] for candidate in payload["candidates"]]
        assert len(ids) == len(set(ids))

    def test_verified_namespace_outranks_a_lookalike_display_name(self) -> None:
        # Anyone can title their server "Vercel"; only the domain owner can publish under
        # com.vercel/*, so the vendor's own entry has to win its own name.
        official = MCPRegistryServer.objects.create(
            registry_name="com.vercel/vercel-mcp",
            display_name="vercel-mcp",
            description="Deploy and manage projects.",
            listed_in_registry=True,
            liveness="alive_auth",
            auth_method="oauth",
            canonical_url="https://mcp.vercel.com/",
        )
        MCPRegistryServer.objects.create(
            registry_name="io.github.someone/vercel-helper",
            display_name="Vercel deploy helper",
            description="Deploy and manage Vercel projects.",
            listed_in_registry=True,
            liveness="alive_open",
            auth_method="none",
            canonical_url="https://helper.example.com/mcp",
        )
        compute_ranking_run("v2_measured_trust")

        payload = self.client.get(self._url("discover/"), {"intent": "vercel"}).json()

        assert payload["candidates"][0]["id"] == str(official.id)

    def _seed_another_projects_stats(self, server: MCPRegistryServer) -> None:
        MCPMeasuredStats.objects.create(
            server=server,
            team_id=self.team.id + 1,
            server_name="PostHog",
            window_days=30,
            calls=999_999,
            errors=0,
            error_rate_pct=0.0,
            intent_coverage_pct=100.0,
            link_method="override",
            computed_at=timezone.now(),
        )

    def _measured_candidate(self, payload: dict[str, Any], server: MCPRegistryServer) -> dict[str, Any]:
        return next(row for row in payload["candidates"] if row["id"] == str(server.id))

    def test_another_projects_measured_stats_stay_hidden(self) -> None:
        # Registry rows are global, so a server measured by several projects carries a stats
        # row per project. A non-staff caller may only see the project it asked as.
        servers = self._seed_index()
        self._seed_another_projects_stats(servers["measured"])

        detail = self.client.get(self._url(f"{servers['measured'].id}/")).json()
        discovered = self.client.get(self._url("discover/"), {"intent": "product analytics"}).json()

        assert [row["calls"] for row in detail["measured_stats"]] == [50_000]
        assert self._measured_candidate(discovered, servers["measured"])["measured"]["calls"] == 50_000

    def test_staff_see_every_projects_measured_stats(self) -> None:
        # The fleet view is the point of the staff tier: ranking is only judgeable across
        # every contributing project, not the one in the route.
        servers = self._seed_index()
        self._seed_another_projects_stats(servers["measured"])
        self.user.is_staff = True
        self.user.save()

        detail = self.client.get(self._url(f"{servers['measured'].id}/")).json()
        discovered = self.client.get(self._url("discover/"), {"intent": "product analytics"}).json()

        assert sorted(row["calls"] for row in detail["measured_stats"]) == [50_000, 999_999]
        assert self._measured_candidate(discovered, servers["measured"])["measured"]["calls"] == 1_049_999

    def test_measured_projects_reports_the_fleet_to_staff_only(self) -> None:
        # It aggregates across projects, so a non-staff caller must not reach it at all.
        servers = self._seed_index()
        self._seed_another_projects_stats(servers["measured"])

        assert self.client.get(self._url("measured_projects/")).status_code == 403

        self.user.is_staff = True
        self.user.save()
        rows = self.client.get(self._url("measured_projects/")).json()

        assert [row["team_id"] for row in rows] == [self.team.id + 1, self.team.id]
        assert [row["calls"] for row in rows] == [999_999, 50_000]

    def _reassign_measurements_to_another_project(self, server: MCPRegistryServer) -> None:
        MCPMeasuredStats.objects.filter(server=server).update(team_id=self.team.id + 1)
        compute_ranking_run("v2_measured_trust")

    def _v2_components(self, detail: dict[str, Any]) -> dict[str, Any]:
        return next(row for row in detail["scores"] if row["version"] == "v2_measured_trust")["components"]

    def test_components_derived_from_hidden_measurements_are_withheld(self) -> None:
        # Ranking components are computed from every contributing project, so returning
        # them whole would disclose by arithmetic what hiding the stats withholds.
        servers = self._seed_index()
        self._reassign_measurements_to_another_project(servers["measured"])

        detail = self.client.get(self._url(f"{servers['measured'].id}/")).json()
        components = self._v2_components(detail)

        assert "measured_reliability" not in components
        assert "trust" not in components
        # The rank itself still shows: only the numbers behind it are withheld.
        assert components["measured"] is True
        assert detail["measured_stats"] == []

    def test_sharing_a_server_withholds_the_blended_breakdown(self) -> None:
        # This project measured the server too, but the components blend its rows with
        # another project's, so it gets its own figures and a redacted breakdown.
        servers = self._seed_index()
        self._seed_another_projects_stats(servers["measured"])
        compute_ranking_run("v2_measured_trust")

        detail = self.client.get(self._url(f"{servers['measured'].id}/")).json()

        assert [row["calls"] for row in detail["measured_stats"]] == [50_000]
        assert "measured_reliability" not in self._v2_components(detail)

    def test_staff_get_the_full_component_breakdown(self) -> None:
        servers = self._seed_index()
        self._reassign_measurements_to_another_project(servers["measured"])
        self.user.is_staff = True
        self.user.save()

        components = self._v2_components(self.client.get(self._url(f"{servers['measured'].id}/")).json())

        assert "measured_reliability" in components

    def test_analytics_sourced_tools_stay_hidden_from_other_projects(self) -> None:
        # A probed tool is ours to show; one learned from another project's traffic is not.
        servers = self._seed_index()
        for name, source in (("probed_tool", "tools_list"), ("learned_from_traffic", "analytics")):
            MCPRegistryTool.objects.create(
                server=servers["measured"],
                name=name,
                description="",
                source=source,
                last_seen_at=timezone.now(),
            )
        self._reassign_measurements_to_another_project(servers["measured"])

        detail = self.client.get(self._url(f"{servers['measured'].id}/")).json()

        assert [tool["name"] for tool in detail["tools"]] == ["probed_tool"]

    def test_measured_only_rows_from_another_project_stay_hidden(self) -> None:
        # A row absent from the official registry exists only because another project's
        # events named a server we could not match, and that name is unvalidated text
        # from whoever captured the event.
        theirs = MCPRegistryServer.objects.create(
            display_name="Their Internal Tools",
            description="Measured via MCP Analytics; not listed in the official registry.",
            listed_in_registry=False,
            is_measured=True,
        )
        MCPMeasuredStats.objects.create(
            server=theirs,
            team_id=self.team.id + 1,
            server_name="Their Internal Tools",
            window_days=30,
            calls=1_000,
            errors=0,
            error_rate_pct=0.0,
            intent_coverage_pct=100.0,
            link_method="standalone",
            computed_at=timezone.now(),
        )
        compute_ranking_run("v2_measured_trust")

        listed = self.client.get(self._url(), {"search": "internal tools"}).json()

        assert [row["id"] for row in listed["results"]] == []
        assert self.client.get(self._url(f"{theirs.id}/")).status_code == 404

        self.user.is_staff = True
        self.user.save()
        assert self.client.get(self._url(f"{theirs.id}/")).status_code == 200

    def test_discover_requires_an_intent(self) -> None:
        assert self.client.get(self._url("discover/")).status_code == 400

    def test_discover_surfaces_tools_that_matched_the_intent(self) -> None:
        self._seed_index()

        payload = self.client.get(self._url("discover/"), {"intent": "query_analytics"}).json()

        matched = payload["candidates"][0]["matched_tools"]
        assert [tool["name"] for tool in matched] == ["query_analytics"]

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

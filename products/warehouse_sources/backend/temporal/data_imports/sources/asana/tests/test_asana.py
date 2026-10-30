from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.asana.asana import (
    ASANA_BASE_URL,
    AsanaResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.asana.settings import (
    ASANA_ENDPOINTS,
    ENDPOINTS,
    AsanaEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.asana.source import AsanaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.asana import AsanaSourceConfig


def _page(items: list[dict[str, Any]], next_uri: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"data": items, "next_page": {"uri": next_uri, "offset": "tok"} if next_uri else None})


def _driver() -> SourceDriver:
    return SourceDriver(AsanaSource(), AsanaSourceConfig(access_token="token"))


class TestTopLevelPagination:
    def test_paginates_via_next_page_uri_and_checkpoints(self) -> None:
        next_uri = f"{ASANA_BASE_URL}/workspaces?offset=tok2"
        result = _driver().run(
            "workspaces",
            [_page([{"gid": "1"}, {"gid": "2"}], next_uri=next_uri), _page([{"gid": "3"}])],
        )

        assert result.raised is None
        assert [row["gid"] for row in result.rows] == ["1", "2", "3"]
        # First request carries the page size and opted-in fields.
        assert result.requests[0].param("limit") == "100"
        assert result.requests[0].param("opt_fields") is not None
        assert result.urls[1] == next_uri
        # Checkpoint saved after the first page (points at the next link); the terminal page saves nothing.
        assert result.saved_states == [AsanaResumeConfig(paginator_state={"next_url": next_uri})]

    def test_resumes_from_saved_next_url(self) -> None:
        resume_url = f"{ASANA_BASE_URL}/workspaces?offset=resume"
        result = _driver().run(
            "workspaces",
            [_page([{"gid": "9"}])],
            resume_state=AsanaResumeConfig(paginator_state={"next_url": resume_url}),
        )

        assert result.raised is None
        assert result.urls == [resume_url]


class TestFanOut:
    def test_workspace_fan_out_drains_every_parent(self) -> None:
        result = _driver().run(
            "projects",
            [_page([{"gid": "W1"}, {"gid": "W2"}]), _page([{"gid": "a"}]), _page([{"gid": "b"}])],
        )

        assert result.raised is None
        assert [row["gid"] for row in result.rows] == ["a", "b"]
        assert result.params("workspace") == [None, "W1", "W2"]
        # Single-hop fan-out keeps resume: the dependent resource checkpoints per-parent progress.
        assert result.saved_states
        state = result.saved_states[-1].paginator_state
        assert state is not None
        assert "completed" in state

    def test_organization_fan_out_skips_non_org_workspaces(self) -> None:
        result = _driver().run(
            "teams",
            [
                _page([{"gid": "W1", "is_organization": True}, {"gid": "W2", "is_organization": False}]),
                _page([{"gid": "team1"}]),
            ],
        )

        assert result.raised is None
        assert [row["gid"] for row in result.rows] == ["team1"]
        assert result.paths == ["/api/1.0/workspaces", "/api/1.0/organizations/W1/teams"]
        # The non-organization workspace never triggers a teams request.
        assert not any("/organizations/W2/" in path for path in result.paths)

    def test_task_level_chain_yields_stories_per_task(self) -> None:
        result = _driver().run(
            "stories",
            [
                _page([{"gid": "W1"}]),
                _page([{"gid": "P1"}]),
                _page([{"gid": "T1"}, {"gid": "T2"}]),
                _page([{"gid": "s1"}]),
                _page([{"gid": "s2"}]),
            ],
        )

        assert result.raised is None
        assert [row["gid"] for row in result.rows] == ["s1", "s2"]
        assert result.paths == [
            "/api/1.0/workspaces",
            "/api/1.0/projects",
            "/api/1.0/tasks",
            "/api/1.0/tasks/T1/stories",
            "/api/1.0/tasks/T2/stories",
        ]
        # The tasks level is fetched compact — story opt_fields must not leak onto the parent walk.
        assert all(
            request.param("opt_fields") is None for request in result.requests if request.param("project") == "P1"
        )

    @pytest.mark.parametrize(
        "endpoint, child_routes, expected_gids",
        [
            ("users", [], ["U1", "U2"]),
            ("time_tracking_entries", [("user=U1", [{"gid": "e1"}]), ("user=U2", [])], ["e1"]),
        ],
    )
    def test_users_are_walked_per_workspace(
        self, endpoint: str, child_routes: list[tuple[str, list[dict[str, Any]]]], expected_gids: list[str]
    ) -> None:
        result = _driver().run(
            endpoint,
            [
                _page([{"gid": "W1"}]),
                _page([{"gid": "U1"}, {"gid": "U2"}]),
                *[_page(items) for _, items in child_routes],
            ],
        )

        assert result.raised is None
        assert [row["gid"] for row in result.rows] == expected_gids
        # Asana rejects an unscoped /users once the token can see more than one workspace.
        user_requests = [request for request in result.requests if "/users" in request.path]
        assert user_requests and all(request.param("workspace") == "W1" for request in user_requests)
        if child_routes:
            assert result.params("user")[-len(child_routes) :] == [route.split("=", 1)[1] for route, _ in child_routes]
        # Every entry request is scoped to a user; an unfiltered request would be rejected.
        assert all(
            request.param("user") is not None for request in result.requests if "/time_tracking_entries" in request.path
        )

    def test_parent_goals_carry_the_child_gid_and_skip_pagination(self) -> None:
        # parentGoals takes no limit/offset and returns no next_page — a limit param is rejected.
        result = _driver().run(
            "parent_goals",
            [
                _page([{"gid": "W1"}]),
                _page([{"gid": "G1"}, {"gid": "G2"}]),
                _page([{"gid": "P"}], next_uri="ignored"),
                _page([{"gid": "P"}]),
            ],
        )

        assert result.raised is None
        # The same parent goal under two children — only the composite key keeps both rows.
        assert [(row["goal_gid"], row["gid"]) for row in result.rows] == [("G1", "P"), ("G2", "P")]
        assert not any("_goals_gid" in row for row in result.rows)
        parent_goal_requests = [request for request in result.requests if "parentGoals" in request.path]
        assert len(parent_goal_requests) == 2
        assert [request.path for request in parent_goal_requests] == [
            "/api/1.0/goals/G1/parentGoals",
            "/api/1.0/goals/G2/parentGoals",
        ]
        assert all(
            request.param("limit") is None and request.param("offset") is None for request in parent_goal_requests
        )

    def test_team_memberships_walk_organizations_then_teams(self) -> None:
        result = _driver().run(
            "team_memberships",
            [
                _page([{"gid": "W1", "is_organization": True}, {"gid": "W2", "is_organization": False}]),
                _page([{"gid": "TM1"}]),
                _page([{"gid": "m1"}]),
            ],
        )

        assert result.raised is None
        assert [row["gid"] for row in result.rows] == ["m1"]
        assert result.paths == [
            "/api/1.0/workspaces",
            "/api/1.0/organizations/W1/teams",
            "/api/1.0/teams/TM1/team_memberships",
        ]
        # Teams only exist under organizations, so the plain workspace is dropped before the walk.
        assert not any("/organizations/W2/" in path for path in result.paths)

    def test_portfolio_items_carry_the_portfolio_gid(self) -> None:
        result = _driver().run(
            "portfolio_items",
            [
                _page([{"gid": "W1"}]),
                _page([{"gid": "PF1"}, {"gid": "PF2"}]),
                _page([{"gid": "PR1"}]),
                _page([{"gid": "PR1"}]),
            ],
        )

        assert result.raised is None
        # The same project held by two portfolios — only the composite key keeps both rows.
        assert [(row["portfolio_gid"], row["gid"]) for row in result.rows] == [("PF1", "PR1"), ("PF2", "PR1")]
        assert not any("_portfolios_gid" in row for row in result.rows)
        assert result.paths[-2:] == ["/api/1.0/portfolios/PF1/items", "/api/1.0/portfolios/PF2/items"]
        assert all(request.param("limit") == "100" for request in result.requests if "/items" in request.path)
        # Asana 400s GET /portfolios for a non-service-account token without an explicit owner.
        assert all(
            request.param("owner") == "me" for request in result.requests if request.path == "/api/1.0/portfolios"
        )

    def test_portfolios_scope_to_the_tokens_own_user(self) -> None:
        result = _driver().run("portfolios", [_page([{"gid": "W1"}]), _page([{"gid": "PF1"}])])

        assert result.raised is None
        assert [row["gid"] for row in result.rows] == ["PF1"]
        # Asana 400s GET /portfolios for a non-service-account token without an explicit owner.
        assert all(request.param("owner") == "me" for request in result.requests if "/portfolios" in request.path)

    def test_project_level_chain_yields_grandchild_rows(self) -> None:
        result = _driver().run(
            "tasks",
            [
                _page([{"gid": "W1"}]),
                _page([{"gid": "P1"}, {"gid": "P2"}]),
                _page([{"gid": "t1"}]),
                _page([{"gid": "t2"}]),
            ],
        )

        assert result.raised is None
        assert [row["gid"] for row in result.rows] == ["t1", "t2"]
        assert result.params("project")[-2:] == ["P1", "P2"]
        # Multi-level fan-out disables resume (one shared hook can't checkpoint two levels);
        # retries re-fetch and the merge dedupes on gid.
        assert result.saved_states == []


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
        ],
    )
    def test_status_mapping(self, status_code: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            assert validate_credentials("token") is expected

        assert network.requests_log[0].path == "/api/1.0/users/me"


class TestAsanaSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = ASANA_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, always(_page([])))

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "week"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    # Creation-time fields that never change after a row is written — safe to partition on.
    # A mutable field (modified_at, lastSeen) would rewrite partitions on every sync.
    STABLE_CREATION_FIELDS = {"created_at", "run_started_at"}

    @pytest.mark.parametrize("config", list(ASANA_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config: AsanaEndpointConfig) -> None:
        if config.partition_key:
            assert config.partition_key in self.STABLE_CREATION_FIELDS
            # The partition field must be opted into the response, else partitioning fails.
            assert config.partition_key in config.opt_fields

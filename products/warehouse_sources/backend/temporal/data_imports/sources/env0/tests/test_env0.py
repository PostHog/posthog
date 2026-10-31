from datetime import UTC, datetime

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.env0.env0 import (
    Env0ResumeConfig,
    _build_date_window_params,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.env0.settings import (
    ENDPOINTS,
    ENV0_ENDPOINTS,
    Env0EndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.env0.source import Env0Source
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.env0 import Env0SourceConfig


def _driver() -> SourceDriver:
    return SourceDriver(Env0Source(), Env0SourceConfig(api_key_id="key-id", api_key_secret="key-secret"))


class TestBuildDateWindowParams:
    @pytest.mark.parametrize(
        "endpoint, should_use_incremental_field, last_value",
        [
            ("deployments", True, None),
            ("deployments", False, datetime(2026, 6, 1, tzinfo=UTC)),
            ("environments", True, datetime(2026, 6, 1, tzinfo=UTC)),
        ],
    )
    def test_no_window_without_watermark_or_support(
        self, endpoint: str, should_use_incremental_field: bool, last_value: datetime | None
    ) -> None:
        assert _build_date_window_params(ENV0_ENDPOINTS[endpoint], should_use_incremental_field, last_value) == {}


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
        ],
    )
    def test_validate_credentials_status_mapping(self, status_code: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            assert validate_credentials("key-id", "key-secret") is expected

        assert network.requests_log[0].path == "/organizations"
        assert network.requests_log[0].method == "GET"


class TestGetRows:
    def test_deployments_fan_out_strips_heavy_and_secret_fields_and_windows_requests(self) -> None:
        deployment = {
            "id": "dep-1",
            "status": "SUCCESS",
            "output": "x" * 100,
            "plan": {"big": True},
            "variables": [{"name": "DB_PASSWORD", "value": "hunter2", "isSensitive": False}],
            "customEnv0EnvironmentVariables": {"oidcToken": "eyJ...", "vcsAccessToken": "ghs_..."},
        }
        result = _driver().run(
            "deployments",
            [
                ScriptedResponse(json=[{"id": "org-1"}]),
                ScriptedResponse(json=[{"id": "env-1"}]),
                ScriptedResponse(json=[deployment]),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.rows == [{"id": "dep-1", "status": "SUCCESS"}]
        deployment_request = next(request for request in result.requests if request.path.endswith("/deployments"))
        assert deployment_request.param("fromDate") == "2026-05-31T00:00:00.000Z"
        assert deployment_request.param("toDate") is not None
        # Multi-level fan-out disables resume (one shared hook can't checkpoint two levels).
        assert result.saved_states == []

    @pytest.mark.parametrize(
        "endpoint, parents, uncovered_path, covered_path, parent_column",
        [
            (
                "environment_costs",
                [{"id": "env-1"}, {"id": "env-2"}],
                "/costs/environments/env-1",
                "/costs/environments/env-2",
                "environment_id",
            ),
            (
                "project_costs",
                [{"id": "proj-1"}, {"id": "proj-2"}],
                "/costs/projects/proj-1",
                "/costs/projects/proj-2",
                "project_id",
            ),
        ],
    )
    def test_costs_inject_the_parent_id_and_skip_404s(
        self,
        endpoint: str,
        parents: list[dict[str, str]],
        uncovered_path: str,
        covered_path: str,
        parent_column: str,
    ) -> None:
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(json=[{"id": "org-1"}]),
                ScriptedResponse(json=parents),
                # The first parent has no cost monitoring configured.
                ScriptedResponse(status=404, json={"message": "not found"}),
                ScriptedResponse(json=[{"date": "2026-06-01", "total": 12.5}]),
            ],
        )

        assert result.raised is None
        assert result.paths[-2:] == [uncovered_path, covered_path]
        assert result.rows == [{"date": "2026-06-01", "total": 12.5, parent_column: parents[1]["id"]}]

    def test_non_404_error_fails_the_sync(self) -> None:
        result = _driver().run(
            "environment_costs",
            [
                ScriptedResponse(json=[{"id": "org-1"}]),
                ScriptedResponse(json=[{"id": "env-1"}]),
                ScriptedResponse(status=403, json={"message": "forbidden"}),
            ],
        )

        assert result.paths[-1] == "/costs/environments/env-1"
        assert isinstance(result.raised, requests.HTTPError)

    def test_resume_offset_applies_only_to_bookmarked_parent(self) -> None:
        result = _driver().run(
            "environments",
            [
                ScriptedResponse(json=[{"id": "org-1"}, {"id": "org-2"}]),
                ScriptedResponse(json=[{"id": "env-9"}]),
                ScriptedResponse(json=[{"id": "env-10"}]),
            ],
            resume_state=Env0ResumeConfig(
                paginator_state={
                    "completed": [],
                    "current": "/environments?organizationId=org-1",
                    "child_state": {"offset": 200},
                }
            ),
        )

        assert result.raised is None
        org1_request = next(request for request in result.requests if request.param("organizationId") == "org-1")
        org2_request = next(request for request in result.requests if request.param("organizationId") == "org-2")
        assert org1_request.param("offset") == "200"
        # The next parent starts a fresh page chain from offset 0.
        assert org2_request.param("offset") == "0"


class TestFanOutShaping:
    def test_organization_users_lifts_the_nested_user_onto_the_row(self) -> None:
        result = _driver().run(
            "organization_users",
            [
                ScriptedResponse(json=[{"id": "org-1"}]),
                ScriptedResponse(
                    json=[
                        {
                            "user": {"user_id": "u-1", "email": "member@example.com"},
                            "role": "Admin",
                            "status": "Active",
                        }
                    ]
                ),
            ],
        )

        assert result.raised is None
        # user_id is the row's identity and sits one level down, so a nested column would leave the
        # primary key unresolvable.
        assert result.rows == [
            {
                "user_id": "u-1",
                "email": "member@example.com",
                "role": "Admin",
                "status": "Active",
                "organization_id": "org-1",
            }
        ]
        assert result.requests[1].param("includeApiKeys") == "true"

    @pytest.mark.parametrize(
        "endpoint, child_row, expected_row, child_path",
        [
            (
                "deployment_resources",
                {"provider": "aws", "type": "aws_s3_bucket", "name": "logs", "mode": "managed"},
                # moduleName is absent for root-module resources but is part of the key, and a NULL
                # key part never matches on merge.
                {"provider": "aws", "type": "aws_s3_bucket", "name": "logs", "mode": "managed", "moduleName": ""},
                "/environments/deployments/dep-1/resources",
            ),
            (
                "deployment_steps",
                {"name": "terraform-plan", "order": 3, "status": "SUCCESS", "deploymentLogId": "dep-1"},
                {"name": "terraform-plan", "order": 3, "status": "SUCCESS", "deploymentLogId": "dep-1"},
                "/deployments/dep-1/steps",
            ),
        ],
    )
    def test_deployment_children_window_the_parent_walk_not_the_child(
        self, endpoint: str, child_row: dict, expected_row: dict, child_path: str
    ) -> None:
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(json=[{"id": "org-1"}]),
                ScriptedResponse(json=[{"id": "env-1"}]),
                ScriptedResponse(json=[{"id": "dep-1", "startedAt": "2026-06-02T10:00:00.000Z"}]),
                ScriptedResponse(json=[child_row]),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.rows == [
            {**expected_row, "deployment_id": "dep-1", "deployment_started_at": "2026-06-02T10:00:00.000Z"}
        ]
        deployment_request = next(request for request in result.requests if request.path.endswith("/deployments"))
        assert deployment_request.param("fromDate") == "2026-05-31T00:00:00.000Z"
        # The child endpoint takes no time filter; only the parent walk is bounded.
        child_request = result.requests[-1]
        assert child_request.path == child_path
        assert child_request.query == {}

    @pytest.mark.parametrize(
        "endpoint, parent_rows, child_responses, expected_child_paths, expected_rows",
        [
            (
                "user_role_assignments",
                [{"id": "env-1"}],
                [
                    ScriptedResponse(
                        json=[
                            {
                                "userId": "u-1",
                                "role": "Viewer",
                                "user": {"user_id": "u-1", "identities": [{"access_token": "fake-token"}]},
                            }
                        ]
                    )
                ],
                ["/roles/assignments/users"],
                [{"userId": "u-1", "role": "Viewer", "environment_id": "env-1"}],
            ),
            (
                "team_role_assignments",
                [{"id": "proj-1"}],
                [ScriptedResponse(json=[{"teamId": "team-1", "role": "Admin", "inherited": True}])],
                ["/roles/assignments/teams"],
                # A missing optional id is part of the key, and a NULL key part never matches on merge.
                [{"teamId": "team-1", "role": "Admin", "inherited": True, "id": "", "project_id": "proj-1"}],
            ),
            (
                "project_budgets",
                [{"id": "proj-1"}, {"id": "proj-2"}],
                [
                    # A project with no budget answers with an empty object, which is not a row.
                    ScriptedResponse(json={}),
                    ScriptedResponse(
                        json={"projectId": "proj-2", "amount": 500, "timeframe": "MONTHLY", "thresholds": [80]}
                    ),
                ],
                ["/costs/project/proj-1/budget", "/costs/project/proj-2/budget"],
                [{"projectId": "proj-2", "amount": 500, "timeframe": "MONTHLY", "thresholds": [80]}],
            ),
        ],
    )
    def test_role_and_budget_fan_out_shaping(
        self,
        endpoint: str,
        parent_rows: list[dict],
        child_responses: list[ScriptedResponse],
        expected_child_paths: list[str],
        expected_rows: list[dict],
    ) -> None:
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json=[{"id": "org-1"}]), ScriptedResponse(json=parent_rows), *child_responses],
        )

        assert result.raised is None
        assert result.paths[-len(expected_child_paths) :] == expected_child_paths
        assert result.rows == expected_rows

    def test_project_budget_summaries_request_one_project_at_a_time(self) -> None:
        result = _driver().run(
            "project_budget_summaries",
            [
                ScriptedResponse(json=[{"id": "org-1"}]),
                ScriptedResponse(json=[{"id": "proj-1"}, {"id": "proj-2"}]),
                ScriptedResponse(json=[{"projectId": "proj-1", "usage": 12.5, "amount": 100}]),
                ScriptedResponse(json=[{"projectId": "proj-2", "usage": 0, "amount": 50}]),
            ],
        )

        assert result.raised is None
        assert [request.param("projectIds") for request in result.requests[-2:]] == ["proj-1", "proj-2"]
        assert [row["projectId"] for row in result.rows] == ["proj-1", "proj-2"]

    def test_audit_logs_window_strip_users_and_follow_the_cursor(self) -> None:
        result = _driver().run(
            "audit_logs",
            [
                ScriptedResponse(json=[{"id": "org-1"}]),
                ScriptedResponse(
                    json={
                        "events": [
                            {
                                "id": "evt-1",
                                "actionName": "deploy",
                                "actorId": "u-1",
                                "timestamp": "2026-06-02T10:00:00.000Z",
                                "actor": {"user_id": "u-1", "identities": [{"refresh_token": "fake-token"}]},
                                "attributedToUser": {"user_id": "u-1"},
                            }
                        ],
                        "nextPageKey": "evt-1",
                    }
                ),
                ScriptedResponse(
                    json={
                        "events": [
                            {
                                "id": "evt-2",
                                "actionName": "destroy",
                                "actorId": "u-2",
                                "timestamp": "2026-06-03T10:00:00.000Z",
                            }
                        ],
                        "nextPageKey": "",
                    }
                ),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.rows == [
            {"id": "evt-1", "actionName": "deploy", "actorId": "u-1", "timestamp": "2026-06-02T10:00:00.000Z"},
            {"id": "evt-2", "actionName": "destroy", "actorId": "u-2", "timestamp": "2026-06-03T10:00:00.000Z"},
        ]
        first_page, second_page = result.requests[1:]
        assert first_page.path == "/audit/events"
        assert first_page.param("organizationId") == "org-1"
        # Audit events take from/to, not the fromDate/toDate names the deployments endpoint uses.
        assert first_page.param("from") == "2026-06-01T00:00:00.000Z"
        assert first_page.param("to") is not None
        assert first_page.param("fromDate") is None
        assert first_page.param("offset") is None
        assert second_page.param("offset") == "evt-1"
        assert second_page.param("from") == "2026-06-01T00:00:00.000Z"


class TestEnv0SourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = ENV0_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, [ScriptedResponse(json=[])])
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        # Unverified API ordering: incremental endpoints must persist their watermark only at
        # successful job end, which "desc" guarantees.
        assert response.sort_mode == ("desc" if config.incremental_fields else "asc")
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", [c for c in ENV0_ENDPOINTS.values() if c.inject_parent_fields])
    def test_fan_out_child_primary_keys_include_parent_id(self, config: Env0EndpointConfig) -> None:
        # Fan-out rows carry no globally-unique id of their own; without the parent id in the key,
        # rows from different parents collapse into one and every later merge multi-matches them.
        assert config.inject_parent_fields["id"] in config.primary_keys

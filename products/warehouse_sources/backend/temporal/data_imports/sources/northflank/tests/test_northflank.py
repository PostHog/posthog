from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.northflank import (
    NorthflankSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.northflank.northflank import (
    NorthflankResumeConfig,
    NorthflankRetryableError,
    _build_url,
    _extract_rows,
    _next_cursor,
    _rate_limit_sleep_seconds,
    get_rows,
    northflank_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.northflank.settings import (
    ENDPOINTS,
    NORTHFLANK_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.northflank.source import NorthflankSource

PATCH_SESSION = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.northflank.northflank.make_tracked_session"
)


def _response(body: dict[str, Any], status_code: int = 200, headers: dict[str, str] | None = None) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.headers = headers or {}
    response.json.return_value = body
    return response


def _page(data_key: str, items: list[dict[str, Any]], cursor: str | None) -> dict[str, Any]:
    return {"data": {data_key: items}, "pagination": {"hasNextPage": cursor is not None, "cursor": cursor}}


def _driver() -> SourceDriver:
    return SourceDriver(NorthflankSource(), NorthflankSourceConfig(api_token="token"))


class TestBuildUrl:
    def test_no_params(self):
        assert _build_url("/v1/projects") == "https://api.northflank.com/v1/projects"


class TestExtractRows:
    @parameterized.expand(
        [
            ("nested_under_data_key", {"data": {"projects": [{"id": "p1"}]}}, "projects", [{"id": "p1"}]),
            ("data_is_the_array", {"data": [{"id": "v1"}]}, "volumes", [{"id": "v1"}]),
            ("missing_key", {"data": {"other": []}}, "projects", []),
            ("empty_body", {}, "projects", []),
        ]
    )
    def test_extract_rows(self, _name, body, data_key, expected):
        assert _extract_rows(body, data_key) == expected


class TestNextCursor:
    @parameterized.expand(
        [
            ({"pagination": {"hasNextPage": True, "cursor": "abc"}}, "abc"),
            ({"pagination": {"hasNextPage": False, "cursor": "abc"}}, None),
            ({"pagination": {"hasNextPage": True}}, None),
            ({}, None),
        ]
    )
    def test_next_cursor(self, body, expected):
        assert _next_cursor(body) == expected


class TestRateLimitSleep:
    @parameterized.expand(
        [
            ({"retry-after": "5"}, 5),
            ({"x-ratelimit-reset": "30"}, 30),
            ({"retry-after": "9999"}, 120),
            ({"retry-after": "-3"}, 0),
            ({"retry-after": "nope"}, 0),
            ({}, 0),
        ]
    )
    def test_sleep_seconds_from_headers(self, headers, expected):
        response = mock.MagicMock()
        response.headers = headers
        assert _rate_limit_sleep_seconds(response) == expected


class TestValidateCredentials:
    @parameterized.expand(
        [
            (200, True),
        ]
    )
    def test_status_mapping(self, status, expected):
        with scripted_network([ScriptedResponse(status=status, json={})]) as network:
            is_valid, error = validate_credentials("token")

        assert is_valid is expected
        assert (error is None) is expected
        assert [request.path for request in network.requests_log] == ["/v1/projects"]
        assert network.requests_log[0].param("per_page") == "1"
        assert network.requests_log[0].headers["authorization"] == "Bearer token"

    def test_connection_error_is_not_valid(self):
        with scripted_network([ConnectionError("boom")]) as network:
            is_valid, error = validate_credentials("token")

        assert is_valid is False
        assert error is not None
        assert [request.path for request in network.requests_log] == ["/v1/projects"]


class TestProjectsPagination:
    def test_page_cap_stops_and_logs(self):
        logger = mock.MagicMock()
        result = _driver().run(
            "projects",
            always(ScriptedResponse(json=_page("projects", [{"id": "p"}], "always-more"))),
            logger=logger,
        )

        assert result.raised is None
        assert len(result.items) == 500
        assert len(result.requests) == 500
        assert result.params("cursor") == [None] + ["always-more"] * 499
        logger.warning.assert_called_once()
        assert "page cap" in logger.warning.call_args.args[0]

    def test_unknown_endpoint_raises(self):
        with pytest.raises(ValueError, match="Unknown Northflank endpoint"):
            list(get_rows("token", "nope", mock.MagicMock()))


class TestFanOut:
    def test_injected_project_id_does_not_clobber_native_field(self):
        # Volumes don't carry projectId natively; the transport must add it for the composite key.
        result = _driver().run(
            "volumes",
            route(
                {
                    "/v1/projects": [ScriptedResponse(json=_page("projects", [{"id": "proj-a"}], None))],
                    "/v1/projects/proj-a/volumes": [
                        ScriptedResponse(
                            json=_page("volumes", [{"id": "vol-1", "createdAt": "2026-01-01T00:00:00Z"}], None)
                        )
                    ],
                }
            ),
        )

        assert result.raised is None
        assert result.paths == ["/v1/projects", "/v1/projects/proj-a/volumes"]
        assert result.rows == [{"id": "vol-1", "createdAt": "2026-01-01T00:00:00Z", "projectId": "proj-a"}]

    def test_child_pagination_per_project(self):
        result = _driver().run(
            "jobs",
            route(
                {
                    "/v1/projects": [ScriptedResponse(json=_page("projects", [{"id": "proj-a"}], None))],
                    "/v1/projects/proj-a/jobs": [
                        ScriptedResponse(json=_page("jobs", [{"id": "j1"}], "jobs-cursor-2")),
                        ScriptedResponse(json=_page("jobs", [{"id": "j2"}], None)),
                    ],
                }
            ),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["j1", "j2"]
        assert result.paths == ["/v1/projects", "/v1/projects/proj-a/jobs", "/v1/projects/proj-a/jobs"]
        assert result.params("cursor") == [None, None, "jobs-cursor-2"]

    def test_nested_fan_out_skips_deployment_services_and_injects_parent_ids(self):
        result = _driver().run(
            "service_builds",
            route(
                {
                    "/v1/projects": [ScriptedResponse(json=_page("projects", [{"id": "proj-a"}], None))],
                    "/v1/projects/proj-a/services": [
                        ScriptedResponse(
                            json=_page(
                                "services",
                                [
                                    {"id": "svc-deploy", "serviceType": "deployment"},
                                    {"id": "svc-build", "serviceType": "combined"},
                                ],
                                None,
                            )
                        )
                    ],
                    "/v1/projects/proj-a/services/svc-build/build": [
                        ScriptedResponse(json=_page("builds", [{"id": "b1"}], "builds-cursor-2")),
                        ScriptedResponse(json=_page("builds", [{"id": "b2"}], None)),
                    ],
                }
            ),
        )

        assert result.raised is None
        assert result.rows == [
            {"id": "b1", "projectId": "proj-a", "serviceId": "svc-build"},
            {"id": "b2", "projectId": "proj-a", "serviceId": "svc-build"},
        ]
        assert result.paths == [
            "/v1/projects",
            "/v1/projects/proj-a/services",
            "/v1/projects/proj-a/services/svc-build/build",
            "/v1/projects/proj-a/services/svc-build/build",
        ]
        assert result.params("cursor") == [None, None, None, "builds-cursor-2"]
        assert result.saved_states == [
            NorthflankResumeConfig(cursor="builds-cursor-2", project_id="proj-a", parent_id="svc-build"),
            NorthflankResumeConfig(cursor=None, project_id="proj-a", parent_id="svc-build"),
        ]

    @parameterized.expand(
        [
            (
                "mid_parent",
                NorthflankResumeConfig(cursor="runs-cursor-2", project_id="proj-b", parent_id="job-1"),
                ["/v1/projects/proj-b/jobs/job-1/runs", "/v1/projects/proj-b/jobs/job-2/runs"],
                ["r2", "r3"],
            ),
            (
                "parent_done",
                NorthflankResumeConfig(cursor=None, project_id="proj-b", parent_id="job-1"),
                ["/v1/projects/proj-b/jobs/job-2/runs"],
                ["r3"],
            ),
        ]
    )
    def test_nested_fan_out_resumes_from_saved_position(self, _name, resume_state, child_paths, expected_ids):
        result = _driver().run(
            "job_runs",
            route(
                {
                    "/v1/projects": [
                        ScriptedResponse(json=_page("projects", [{"id": "proj-a"}, {"id": "proj-b"}], None))
                    ],
                    "/v1/projects/proj-b/jobs": [
                        ScriptedResponse(json=_page("jobs", [{"id": "job-0"}, {"id": "job-1"}, {"id": "job-2"}], None))
                    ],
                    "/v1/projects/proj-b/jobs/job-1/runs": [ScriptedResponse(json=_page("runs", [{"id": "r2"}], None))],
                    "/v1/projects/proj-b/jobs/job-2/runs": [ScriptedResponse(json=_page("runs", [{"id": "r3"}], None))],
                }
            ),
            resume_state=resume_state,
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == expected_ids
        assert result.paths == ["/v1/projects", "/v1/projects/proj-b/jobs", *child_paths]
        assert result.params("cursor")[2] == resume_state.cursor

    @parameterized.expand(
        [
            ("full_run", None, ["development", "staging", "production"], ["d1", "p1"]),
            (
                "resume_mid_stage",
                NorthflankResumeConfig(
                    cursor="dev-cursor-2", project_id="proj-a", parent_id="pl-1", stage="development"
                ),
                ["development", "staging", "production"],
                ["d1", "p1"],
            ),
            (
                "resume_after_stage",
                NorthflankResumeConfig(cursor=None, project_id="proj-a", parent_id="pl-1", stage="staging"),
                ["production"],
                ["p1"],
            ),
        ]
    )
    def test_release_flow_runs_walk_each_stage(self, _name, resume_state, stages_requested, expected_ids):
        stage_path = "/v1/projects/proj-a/pipelines/pl-1/release-flows/{}/runs"
        result = _driver().run(
            "release_flow_runs",
            route(
                {
                    "/v1/projects": [ScriptedResponse(json=_page("projects", [{"id": "proj-a"}], None))],
                    "/v1/projects/proj-a/pipelines": [
                        ScriptedResponse(json=_page("pipelines", [{"id": "pl-1"}], None))
                    ],
                    stage_path.format("development"): [ScriptedResponse(json=_page("runs", [{"id": "d1"}], None))],
                    # A stage without a release flow 404s.
                    stage_path.format("staging"): [ScriptedResponse(status=404, json={})],
                    stage_path.format("production"): [ScriptedResponse(json=_page("runs", [{"id": "p1"}], None))],
                }
            ),
            resume_state=resume_state,
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == expected_ids
        assert all(row["projectId"] == "proj-a" and row["pipelineId"] == "pl-1" for row in result.rows)
        stage_by_id = {"d1": "development", "p1": "production"}
        assert [row["stage"] for row in result.rows] == [stage_by_id[row_id] for row_id in expected_ids]
        assert result.paths[2:] == [stage_path.format(stage) for stage in stages_requested]
        assert result.params("cursor")[2] == (resume_state.cursor if resume_state else None)
        assert result.saved_states[-1] == NorthflankResumeConfig(
            cursor=None, project_id="proj-a", parent_id="pl-1", stage="production"
        )

    @parameterized.expand(
        [
            ("job_builds_skips_missing", "job_builds", "jobs", "jobs", "/v1/projects/proj-a/jobs/j1/build", False),
            ("job_runs_raises", "job_runs", "jobs", "jobs", "/v1/projects/proj-a/jobs/j1/runs", True),
            # The workflow list nests its rows under `data.pipelines`.
            (
                "workflow_runs_raises",
                "workflow_runs",
                "workflows",
                "pipelines",
                "/v1/projects/proj-a/workflows/j1/runs",
                True,
            ),
        ]
    )
    def test_child_not_found(self, _name, endpoint, parent_resource, parent_data_key, child_path, raises):
        result = _driver().run(
            endpoint,
            route(
                {
                    "/v1/projects": [ScriptedResponse(json=_page("projects", [{"id": "proj-a"}], None))],
                    f"/v1/projects/proj-a/{parent_resource}": [
                        ScriptedResponse(json=_page(parent_data_key, [{"id": "j1"}], None))
                    ],
                    child_path: [ScriptedResponse(status=404, json={})],
                }
            ),
        )

        assert result.paths == ["/v1/projects", f"/v1/projects/proj-a/{parent_resource}", child_path]
        assert result.rows == []
        if raises:
            assert isinstance(result.raised, requests.HTTPError)
            assert "404 Client Error" in str(result.raised)
        else:
            assert result.raised is None

    def test_project_without_id_raises(self):
        # A project missing its id would silently drop all of its nested resources; fail loudly instead.
        result = _driver().run("services", [ScriptedResponse(json=_page("projects", [{"name": "no id"}], None))])

        assert isinstance(result.raised, ValueError)
        assert "missing a required 'id' field" in str(result.raised)
        assert result.paths == ["/v1/projects"]


class TestTopLevelRequestShaping:
    @parameterized.expand(
        [
            (
                "usage_full_refresh",
                "usage",
                {},
                {"perPage": "100", "removeLegacyFields": "true", "startTime": "0", "per_page": None},
            ),
            (
                "usage_incremental",
                "usage",
                {"incremental_field": "timestamp", "db_incremental_field_last_value": 1767225600.0},
                {"perPage": "100", "removeLegacyFields": "true", "startTime": "1767225600", "per_page": None},
            ),
            ("plans_unpaginated", "plans", {}, {"per_page": None, "cursor": None}),
        ]
    )
    def test_request_params(self, _name, endpoint, inputs, expected_params):
        result = _driver().run(
            endpoint, [ScriptedResponse(json={"data": {endpoint: [{"timestamp": 1767225600, "id": "x"}]}})], **inputs
        )

        assert result.raised is None
        assert len(result.rows) == 1
        assert len(result.requests) == 1
        for name, value in expected_params.items():
            assert result.params(name) == [value]


class TestRetryBehavior:
    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(PATCH_SESSION)
    def test_429_honors_rate_limit_header(self, mock_session, mock_sleep):
        mock_session.return_value.get.side_effect = [
            _response({}, status_code=429, headers={"retry-after": "7"}),
            _response(_page("projects", [{"id": "p1"}], None)),
        ]

        rows = [row for batch in get_rows("token", "projects", mock.MagicMock()) for row in batch]

        assert [row["id"] for row in rows] == ["p1"]
        mock_sleep.assert_called_once_with(7)

    def test_5xx_retries_then_succeeds(self):
        result = _driver().run(
            "projects",
            [
                ScriptedResponse(status=503, json={}),
                ScriptedResponse(json=_page("projects", [{"id": "p1"}], None)),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["p1"]
        assert result.paths == ["/v1/projects", "/v1/projects"]

    def test_persistent_5xx_raises(self):
        result = _driver().run("projects", always(ScriptedResponse(status=500, json={})))

        assert isinstance(result.raised, NorthflankRetryableError)
        assert result.paths == ["/v1/projects"] * 5

    def test_4xx_raises_immediately(self):
        result = _driver().run("projects", [ScriptedResponse(status=401, json={})])

        assert isinstance(result.raised, requests.HTTPError)
        assert "401 Client Error" in str(result.raised)
        assert result.paths == ["/v1/projects"]


class TestNorthflankSourceResponse:
    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_response_metadata_per_endpoint(self, endpoint):
        config = NORTHFLANK_ENDPOINTS[endpoint]
        response = northflank_source("token", endpoint, mock.MagicMock())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_fan_out_children_key_includes_project(self, endpoint):
        config = NORTHFLANK_ENDPOINTS[endpoint]
        # A fan-out child's id is only unique within its project, so the key must include projectId
        # or duplicate rows accumulate and every merge multi-matches them.
        if config.fan_out_over_projects:
            assert "projectId" in config.primary_keys

from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.circleci.circleci import (
    CIRCLECI_V2,
    CIRCLECI_V3,
    V3_PROJECTS_PAGE_LIMIT,
    CircleCIResumeConfig,
    CircleCIRetryableError,
    _rate_limit_sleep_seconds,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.circleci.settings import (
    CIRCLECI_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.circleci.source import CircleCISource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.circleci import (
    CircleCISourceConfig,
)

PATCH_SESSION = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.circleci.circleci.make_tracked_session"
)


def _make_manager(resume_state: CircleCIResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(
    body: dict[str, Any] | ScriptedResponse, status_code: int = 200, headers: dict[str, str] | None = None
) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.headers = headers or {}
    response.json.return_value = body.json if isinstance(body, ScriptedResponse) else body
    return response


def _page(items: list[dict[str, Any]], next_token: str | None) -> ScriptedResponse:
    return ScriptedResponse(json={"items": items, "next_page_token": next_token})


def _driver() -> SourceDriver:
    return SourceDriver(CircleCISource(), CircleCISourceConfig(api_token="token", org_slug="gh/posthog"))


class TestRateLimitSleep:
    @parameterized.expand(
        [
            ({"retry-after": "5"}, 5),
            ({"ratelimit-reset": "30"}, 30),
            ({"x-ratelimit-reset": "12"}, 12),
            ({"retry-after": "9999"}, 120),
            ({"retry-after": "-3"}, 0),
            ({"retry-after": "not-a-number"}, 0),
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
            (200, 200, True),
            (200, 404, False),
            (200, 403, False),
        ]
    )
    def test_status_mapping(self, me_status, pipeline_status, expected):
        responses = [ScriptedResponse(status=me_status, json={})]
        if pipeline_status is not None:
            responses.append(ScriptedResponse(status=pipeline_status, json={"items": [], "next_page_token": None}))

        with scripted_network(responses) as network:
            is_valid, error = validate_credentials("token", "gh/posthog", CIRCLECI_V2)

        assert is_valid is expected
        assert (error is None) is expected
        assert network.requests_log[0].path == "/api/v2/me"
        if pipeline_status is not None:
            assert network.requests_log[-1].param("org-slug") == "gh/posthog"

    def test_swallows_connection_errors(self):
        with scripted_network([ConnectionResetError("boom")]):
            is_valid, error = validate_credentials("token", "gh/posthog", CIRCLECI_V2)

        assert is_valid is False
        assert error is not None

    def test_sends_circle_token_header(self):
        with scripted_network([ScriptedResponse(json={})]) as network:
            validate_credentials("token", None, CIRCLECI_V2)

        assert network.requests_log[0].headers["circle-token"] == "token"
        assert network.session_options[0]["redact_values"] == ("token",)

    @parameterized.expand(
        [
            ("valid", [{"id": "org-uuid", "slug": "gh/posthog"}], 200, True),
            ("org not visible to the token", [{"id": "other-uuid", "slug": "gh/other"}], None, False),
            ("v3 rejects the token", [{"id": "org-uuid", "slug": "gh/posthog"}], 401, False),
        ]
    )
    def test_v3_probes_org_projects_with_bearer_token(self, _name, collaborations, v3_status, expected):
        responses = [ScriptedResponse(json={}), ScriptedResponse(json=collaborations)]
        if v3_status is not None:
            responses.append(ScriptedResponse(status=v3_status, json={"data": [], "page": {"next": None}}))

        with scripted_network(responses) as network:
            is_valid, error = validate_credentials("token", "gh/posthog", CIRCLECI_V3)

        assert is_valid is expected
        assert (error is None) is expected
        if v3_status is not None:
            v3_call = network.requests_log[-1]
            assert v3_call.path == "/api/v3/projects"
            assert v3_call.param("filter[org_id]") == "org-uuid"
            assert v3_call.headers["authorization"] == "Bearer token"


class TestPipelinesRows:
    def test_state_saved_after_yield_not_before(self):
        result = _driver().run(
            "pipelines", [_page([{"id": "p1"}], "token-2"), _page([], None)], api_version=CIRCLECI_V2
        )

        assert result.raised is None
        assert result.rows == [{"id": "p1"}]
        assert result.params("page-token") == [None, "token-2"]
        assert result.saved_states == [CircleCIResumeConfig(next_page_token="token-2")]
        assert result.committed_states == []

    def test_unknown_endpoint_raises(self):
        with pytest.raises(ValueError, match="Unknown CircleCI endpoint"):
            list(get_rows("token", "gh/posthog", "nope", mock.MagicMock(), _make_manager(), CIRCLECI_V2))


class TestRetryBehavior:
    # Patch the sleep tenacity actually uses; the wait time is computed by `_retry_wait`, so a
    # single sleep of exactly `retry_after` proves we honor the header without double-waiting.
    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(PATCH_SESSION)
    def test_429_honors_rate_limit_headers_then_retries(self, mock_session, mock_sleep):
        mock_session.return_value.get.side_effect = [
            _response({}, status_code=429, headers={"retry-after": "7"}),
            _response(_page([{"id": "p1"}], None)),
        ]

        manager = _make_manager()
        batches = list(get_rows("token", "gh/posthog", "pipelines", mock.MagicMock(), manager, CIRCLECI_V2))

        assert [item["id"] for batch in batches for item in batch] == ["p1"]
        mock_sleep.assert_called_once_with(7)

    def test_5xx_retries_then_succeeds(self):
        result = _driver().run(
            "pipelines", [ScriptedResponse(status=503, json={}), _page([{"id": "p1"}], None)], api_version=CIRCLECI_V2
        )

        assert result.raised is None
        assert [item["id"] for item in result.rows] == ["p1"]
        assert result.paths == ["/api/v2/pipeline", "/api/v2/pipeline"]

    def test_persistent_5xx_raises_after_max_retries(self):
        result = _driver().run("pipelines", always(ScriptedResponse(status=500)), api_version=CIRCLECI_V2)

        assert isinstance(result.raised, CircleCIRetryableError)
        assert set(result.paths) == {"/api/v2/pipeline"}

    def test_4xx_raises_immediately(self):
        result = _driver().run("pipelines", [ScriptedResponse(status=401, json={})], api_version=CIRCLECI_V2)

        assert isinstance(result.raised, requests.HTTPError)
        assert "401 Client Error" in str(result.raised)
        assert len(result.requests) == 1


class TestWorkflowsFanOut:
    def test_saves_pipeline_scan_state_after_fanout_page(self):
        result = _driver().run(
            "workflows",
            route(
                {
                    "/api/v2/pipeline": [
                        _page([{"id": "p1"}], "pipeline-token-2"),
                        _page([], None),
                    ],
                    "/api/v2/pipeline/p1/workflow": [_page([{"id": "w1", "pipeline_id": "p1"}], None)],
                }
            ),
            api_version=CIRCLECI_V2,
        )

        assert result.raised is None
        assert result.rows == [{"id": "w1", "pipeline_id": "p1"}]
        assert result.saved_states == [CircleCIResumeConfig(next_page_token="pipeline-token-2")]


class TestJobsFanOut:
    def test_jobs_traverse_every_workflow_of_every_pipeline(self):
        result = _driver().run(
            "jobs",
            route(
                {
                    "/api/v2/pipeline": [_page([{"id": "p1"}, {"id": "p2"}], None)],
                    "/api/v2/pipeline/p1/workflow": [_page([{"id": "w1"}, {"id": "w2"}], None)],
                    "/api/v2/pipeline/p2/workflow": [_page([{"id": "w3"}], None)],
                    "/api/v2/workflow/w1/job": [_page([{"id": "j1"}], None)],
                    "/api/v2/workflow/w2/job": [_page([{"id": "j2"}], None)],
                    "/api/v2/workflow/w3/job": [_page([{"id": "j3"}], None)],
                }
            ),
            api_version=CIRCLECI_V2,
        )
        assert result.raised is None
        assert [(row["id"], row["pipeline_id"], row["workflow_id"]) for row in result.rows] == [
            ("j1", "p1", "w1"),
            ("j2", "p1", "w2"),
            ("j3", "p2", "w3"),
        ]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.circleci.circleci.MAX_JOB_PAGES_PER_WORKFLOW",
        2,
    )
    def test_job_page_cap_logs_workflow_identifier(self):
        logger = mock.MagicMock()
        result = _driver().run(
            "jobs",
            route(
                {
                    "/api/v2/pipeline": [_page([{"id": "p1"}], None)],
                    "/api/v2/pipeline/p1/workflow": [_page([{"id": "w1"}], None)],
                    "/api/v2/workflow/w1/job": [
                        _page([{"id": "ja"}], "t2"),
                        _page([{"id": "jb"}], "t3"),
                        _page([{"id": "jc"}], "t4"),
                    ],
                }
            ),
            logger=logger,
            api_version=CIRCLECI_V2,
        )

        assert result.raised is None
        assert len(result.rows) == 2
        logger.warning.assert_called_once()
        assert "page cap" in logger.warning.call_args.args[0]
        assert "w1" in logger.warning.call_args.args[0]


class TestProjectsRows:
    def test_distinct_project_slugs_resolved_once(self):
        result = _driver().run(
            "projects",
            route(
                {
                    "/api/v2/pipeline": [
                        _page(
                            [
                                {"id": "p1", "project_slug": "gh/posthog/posthog"},
                                {"id": "p2", "project_slug": "gh/posthog/posthog"},
                                {"id": "p3", "project_slug": "gh/posthog/posthog.com"},
                                {"id": "p4"},
                            ],
                            None,
                        )
                    ],
                    "/api/v2/project/gh/posthog/posthog": [
                        ScriptedResponse(json={"id": "proj-1", "slug": "gh/posthog/posthog"})
                    ],
                    "/api/v2/project/gh/posthog/posthog.com": [
                        ScriptedResponse(json={"id": "proj-2", "slug": "gh/posthog/posthog.com"})
                    ],
                }
            ),
            api_version=CIRCLECI_V2,
        )
        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["proj-1", "proj-2"]
        assert len([path for path in result.paths if "/project/" in path]) == 2


COLLABORATIONS_PATH = "/api/v2/me/collaborations"
COLLABORATIONS = [{"id": "org-uuid", "slug": "gh/posthog", "name": "PostHog"}]


class TestComponentsRows:
    def test_resumes_from_saved_component_page_token(self):
        result = _driver().run(
            "components",
            route(
                {
                    COLLABORATIONS_PATH: [ScriptedResponse(json=COLLABORATIONS)],
                    "/api/v2/deploy/components": [_page([{"id": "c9"}], None)],
                }
            ),
            resume_state=CircleCIResumeConfig(next_page_token="resume-token"),
            api_version=CIRCLECI_V2,
        )

        assert result.raised is None
        assert result.rows == [{"id": "c9"}]
        component_request = next(request for request in result.requests if "/deploy/components" in request.path)
        assert component_request.param("page-token") == "resume-token"

    @parameterized.expand(
        [
            (endpoint, name, collaborations)
            for endpoint in ("components", "environments", "groups")
            for name, collaborations in (
                ("slug not visible to the token", [{"id": "other-uuid", "slug": "gh/other"}]),
                ("collaboration without an id", [{"id": None, "slug": "gh/posthog"}]),
            )
        ]
    )
    def test_unresolvable_org_raises_with_slug(self, endpoint, _name, collaborations):
        result = _driver().run(endpoint, [ScriptedResponse(json=collaborations)], api_version=CIRCLECI_V2)

        assert isinstance(result.raised, ValueError)
        assert "gh/posthog" in str(result.raised)
        assert result.paths == [COLLABORATIONS_PATH]


class TestOrgListRows:
    @parameterized.expand(
        [
            ("components", "/api/v2/deploy/components", {"org-id": "org-uuid", "page-size": "20"}),
            ("environments", "/api/v2/deploy/environments", {"org-id": "org-uuid", "page-size": "20"}),
            ("groups", "/api/v2/organizations/org-uuid/groups", {}),
        ]
    )
    def test_walks_every_page_of_the_resolved_org(self, endpoint, path, expected_params):
        result = _driver().run(
            endpoint,
            route(
                {
                    COLLABORATIONS_PATH: [ScriptedResponse(json=COLLABORATIONS)],
                    path: [
                        _page([{"id": "a", "created_at": "2026-01-01T00:00:00Z"}], "token-2"),
                        _page([], "token-3"),
                        _page([{"id": "b", "created_at": "2026-01-02T00:00:00Z"}], None),
                    ],
                }
            ),
            api_version=CIRCLECI_V3,
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["a", "b"]
        assert result.paths == [COLLABORATIONS_PATH, path, path, path]
        list_requests = [request for request in result.requests if request.path == path]
        assert all({key: request.param(key) for key in expected_params} == expected_params for request in list_requests)
        assert [request.param("page-token") for request in list_requests] == [None, "token-2", "token-3"]
        assert result.saved_states == [
            CircleCIResumeConfig(next_page_token="token-2"),
            CircleCIResumeConfig(next_page_token="token-3"),
        ]


class TestCollaborationsRows:
    def test_yields_every_org_the_token_sees_in_one_request(self):
        collaborations = [
            {"id": "org-uuid", "slug": "gh/posthog", "name": "PostHog", "vcs-type": "github"},
            {"id": "other-uuid", "slug": "bb/other", "name": "Other", "vcs-type": "bitbucket"},
            {"id": None, "slug": "circleci/standalone", "name": "Standalone", "vcs-type": "circleci"},
        ]
        result = _driver().run("collaborations", [ScriptedResponse(json=collaborations)], api_version=CIRCLECI_V3)

        assert result.raised is None
        assert result.rows == collaborations
        assert result.paths == [COLLABORATIONS_PATH]
        assert result.saved_states == []

    def test_empty_collaborations_yield_no_rows(self):
        result = _driver().run("collaborations", [ScriptedResponse(json=[])], api_version=CIRCLECI_V2)

        assert result.raised is None
        assert result.rows == []


class TestComponentVersionsFanOut:
    def test_versions_carry_component_id_and_never_null_merge_keys(self):
        result = _driver().run(
            "component_versions",
            route(
                {
                    COLLABORATIONS_PATH: [ScriptedResponse(json=COLLABORATIONS)],
                    "/api/v2/deploy/components": [_page([{"id": "c1"}, {"id": "c2"}], None)],
                    "/api/v2/deploy/components/c1/versions": [
                        _page(
                            [
                                {
                                    "name": "1.0.0",
                                    "environment_id": "env-1",
                                    "namespace": "default",
                                    "is_live": True,
                                    "last_deployed_at": "2026-01-01T00:00:00Z",
                                },
                                {"name": "1.0.1", "environment_id": None},
                            ],
                            None,
                        )
                    ],
                    "/api/v2/deploy/components/c2/versions": [
                        _page([{"name": "2.0.0", "environment_id": "env-2"}], None)
                    ],
                }
            ),
            api_version=CIRCLECI_V2,
        )
        assert result.raised is None
        rows = result.rows

        assert [(row["component_id"], row["name"]) for row in rows] == [
            ("c1", "1.0.0"),
            ("c1", "1.0.1"),
            ("c2", "2.0.0"),
        ]
        # Native fields survive the injection.
        assert rows[0]["is_live"] is True
        assert rows[0]["namespace"] == "default"
        # A missing part of the composite key becomes "" so merges match instead of re-inserting.
        assert rows[1]["environment_id"] == ""
        assert rows[1]["namespace"] == ""

    def test_repeated_page_token_fails_the_run(self):
        # The versions endpoint documents no page-token param; if it ignores ours it hands
        # back the same token forever. Truncating there would publish a partial table.
        result = _driver().run(
            "component_versions",
            route(
                {
                    COLLABORATIONS_PATH: [ScriptedResponse(json=COLLABORATIONS)],
                    "/api/v2/deploy/components": [_page([{"id": "c1"}], None)],
                    "/api/v2/deploy/components/c1/versions": [
                        _page([{"name": "1.0.0"}], "same-token"),
                        _page([{"name": "1.0.0"}], "same-token"),
                    ],
                }
            ),
            api_version=CIRCLECI_V2,
        )

        assert isinstance(result.raised, ValueError)
        assert "same page token twice" in str(result.raised)


class TestUsersRows:
    def test_deleted_actor_is_skipped(self):
        result = _driver().run(
            "users",
            route(
                {
                    "/api/v2/pipeline": [_page([{"id": "p1"}], None)],
                    "/api/v2/pipeline/p1/workflow": [
                        _page([{"id": "w1", "started_by": "gone", "canceled_by": "u2"}], None)
                    ],
                    "/api/v2/user/gone": [ScriptedResponse(status=404, json={})],
                    "/api/v2/user/u2": [ScriptedResponse(json={"id": "u2", "login": "two"})],
                }
            ),
            api_version=CIRCLECI_V2,
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["u2"]
        assert "/api/v2/user/gone" in result.paths


def _v3_page(items: list[dict[str, Any]], next_cursor: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"data": items, "page": {"next": next_cursor, "prev": None}})


class TestV3Rows:
    def test_pipelines_walk_org_projects_into_runs(self):
        result = _driver().run(
            "pipelines",
            route(
                {
                    COLLABORATIONS_PATH: [ScriptedResponse(json=COLLABORATIONS)],
                    "/api/v3/projects": [
                        _v3_page([{"id": "proj-1", "attributes": {"name": "posthog"}}], "projects-cursor-2"),
                        _v3_page([{"id": "proj-2", "attributes": {"name": "other"}}]),
                    ],
                    "/api/v3/runs": [
                        _v3_page(
                            [
                                {
                                    "id": "run-1",
                                    "attributes": {"number": 7, "created_at": "2026-01-01T00:00:00Z", "phase": "ended"},
                                    "references": {"project": {"id": "proj-1"}},
                                }
                            ],
                            "runs-cursor-2",
                        ),
                        _v3_page([{"id": "run-2", "attributes": {"number": 8, "created_at": "2026-01-02T00:00:00Z"}}]),
                        _v3_page([{"id": "run-3", "attributes": {"number": 1, "created_at": "2026-01-03T00:00:00Z"}}]),
                    ],
                }
            ),
            api_version=CIRCLECI_V3,
        )

        # The next projects cursor is staged before the first page's last batch, so the pipeline
        # commits it together with that batch.
        assert result.raised is None
        assert result.saved_states == [CircleCIResumeConfig(page_cursor="projects-cursor-2")]
        assert result.committed_states == [CircleCIResumeConfig(page_cursor="projects-cursor-2")]

        assert [row["id"] for row in result.rows] == ["run-1", "run-2", "run-3"]
        # Attributes are lifted to top-level columns so the created_at partition key resolves.
        assert result.rows[0]["created_at"] == "2026-01-01T00:00:00Z"
        assert result.rows[0]["number"] == 7
        assert result.rows[0]["references"] == {"project": {"id": "proj-1"}}

        v3_calls = [request for request in result.requests if "/api/v3/" in request.path]
        assert all(request.headers["authorization"] == "Bearer token" for request in v3_calls)
        queries = [(request.path, dict(request.query)) for request in v3_calls]
        assert queries == [
            ("/api/v3/projects", {"filter[org_id]": ("org-uuid",), "page[limit]": (str(V3_PROJECTS_PAGE_LIMIT),)}),
            ("/api/v3/runs", {"filter[project_id]": ("proj-1",)}),
            ("/api/v3/runs", {"filter[project_id]": ("proj-1",), "page[cursor]": ("runs-cursor-2",)}),
            (
                "/api/v3/projects",
                {
                    "filter[org_id]": ("org-uuid",),
                    "page[limit]": (str(V3_PROJECTS_PAGE_LIMIT),),
                    "page[cursor]": ("projects-cursor-2",),
                },
            ),
            ("/api/v3/runs", {"filter[project_id]": ("proj-2",)}),
        ]

    def test_resumes_projects_scan_from_saved_cursor(self):
        result = _driver().run(
            "projects",
            route(
                {
                    COLLABORATIONS_PATH: [ScriptedResponse(json=COLLABORATIONS)],
                    "/api/v3/projects": [_v3_page([{"id": "proj-9", "attributes": {}}])],
                }
            ),
            resume_state=CircleCIResumeConfig(page_cursor="resume-cursor"),
            api_version=CIRCLECI_V3,
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["proj-9"]
        project_request = next(request for request in result.requests if request.path == "/api/v3/projects")
        assert project_request.param("page[cursor]") == "resume-cursor"

    def test_job_rows_carry_parent_identifiers(self):
        result = _driver().run(
            "jobs",
            route(
                {
                    COLLABORATIONS_PATH: [ScriptedResponse(json=COLLABORATIONS)],
                    "/api/v3/projects": [_v3_page([{"id": "proj-1", "attributes": {}}])],
                    "/api/v3/runs": [_v3_page([{"id": "run-1", "attributes": {}}])],
                    "/api/v3/workflows": [
                        _v3_page(
                            [{"id": "wf-1", "attributes": {"name": "build", "created_at": "2026-01-01T00:00:00Z"}}]
                        )
                    ],
                    # The v3 jobs collection is not paginated, so it carries no page member.
                    "/api/v3/jobs": [
                        ScriptedResponse(
                            json={
                                "data": [
                                    {
                                        "id": "job-1",
                                        "attributes": {"name": "test", "number": 42, "phase": "ended", "type": "build"},
                                        "references": {"workflow": {"id": "wf-1"}, "project": {"id": "proj-1"}},
                                    }
                                ]
                            }
                        )
                    ],
                }
            ),
            api_version=CIRCLECI_V3,
        )

        assert result.raised is None
        rows = result.rows

        assert len(rows) == 1
        assert rows[0]["id"] == "job-1"
        assert rows[0]["number"] == 42
        assert rows[0]["run_id"] == "run-1"
        assert rows[0]["workflow_id"] == "wf-1"
        assert rows[0]["workflow_created_at"] == "2026-01-01T00:00:00Z"
        assert result.requests[-1].param("filter[workflow_id]") == "wf-1"


class TestCircleCISourceResponse:
    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_response_metadata_per_endpoint(self, endpoint):
        config = CIRCLECI_ENDPOINTS[endpoint]

        def answer(request: RecordedRequest) -> ScriptedResponse:
            if request.path == COLLABORATIONS_PATH:
                return ScriptedResponse(json=COLLABORATIONS)
            return ScriptedResponse(json={"items": [], "next_page_token": None})

        result = _driver().run(endpoint, answer, api_version=CIRCLECI_V2)
        assert result.raised is None
        response = result.response
        assert response is not None

        assert response.name == endpoint
        assert response.primary_keys == list(config.primary_keys)
        assert response.sort_mode == "desc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @parameterized.expand([(config,) for config in CIRCLECI_ENDPOINTS.values()])
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key in {"created_at", "workflow_created_at"}

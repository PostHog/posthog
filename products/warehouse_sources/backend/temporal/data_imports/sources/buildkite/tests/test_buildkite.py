from datetime import UTC, date, datetime
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.buildkite.buildkite import (
    BuildkiteResumeConfig,
    _build_initial_params,
    _format_incremental_value,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.buildkite.settings import BUILDKITE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.buildkite.source import BuildkiteSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.buildkite import (
    BuildkiteSourceConfig,
)

ORG_URL = "https://api.buildkite.com/v2/organizations/my-org"


def _driver() -> SourceDriver:
    return SourceDriver(BuildkiteSource(), BuildkiteSourceConfig(api_access_token="bkua", organization="my-org"))


def _response(body: Any, link: str | None = None) -> ScriptedResponse:
    headers = {"Link": f'<{link}>; rel="next"'} if link else {}
    return ScriptedResponse(json=body, headers=headers)


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format_incremental_value(self, _name: str, value: object, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestBuildInitialParams:
    @parameterized.expand(
        [
            ("organizations",),
            ("organization_members",),
            ("pipelines",),
            ("agents",),
            ("teams",),
            ("test_suites",),
        ]
    )
    def test_full_refresh_endpoints_never_get_a_time_filter(self, endpoint: str) -> None:
        # These endpoints expose no server-side timestamp filter, so an incremental request must
        # not silently add one (it would be ignored by the API and misrepresent the sync).
        params = _build_initial_params(
            BUILDKITE_ENDPOINTS[endpoint],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field="created_at",
        )
        assert params == {"per_page": 100}


class TestPagination:
    def test_follows_link_header_pagination(self) -> None:
        page2 = "https://api.buildkite.com/v2/organizations/my-org/pipelines?page=2&per_page=100"
        result = _driver().run(
            "pipelines",
            [
                _response([{"id": "p1"}, {"id": "p2"}], link=page2),
                _response([{"id": "p3"}]),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["p1", "p2", "p3"]
        assert result.urls[0].split("?")[0] == f"{ORG_URL}/pipelines"
        assert result.requests[0].param("per_page") == "100"
        # The next-page URL is self-contained; the original params must not be re-appended.
        assert result.urls[1] == page2
        assert result.queries[1] == {"page": ("2",), "per_page": ("100",)}

    def test_resumes_from_saved_state(self) -> None:
        resume_url = "https://api.buildkite.com/v2/organizations/my-org/pipelines?page=3&per_page=100"
        result = _driver().run(
            "pipelines", [_response([{"id": "p9"}])], resume_state=BuildkiteResumeConfig(next_url=resume_url)
        )

        # Resume must start at the saved URL, not the freshly-built first-page URL.
        assert result.raised is None
        assert result.urls == [resume_url]
        assert [row["id"] for row in result.rows] == ["p9"]

    def test_incremental_sync_sends_created_from(self) -> None:
        result = _driver().run(
            "builds",
            [_response([{"id": "b1"}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="created_at",
        )

        assert result.raised is None
        assert result.queries == [{"per_page": ("100",), "created_from": ("2026-03-04T02:58:14+00:00",)}]

    def test_non_list_body_fails_loudly(self) -> None:
        # Buildkite list endpoints return a top-level JSON array; a 200 with a non-list body means
        # the response shape changed — fail loud instead of syncing garbage.
        result = _driver().run("pipelines", [_response({"message": "something unexpected"})])

        assert isinstance(result.raised, ValueError)
        assert "list response body" in str(result.raised)


class TestBuildkiteSourceResponse:
    @parameterized.expand(
        [
            ("organizations", ["id"], "asc", "created_at"),
            ("pipelines", ["id"], "asc", "created_at"),
            ("builds", ["id"], "desc", "created_at"),
            ("agents", ["id"], "asc", "created_at"),
            ("teams", ["id"], "asc", "created_at"),
            # A fan-out child carries its parent in the key, because its own id is only unique
            # within that parent once every parent's rows land in one table.
            ("pipeline_schedules", ["pipeline_slug", "id"], "desc", "created_at"),
            ("cluster_queues", ["cluster_id", "id"], "asc", "created_at"),
            # A team-to-pipeline link has no id of its own, so the pair it joins is the key.
            ("team_pipelines", ["team_id", "pipeline_id"], "asc", "created_at"),
            # A member row carries no timestamp, so it is not partitioned.
            ("organization_members", ["id"], "asc", None),
            ("jobs", ["id"], "desc", "build_created_at"),
            ("test_suite_runs", ["suite_slug", "id"], "desc", "created_at"),
            # Suites and tests expose no creation timestamp, so they are not partitioned.
            ("test_suites", ["id"], "asc", None),
            ("test_suite_tests", ["suite_slug", "id"], "asc", None),
        ]
    )
    def test_source_response_shape(
        self, endpoint: str, primary_keys: list[str], sort_mode: str, partition_key: str | None
    ) -> None:
        result = _driver().run(endpoint, [_response([])])

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == sort_mode
        assert response.partition_mode == ("datetime" if partition_key else None)
        assert response.partition_format == ("week" if partition_key else None)
        assert response.partition_keys == ([partition_key] if partition_key else None)


class TestValidateCredentials:
    def test_invalid_token(self) -> None:
        with scripted_network([ScriptedResponse(status=401)]) as network:
            ok, error = validate_credentials("bkua", "my-org")

        assert ok is False
        assert error is not None and "invalid" in error.lower()
        assert network.requests_log[0].path == "/v2/organizations/my-org"

    def test_forbidden_accepted_at_source_create(self) -> None:
        # A valid token may lack read_organizations while still holding the per-endpoint scopes the
        # user wants — so a 403 at source-create (schema_name=None) must not block connecting.
        with scripted_network([ScriptedResponse(status=403)]) as network:
            assert validate_credentials("bkua", "my-org") == (True, None)

        assert network.requests_log[0].path == "/v2/organizations/my-org"

    def test_forbidden_rejected_for_specific_schema(self) -> None:
        with scripted_network([ScriptedResponse(status=403)]) as network:
            ok, error = validate_credentials("bkua", "my-org", schema_name="builds")

        assert ok is False
        assert error is not None and "builds" in error
        assert network.requests_log[0].path == "/v2/organizations/my-org/builds"

    def test_org_not_found(self) -> None:
        with scripted_network([ScriptedResponse(status=404)]) as network:
            ok, error = validate_credentials("bkua", "missing-org")

        assert ok is False
        assert error is not None and "missing-org" in error
        assert network.requests_log[0].path == "/v2/organizations/missing-org"

    @parameterized.expand(
        [
            ("test_suite_runs", "https://api.buildkite.com/v2/analytics/organizations/my-org/suites?per_page=1"),
            ("test_suite_tests", "https://api.buildkite.com/v2/analytics/organizations/my-org/suites?per_page=1"),
            ("team_pipelines", f"{ORG_URL}/teams?per_page=1"),
            ("pipeline_schedules", f"{ORG_URL}/pipelines?per_page=1"),
            ("cluster_queues", f"{ORG_URL}/clusters?per_page=1"),
            ("team_members", f"{ORG_URL}/teams?per_page=1"),
            ("artifacts", f"{ORG_URL}/builds?per_page=1"),
            ("annotations", f"{ORG_URL}/builds?per_page=1"),
        ]
    )
    def test_fanout_schema_probe_targets_the_parent_listing(self, endpoint: str, expected_url: str) -> None:
        # A fan-out child's own path needs a parent row, so the probe hits the listing that
        # carries the same scope. Formatting the child path here would raise on the parent
        # placeholder it still carries, such as {suite_slug} or {team_id}.
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials("bkua", "my-org", schema_name=endpoint)

        assert network.requests_log[0].url == expected_url
        assert network.requests_log[0].headers["authorization"] == "Bearer bkua"


class TestSuiteFanout:
    @parameterized.expand([("test_suite_runs", "runs"), ("test_suite_tests", "tests")])
    def test_fans_out_over_every_suite(self, endpoint: str, path_segment: str) -> None:
        base = "https://api.buildkite.com/v2/analytics/organizations/my-org/suites"
        result = _driver().run(
            endpoint,
            [
                _response([{"id": "s1", "slug": "web"}, {"id": "s2", "slug": "api"}]),
                _response([{"id": "a"}]),
                _response([{"id": "b"}]),
            ],
        )

        assert result.raised is None
        assert result.urls[0] == base
        # The suites listing takes no page-size param; only the children are paginated.
        assert result.queries[0] == {}
        assert result.paths[1:] == [
            f"/v2/analytics/organizations/my-org/suites/web/{path_segment}",
            f"/v2/analytics/organizations/my-org/suites/api/{path_segment}",
        ]
        assert result.requests[1].param("per_page") == "100"
        # Runs and tests are only identified within their suite, so the suite has to reach the row
        # for the composite primary key to be unique table-wide.
        assert [(row["id"], row["suite_id"], row["suite_slug"]) for row in result.rows] == [
            ("a", "s1", "web"),
            ("b", "s2", "api"),
        ]


class TestSimpleFanout:
    @parameterized.expand(
        [
            (
                "team_pipelines",
                [{"id": "t1", "slug": "backend"}, {"id": "t2", "slug": "frontend"}],
                f"{ORG_URL}/teams",
                [f"{ORG_URL}/teams/t1/pipelines", f"{ORG_URL}/teams/t2/pipelines"],
                [{"pipeline_id": "p1"}, {"pipeline_id": "p2"}],
                [{"team_id": "t1", "team_slug": "backend"}, {"team_id": "t2", "team_slug": "frontend"}],
            ),
            (
                "pipeline_schedules",
                [{"id": "pl1", "slug": "web"}, {"id": "pl2", "slug": "api"}],
                f"{ORG_URL}/pipelines",
                [f"{ORG_URL}/pipelines/web/schedules", f"{ORG_URL}/pipelines/api/schedules"],
                [{"id": "s1"}, {"id": "s2"}],
                [{"pipeline_slug": "web"}, {"pipeline_slug": "api"}],
            ),
            (
                "team_members",
                [{"id": "t1", "slug": "backend"}, {"id": "t2", "slug": "frontend"}],
                f"{ORG_URL}/teams",
                [f"{ORG_URL}/teams/t1/members", f"{ORG_URL}/teams/t2/members"],
                [{"user_id": "u1", "role": "member"}, {"user_id": "u1", "role": "maintainer"}],
                [{"team_id": "t1", "team_slug": "backend"}, {"team_id": "t2", "team_slug": "frontend"}],
            ),
            (
                "cluster_queues",
                [{"id": "c1"}, {"id": "c2"}],
                f"{ORG_URL}/clusters",
                [f"{ORG_URL}/clusters/c1/queues", f"{ORG_URL}/clusters/c2/queues"],
                [{"id": "q1"}, {"id": "q2"}],
                [{"cluster_id": "c1"}, {"cluster_id": "c2"}],
            ),
        ]
    )
    def test_binds_the_parent_path_and_carries_the_parent_onto_each_row(
        self,
        endpoint: str,
        parent_rows: list[dict[str, Any]],
        parent_url: str,
        child_urls: list[str],
        child_rows: list[dict[str, Any]],
        parent_columns: list[dict[str, Any]],
    ) -> None:
        result = _driver().run(
            endpoint, [_response(parent_rows), _response([child_rows[0]]), _response([child_rows[1]])]
        )

        assert result.raised is None
        assert result.urls[0].split("?")[0] == parent_url
        assert result.requests[0].param("per_page") == "100"
        assert [url.split("?")[0] for url in result.urls[1:]] == child_urls
        # The parent identifier has to land on the row under its final column name, because the
        # composite primary key keys on it. A missing rename leaves the key with no column.
        assert result.rows == [{**child_rows[i], **parent_columns[i]} for i in (0, 1)]


class TestJobsFanout:
    @staticmethod
    def _builds_page() -> ScriptedResponse:
        return _response(
            [{"id": "b1", "number": 42, "created_at": "2026-03-04T02:58:14Z", "pipeline": {"slug": "web"}}]
        )

    @staticmethod
    def _jobs_page(job_ids: list[str], next_url: str | None = None) -> ScriptedResponse:
        # The jobs endpoint answers with an envelope and paginates on a cursor URL in the body,
        # unlike every other Buildkite list endpoint.
        return _response(
            {"items": [{"id": job_id} for job_id in job_ids], "links": {"next": next_url} if next_url else {}}
        )

    def test_incremental_windows_the_parent_build_walk(self) -> None:
        result = _driver().run(
            "jobs",
            [self._builds_page(), self._jobs_page(["j1"])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="build_created_at",
        )

        # Jobs carry no server-side time filter, so the watermark has to bound the builds request
        # that drives the fan-out — otherwise every sync re-walks the whole organization.
        assert result.raised is None
        assert result.requests[0].param("created_from") == "2026-03-04T02:58:14+00:00"
        assert result.requests[0].param("per_page") == "100"
        assert result.requests[1].param("created_from") is None


class TestBuildChildFanout:
    @parameterized.expand(
        [
            ("artifacts", {}),
            # Without scope=all the listing drops every job-scoped annotation.
            ("annotations", {"scope": ("all",)}),
        ]
    )
    def test_walks_every_page_of_each_build_inside_the_incremental_window(
        self, endpoint: str, extra_query: dict[str, tuple[str, ...]]
    ) -> None:
        child_base = f"{ORG_URL}/pipelines/web/builds/42/{endpoint}"
        page2 = f"{child_base}?page=2&per_page=100"
        result = _driver().run(
            endpoint,
            [
                _response(
                    [{"id": "b1", "number": 42, "created_at": "2026-03-04T02:58:14Z", "pipeline": {"slug": "web"}}]
                ),
                # Unlike jobs, these children are top-level arrays paginated on a Link header.
                _response([{"id": "x1"}], link=page2),
                _response([{"id": "x2"}]),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="build_created_at",
        )

        assert result.raised is None
        assert result.requests[0].param("created_from") == "2026-03-04T02:58:14+00:00"
        assert result.urls[1].split("?")[0] == child_base
        assert result.queries[1] == {"per_page": ("100",), **extra_query}
        assert result.urls[2] == page2
        # The build id is part of the primary key, and build_created_at is the incremental cursor.
        assert [
            (row["id"], row["build_id"], row["build_number"], row["pipeline_slug"], row["build_created_at"])
            for row in result.rows
        ] == [
            ("x1", "b1", 42, "web", "2026-03-04T02:58:14Z"),
            ("x2", "b1", 42, "web", "2026-03-04T02:58:14Z"),
        ]

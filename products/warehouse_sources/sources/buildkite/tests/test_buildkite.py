from datetime import UTC, date, datetime
from typing import Any

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.sources.buildkite._config import BuildkiteSourceConfig
from products.warehouse_sources.sources.buildkite.buildkite import (
    BuildkiteResumeConfig,
    _build_initial_params,
    _format_incremental_value,
    _usage_windows,
    validate_credentials,
)
from products.warehouse_sources.sources.buildkite.settings import BUILDKITE_ENDPOINTS
from products.warehouse_sources.sources.buildkite.source import BuildkiteSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, scripted_network

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
            ("team_suites", ["team_id", "suite_id"], "asc", "created_at"),
            ("audit_events", ["uuid"], "desc", "occurred_at"),
            ("build_tests", ["build_id", "id"], "desc", "build_created_at"),
        ]
    )
    def test_source_response_shape(
        self, endpoint: str, primary_keys: list[str], sort_mode: str, partition_key: str | None
    ) -> None:
        result = _driver().run(endpoint, [_response({"items": []} if endpoint == "audit_events" else [])])

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
            ("team_suites", f"{ORG_URL}/teams?per_page=1"),
            ("build_tests", "https://api.buildkite.com/v2/analytics/organizations/my-org/suites?per_page=1"),
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
                "team_suites",
                [{"id": "t1", "slug": "backend"}, {"id": "t2", "slug": "frontend"}],
                f"{ORG_URL}/teams",
                [f"{ORG_URL}/teams/t1/suites", f"{ORG_URL}/teams/t2/suites"],
                [{"suite_id": "s1", "access_level": ["read"]}, {"suite_id": "s1", "access_level": ["read", "edit"]}],
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
        assert result.requests[0].param("exclude_jobs") == "true"
        assert result.requests[1].param("created_from") is None


def _build(build_id: str, created_at: str, finished_at: str | None) -> dict[str, Any]:
    return {
        "id": build_id,
        "number": 1,
        "pipeline": {"slug": "web"},
        "created_at": created_at,
        "finished_at": finished_at,
    }


class TestBuildChildFanout:
    @parameterized.expand(
        [
            ("artifacts", f"{ORG_URL}/pipelines/web/builds/42/artifacts", {}, "2026-03-04T02:58:14+00:00"),
            # Without scope=all the listing drops every job-scoped annotation.
            (
                "annotations",
                f"{ORG_URL}/pipelines/web/builds/42/annotations",
                {"scope": ("all",)},
                "2026-03-04T02:58:14+00:00",
            ),
            # Test Engine addresses a build by its id, not by pipeline and number, and its window
            # starts a day early to revisit unfinished builds.
            (
                "build_tests",
                "https://api.buildkite.com/v2/analytics/organizations/my-org/builds/b1/tests",
                {},
                "2026-03-03T02:58:14+00:00",
            ),
        ]
    )
    def test_walks_every_page_of_each_build_inside_the_incremental_window(
        self, endpoint: str, child_base: str, extra_query: dict[str, tuple[str, ...]], created_from: str
    ) -> None:
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
        assert result.requests[0].param("created_from") == created_from
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

    def test_build_tests_revisits_only_builds_unfinished_at_the_watermark(self) -> None:
        result = _driver().run(
            "build_tests",
            [
                _response(
                    [
                        _build("new", "2026-03-04T03:00:00Z", None),
                        _build("running", "2026-03-04T01:00:00Z", None),
                        _build("finished_later", "2026-03-04T01:00:00Z", "2026-03-04T04:00:00Z"),
                        _build("finished_before", "2026-03-04T01:00:00Z", "2026-03-04T02:00:00Z"),
                    ]
                ),
                _response([{"id": "t1"}]),
                _response([{"id": "t2"}]),
                _response([{"id": "t3"}]),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-03-04T02:58:14Z",
            incremental_field="build_created_at",
        )

        assert result.raised is None
        assert [url.split("?")[0].split("/")[-2] for url in result.urls[1:]] == ["new", "running", "finished_later"]
        assert [(row["id"], row["build_id"]) for row in result.rows] == [
            ("t1", "new"),
            ("t2", "running"),
            ("t3", "finished_later"),
        ]


class TestAuditEvents:
    def test_follows_the_body_cursor_and_reads_the_items_envelope(self) -> None:
        page2 = f"{ORG_URL}/audit_events?per_page=100&after=cursor1"
        result = _driver().run(
            "audit_events",
            [
                _response({"items": [{"uuid": "e1"}, {"uuid": "e2"}], "links": {"next": page2}}),
                _response({"items": [{"uuid": "e3"}], "links": {}}),
            ],
        )

        assert result.raised is None
        assert result.urls[0].split("?")[0] == f"{ORG_URL}/audit_events"
        assert result.requests[0].param("per_page") == "100"
        assert result.urls[1] == page2
        assert [row["uuid"] for row in result.rows] == ["e1", "e2", "e3"]


class TestUsageWindows:
    @parameterized.expand(
        [
            (
                # The lookback ends mid-August, so the cut August is left out.
                "mid_month",
                date(2026, 11, 21),
                None,
                [
                    (date(2026, 9, 1), date(2026, 9, 30)),
                    (date(2026, 10, 1), date(2026, 10, 31)),
                    (date(2026, 11, 1), date(2026, 11, 21)),
                ],
            ),
            (
                "lookback_on_a_month_start",
                date(2026, 11, 1),
                None,
                [
                    (date(2026, 8, 1), date(2026, 8, 31)),
                    (date(2026, 9, 1), date(2026, 9, 30)),
                    (date(2026, 10, 1), date(2026, 10, 31)),
                    (date(2026, 11, 1), date(2026, 11, 1)),
                ],
            ),
            (
                "short_month_lookback",
                date(2026, 5, 31),
                None,
                [
                    (date(2026, 3, 1), date(2026, 3, 31)),
                    (date(2026, 4, 1), date(2026, 4, 30)),
                    (date(2026, 5, 1), date(2026, 5, 31)),
                ],
            ),
            (
                "watermark_rereads_the_month_before_its_own",
                date(2026, 11, 21),
                "2026-10-01",
                [
                    (date(2026, 9, 1), date(2026, 9, 30)),
                    (date(2026, 10, 1), date(2026, 10, 31)),
                    (date(2026, 11, 1), date(2026, 11, 21)),
                ],
            ),
            (
                # The sync after the first one of a new month still refreshes the closed month.
                "second_sync_after_month_rollover",
                date(2026, 11, 2),
                date(2026, 11, 1),
                [(date(2026, 10, 1), date(2026, 10, 31)), (date(2026, 11, 1), date(2026, 11, 2))],
            ),
            (
                "watermark_older_than_the_lookback",
                date(2026, 11, 21),
                "2025-01-01",
                [
                    (date(2026, 9, 1), date(2026, 9, 30)),
                    (date(2026, 10, 1), date(2026, 10, 31)),
                    (date(2026, 11, 1), date(2026, 11, 21)),
                ],
            ),
        ]
    )
    def test_usage_windows(self, _name: str, today: date, last_value: Any, expected: list[tuple[date, date]]) -> None:
        assert [(window.start, window.end) for window in _usage_windows(today, last_value)] == expected


class TestOrganizationUsage:
    @staticmethod
    def _usage(period_from: str, period_to: str) -> ScriptedResponse:
        return _response({"reporting_period": {"from": period_from, "to": period_to}, "active_users_count": 3})

    @parameterized.expand(
        [
            (
                "full_refresh",
                False,
                None,
                [("2026-09-01", "2026-09-30"), ("2026-10-01", "2026-10-31"), ("2026-11-01", "2026-11-21")],
            ),
            ("incremental", True, "2026-11-01", [("2026-10-01", "2026-10-31"), ("2026-11-01", "2026-11-21")]),
        ]
    )
    @mock.patch("products.warehouse_sources.sources.buildkite.buildkite._today", return_value=date(2026, 11, 21))
    def test_requests_one_month_per_row(
        self,
        _name: str,
        incremental: bool,
        last_value: str | None,
        windows: list[tuple[str, str]],
        _today: mock.MagicMock,
    ) -> None:
        result = _driver().run(
            "organization_usage",
            [self._usage(start, end) for start, end in windows],
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=last_value,
            incremental_field="reporting_period_from",
        )

        assert result.raised is None
        assert [url.split("?")[0] for url in result.urls] == [f"{ORG_URL}/usage"] * len(windows)
        assert [(r.param("from"), r.param("to")) for r in result.requests] == windows
        # The nested period is lifted to the top level, because the primary key keys on it.
        assert [(row["reporting_period_from"], row["reporting_period_to"]) for row in result.rows] == windows
        assert all(row["active_users_count"] == 3 for row in result.rows)

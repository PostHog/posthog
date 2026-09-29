import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.buildkite.buildkite import (
    BuildkiteResumeConfig,
    _build_initial_params,
    _format_incremental_value,
    buildkite_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.buildkite.settings import BUILDKITE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the buildkite module.
BUILDKITE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.buildkite.buildkite.make_tracked_session"
)
ORG_URL = "https://api.buildkite.com/v2/organizations/my-org"


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
    def test_builds_incremental_maps_to_created_from(self) -> None:
        params = _build_initial_params(
            BUILDKITE_ENDPOINTS["builds"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="created_at",
        )
        assert params["per_page"] == 100
        assert params["created_from"] == "2026-03-04T02:58:14+00:00"

    def test_builds_full_refresh_has_no_filter(self) -> None:
        params = _build_initial_params(
            BUILDKITE_ENDPOINTS["builds"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        assert params == {"per_page": 100}

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


def _response(body: Any, link: str | None = None) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    if link:
        # Buildkite paginates via an RFC 5988 Link header with rel="next".
        resp.headers["Link"] = f'<{link}>; rel="next"'
    return resp


def _make_manager(resume_state: BuildkiteResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's url/params/auth AT PREPARE TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {}), "auth": request.auth})
        return MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(
    endpoint: str,
    manager: MagicMock,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    return buildkite_source(
        api_access_token="bkua",
        organization="my-org",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        incremental_field=incremental_field,
    )


def _rows(source_response: SourceResponse) -> list[dict[str, Any]]:
    return [row for page in cast("Iterable[Any]", source_response.items()) for row in page]


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_link_header_pagination(self, MockSession) -> None:
        session = MockSession.return_value
        page2 = "https://api.buildkite.com/v2/organizations/my-org/pipelines?page=2&per_page=100"
        snapshots = _wire(
            session,
            [
                _response([{"id": "p1"}, {"id": "p2"}], link=page2),
                _response([{"id": "p3"}]),
            ],
        )

        rows = _rows(_source("pipelines", _make_manager()))

        assert [r["id"] for r in rows] == ["p1", "p2", "p3"]
        assert snapshots[0]["url"] == "https://api.buildkite.com/v2/organizations/my-org/pipelines"
        assert snapshots[0]["params"] == {"per_page": 100}
        # The next-page URL is self-contained; the original params must not be re-appended.
        assert snapshots[1]["url"] == page2
        assert snapshots[1]["params"] == {}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_org_scoped_path_ignores_placeholder(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": "o1"}])])

        _rows(_source("organizations", _make_manager()))

        assert snapshots[0]["url"] == "https://api.buildkite.com/v2/organizations"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_empty_page_without_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        manager = _make_manager()
        rows = _rows(_source("agents", manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state(self, MockSession) -> None:
        session = MockSession.return_value
        resume_url = "https://api.buildkite.com/v2/organizations/my-org/pipelines?page=3&per_page=100"
        snapshots = _wire(session, [_response([{"id": "p9"}])])

        manager = _make_manager(BuildkiteResumeConfig(next_url=resume_url))
        rows = _rows(_source("pipelines", manager))

        # Resume must start at the saved URL, not the freshly-built first-page URL.
        assert snapshots[0]["url"] == resume_url
        assert [r["id"] for r in rows] == ["p9"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_state_after_yielding_a_page(self, MockSession) -> None:
        session = MockSession.return_value
        page2 = "https://api.buildkite.com/v2/organizations/my-org/builds?page=2&per_page=100"
        _wire(
            session,
            [
                _response([{"id": "b1"}], link=page2),
                _response([{"id": "b2"}]),
            ],
        )

        manager = _make_manager()
        _rows(_source("builds", manager))

        # State is saved AFTER a page is yielded and points at the NEXT page, so a crash re-yields
        # the last page (merge dedupes on the primary key) rather than skipping it. The final page
        # has no next link, so no checkpoint is written for it.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == BuildkiteResumeConfig(next_url=page2)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_sync_sends_created_from(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": "b1"}])])

        _rows(
            _source(
                "builds",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
                incremental_field="created_at",
            )
        )

        assert snapshots[0]["params"] == {"per_page": 100, "created_from": "2026-03-04T02:58:14+00:00"}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_auth_is_framework_bearer(self, MockSession) -> None:
        # The token must flow through the framework auth config (so it's redacted from logs),
        # not a hand-built Authorization header.
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": "p1"}])])

        _rows(_source("pipelines", _make_manager()))

        auth = snapshots[0]["auth"]
        assert isinstance(auth, BearerTokenAuth)
        assert auth.token == "bkua"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_body_fails_loudly(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"message": "something unexpected"})])

        # Buildkite list endpoints return a top-level JSON array; a 200 with a non-list body means
        # the response shape changed — fail loud instead of syncing garbage.
        with pytest.raises(ValueError, match="list response body"):
            _rows(_source("pipelines", _make_manager()))


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
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(
        self, endpoint: str, primary_keys: list[str], sort_mode: str, partition_key: str | None, MockSession
    ) -> None:
        MockSession.return_value.headers = {}
        response = _source(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == sort_mode
        assert response.partition_mode == ("datetime" if partition_key else None)
        assert response.partition_format == ("week" if partition_key else None)
        assert response.partition_keys == ([partition_key] if partition_key else None)


class TestValidateCredentials:
    @staticmethod
    def _patch_get(mock_session: MagicMock, status_code: int) -> dict[str, str]:
        captured: dict[str, str] = {}

        def fake_get(url: str, **kwargs: Any) -> MagicMock:
            captured["url"] = url
            return MagicMock(status_code=status_code)

        mock_session.return_value.get.side_effect = fake_get
        return captured

    @mock.patch(BUILDKITE_SESSION_PATCH)
    def test_success(self, mock_session) -> None:
        self._patch_get(mock_session, 200)
        assert validate_credentials("bkua", "my-org") == (True, None)

    @mock.patch(BUILDKITE_SESSION_PATCH)
    def test_invalid_token(self, mock_session) -> None:
        self._patch_get(mock_session, 401)
        ok, error = validate_credentials("bkua", "my-org")
        assert ok is False
        assert error is not None and "invalid" in error.lower()

    @mock.patch(BUILDKITE_SESSION_PATCH)
    def test_forbidden_accepted_at_source_create(self, mock_session) -> None:
        # A valid token may lack read_organizations while still holding the per-endpoint scopes the
        # user wants — so a 403 at source-create (schema_name=None) must not block connecting.
        self._patch_get(mock_session, 403)
        assert validate_credentials("bkua", "my-org") == (True, None)

    @mock.patch(BUILDKITE_SESSION_PATCH)
    def test_forbidden_rejected_for_specific_schema(self, mock_session) -> None:
        self._patch_get(mock_session, 403)
        ok, error = validate_credentials("bkua", "my-org", schema_name="builds")
        assert ok is False
        assert error is not None and "builds" in error

    @mock.patch(BUILDKITE_SESSION_PATCH)
    def test_org_not_found(self, mock_session) -> None:
        self._patch_get(mock_session, 404)
        ok, error = validate_credentials("bkua", "missing-org")
        assert ok is False
        assert error is not None and "missing-org" in error

    @mock.patch(BUILDKITE_SESSION_PATCH)
    def test_schema_probe_targets_endpoint_path(self, mock_session) -> None:
        captured = self._patch_get(mock_session, 200)
        validate_credentials("bkua", "my-org", schema_name="agents")
        assert captured["url"] == "https://api.buildkite.com/v2/organizations/my-org/agents?per_page=1"

    @parameterized.expand(
        [
            ("test_suite_runs", "https://api.buildkite.com/v2/analytics/organizations/my-org/suites?per_page=1"),
            ("test_suite_tests", "https://api.buildkite.com/v2/analytics/organizations/my-org/suites?per_page=1"),
            ("team_pipelines", f"{ORG_URL}/teams?per_page=1"),
            ("pipeline_schedules", f"{ORG_URL}/pipelines?per_page=1"),
            ("cluster_queues", f"{ORG_URL}/clusters?per_page=1"),
        ]
    )
    @mock.patch(BUILDKITE_SESSION_PATCH)
    def test_fanout_schema_probe_targets_the_parent_listing(
        self, endpoint: str, expected_url: str, mock_session
    ) -> None:
        # A fan-out child's own path needs a parent row, so the probe hits the listing that
        # carries the same scope. Formatting the child path here would raise on the parent
        # placeholder it still carries, such as {suite_slug} or {team_id}.
        captured = self._patch_get(mock_session, 200)
        validate_credentials("bkua", "my-org", schema_name=endpoint)
        assert captured["url"] == expected_url

    @mock.patch(BUILDKITE_SESSION_PATCH)
    def test_jobs_schema_probe_targets_the_builds_listing(self, mock_session) -> None:
        captured = self._patch_get(mock_session, 200)
        validate_credentials("bkua", "my-org", schema_name="jobs")
        assert captured["url"] == "https://api.buildkite.com/v2/organizations/my-org/builds?per_page=1"

    @mock.patch(BUILDKITE_SESSION_PATCH)
    def test_source_create_probe_targets_org(self, mock_session) -> None:
        captured = self._patch_get(mock_session, 200)
        validate_credentials("bkua", "my-org")
        assert captured["url"] == "https://api.buildkite.com/v2/organizations/my-org"

    @mock.patch(BUILDKITE_SESSION_PATCH)
    def test_swallows_transport_errors(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        ok, error = validate_credentials("bkua", "my-org")
        assert ok is False
        assert error is not None


class TestSuiteFanout:
    @staticmethod
    def _suites_page() -> Response:
        return _response([{"id": "s1", "slug": "web"}, {"id": "s2", "slug": "api"}])

    @parameterized.expand([("test_suite_runs", "runs"), ("test_suite_tests", "tests")])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fans_out_over_every_suite(self, endpoint: str, path_segment: str, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [self._suites_page(), _response([{"id": "a"}]), _response([{"id": "b"}])])

        rows = _rows(_source(endpoint, _make_manager()))

        base = "https://api.buildkite.com/v2/analytics/organizations/my-org/suites"
        assert snapshots[0]["url"] == base
        # The suites listing takes no page-size param; only the children are paginated.
        assert snapshots[0]["params"] == {}
        assert [s["url"] for s in snapshots[1:]] == [f"{base}/web/{path_segment}", f"{base}/api/{path_segment}"]
        assert snapshots[1]["params"] == {"per_page": 100}
        # Runs and tests are only identified within their suite, so the suite has to reach the row
        # for the composite primary key to be unique table-wide.
        assert [(r["id"], r["suite_id"], r["suite_slug"]) for r in rows] == [
            ("a", "s1", "web"),
            ("b", "s2", "api"),
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_deleted_suite_does_not_fail_the_sync(self, MockSession) -> None:
        session = MockSession.return_value
        gone = Response()
        gone.status_code = 404
        gone._content = b'{"message": "Not Found"}'
        _wire(session, [self._suites_page(), gone, _response([{"id": "b"}])])

        rows = _rows(_source("test_suite_runs", _make_manager()))

        assert [r["id"] for r in rows] == ["b"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_and_resumes_the_fanout_snapshot(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [self._suites_page(), _response([{"id": "a"}]), _response([{"id": "b"}])])

        manager = _make_manager()
        _rows(_source("test_suite_runs", manager))

        saved = [call.args[0].fanout_state for call in manager.save_state.call_args_list]
        assert saved[-1]["completed"] == [
            "/v2/analytics/organizations/my-org/suites/api/runs",
            "/v2/analytics/organizations/my-org/suites/web/runs",
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_skips_suites_already_completed(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [self._suites_page(), _response([{"id": "b"}])])

        resume = BuildkiteResumeConfig(
            fanout_state={
                "completed": ["/v2/analytics/organizations/my-org/suites/web/runs"],
                "current": None,
                "child_state": None,
            }
        )
        rows = _rows(_source("test_suite_runs", _make_manager(resume)))

        # The suite list is re-fetched each run; only the unfinished suite is fanned out again.
        assert [s["url"] for s in snapshots[1:]] == [
            "https://api.buildkite.com/v2/analytics/organizations/my-org/suites/api/runs"
        ]
        assert [r["id"] for r in rows] == ["b"]


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
                "cluster_queues",
                [{"id": "c1"}, {"id": "c2"}],
                f"{ORG_URL}/clusters",
                [f"{ORG_URL}/clusters/c1/queues", f"{ORG_URL}/clusters/c2/queues"],
                [{"id": "q1"}, {"id": "q2"}],
                [{"cluster_id": "c1"}, {"cluster_id": "c2"}],
            ),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_binds_the_parent_path_and_carries_the_parent_onto_each_row(
        self,
        endpoint: str,
        parent_rows: list[dict[str, Any]],
        parent_url: str,
        child_urls: list[str],
        child_rows: list[dict[str, Any]],
        parent_columns: list[dict[str, Any]],
        MockSession,
    ) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response(parent_rows), _response([child_rows[0]]), _response([child_rows[1]])])

        rows = _rows(_source(endpoint, _make_manager()))

        assert snapshots[0]["url"] == parent_url
        assert snapshots[0]["params"] == {"per_page": 100}
        assert [s["url"] for s in snapshots[1:]] == child_urls
        # The parent identifier has to land on the row under its final column name, because the
        # composite primary key keys on it. A missing rename leaves the key with no column.
        assert rows == [{**child_rows[i], **parent_columns[i]} for i in (0, 1)]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_deleted_parent_does_not_fail_the_sync(self, MockSession) -> None:
        session = MockSession.return_value
        gone = Response()
        gone.status_code = 404
        gone._content = b'{"message": "Not Found"}'
        _wire(
            session,
            [
                _response([{"id": "t1", "slug": "backend"}, {"id": "t2", "slug": "frontend"}]),
                gone,
                _response([{"pipeline_id": "p2"}]),
            ],
        )

        rows = _rows(_source("team_pipelines", _make_manager()))

        assert [r["pipeline_id"] for r in rows] == ["p2"]


class TestJobsFanout:
    @staticmethod
    def _builds_page() -> Response:
        return _response(
            [{"id": "b1", "number": 42, "created_at": "2026-03-04T02:58:14Z", "pipeline": {"slug": "web"}}]
        )

    @staticmethod
    def _jobs_page(job_ids: list[str], next_url: str | None = None) -> Response:
        # The jobs endpoint answers with an envelope and paginates on a cursor URL in the body,
        # unlike every other Buildkite list endpoint.
        return _response({"items": [{"id": i} for i in job_ids], "links": {"next": next_url} if next_url else {}})

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_binds_both_path_params_from_one_build_row(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [self._builds_page(), self._jobs_page(["j1"])])

        rows = _rows(_source("jobs", _make_manager()))

        assert snapshots[0]["url"] == "https://api.buildkite.com/v2/organizations/my-org/builds"
        # The pipeline slug is nested under `pipeline` on a build and has to be flattened before
        # it can bind the path or reach the job row.
        assert snapshots[1]["url"] == "https://api.buildkite.com/v2/organizations/my-org/pipelines/web/builds/42/jobs"
        assert rows == [
            {
                "id": "j1",
                "build_id": "b1",
                "build_number": 42,
                "build_created_at": "2026-03-04T02:58:14Z",
                "pipeline_slug": "web",
            }
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_the_body_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        page2 = "https://api.buildkite.com/v2/organizations/my-org/pipelines/web/builds/42/jobs?after=abc"
        snapshots = _wire(
            session, [self._builds_page(), self._jobs_page(["j1"], next_url=page2), self._jobs_page(["j2"])]
        )

        rows = _rows(_source("jobs", _make_manager()))

        assert [r["id"] for r in rows] == ["j1", "j2"]
        assert snapshots[2]["url"] == page2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_windows_the_parent_build_walk(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [self._builds_page(), self._jobs_page(["j1"])])

        _rows(
            _source(
                "jobs",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
                incremental_field="build_created_at",
            )
        )

        # Jobs carry no server-side time filter, so the watermark has to bound the builds request
        # that drives the fan-out — otherwise every sync re-walks the whole organization.
        assert snapshots[0]["params"] == {"per_page": 100, "created_from": "2026-03-04T02:58:14+00:00"}
        assert "created_from" not in snapshots[1]["params"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_omits_the_window(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [self._builds_page(), self._jobs_page(["j1"])])

        _rows(_source("jobs", _make_manager()))

        assert snapshots[0]["params"] == {"per_page": 100}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoints_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [self._builds_page(), self._jobs_page(["j1"])])

        manager = _make_manager()
        _rows(_source("jobs", manager))

        # Resume is off for this fan-out: the framework rewrites the full set of completed child
        # paths on every parent, which an organization's build list makes quadratic.
        manager.save_state.assert_not_called()

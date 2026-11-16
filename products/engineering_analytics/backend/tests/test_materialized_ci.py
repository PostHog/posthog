from datetime import UTC, datetime, timedelta
from typing import Any

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.metadata import get_table_names
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from products.data_modeling.backend.facade.api import (
    definition_fingerprint,
    get_incremental_config,
    set_incremental_state,
)
from products.data_modeling.backend.facade.models import (
    DataModelingJob,
    DataWarehouseManagedViewSet,
    DataWarehouseSavedQuery,
)
from products.engineering_analytics.backend.facade.contracts import MATERIALIZED_VIEWS_FEATURE_FLAG
from products.engineering_analytics.backend.logic.materialized_ci import MAX_MATERIALIZATION_AGE
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.sources import (
    DEPOT_JOB_ATTEMPTS_SCHEMA,
    PULL_REQUESTS_SCHEMA,
    WORKFLOW_JOBS_SCHEMA,
    WORKFLOW_RUNS_SCHEMA,
)
from products.engineering_analytics.backend.logic.views import ci_rows
from products.engineering_analytics.backend.logic.views.source_schema import (
    DEPOT_JOB_ATTEMPTS_COLUMNS,
    PULL_REQUESTS_COLUMNS,
    WORKFLOW_JOBS_COLUMNS,
    WORKFLOW_RUNS_COLUMNS,
)
from products.engineering_analytics.backend.tests._github_fixtures import (
    _depot_attempt_row,
    _pr_row,
    _run_row,
    create_depot_source,
    create_github_source,
    create_warehouse_table_row,
    link_schema,
)
from products.engineering_analytics.backend.tests._logic_helpers import _ago_with_duration, _job_row, _WarehouseMixin
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataJob, ExternalDataSchema
from products.warehouse_sources.backend.facade.types import DataWarehouseManagedViewSetKind


def _ready_views(
    test: BaseTest, *, backing_tables: dict[str, DataWarehouseTable] | None = None
) -> dict[str, DataWarehouseSavedQuery]:
    queries = ci_rows.build_team_views(test.team)
    assert queries is not None
    for schema in ExternalDataSchema.objects.filter(team=test.team, deleted=False, should_sync=True):
        imported = ExternalDataJob.objects.create(
            team=test.team,
            pipeline=schema.source,
            schema=schema,
            status=ExternalDataJob.Status.COMPLETED,
            finished_at=timezone.now() - timedelta(minutes=11),
        )
        ExternalDataJob.objects.filter(id=imported.id).update(created_at=timezone.now() - timedelta(minutes=12))
    viewset = DataWarehouseManagedViewSet.objects.create(
        team=test.team, kind=DataWarehouseManagedViewSetKind.ENGINEERING_ANALYTICS
    )
    views = {}
    for name, query, fields, config in (
        (ci_rows.RUNS_VIEW_NAME, queries.runs, ci_rows.RUN_FIELDS, ci_rows.RUN_INCREMENTAL_CONFIG),
        (ci_rows.JOBS_VIEW_NAME, queries.jobs, ci_rows.JOB_FIELDS, ci_rows.JOB_INCREMENTAL_CONFIG),
    ):
        columns = DataWarehouseManagedViewSet._get_columns_from_fields(fields)
        table = (
            backing_tables[name]
            if backing_tables is not None
            else create_warehouse_table_row(test.team, name=f"backing_{name}")
        )
        table.columns = columns
        table.save(update_fields=["columns"])
        view = DataWarehouseSavedQuery.objects.create(
            team=test.team,
            name=name,
            query={"kind": "HogQLQuery", "query": query},
            columns=columns,
            table=table,
            is_materialized=True,
            managed_viewset=viewset,
            origin=DataWarehouseSavedQuery.Origin.MANAGED_VIEWSET,
            incremental_config=config,
        )
        incremental = get_incremental_config(view)
        assert incremental is not None
        fingerprint = definition_fingerprint(view.query, incremental)
        assert fingerprint is not None
        set_incremental_state(view, watermark=timezone.now(), fingerprint=fingerprint, mode="full_refresh")
        job = DataModelingJob.objects.create(
            team=test.team,
            saved_query=view,
            status=DataModelingJob.Status.COMPLETED,
            last_run_at=timezone.now() - timedelta(minutes=5),
        )
        DataModelingJob.objects.filter(id=job.id).update(created_at=timezone.now() - timedelta(minutes=6))
        views[name] = view
    return views


@time_machine.travel("2026-10-21T12:00:00Z", tick=False)
class TestMaterializedCI(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.source = create_github_source(self.team, repository="example/widgets")
        for endpoint, columns in (
            (PULL_REQUESTS_SCHEMA, PULL_REQUESTS_COLUMNS),
            (WORKFLOW_RUNS_SCHEMA, WORKFLOW_RUNS_COLUMNS),
            (WORKFLOW_JOBS_SCHEMA, WORKFLOW_JOBS_COLUMNS),
        ):
            table = create_warehouse_table_row(self.team, name=f"raw_github_{endpoint}", source=self.source)
            table.columns = columns
            table.save(update_fields=["columns"])
            schema = link_schema(self.team, self.source, name=endpoint, table=table)
            ExternalDataSchema.objects.filter(id=schema.id).update(last_synced_at=timezone.now())

    def _reader(self) -> CuratedGitHubSource:
        return CuratedGitHubSource.for_team(self.team, source_id=str(self.source.id), repo="example/widgets")

    @parameterized.expand([("enabled", True, True), ("disabled", False, False), ("unavailable", None, False)])
    def test_shared_sources_choose_ready_materializations_only_when_enabled(
        self, _: str, enabled: bool | None, stored: bool
    ) -> None:
        _ready_views(self)
        with patch("posthoganalytics.feature_enabled", return_value=enabled):
            reader = self._reader()
            runs = set(get_table_names(parse_select(reader.run_source())))
            jobs = set(get_table_names(parse_select(reader.jobs_source() or "")))
            costs = set(get_table_names(parse_select(reader.job_cost_source() or "")))
            detail = set(get_table_names(parse_select(reader.jobs_source(include_steps=True) or "")))
            current = set(get_table_names(parse_select(reader.runs_cte().removeprefix("runs AS "))))
        if stored:
            assert runs == {ci_rows.RUNS_VIEW_NAME}
            assert jobs == {ci_rows.JOBS_VIEW_NAME}
            assert costs == {ci_rows.RUNS_VIEW_NAME, ci_rows.JOBS_VIEW_NAME}
        else:
            assert "raw_github_workflow_runs" in runs
            assert "raw_github_workflow_jobs" in jobs & costs
        assert "raw_github_workflow_jobs" in detail
        assert "raw_github_workflow_runs" in current

    @parameterized.expand(
        [
            "missing_pair",
            "disabled_view",
            "stale",
            "definition_not_built",
            "new_definition",
            "missing_stored_column",
            "wrong_viewset",
        ]
    )
    def test_unusable_materializations_fall_back_together(self, condition: str) -> None:
        views = _ready_views(self)
        jobs = views[ci_rows.JOBS_VIEW_NAME]
        if condition == "missing_pair":
            DataWarehouseSavedQuery.objects.filter(id=jobs.id).update(deleted=True)
        elif condition == "disabled_view":
            DataWarehouseSavedQuery.objects.filter(id=jobs.id).update(is_materialized=False)
        elif condition == "stale":
            DataModelingJob.objects.filter(saved_query=jobs).update(
                last_run_at=timezone.now() - MAX_MATERIALIZATION_AGE - timedelta(seconds=1)
            )
        elif condition == "definition_not_built":
            DataWarehouseSavedQuery.objects.filter(id=jobs.id).update(incremental_state={})
        elif condition == "new_definition":
            DataWarehouseSavedQuery.objects.filter(id=jobs.id).update(query={"kind": "HogQLQuery", "query": "SELECT 1"})
        elif condition == "missing_stored_column":
            assert jobs.table is not None
            assert jobs.table.columns is not None
            jobs.table.columns.pop("native_job_id")
            jobs.table.save(update_fields=["columns"])
        elif condition == "wrong_viewset":
            DataWarehouseSavedQuery.objects.filter(id=jobs.id).update(managed_viewset=None)

        with patch("posthoganalytics.feature_enabled", return_value=True):
            reader = self._reader()
            assert "raw_github_workflow_runs" in get_table_names(parse_select(reader.run_source()))
            assert "raw_github_workflow_jobs" in get_table_names(parse_select(reader.jobs_source() or ""))

    @parameterized.expand([DataModelingJob.Status.RUNNING, DataModelingJob.Status.FAILED])
    def test_an_unfinished_newer_build_keeps_the_completed_one_serving(self, status: str) -> None:
        views = _ready_views(self)
        DataModelingJob.objects.create(team=self.team, saved_query=views[ci_rows.JOBS_VIEW_NAME], status=status)

        with patch("posthoganalytics.feature_enabled", return_value=True):
            reader = self._reader()
            assert set(get_table_names(parse_select(reader.run_source()))) == {ci_rows.RUNS_VIEW_NAME}
            assert set(get_table_names(parse_select(reader.jobs_source() or ""))) == {ci_rows.JOBS_VIEW_NAME}

    def test_flag_exception_falls_back_to_live_sources(self) -> None:
        _ready_views(self)

        def flag(key: str, *args: object, **kwargs: object) -> bool:
            if key == MATERIALIZED_VIEWS_FEATURE_FLAG:
                raise RuntimeError("flag unavailable")
            return False

        with patch("posthoganalytics.feature_enabled", side_effect=flag):
            assert "raw_github_workflow_runs" in get_table_names(parse_select(self._reader().run_source()))

    def test_freshness_and_cache_scope_follow_materialization(self) -> None:
        _ready_views(self)
        consumed_at = timezone.now() - timedelta(minutes=10)
        for schema in ExternalDataSchema.objects.filter(source=self.source):
            old = ExternalDataJob.objects.create(
                team=self.team,
                pipeline=self.source,
                schema=schema,
                status=ExternalDataJob.Status.COMPLETED,
                created_at=consumed_at,
                finished_at=consumed_at + timedelta(minutes=1),
            )
            ExternalDataJob.objects.filter(id=old.id).update(created_at=consumed_at)
            recent = ExternalDataJob.objects.create(
                team=self.team,
                pipeline=self.source,
                schema=schema,
                status=ExternalDataJob.Status.COMPLETED,
                created_at=timezone.now() - timedelta(minutes=2),
                finished_at=timezone.now() - timedelta(minutes=1),
            )
            ExternalDataJob.objects.filter(id=recent.id).update(created_at=timezone.now() - timedelta(minutes=2))
        with patch("posthoganalytics.feature_enabled", return_value=True):
            stored = self._reader()
            freshness = stored.ci_data_freshness()
            assert freshness.runs_synced_at == consumed_at
            assert freshness.jobs_synced_at == consumed_at
            stored_scope = stored.ci_read_scope()
        with patch("posthoganalytics.feature_enabled", return_value=False):
            assert self._reader().ci_read_scope() != stored_scope

    def test_a_second_github_source_keeps_its_live_depot_rows(self) -> None:
        depot = create_depot_source(self.team, repository="example/widgets")
        table = create_warehouse_table_row(self.team, name="depot_attempts", source=depot)
        table.columns = DEPOT_JOB_ATTEMPTS_COLUMNS
        table.save(update_fields=["columns"])
        link_schema(self.team, depot, name=DEPOT_JOB_ATTEMPTS_SCHEMA, table=table)
        other = create_github_source(self.team, prefix="second_", repository="example/widgets")
        for endpoint in (PULL_REQUESTS_SCHEMA, WORKFLOW_RUNS_SCHEMA, WORKFLOW_JOBS_SCHEMA):
            table = create_warehouse_table_row(self.team, name=f"second_github_{endpoint}", source=other)
            link_schema(self.team, other, name=endpoint, table=table)
        _ready_views(self)
        with patch("posthoganalytics.feature_enabled", return_value=True):
            reader = CuratedGitHubSource.for_team(self.team, source_id=str(other.id), repo="example/widgets")
            assert "second_github_workflow_runs" in get_table_names(parse_select(reader.run_source()))
            assert "depot_attempts" in get_table_names(parse_select(reader.jobs_source() or ""))


@time_machine.travel(lambda: datetime.now(UTC), tick=False)
class TestMaterializedCIParity(_WarehouseMixin):
    def test_stored_and_live_reads_agree_across_sources_retries_and_handoffs(self) -> None:
        repository = "example/widgets"
        source = create_github_source(self.team, repository=repository)
        started, completed = _ago_with_duration(1, 120)
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [_pr_row(10, "developer", "open", 0, started, full_name=repository, head_ref="main")],
            source=source,
        )
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [
                _run_row(
                    100,
                    "CI",
                    "retry-head",
                    "completed",
                    "failure",
                    started,
                    completed,
                    full_name=repository,
                    run_attempt=2,
                    pr_number=10,
                ),
                {
                    **_run_row(
                        101,
                        "Backend CI",
                        "handoff-head",
                        "completed",
                        "success",
                        started,
                        completed,
                        full_name=repository,
                        pr_number=10,
                    ),
                    "created_at": (timezone.now() - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
            ],
            source=source,
        )
        jobs = [
            _job_row(501, 100, "tests", "failure", started=started, completed=completed),
            _job_row(502, 100, "tests", "failure", run_attempt=2, started=started, completed=completed),
            _job_row(503, 999, "orphan", "success", started=started, completed=completed),
            _job_row(601, 101, "Hand off backend tests to Depot CI", "success", started=started, completed=completed),
            _job_row(602, 101, "Django Tests Pass", "success", started=started, completed=completed),
        ]
        self._create_table("github_workflow_jobs", WORKFLOW_JOBS_COLUMNS, jobs, source=source)
        depot = create_depot_source(self.team, prefix="depot_", repository=repository)
        attempt = _depot_attempt_row(
            repo=repository,
            ref="refs/pull/10/merge",
            head_sha="handoff-head",
            sha="handoff-head",
            workflow_name="Backend CI on Depot",
            workflow_status="finished",
            workflow_created_at=started,
            workflow_started_at=started,
            workflow_finished_at=completed,
            job_key="ci-backend.yml:tests",
            job_display_name="Depot tests",
            attempt_status="finished",
            attempt_started_at=started,
            attempt_finished_at=completed,
        )
        wait = {
            **attempt,
            "job_id": "2222222222",
            "attempt_id": "3333333333",
            "job_key": "ci-backend.yml:wait-for-handoff",
            "job_display_name": "Wait for handoff",
        }
        self._create_table(
            "depot_job_attempts",
            DEPOT_JOB_ATTEMPTS_COLUMNS,
            [
                attempt,
                wait,
                {
                    **wait,
                    "workflow_id": "4444444444",
                    "run_id": "5555555555",
                    "job_id": "6666666666",
                    "attempt_id": "7777777777",
                },
            ],
            source=depot,
            prefix="depot_",
            schema_name=DEPOT_JOB_ATTEMPTS_SCHEMA,
        )
        other = create_github_source(self.team, prefix="other_", repository=repository)
        for endpoint, columns, rows in (
            (
                PULL_REQUESTS_SCHEMA,
                PULL_REQUESTS_COLUMNS,
                [_pr_row(10, "other-developer", "open", 0, started, full_name=repository)],
            ),
            (
                WORKFLOW_RUNS_SCHEMA,
                WORKFLOW_RUNS_COLUMNS,
                [
                    _run_row(
                        100,
                        "other-workflow",
                        "other-head",
                        "completed",
                        "success",
                        started,
                        completed,
                        full_name=repository,
                        pr_number=10,
                    )
                ],
            ),
            (
                WORKFLOW_JOBS_SCHEMA,
                WORKFLOW_JOBS_COLUMNS,
                [_job_row(501, 100, "other-tests", "success", started=started, completed=completed)],
            ),
        ):
            self._create_table(f"github_{endpoint}", columns, rows, source=other, prefix="other_")
        for endpoint, columns, rows in (
            (
                PULL_REQUESTS_SCHEMA,
                PULL_REQUESTS_COLUMNS,
                [_pr_row(20, "another-developer", "open", 0, started, full_name="example/another")],
            ),
            (
                WORKFLOW_RUNS_SCHEMA,
                WORKFLOW_RUNS_COLUMNS,
                [
                    _run_row(
                        200,
                        "another-workflow",
                        "another-head",
                        "completed",
                        "success",
                        started,
                        completed,
                        full_name="example/another",
                        pr_number=20,
                    )
                ],
            ),
            (
                WORKFLOW_JOBS_SCHEMA,
                WORKFLOW_JOBS_COLUMNS,
                [_job_row(701, 200, "another-tests", "success", started=started, completed=completed)],
            ),
        ):
            self._create_table(
                f"another_{endpoint}",
                columns,
                rows,
                source=source,
                prefix="another_",
                schema_name=f"example/another.{endpoint}",
            )

        def read(*, stored: bool = False, floor: datetime | None = None) -> dict[str, list[tuple]]:
            reader = CuratedGitHubSource.for_team(self.team, source_id=str(source.id), repo=repository)
            if stored:
                assert set(get_table_names(parse_select(reader.run_source()))) == {ci_rows.RUNS_VIEW_NAME}
            floor_value = floor.strftime("%Y-%m-%d") if floor is not None else None
            queries = {
                "runs": f"SELECT id, run_attempt, pr_number, ci_engine, stopped_reporting FROM {reader.run_source(started_floor=floor is not None)} ORDER BY ci_engine, id",
                "jobs": f"SELECT id, run_id, run_attempt, is_rerun_copy, ci_engine FROM {reader.jobs_source(created_floor=floor is not None)} ORDER BY ci_engine, id",
                "costs": f"SELECT run_id, job_name, run_attempt, head_branch, estimated_cost_usd, pr_number, ci_engine FROM {reader.job_cost_source(created_floor=floor is not None)} ORDER BY ci_engine, run_id, job_name, run_attempt",
            }
            return {
                kind: list(
                    reader.run(
                        sql,
                        query_type="engineering_analytics.test_stored_ci",
                        placeholders={
                            "run_started_floor": ast.Constant(value=floor_value),
                            "job_created_floor": ast.Constant(value=floor_value),
                        },
                    ).results
                    or []
                )
                for kind, sql in queries.items()
            }

        with patch("posthoganalytics.feature_enabled", return_value=False):
            live = read()
            future = timezone.now() + timedelta(days=1)
            assert read(floor=future) == {"runs": [], "jobs": [], "costs": []}
        assert len(live["runs"]) == 2
        assert len(live["jobs"]) == 5
        assert any(row[3] for row in live["jobs"])

        queries = ci_rows.build_team_views(self.team)
        assert queries is not None
        backing_tables = {}
        stored_run_rows: list[dict[str, Any]] = []
        for name, sql, fields in (
            (ci_rows.RUNS_VIEW_NAME, queries.runs, ci_rows.RUN_FIELDS),
            (ci_rows.JOBS_VIEW_NAME, queries.jobs, ci_rows.JOB_FIELDS),
        ):
            response = execute_hogql_query(
                sql,
                team=self.team,
                query_type="engineering_analytics.test_build_stored_ci",
                placeholders={"incremental_window_start": ast.Constant(value=None)},
                bypass_warehouse_access_control=True,
            )
            if name == ci_rows.JOBS_VIEW_NAME:
                windowed = execute_hogql_query(
                    sql,
                    team=self.team,
                    query_type="engineering_analytics.test_build_stored_ci",
                    placeholders={"incremental_window_start": ast.Constant(value=timezone.now() - timedelta(days=2))},
                    bypass_warehouse_access_control=True,
                )
                assert sorted(windowed.results or []) == sorted(response.results or [])
            stored_rows: list[dict[str, Any]] = [
                {
                    str(column): value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")
                    if isinstance(value, datetime)
                    else value
                    for column, value in zip(response.columns or [], row, strict=True)
                }
                for row in response.results or []
            ]
            if name == ci_rows.RUNS_VIEW_NAME:
                stored_run_rows = stored_rows
            self._create_table(
                name,
                DataWarehouseManagedViewSet._get_columns_from_fields(fields),
                stored_rows,
                source=source,
                prefix="stored_",
            )
            backing_tables[name] = DataWarehouseTable.objects.get(team=self.team, name=f"stored_{name}")
        _ready_views(self, backing_tables=backing_tables)

        with patch("posthoganalytics.feature_enabled", return_value=True):
            observed = read(stored=True)
            assert observed == live, repr({"stored": observed, "live": live})
            assert read(stored=True, floor=timezone.now() - timedelta(days=2)) == live
            assert read(stored=True, floor=future) == {"runs": [], "jobs": [], "costs": []}

        self._create_table(
            "skewed_ci_runs",
            DataWarehouseManagedViewSet._get_columns_from_fields(ci_rows.RUN_FIELDS),
            [{**row, "is_handoff_shell": 1} if row["id"] == 100 else row for row in stored_run_rows],
            source=source,
            prefix="stored_",
        )
        skewed_runs = DataWarehouseTable.objects.get(team=self.team, name="stored_skewed_ci_runs")
        DataWarehouseSavedQuery.objects.filter(team=self.team, name=ci_rows.RUNS_VIEW_NAME).update(table=skewed_runs)
        with patch("posthoganalytics.feature_enabled", return_value=True):
            skewed = read(stored=True)
            assert skewed["jobs"] == live["jobs"]
            assert skewed["costs"] == live["costs"]

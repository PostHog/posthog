import json
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.test import SimpleTestCase

import pandas as pd
import pyarrow as pa
from deltalake import DeltaTable, write_deltalake
from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute

from products.data_modeling.backend.facade.api import check_incremental_eligibility, get_incremental_config
from products.data_modeling.backend.facade.models import DataWarehouseManagedViewSet, DataWarehouseSavedQuery
from products.data_modeling.backend.temporal.activities.incremental_write import UniqueKeyTracker, upsert_batch
from products.engineering_analytics.backend.facade.warehouse_views import get_expected_warehouse_views
from products.engineering_analytics.backend.logic.job_logs.constants import CI_LOGS_SERVICE_NAME
from products.engineering_analytics.backend.logic.sources import (
    PULL_REQUESTS_SCHEMA,
    WORKFLOW_JOBS_SCHEMA,
    WORKFLOW_RUNS_SCHEMA,
    JobSourceTables,
)
from products.engineering_analytics.backend.logic.views import (
    ci_failures,
    ci_job_history,
    ci_rows,
    depot_ci,
    job_costs,
    pr_friction,
)
from products.engineering_analytics.backend.logic.views.incremental_floor import SEED_LOOKBACK
from products.engineering_analytics.backend.logic.views.source_schema import (
    WORKFLOW_JOBS_COLUMNS,
    WORKFLOW_RUNS_COLUMNS,
)
from products.engineering_analytics.backend.tests._github_fixtures import (
    pr_association_entry,
    repo_id,
    seeding_object_storage,
)
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.testing import create_data_warehouse_table_from_csv
from products.warehouse_sources.backend.facade.types import DataWarehouseManagedViewSetKind, ExternalDataSourceType

TEST_BUCKET = "test_storage_bucket-posthog.products.engineering_analytics.ci_views"
GITHUB_SOURCE_PREFIX = "myprefix"

_BASE = "2026-01-01 10:00:00"
_LATER = "2026-01-01 10:10:00"
_REPO = "PostHog/posthog"


def _job_row(job_id: int, run_id: int, name: str) -> dict[str, Any]:
    return {
        "id": job_id,
        "run_id": run_id,
        "run_attempt": 1,
        "name": name,
        "workflow_name": "Backend CI",
        "status": "completed",
        "conclusion": "failure",
        "head_sha": f"jobsha{job_id}",
        "head_branch": "master",
        "labels": "[]",
        "runner_name": "runner-x",
        "runner_group_name": "",
        "created_at": _BASE,
        "started_at": _BASE,
        "completed_at": _LATER,
        "steps": "[]",
    }


def _run_row(
    run_id: int,
    head_sha: str,
    pr_numbers: list[int],
    head_commit: dict,
    run_attempt: int = 1,
    fork_pr_numbers: tuple[int, ...] = (),
) -> dict[str, Any]:
    return {
        "id": run_id,
        "name": "Backend CI",
        "head_sha": head_sha,
        "head_branch": "master",
        "status": "completed",
        "conclusion": "failure",
        "created_at": _BASE,
        "run_started_at": _BASE,
        "updated_at": _LATER,
        "run_attempt": run_attempt,
        "pull_requests": json.dumps(
            [pr_association_entry(number, base_repo="Mu-L/posthog-1") for number in fork_pr_numbers]
            + [pr_association_entry(number, base_repo=_REPO) for number in pr_numbers]
        ),
        "repository": json.dumps({"full_name": _REPO, "id": repo_id(_REPO)}),
        "head_commit": json.dumps(head_commit),
    }


def _create_table(test: BaseTest, base_name: str, columns: dict, rows: list[dict[str, Any]]) -> str:
    df = pd.DataFrame(rows, columns=list(columns.keys()))
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
    df.to_csv(tmp.name, index=False)
    tmp.close()
    test.addCleanup(Path(tmp.name).unlink, missing_ok=True)
    with seeding_object_storage(test):
        table, _source, _credential, _df, cleanup = create_data_warehouse_table_from_csv(
            csv_path=Path(tmp.name),
            table_name=base_name,
            table_columns=columns,
            test_bucket=TEST_BUCKET,
            team=test.team,
            source_prefix=GITHUB_SOURCE_PREFIX,
        )
    test.addCleanup(cleanup)
    return table.name


class TestCIJobHistoryView(ClickhouseTestMixin, BaseTest):
    def test_exposes_fields_and_derives_commit_attribution(self) -> None:
        jobs_table = _create_table(
            self,
            "github_workflow_jobs",
            WORKFLOW_JOBS_COLUMNS,
            [
                _job_row(1, run_id=100, name="job-a"),
                _job_row(2, run_id=200, name="job-b"),
                # No run row exists for run 999.
                _job_row(3, run_id=999, name="job-c"),
                _job_row(4, run_id=300, name="job-d"),
                _job_row(5, run_id=400, name="job-e"),
            ],
        )
        runs_table = _create_table(
            self,
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [
                _run_row(
                    100,
                    head_sha="runsha100",
                    pr_numbers=[5],
                    head_commit={
                        "author": {"name": "Alice", "email": "alice@x.com"},
                        "message": "fix(ci): thing (#4242)",
                    },
                ),
                # A master push with no pull_requests association and no (#NNNN) squash-merge suffix.
                _run_row(
                    200,
                    head_sha="runsha200",
                    pr_numbers=[],
                    head_commit={"author": {"name": "Bob"}, "message": "chore: no pr suffix"},
                ),
                # On a master push GitHub attaches the fork network's PRs, which share the head SHA and
                # have a foreign base repo. The commit is also a revert, so its message quotes the
                # reverted PR's (#N) before the reverting PR's own suffix.
                _run_row(
                    300,
                    head_sha="runsha300",
                    pr_numbers=[],
                    fork_pr_numbers=(1379, 3),
                    head_commit={
                        "author": {"name": "Carol"},
                        "message": 'Revert "feat(ci): thing (#4242)" (#4300)\n\nThis reverts commit abc.',
                    },
                ),
                # The runs snapshot keeps only the newest attempt's row per id, so this re-run row
                # carries run_attempt 2 while job-e is attempt 1.
                _run_row(
                    400,
                    head_sha="runsha400",
                    pr_numbers=[],
                    head_commit={"author": {"name": "Dave"}, "message": "fix: rerun me"},
                    run_attempt=2,
                ),
            ],
        )

        query = ci_job_history.build_query(
            jobs_table=depot_ci.with_depot_jobs(jobs_table, None, runs_table),
            runs_table=depot_ci.with_depot_runs(runs_table, None, None, None),
        )

        columns = execute_hogql_query(
            query=f"SELECT * FROM ({query})", team=self.team, query_type="engineering_analytics.test"
        ).columns
        assert columns == list(ci_job_history.FIELDS)

        select = ", ".join(ci_job_history.FIELDS)
        rows = execute_hogql_query(
            query=f"SELECT {select} FROM ({query}) ORDER BY job_name",
            team=self.team,
            query_type="engineering_analytics.test",
        ).results
        by_job = {row[list(ci_job_history.FIELDS).index("job_name")]: row for row in rows}
        field_index = {name: i for i, name in enumerate(ci_job_history.FIELDS)}

        def value(job_name: str, field: str) -> Any:
            return by_job[job_name][field_index[field]]

        assert value("job-a", "pr_number") == 5
        assert value("job-a", "commit_author_name") == "Alice"
        assert value("job-a", "commit_author_email") == "alice@x.com"
        assert value("job-a", "commit_message") == "fix(ci): thing (#4242)"
        assert value("job-a", "commit_pr_number") == 4242
        assert (value("job-a", "repo_owner"), value("job-a", "repo_name")) == ("PostHog", "posthog")
        assert value("job-a", "head_sha") == "runsha100"
        # Scan floors compare created_at_raw as a string, so it must stay the unparsed source value.
        assert value("job-a", "created_at_raw") == _BASE

        assert value("job-b", "pr_number") == 0
        assert value("job-b", "commit_author_name") == "Bob"
        assert value("job-b", "commit_pr_number") is None
        assert value("job-b", "commit_message") == "chore: no pr suffix"

        # The reverting PR gets the credit, not the reverted PR quoted in the title, and a fork
        # network PR never becomes pr_number.
        assert value("job-d", "commit_pr_number") == 4300
        assert value("job-d", "pr_number") == 0

        # ClickHouse fills the unmatched side of the LEFT JOIN with type defaults, so the
        # attribution of a job without a run row is empty and not NULL.
        assert "job-c" in by_job
        assert value("job-c", "repo_owner") == ""
        assert value("job-c", "commit_pr_number") is None

        # A join that also matched run_attempt would blank this attempt-1 job's attribution.
        assert value("job-e", "run_attempt") == 1
        assert value("job-e", "commit_author_name") == "Dave"
        assert value("job-e", "head_sha") == "runsha400"

    def test_union_all_of_two_sources_parses_and_stacks(self) -> None:
        jobs_table = _create_table(
            self, "github_workflow_jobs", WORKFLOW_JOBS_COLUMNS, [_job_row(1, run_id=100, name="job-a")]
        )
        runs_table = _create_table(
            self,
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [_run_row(100, head_sha="s", pr_numbers=[1], head_commit={"message": "m"})],
        )
        query = ci_job_history.build_query(
            jobs_table=depot_ci.with_depot_jobs(jobs_table, None, runs_table),
            runs_table=depot_ci.with_depot_runs(runs_table, None, None, None),
        )
        unioned = "\nUNION ALL\n".join([query, query])
        rows = execute_hogql_query(
            query=f"SELECT count() FROM ({unioned})", team=self.team, query_type="engineering_analytics.test"
        ).results
        assert rows[0][0] == 2


class TestCIFailuresView(ClickhouseTestMixin, BaseTest):
    def _insert_logs(self, rows: list[dict[str, Any]]) -> None:
        payload = "".join(json.dumps({"team_id": self.team.id, **row}) + "\n" for row in rows)
        sync_execute(f"INSERT INTO logs FORMAT JSONEachRow\n{payload}")

    def _log(self, body: str, attributes: dict[str, str], minute: int = 0) -> dict[str, Any]:
        # The logs table strips the "__str" key suffix to build the queryable `attributes` map,
        # so HogQL `attributes['run_id']` reads "run_id__str".
        return {
            "timestamp": f"2026-06-23 12:{minute:02d}:00.000000",
            "body": body,
            "service_name": CI_LOGS_SERVICE_NAME,
            "attributes_map_str": {f"{key}__str": value for key, value in attributes.items()},
        }

    def test_fingerprints_pytest_failures_and_skips_other_lines(self) -> None:
        attrs = {
            "run_id": "100",
            "job_id": "9",
            "run_attempt": "1",
            "branch": "master",
            "head_sha": "abc123",
            "repo": "PostHog/posthog",
            "workflow_name": "Backend CI",
            "job_name": "test (3)",
            "conclusion": "failure",
        }
        self._insert_logs(
            [
                self._log(
                    "FAILED posthog/api/test_foo.py::TestFoo::test_bar - AssertionError: got 42 at 0xdeadbeefcafe1234",
                    attrs,
                    minute=0,
                ),
                self._log("FAILED posthog/api/test_baz.py::test_qux", attrs, minute=1),
                self._log("PASSED posthog/api/test_ok.py::test_ok", attrs, minute=2),
                # Runner environment dumps contain FAILED without a '::' node id.
                self._log("E2E_TESTS: FAILED [1] (stage: build)", attrs, minute=3),
                # The space inside [...] must not truncate the node id.
                self._log("FAILED tests/test_api.py::test_status[user 123] - AssertionError: boom", attrs, minute=4),
            ]
        )

        rows = execute_hogql_query(
            query=ci_failures.build_query(), team=self.team, query_type="engineering_analytics.test"
        ).results
        by_test = {row[list(ci_failures.FIELDS).index("test_id")]: row for row in rows}
        field_index = {name: i for i, name in enumerate(ci_failures.FIELDS)}

        assert set(by_test) == {
            "posthog/api/test_foo.py::TestFoo::test_bar",
            "posthog/api/test_baz.py::test_qux",
            "tests/test_api.py::test_status[user 123]",
        }
        assert by_test["tests/test_api.py::test_status[user 123]"][field_index["error_signature"]] == (
            "AssertionError: boom"
        )

        detailed = by_test["posthog/api/test_foo.py::TestFoo::test_bar"]

        def value(field: str) -> Any:
            return detailed[field_index[field]]

        # Digit runs and hex blobs normalize to N so that re-runs share a signature.
        assert value("error_signature") == "AssertionError: got N at NxN"
        assert value("fingerprint") == "posthog/api/test_foo.py::TestFoo::test_bar | AssertionError: got N at NxN"
        assert value("run_id") == 100
        assert value("job_id") == 9
        assert value("run_attempt") == 1
        assert value("branch") == "master"
        assert value("repo") == "PostHog/posthog"
        assert value("conclusion") == "failure"

        no_detail = by_test["posthog/api/test_baz.py::test_qux"]
        assert no_detail[field_index["error_signature"]] is None
        assert no_detail[field_index["fingerprint"]] == "posthog/api/test_baz.py::test_qux | "


class TestStoredCIConfig(SimpleTestCase):
    @parameterized.expand(
        [
            ("runs", ci_rows.RUN_INCREMENTAL_CONFIG, "github_actions", 1, 1, 2, False),
            ("github_jobs", ci_rows.JOB_INCREMENTAL_CONFIG, "github_actions", 1, 2, 2, True),
            ("depot_jobs", ci_rows.JOB_INCREMENTAL_CONFIG, "depot_ci", 2, 2, 2, False),
        ]
    )
    def test_retry_upserts_preserve_each_source_and_replace_only_the_same_logical_row(
        self,
        _name: str,
        raw_config: dict[str, Any],
        engine: str,
        previous_attempt: int,
        next_id: int,
        next_attempt: int,
        keeps_previous: bool,
    ) -> None:
        config = get_incremental_config(DataWarehouseSavedQuery(incremental_config=raw_config))
        assert config is not None
        original = {
            "source_id": "first",
            "ci_engine": engine,
            "id": 1,
            "native_job_id": "job-1",
            "run_attempt": previous_attempt,
        }
        initial = pa.RecordBatch.from_pylist([original, {**original, "source_id": "second"}])
        UniqueKeyTracker(config.unique_key).check(initial)
        updated = {
            **original,
            "id": next_id,
            "run_attempt": next_attempt,
            "native_job_id": f"job-{next_id}" if engine == "github_actions" else "job-1",
        }
        with tempfile.TemporaryDirectory() as directory:
            write_deltalake(directory, pa.Table.from_batches([initial]))
            upsert_batch(directory, {}, pa.RecordBatch.from_pylist([updated]), config.unique_key, commit_metadata={})
            rows = DeltaTable(directory).to_pyarrow_table().to_pylist()

        expected = {("second", 1, previous_attempt), ("first", next_id, next_attempt)}
        if keeps_previous:
            expected.add(("first", 1, previous_attempt))
        assert {(row["source_id"], row["id"], row["run_attempt"]) for row in rows} == expected

    @parameterized.expand(
        [
            ("runs", ci_rows.runs_select, ci_rows.RUN_INCREMENTAL_CONFIG, False),
            ("jobs", ci_rows.jobs_select, ci_rows.JOB_INCREMENTAL_CONFIG, False),
            ("runs_with_depot", ci_rows.runs_select, ci_rows.RUN_INCREMENTAL_CONFIG, True),
            ("jobs_with_depot", ci_rows.jobs_select, ci_rows.JOB_INCREMENTAL_CONFIG, True),
        ]
    )
    def test_stored_views_are_eligible_for_their_incremental_config(
        self, _name: str, select: Callable[[JobSourceTables], str], raw_config: dict[str, Any], with_depot: bool
    ) -> None:
        source = JobSourceTables(
            github_workflow_jobs="github_workflow_jobs",
            github_workflow_runs="github_workflow_runs",
            source_id="source",
            repository=_REPO,
            depot_job_attempts=depot_ci.DepotJobAttempts(table="depot_job_attempts", repository=_REPO)
            if with_depot
            else None,
        )
        config = get_incremental_config(DataWarehouseSavedQuery(incremental_config=raw_config))
        assert config is not None
        result = check_incremental_eligibility(select(source), config)
        assert result.eligible, result.blockers


class TestStoredCIViews(ClickhouseTestMixin, BaseTest):
    @parameterized.expand(
        [
            ("runs", ci_rows.runs_select, ci_rows.RUN_FIELDS, [100, 200], {"is_handoff_shell": 0}),
            ("jobs", ci_rows.jobs_select, ci_rows.JOB_FIELDS, [1, 2, 3], {"is_rerun_copy": 0, "is_handoff_shell": 0}),
        ]
    )
    def test_view_runs_with_the_window_start_bound(
        self,
        _name: str,
        select: Callable[[JobSourceTables], str],
        fields: dict[str, Any],
        seeded_ids: list[int],
        flags: dict[str, int],
    ) -> None:
        recent = datetime.now(UTC).replace(microsecond=0) - timedelta(days=1)
        created_at = recent.strftime("%Y-%m-%dT%H:%M:%S.123Z")
        before_seed = (recent - SEED_LOOKBACK).strftime("%Y-%m-%dT%H:%M:%S.123Z")
        jobs_table = _create_table(
            self,
            "github_workflow_jobs",
            WORKFLOW_JOBS_COLUMNS,
            [
                {**_job_row(1, run_id=100, name="a"), "created_at": created_at},
                {**_job_row(2, run_id=100, name="b"), "created_at": created_at},
                {**_job_row(3, run_id=200, name="c"), "created_at": created_at},
                {**_job_row(4, run_id=300, name="d"), "created_at": before_seed},
            ],
        )
        runs_table = _create_table(
            self,
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [
                {**_run_row(100, head_sha="s100", pr_numbers=[5], head_commit={}), "created_at": created_at},
                {**_run_row(200, head_sha="s200", pr_numbers=[], head_commit={}), "created_at": created_at},
                {**_run_row(300, head_sha="s300", pr_numbers=[], head_commit={}), "created_at": before_seed},
            ],
        )
        source = JobSourceTables(
            github_workflow_jobs=jobs_table,
            github_workflow_runs=runs_table,
            source_id=str(uuid4()),
            repository=_REPO,
        )
        query = f"SELECT {', '.join(fields)} FROM ({select(source)}) ORDER BY id"

        rows_by_window = {}
        for since, expected_ids in (
            (None, seeded_ids),
            (recent, seeded_ids),
            (recent + timedelta(hours=1), []),
        ):
            response = execute_hogql_query(
                query=query,
                team=self.team,
                query_type="engineering_analytics.test",
                placeholders={"incremental_window_start": ast.Constant(value=since)},
            )
            assert response.columns == list(fields)
            assert [dict(zip(fields, row))["id"] for row in response.results] == expected_ids, since
            rows_by_window[since] = response.results

        first = dict(zip(fields, rows_by_window[None][0]))
        assert first["repository"] == _REPO.casefold()
        assert first["created_at_raw"] == created_at
        assert {flag: first[flag] for flag in flags} == flags


class TestExpectedWarehouseViews(BaseTest):
    def _qualifying_source(self, *, with_pull_requests: bool = False) -> ExternalDataSource:
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="gh",
            connection_id="gh",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.GITHUB,
            prefix=GITHUB_SOURCE_PREFIX,
        )
        endpoints = [(WORKFLOW_RUNS_SCHEMA, "workflow_runs"), (WORKFLOW_JOBS_SCHEMA, "workflow_jobs")]
        if with_pull_requests:
            endpoints.append((PULL_REQUESTS_SCHEMA, "pull_requests"))
        for schema_name, endpoint in endpoints:
            table = DataWarehouseTable.objects.create(
                team=self.team,
                name=f"{GITHUB_SOURCE_PREFIX}github_{endpoint}",
                format=DataWarehouseTable.TableFormat.CSVWithNames,
                url_pattern="",
                external_data_source=source,
                columns={},
            )
            ExternalDataSchema.objects.create(
                team=self.team, source=source, name=schema_name, table=table, should_sync=True
            )
        return source

    def test_no_source_exposes_no_views(self) -> None:
        assert get_expected_warehouse_views(self.team) == []

    def test_qualifying_source_exposes_every_view(self) -> None:
        self._qualifying_source()
        with patch("posthoganalytics.feature_enabled", return_value=True):
            views = {view.name: view for view in get_expected_warehouse_views(self.team)}
        assert set(views) == {
            job_costs.VIEW_NAME,
            ci_job_history.VIEW_NAME,
            ci_failures.VIEW_NAME,
            ci_rows.RUNS_VIEW_NAME,
            ci_rows.JOBS_VIEW_NAME,
        }
        for name, config in (
            (ci_rows.RUNS_VIEW_NAME, ci_rows.RUN_INCREMENTAL_CONFIG),
            (ci_rows.JOBS_VIEW_NAME, ci_rows.JOB_INCREMENTAL_CONFIG),
        ):
            assert views[name].sync_frequency == ci_rows.SYNC_FREQUENCY
            assert views[name].incremental_config == config

    @parameterized.expand(
        [
            ("flag_on", True, None, False, (ci_rows.RUNS_VIEW_NAME, ci_rows.JOBS_VIEW_NAME, pr_friction.VIEW_NAME)),
            ("flag_off", False, pr_friction.VIEW_NAME, True, ()),
            ("no_answer_keeps_friction_only", None, pr_friction.VIEW_NAME, True, (pr_friction.VIEW_NAME,)),
            ("no_answer_keeps_runs_only", None, ci_rows.RUNS_VIEW_NAME, True, (ci_rows.RUNS_VIEW_NAME,)),
            ("no_answer_keeps_jobs_only", None, ci_rows.JOBS_VIEW_NAME, True, (ci_rows.JOBS_VIEW_NAME,)),
            ("no_answer_ignores_a_user_query_of_that_name", None, pr_friction.VIEW_NAME, False, ()),
            ("no_answer_adds_no_view", None, None, False, ()),
        ]
    )
    def test_materialized_views_preserve_only_existing_managed_views_when_the_flag_has_no_answer(
        self, _name: str, flag: bool | None, existing_name: str | None, managed: bool, expected: tuple[str, ...]
    ) -> None:
        self._qualifying_source(with_pull_requests=True)
        if existing_name:
            viewset = (
                DataWarehouseManagedViewSet.objects.create(
                    team=self.team, kind=DataWarehouseManagedViewSetKind.ENGINEERING_ANALYTICS
                )
                if managed
                else None
            )
            DataWarehouseSavedQuery.objects.create(
                team=self.team,
                name=existing_name,
                query={"kind": "HogQLQuery", "query": "SELECT 1"},
                managed_viewset=viewset,
            )
        with patch("posthoganalytics.feature_enabled", return_value=flag):
            materialized = {view.name: view.materialized for view in get_expected_warehouse_views(self.team)}
        per_job = {job_costs.VIEW_NAME: False, ci_job_history.VIEW_NAME: False, ci_failures.VIEW_NAME: False}
        assert materialized == {**per_job, **dict.fromkeys(expected, True)}

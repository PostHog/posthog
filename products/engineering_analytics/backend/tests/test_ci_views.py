import json
import tempfile
from pathlib import Path
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin

import pandas as pd

from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute

from products.engineering_analytics.backend.facade.warehouse_views import get_expected_warehouse_views
from products.engineering_analytics.backend.logic.job_logs.constants import CI_LOGS_SERVICE_NAME
from products.engineering_analytics.backend.logic.sources import WORKFLOW_JOBS_SCHEMA, WORKFLOW_RUNS_SCHEMA
from products.engineering_analytics.backend.logic.views import ci_failures, ci_job_history, job_costs
from products.engineering_analytics.backend.logic.views.source_schema import (
    WORKFLOW_JOBS_COLUMNS,
    WORKFLOW_RUNS_COLUMNS,
)
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType
from products.warehouse_sources.backend.test.utils import create_data_warehouse_table_from_csv

TEST_BUCKET = "test_storage_bucket-posthog.products.engineering_analytics.ci_views"
GITHUB_SOURCE_PREFIX = "myprefix"

_BASE = "2026-01-01 10:00:00"
_LATER = "2026-01-01 10:10:00"


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
    run_id: int, head_sha: str, pull_requests: list[dict], head_commit: dict, run_attempt: int = 1
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
        "pull_requests": json.dumps(pull_requests),
        "repository": json.dumps({"full_name": "PostHog/posthog"}),
        "head_commit": json.dumps(head_commit),
    }


class TestCIJobHistoryView(ClickhouseTestMixin, BaseTest):
    """The generated ci_job_history SQL must expose exactly the FIELDS columns and correctly derive
    commit attribution — the substrate the green/red boundary analysis reads. Skips when object
    storage is unreachable so the suite still runs without the dev stack."""

    def _create_table(self, base_name: str, columns: dict, rows: list[dict[str, Any]]) -> str:
        df = pd.DataFrame(rows, columns=list(columns.keys()))
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
        df.to_csv(tmp.name, index=False)
        tmp.close()
        self.addCleanup(Path(tmp.name).unlink, missing_ok=True)
        try:
            table, _source, _credential, _df, cleanup = create_data_warehouse_table_from_csv(
                csv_path=Path(tmp.name),
                table_name=base_name,
                table_columns=columns,
                test_bucket=TEST_BUCKET,
                team=self.team,
                source_prefix=GITHUB_SOURCE_PREFIX,
            )
        except PermissionError as err:
            self.skipTest(f"object storage unavailable: {err}")
        self.addCleanup(cleanup)
        return table.name

    def test_exposes_fields_and_derives_commit_attribution(self) -> None:
        jobs_table = self._create_table(
            "github_workflow_jobs",
            WORKFLOW_JOBS_COLUMNS,
            [
                _job_row(1, run_id=100, name="job-a"),
                _job_row(2, run_id=200, name="job-b"),
                # A job whose run row is missing — the LEFT JOIN must keep it with NULL attribution.
                _job_row(3, run_id=999, name="job-c"),
                _job_row(4, run_id=300, name="job-d"),
                # A first-attempt job whose run row was upserted by a re-run (run_attempt 2): the
                # run_id-only join must still attach the run's attribution.
                _job_row(5, run_id=400, name="job-e"),
            ],
        )
        runs_table = self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [
                _run_row(
                    100,
                    head_sha="runsha100",
                    pull_requests=[{"number": 5}],
                    head_commit={
                        "author": {"name": "Alice", "email": "alice@x.com"},
                        "message": "fix(ci): thing (#4242)",
                    },
                ),
                # No pull_requests association (a master push): pr_number stays 0, and the only PR
                # attribution comes from the (#NNNN) squash-merge suffix — here deliberately absent.
                _run_row(
                    200,
                    head_sha="runsha200",
                    pull_requests=[],
                    head_commit={"author": {"name": "Bob"}, "message": "chore: no pr suffix"},
                ),
                # A revert: the message carries the reverted PR's (#N) inside quotes AND the revert
                # PR's own suffix — the anchored extraction must attribute the reverting PR.
                _run_row(
                    300,
                    head_sha="runsha300",
                    pull_requests=[],
                    head_commit={
                        "author": {"name": "Carol"},
                        "message": 'Revert "feat(ci): thing (#4242)" (#4300)\n\nThis reverts commit abc.',
                    },
                ),
                # The runs snapshot keeps only the newest attempt's row per id — this run was re-run,
                # so its row carries run_attempt 2 while the seeded job above is attempt 1.
                _run_row(
                    400,
                    head_sha="runsha400",
                    pull_requests=[],
                    head_commit={"author": {"name": "Dave"}, "message": "fix: rerun me"},
                    run_attempt=2,
                ),
            ],
        )

        query = ci_job_history.build_query(jobs_table=jobs_table, runs_table=runs_table)

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

        # Run with a PR association + a (#NNNN) merge suffix: both PR keys resolve, commit attribution
        # comes off head_commit, and head_sha is the run's (not the job's) sha.
        assert value("job-a", "pr_number") == 5
        assert value("job-a", "commit_author_name") == "Alice"
        assert value("job-a", "commit_author_email") == "alice@x.com"
        assert value("job-a", "commit_message") == "fix(ci): thing (#4242)"
        assert value("job-a", "commit_pr_number") == 4242
        assert (value("job-a", "repo_owner"), value("job-a", "repo_name")) == ("PostHog", "posthog")
        assert value("job-a", "head_sha") == "runsha100"
        # created_at_raw carries the unparsed source string (the scan-pruning floor rides on this),
        # not the parsed datetime — so it must equal the raw value, distinct from parsed created_at.
        assert value("job-a", "created_at_raw") == _BASE

        # Master push: pr_number 0 (builder semantics kept, not nulled), no (#NNNN) → commit_pr_number NULL.
        assert value("job-b", "pr_number") == 0
        assert value("job-b", "commit_author_name") == "Bob"
        assert value("job-b", "commit_pr_number") is None
        assert value("job-b", "commit_message") == "chore: no pr suffix"

        # Revert commit: two (#N) occurrences — the anchored extraction must credit the reverting
        # PR (#4300), never the reverted one quoted in the title (#4242).
        assert value("job-d", "commit_pr_number") == 4300

        # Unjoined run: the LEFT JOIN keeps the job attempt (an INNER join would drop it — the guard
        # here). ClickHouse fills the unmatched run side with type defaults, so attribution is empty
        # (not a real repo) and no PR resolves off the absent commit message.
        assert "job-c" in by_job
        assert value("job-c", "repo_owner") == ""
        assert value("job-c", "commit_pr_number") is None

        # Re-run: the runs row was upserted to attempt 2 while this job is attempt 1 — the
        # run_id-only join must still carry the run's attribution (an attempt-equality join blanks it).
        assert value("job-e", "run_attempt") == 1
        assert value("job-e", "commit_author_name") == "Dave"
        assert value("job-e", "head_sha") == "runsha400"

    def test_union_all_of_two_sources_parses_and_stacks(self) -> None:
        # build_team_view stitches per-source SELECTs with UNION ALL; the columns must line up across
        # the boundary. Unioning one source's SELECT with itself proves the shape agrees and stacks.
        jobs_table = self._create_table(
            "github_workflow_jobs", WORKFLOW_JOBS_COLUMNS, [_job_row(1, run_id=100, name="job-a")]
        )
        runs_table = self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [_run_row(100, head_sha="s", pull_requests=[{"number": 1}], head_commit={"message": "m"})],
        )
        query = ci_job_history.build_query(jobs_table=jobs_table, runs_table=runs_table)
        unioned = "\nUNION ALL\n".join([query, query])
        rows = execute_hogql_query(
            query=f"SELECT count() FROM ({unioned})", team=self.team, query_type="engineering_analytics.test"
        ).results
        assert rows[0][0] == 2


class TestCIFailuresView(ClickhouseTestMixin, BaseTest):
    """The generated ci_failures SQL must fingerprint pytest FAILED lines from the Logs product and
    ignore everything else — the failure-index substrate."""

    def _insert_logs(self, rows: list[dict[str, Any]]) -> None:
        payload = "".join(json.dumps({"team_id": self.team.id, **row}) + "\n" for row in rows)
        sync_execute(f"INSERT INTO logs FORMAT JSONEachRow\n{payload}")

    def _log(self, body: str, attributes: dict[str, str], minute: int = 0) -> dict[str, Any]:
        # attributes_map_str keys carry the "__str" suffix the logs table strips for the queryable
        # `attributes` map (see logs34 mapApply), so a HogQL `attributes['run_id']` reads "run_id__str".
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
                # A failure with a trailing detail carrying volatile bits (a count and a hex blob).
                self._log(
                    "FAILED posthog/api/test_foo.py::TestFoo::test_bar - AssertionError: got 42 at 0xdeadbeefcafe1234",
                    attrs,
                    minute=0,
                ),
                # A failure with no " - detail" — its signature is empty, so error_signature is NULL.
                self._log("FAILED posthog/api/test_baz.py::test_qux", attrs, minute=1),
                # Not a pytest FAILED line — must be filtered out by the WHERE clause.
                self._log("PASSED posthog/api/test_ok.py::test_ok", attrs, minute=2),
                # Contains FAILED but no '::' node id (runner env-dump noise seen in real CI logs) —
                # must not produce a junk fingerprint.
                self._log("E2E_TESTS: FAILED [1] (stage: build)", attrs, minute=3),
                # A parameterized id with a space inside [...] — the extraction must keep the full
                # node id (not truncate at the space) and normalize only the signature, never the id.
                self._log("FAILED tests/test_api.py::test_status[user 123] - AssertionError: boom", attrs, minute=4),
            ]
        )

        rows = execute_hogql_query(
            query=ci_failures.build_query(), team=self.team, query_type="engineering_analytics.test"
        ).results
        by_test = {row[list(ci_failures.FIELDS).index("test_id")]: row for row in rows}
        field_index = {name: i for i, name in enumerate(ci_failures.FIELDS)}

        # The PASSED line is excluded; only the real FAILED node ids survive — including the
        # parameterized one, whose id keeps the space inside [...] untruncated and unnormalized.
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

        # Volatile bits (the digit run and the long hex blob) normalize to N so re-runs share a signature.
        assert value("error_signature") == "AssertionError: got N at NxN"
        assert value("fingerprint") == "posthog/api/test_foo.py::TestFoo::test_bar | AssertionError: got N at NxN"
        assert value("run_id") == 100
        assert value("job_id") == 9
        assert value("run_attempt") == 1
        assert value("branch") == "master"
        assert value("repo") == "PostHog/posthog"
        assert value("conclusion") == "failure"

        # No trailing detail → empty signature → NULL error_signature, but the fingerprint still forms.
        no_detail = by_test["posthog/api/test_baz.py::test_qux"]
        assert no_detail[field_index["error_signature"]] is None
        assert no_detail[field_index["fingerprint"]] == "posthog/api/test_baz.py::test_qux | "


class TestExpectedWarehouseViews(BaseTest):
    """The facade must expose all three views together for a qualifying GitHub source, and nothing
    for a team without one — so a consumer sees a coherent set, never a partial one."""

    def _qualifying_source(self) -> ExternalDataSource:
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="gh",
            connection_id="gh",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.GITHUB,
            prefix=GITHUB_SOURCE_PREFIX,
        )
        for schema_name, endpoint in ((WORKFLOW_RUNS_SCHEMA, "workflow_runs"), (WORKFLOW_JOBS_SCHEMA, "workflow_jobs")):
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

    def test_qualifying_source_exposes_all_three_views(self) -> None:
        self._qualifying_source()
        names = {view.name for view in get_expected_warehouse_views(self.team)}
        assert names == {job_costs.VIEW_NAME, ci_job_history.VIEW_NAME, ci_failures.VIEW_NAME}

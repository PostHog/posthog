import json
import datetime as dt
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, cast

import pytest
import time_machine
from unittest import mock

import pyarrow as pa
import deltalake
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.test.helpers import (
    make_local_table_ref,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.writer import DeltaWriter
from products.warehouse_sources.backend.temporal.data_imports.sources.common.cursor import SourceCursorManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.depot.depot import (
    DEPOT_CI_SERVICE_URL,
    depot_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.depot.source import (
    DepotReconciliationCursor,
    DepotSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.depot import DepotSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSchemaSyncType

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.depot.depot"
REPOSITORY = "example-org/example-repo"
API_TOKEN = "depot-test-token"
IN_FLIGHT = ["queued", "running"]
TERMINAL = ["finished", "failed", "cancelled"]
NOW = dt.datetime.now(dt.UTC)


def _iso(value: dt.datetime) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _run(run_id: str, age: dt.timedelta) -> dict[str, Any]:
    return {"runId": run_id, "repo": REPOSITORY, "status": "finished", "createdAt": _iso(NOW - age)}


def _response(status: int, body: dict[str, Any], method: str) -> Response:
    response = Response()
    response.status_code = status
    response.reason = {200: "OK", 401: "Unauthorized", 403: "Forbidden"}.get(status, "Error")
    response.url = f"{DEPOT_CI_SERVICE_URL}/{method}"
    response._content = json.dumps(body).encode()
    return response


def _single_attempt_workflow(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "runId": run["runId"],
        "workflowId": f"{run['runId']}-wf",
        "jobs": [
            {"jobId": f"{run['runId']}-job", "attempts": [{"attemptId": f"{run['runId']}-attempt", "attempt": 1}]}
        ],
    }


def _fake_session(
    terminal_runs: list[dict[str, Any]],
    in_flight_runs: list[dict[str, Any]] | None = None,
    workflows_by_run: dict[str, list[dict[str, Any]]] | None = None,
) -> mock.MagicMock:
    workflows = workflows_by_run or {run["runId"]: [_single_attempt_workflow(run)] for run in terminal_runs}
    workflows_by_id = {workflow["workflowId"]: workflow for runs in workflows.values() for workflow in runs}

    def post(url: str, json: dict[str, Any], timeout: float) -> Response:
        method = url.removeprefix(f"{DEPOT_CI_SERVICE_URL}/")
        if method == "ListRuns" and json["status"] == IN_FLIGHT:
            return _response(200, {"runs": in_flight_runs or []}, method)
        if method == "ListRuns":
            # Depot's cursor: a page that ends inside a second makes the next page skip the rest of it.
            start = int(json.get("pageToken", "0"))
            page = terminal_runs[start : start + json["pageSize"]]
            end = start + len(page)
            while page and end < len(terminal_runs) and terminal_runs[end]["createdAt"] == page[-1]["createdAt"]:
                end += 1
            next_page_token = str(end) if end < len(terminal_runs) else ""
            return _response(200, {"runs": page, "nextPageToken": next_page_token}, method)
        if method == "GetRunStatus":
            run_workflows = workflows.get(json["runId"], [])
            return _response(200, {"workflows": [{"workflowId": w["workflowId"]} for w in run_workflows]}, method)
        return _response(200, workflows_by_id[json["workflowId"]], method)

    session = mock.MagicMock()
    session.post.side_effect = post
    return session


def _requests(session: mock.MagicMock) -> list[tuple[str, dict[str, Any]]]:
    return [
        (call.args[0].removeprefix(f"{DEPOT_CI_SERVICE_URL}/"), call.kwargs["json"])
        for call in session.post.call_args_list
    ]


def _batches(response: SourceResponse) -> list[list[dict[str, Any]]]:
    return list(cast(Iterable[list[dict[str, Any]]], response.items()))


def _synced_rows(session: mock.MagicMock, created_after: dt.datetime | str | None) -> list[dict[str, Any]]:
    with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
        batches = _batches(depot_source(API_TOKEN, REPOSITORY, created_after, mock.MagicMock()))
    return [row for batch in batches for row in batch]


# Newest first, the order ListRuns returns terminal runs in.
TERMINAL_RUNS = [
    _run("r6", dt.timedelta(minutes=10)),
    _run("r5", dt.timedelta(hours=1)),
    _run("r4", dt.timedelta(hours=2)),
    _run("r3", dt.timedelta(hours=3)),
    _run("r2", dt.timedelta(hours=4)),
    _run("r1", dt.timedelta(hours=5)),
    _run("r0", dt.timedelta(days=6)),
]
# Between r3 and r2, so no run can tie it.
WATERMARK = NOW - dt.timedelta(hours=3, minutes=30)


class TestDepotSource:
    def test_in_flight_runs_do_not_block_terminal_runs(self) -> None:
        stuck = {**_run("stuck", dt.timedelta(days=30)), "status": "running"}
        workflows = {run["runId"]: [_single_attempt_workflow(run)] for run in [*TERMINAL_RUNS, stuck]}
        session = _fake_session(TERMINAL_RUNS, [stuck], workflows_by_run=workflows)

        assert [row["run_id"] for row in _synced_rows(session, WATERMARK)] == ["r6", "r5", "r4", "r3"]

    @pytest.mark.parametrize(
        "created_after, expected_run_ids, expected_terminal_pages",
        [
            (WATERMARK, ["r6", "r5", "r4", "r3"], 5),
            (TERMINAL_RUNS[4]["createdAt"], ["r6", "r5", "r4", "r3", "r2"], 5),
            (None, ["r6", "r5", "r4", "r3", "r2", "r1", "r0"], 7),
        ],
        # The bounds derive from the wall clock, so fixed ids keep every xdist worker collecting the same tests.
        ids=["datetime_watermark", "watermark_in_a_runs_second", "no_watermark"],
    )
    def test_walks_terminal_runs_down_to_the_lower_bound_and_yields_them_newest_first(
        self, created_after: dt.datetime | str | None, expected_run_ids: list[str], expected_terminal_pages: int
    ) -> None:
        session = _fake_session(TERMINAL_RUNS)

        with mock.patch(f"{MODULE}.LIST_RUNS_PAGE_SIZES", (2, 3)):
            rows = _synced_rows(session, created_after)

        assert [row["run_id"] for row in rows] == expected_run_ids
        terminal_list_calls = [
            body for method, body in _requests(session) if method == "ListRuns" and body["status"] == TERMINAL
        ]
        assert len(terminal_list_calls) == expected_terminal_pages

    @pytest.mark.parametrize(
        "page_sizes, expected_run_ids",
        [
            ((3,), ["newest", "tied-1", "tied-0", "oldest"]),
            ((3, 4), ["newest", "tied-2", "tied-1", "tied-0", "oldest"]),
        ],
        ids=["one_walk_skips_the_rest_of_the_second", "a_second_walk_returns_it"],
    )
    def test_a_second_walk_returns_runs_a_page_end_skips(
        self, page_sizes: tuple[int, ...], expected_run_ids: list[str]
    ) -> None:
        runs = [
            _run("newest", dt.timedelta(minutes=10)),
            *[_run(f"tied-{index}", dt.timedelta(hours=1)) for index in range(3)],
            _run("oldest", dt.timedelta(hours=2)),
        ]
        session = _fake_session(runs)

        with mock.patch(f"{MODULE}.LIST_RUNS_PAGE_SIZES", page_sizes):
            rows = _synced_rows(session, None)

        assert [row["run_id"] for row in rows] == expected_run_ids

    def test_request_shapes(self) -> None:
        session = _fake_session(TERMINAL_RUNS[:4])

        with (
            mock.patch(f"{MODULE}.make_tracked_session", return_value=session) as make_session,
            mock.patch(f"{MODULE}.LIST_RUNS_PAGE_SIZES", (2, 3)),
        ):
            _batches(depot_source(API_TOKEN, REPOSITORY, None, mock.MagicMock()))

        assert make_session.call_args.kwargs["headers"] == {"Authorization": f"Bearer {API_TOKEN}"}
        assert API_TOKEN in make_session.call_args.kwargs["redact_values"]
        # Every Depot RPC is a POST, which the shared retry leaves out, so a 429 must still retry.
        assert make_session.call_args.kwargs["retry"].is_retry("POST", 429)
        assert _requests(session)[:4] == [
            ("ListRuns", {"repo": REPOSITORY, "status": TERMINAL, "pageSize": 2}),
            ("ListRuns", {"repo": REPOSITORY, "status": TERMINAL, "pageSize": 2, "pageToken": "2"}),
            ("ListRuns", {"repo": REPOSITORY, "status": TERMINAL, "pageSize": 3}),
            ("ListRuns", {"repo": REPOSITORY, "status": TERMINAL, "pageSize": 3, "pageToken": "3"}),
        ]
        assert _requests(session)[4:6] == [("GetRunStatus", {"runId": "r6"}), ("GetWorkflow", {"workflowId": "r6-wf"})]

    def test_flattens_one_row_per_attempt_of_every_workflow_in_the_run(self) -> None:
        run = _run("run-1", dt.timedelta(hours=1))
        backend = {
            "runId": "run-1",
            "repo": REPOSITORY,
            "ref": "refs/pull/42/merge",
            "sha": "abc123",
            "headSha": "def456",
            "trigger": "pull_request",
            "runStatus": "failed",
            # A different precision from the listing, which the cursor must not take.
            "runCreatedAt": "2026-01-01T00:00:00Z",
            "runStartedAt": "2026-01-01T00:00:01Z",
            "runFinishedAt": "2026-01-01T00:10:00Z",
            "workflowId": "wf-1",
            "workflowName": "Backend CI",
            "workflowPath": "ci-backend.yml",
            "workflowStatus": "failed",
            "workflowCreatedAt": "2026-01-01T00:00:00Z",
            "workflowStartedAt": "2026-01-01T00:00:02Z",
            "workflowFinishedAt": "2026-01-01T00:09:59Z",
            "jobs": [
                {
                    "jobId": "job-matrix",
                    "jobKey": "ci-backend.yml:turbo-tests:matrix-38",
                    "jobDisplayName": "Product tests (shard 38)",
                    "status": "finished",
                    "startedAt": "2026-01-01T00:00:04Z",
                    "finishedAt": "2026-01-01T00:08:00Z",
                    "attempts": [
                        {
                            "attemptId": "attempt-1",
                            "attempt": 1,
                            "status": "failed",
                            "sandboxId": "sandbox-1",
                            "sessionId": "session-1",
                            "startedAt": "2026-01-01T00:00:04Z",
                            "finishedAt": "2026-01-01T00:04:00Z",
                        },
                        {"attemptId": "attempt-2", "attempt": 2},
                    ],
                },
                {"jobId": "job-placeholder", "jobKey": "ci-backend.yml:django:_dynamicMatrix", "status": "skipped"},
            ],
        }
        report = {
            "runId": "run-1",
            "workflowId": "wf-2",
            "jobs": [{"jobId": "job-report", "attempts": [{"attemptId": "attempt-3"}]}],
        }
        session = _fake_session([run], workflows_by_run={"run-1": [backend, report]})

        rows = _synced_rows(session, None)

        assert [(row["workflow_id"], row["attempt_id"], row["job_display_name"]) for row in rows] == [
            ("wf-1", "attempt-1", "Product tests (shard 38)"),
            ("wf-1", "attempt-2", "Product tests (shard 38)"),
            ("wf-2", "attempt-3", None),
        ]
        assert rows[0] == {
            "run_id": "run-1",
            "run_workflow_count": 2,
            "repo": REPOSITORY,
            "ref": "refs/pull/42/merge",
            "sha": "abc123",
            "head_sha": "def456",
            "trigger": "pull_request",
            "run_status": "failed",
            "run_created_at": run["createdAt"],
            "run_started_at": "2026-01-01T00:00:01Z",
            "run_finished_at": "2026-01-01T00:10:00Z",
            "workflow_id": "wf-1",
            "workflow_name": "Backend CI",
            "workflow_path": "ci-backend.yml",
            "workflow_status": "failed",
            "workflow_created_at": "2026-01-01T00:00:00Z",
            "workflow_started_at": "2026-01-01T00:00:02Z",
            "workflow_finished_at": "2026-01-01T00:09:59Z",
            "job_id": "job-matrix",
            "job_key": "ci-backend.yml:turbo-tests:matrix-38",
            "job_display_name": "Product tests (shard 38)",
            "job_status": "finished",
            "job_started_at": "2026-01-01T00:00:04Z",
            "job_finished_at": "2026-01-01T00:08:00Z",
            "attempt_id": "attempt-1",
            "attempt": 1,
            "attempt_status": "failed",
            "attempt_started_at": "2026-01-01T00:00:04Z",
            "attempt_finished_at": "2026-01-01T00:04:00Z",
            "sandbox_id": "sandbox-1",
        }


class TestDepotReconciliation:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("age_days,reconciled_days_ago", [(2, 1), (14, 7)])
    async def test_replayed_attempts_update_storage_without_duplicates(
        self, age_days: int, reconciled_days_ago: int, tmp_path: Path
    ) -> None:
        source = DepotSource()
        config = DepotSourceConfig(api_token=API_TOKEN, repository=REPOSITORY)
        run = _run("run-1", dt.timedelta(days=age_days))
        workflow = _single_attempt_workflow(run)
        workflow["workflowStatus"] = "failed"
        job = workflow["jobs"][0]
        job["attempts"][0]["status"] = "failed"
        session = _fake_session([run], workflows_by_run={run["runId"]: [workflow]})
        manager = SourceCursorManager(source.cursor_class(), None, source)
        inputs = mock.MagicMock(
            sync_type=ExternalDataSchemaSyncType.INCREMENTAL,
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            history_start=NOW - dt.timedelta(days=30),
            source_cursor=manager,
        )
        columns = ("attempt_id", "attempt_status", "workflow_status")

        async def sync_and_read_storage() -> list[tuple[str, str, str]]:
            response = source.source_for_pipeline(config, inputs)
            rows = [row for batch in _batches(response) for row in batch]
            await DeltaWriter(make_local_table_ref(str(tmp_path / "attempts"))).write(
                data=pa.Table.from_pylist([{key: row[key] for key in columns} for row in rows]),
                write_type="incremental",
                should_overwrite_table=False,
                primary_keys=response.primary_keys,
            )
            stored = deltalake.DeltaTable(str(tmp_path / "attempts")).to_pyarrow_table().to_pylist()
            return sorted(tuple(row[key] for key in columns) for row in stored)

        with time_machine.travel(NOW, tick=False), mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            assert await sync_and_read_storage() == [("run-1-attempt", "failed", "failed")]

            workflow["workflowStatus"] = "finished"
            job["attempts"].append({"attemptId": "retry-2", "attempt": 2, "status": "finished"})
            inputs.db_incremental_field_last_value = _iso(NOW - dt.timedelta(minutes=10))
            inputs.source_cursor = SourceCursorManager(
                source.cursor_class(),
                DepotReconciliationCursor(reconciled_at=_iso(NOW - dt.timedelta(days=reconciled_days_ago))),
                source,
            )
            after_retry = [("retry-2", "finished", "finished"), ("run-1-attempt", "failed", "finished")]
            assert await sync_and_read_storage() == after_retry
            assert await sync_and_read_storage() == after_retry

    @pytest.mark.parametrize(
        "reconciled_days_ago, history_days, has_watermark, expected_runs, expected_reconciled",
        [
            (None, 30, True, ["recent", "old"], True),
            (1, 30, True, ["recent"], False),
            (7, 30, True, ["recent", "old"], True),
            (1, 30, False, ["recent", "old"], True),
            (None, None, True, ["recent", "old", "outside"], True),
            (1, 1, True, [], False),
        ],
    )
    def test_replays_retries_and_reconciles_retained_history(
        self,
        reconciled_days_ago: int | None,
        history_days: int | None,
        has_watermark: bool,
        expected_runs: list[str],
        expected_reconciled: bool,
    ) -> None:
        source = DepotSource()
        cursor = (
            DepotReconciliationCursor(reconciled_at=_iso(NOW - dt.timedelta(days=reconciled_days_ago)))
            if reconciled_days_ago is not None
            else None
        )
        manager = SourceCursorManager(source.cursor_class(), cursor, source)
        inputs = mock.MagicMock(
            should_use_incremental_field=True,
            db_incremental_field_last_value=_iso(NOW - dt.timedelta(minutes=10)) if has_watermark else None,
            history_start=NOW - dt.timedelta(days=history_days) if history_days is not None else None,
            source_cursor=manager,
        )
        runs = [
            _run("recent", dt.timedelta(days=2)),
            _run("old", dt.timedelta(days=14)),
            _run("outside", dt.timedelta(days=40)),
        ]
        workflows = {run["runId"]: [_single_attempt_workflow(run)] for run in runs}
        for run_workflows in workflows.values():
            job = run_workflows[0]["jobs"][0]
            job["attempts"].append({"attemptId": f"{job['jobId']}-retry", "attempt": 2})
        session = _fake_session(runs, workflows_by_run=workflows)

        with time_machine.travel(NOW, tick=False), mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            response = source.source_for_pipeline(DepotSourceConfig(api_token=API_TOKEN, repository=REPOSITORY), inputs)
            assert manager.staged is None
            rows = [row for batch in _batches(response) for row in batch]

        assert [row["run_id"] for row in rows if row["attempt"] == 2] == expected_runs
        assert (manager.staged is not None) == expected_reconciled

    def test_incomplete_reconciliation_does_not_advance_the_cursor(self) -> None:
        source = DepotSource()
        manager = SourceCursorManager(source.cursor_class(), None, source)
        inputs = mock.MagicMock(should_use_incremental_field=False, history_start=None, source_cursor=manager)
        runs = [_run("recent", dt.timedelta(days=2)), _run("old", dt.timedelta(days=14))]
        session = _fake_session(runs)
        post = session.post.side_effect

        def interrupted_post(url: str, json: dict[str, Any], timeout: float) -> Response:
            if url.endswith("/GetWorkflow") and json["workflowId"] == "old-wf":
                return _response(500, {}, "GetWorkflow")
            return cast(Response, post(url, json=json, timeout=timeout))

        session.post.side_effect = interrupted_post
        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            response = source.source_for_pipeline(DepotSourceConfig(api_token=API_TOKEN, repository=REPOSITORY), inputs)
            batches = cast(Iterator[list[dict[str, Any]]], response.items())
            assert next(batches)[0]["run_id"] == "recent"
            assert manager.staged is None
            with pytest.raises(HTTPError, match="500 Server Error"):
                list(batches)
            assert manager.staged is None


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, expected_valid, expected_message_fragment",
        [
            (200, True, None),
            (401, False, "didn't accept this API token"),
            (403, False, "organization API token"),
            (500, False, "HTTP 500"),
        ],
    )
    def test_maps_probe_status_to_result(
        self, status: int, expected_valid: bool, expected_message_fragment: str | None
    ) -> None:
        session = mock.MagicMock()
        session.post.return_value = _response(
            status, {"runs": []} if status == 200 else {"code": "permission_denied", "message": "denied"}, "ListRuns"
        )

        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            valid, message = validate_credentials(API_TOKEN, REPOSITORY)

        assert valid is expected_valid
        if expected_message_fragment is None:
            assert message is None
        else:
            assert message is not None and expected_message_fragment in message
        assert session.post.call_args.kwargs["json"] == {"repo": REPOSITORY, "pageSize": 1}

import json
import datetime as dt
from collections.abc import Iterable, Iterator
from typing import Any, cast

import pytest
import time_machine
from unittest import mock

from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.cursor import SourceCursorManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.depot.depot import (
    DEPOT_CI_SERVICE_URL,
    depot_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.depot.settings import (
    ARTIFACTS,
    FAILURE_DIAGNOSES,
    JOB_ATTEMPTS,
    JOB_METRICS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.depot.source import (
    DepotReconciliationCursor,
    DepotSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.depot import DepotSourceConfig

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.depot.depot"
REPOSITORY = "example-org/example-repo"
API_TOKEN = "depot-test-token"
IN_FLIGHT = ["queued", "running"]
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
            return _response(200, {"workflows": workflows.get(json["runId"], [])}, method)
        if method == "GetJobMetrics":
            attempts = next(
                job["attempts"]
                for workflow in workflows_by_id.values()
                for job in workflow["jobs"]
                if job["jobId"] == json["jobId"]
            )
            summaries = [{"attempt": attempt, "stats": {"peakMemoryUsageBytes": "1024"}} for attempt in attempts]
            return _response(200, {"job": {"jobKey": "build"}, "attempts": summaries}, method)
        if method == "ListArtifacts":
            artifacts_page: dict[str, Any]
            if "pageToken" not in json:
                artifacts_page = {
                    "artifacts": [{"artifactId": f"{json['runId']}-a1", "sizeBytes": "2048"}],
                    "nextPageToken": "p2",
                }
            else:
                artifacts_page = {"artifacts": [{"artifactId": f"{json['runId']}-a2", "sizeBytes": "4096"}]}
            return _response(200, artifacts_page, method)
        if method == "GetFailureDiagnosis":
            groups = [{"fingerprint": "fp-1", "count": 2, "errorMessage": "exit status 1"}]
            return _response(
                200, {"state": "FAILURE_DIAGNOSIS_STATE_GROUPED_FAILURES", "failureGroups": groups}, method
            )
        return _response(200, workflows_by_id[json["workflowId"]], method)

    session = mock.MagicMock()
    session.post.side_effect = post
    return session


def _batches(response: SourceResponse) -> list[list[dict[str, Any]]]:
    return list(cast(Iterable[list[dict[str, Any]]], response.items()))


def _synced_rows(
    session: mock.MagicMock, created_after: dt.datetime | str | None, endpoint: str = JOB_ATTEMPTS
) -> list[dict[str, Any]]:
    with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
        batches = _batches(depot_source(API_TOKEN, REPOSITORY, created_after, mock.MagicMock(), endpoint=endpoint))
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

    @pytest.mark.parametrize(
        "endpoint, columns, expected_rows, expected_calls",
        [
            (
                JOB_METRICS,
                ("run_id", "attempt_id", "peak_memory_usage_bytes"),
                [("failed", "failed-attempt", 1024), ("ok", "ok-attempt", 1024)],
                [("GetJobMetrics", {"jobId": "failed-job"}), ("GetJobMetrics", {"jobId": "ok-job"})],
            ),
            (
                ARTIFACTS,
                ("run_id", "artifact_id", "size_bytes"),
                [
                    ("failed", "failed-a1", 2048),
                    ("failed", "failed-a2", 4096),
                    ("ok", "ok-a1", 2048),
                    ("ok", "ok-a2", 4096),
                ],
                [
                    ("ListArtifacts", {"runId": "failed", "pageSize": 500}),
                    ("ListArtifacts", {"runId": "failed", "pageSize": 500, "pageToken": "p2"}),
                    ("ListArtifacts", {"runId": "ok", "pageSize": 500}),
                    ("ListArtifacts", {"runId": "ok", "pageSize": 500, "pageToken": "p2"}),
                ],
            ),
            (
                FAILURE_DIAGNOSES,
                ("run_id", "fingerprint", "count"),
                [("failed", "fp-1", 2)],
                [("GetFailureDiagnosis", {"targetId": "failed", "targetType": "FAILURE_DIAGNOSIS_TARGET_TYPE_RUN"})],
            ),
        ],
    )
    def test_run_child_tables(
        self,
        endpoint: str,
        columns: tuple[str, ...],
        expected_rows: list[tuple[Any, ...]],
        expected_calls: list[tuple[str, dict[str, Any]]],
    ) -> None:
        runs = [{**_run("failed", dt.timedelta(hours=1)), "status": "failed"}, _run("ok", dt.timedelta(hours=2))]
        workflows = {run["runId"]: [_single_attempt_workflow(run)] for run in runs}
        workflows["ok"][0]["jobs"].append({"jobId": "ok-skipped-job", "attempts": []})
        session = _fake_session(runs, workflows_by_run=workflows)

        rows = _synced_rows(session, None, endpoint)

        assert [tuple(row[column] for column in columns) for row in rows] == expected_rows
        assert all(row["run_created_at"] for row in rows)
        called_method = expected_calls[0][0]
        calls = [
            (call.args[0].rsplit("/", 1)[-1], call.kwargs["json"])
            for call in session.post.call_args_list
            if call.args[0].endswith(f"/{called_method}")
        ]
        assert calls == expected_calls


class TestDepotReconciliation:
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
            schema_name=JOB_ATTEMPTS,
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
        inputs = mock.MagicMock(
            should_use_incremental_field=False, history_start=None, source_cursor=manager, schema_name=JOB_ATTEMPTS
        )
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
        body: dict[str, Any] = {"runs": []} if status == 200 else {"code": "permission_denied", "message": "denied"}
        with scripted_network(always(ScriptedResponse(status=status, json=body))) as network:
            valid, message = validate_credentials(API_TOKEN, REPOSITORY)

        assert valid is expected_valid
        if expected_message_fragment is None:
            assert message is None
        else:
            assert message is not None and expected_message_fragment in message
        assert network.requests_log[0].json() == {"repo": REPOSITORY, "pageSize": 1}

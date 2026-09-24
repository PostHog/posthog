import json
import datetime as dt
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.depot.depot import (
    DEPOT_CI_SERVICE_URL,
    depot_source,
    validate_credentials,
)

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


def _single_attempt_metrics(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "run": {"runId": run["runId"], "createdAt": run["createdAt"]},
        "workflows": [
            {
                "workflow": {"workflowId": f"{run['runId']}-wf"},
                "jobs": [
                    {
                        "job": {"jobId": f"{run['runId']}-job"},
                        "attempts": [{"attempt": {"attemptId": f"{run['runId']}-attempt", "attempt": 1}}],
                    }
                ],
            }
        ],
    }


def _fake_session(
    terminal_pages: list[list[dict[str, Any]]],
    in_flight_runs: list[dict[str, Any]] | None = None,
    run_metrics: dict[str, dict[str, Any]] | None = None,
    run_statuses: dict[str, dict[str, Any]] | None = None,
) -> mock.MagicMock:
    metrics = run_metrics or {run["runId"]: _single_attempt_metrics(run) for page in terminal_pages for run in page}
    statuses = run_statuses or {}

    def post(url: str, json: dict[str, Any], timeout: float) -> Response:
        method = url.removeprefix(f"{DEPOT_CI_SERVICE_URL}/")
        if method == "ListRuns" and json["status"] == IN_FLIGHT:
            return _response(200, {"runs": in_flight_runs or []}, method)
        if method == "ListRuns":
            page_index = int(json.get("pageToken", "0"))
            next_page_token = str(page_index + 1) if page_index + 1 < len(terminal_pages) else ""
            return _response(200, {"runs": terminal_pages[page_index], "nextPageToken": next_page_token}, method)
        if method == "GetRunMetrics":
            return _response(200, metrics[json["runId"]], method)
        return _response(200, statuses.get(json["runId"], {}), method)

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
TERMINAL_PAGES = [
    [_run("r6", dt.timedelta(minutes=10)), _run("r5", dt.timedelta(hours=1))],
    [_run("r4", dt.timedelta(hours=2)), _run("r3", dt.timedelta(hours=3))],
    [_run("r2", dt.timedelta(hours=4)), _run("r1", dt.timedelta(hours=5))],
    [_run("r0", dt.timedelta(days=6))],
]
WATERMARK = NOW - dt.timedelta(hours=4)
RECENT_IN_FLIGHT = _run("in-flight", dt.timedelta(minutes=90))
STALE_QUEUED = _run("stale", dt.timedelta(days=30))


class TestDepotSource:
    @pytest.mark.parametrize(
        "in_flight_runs, expected_run_ids",
        [
            ([], ["r3", "r4", "r5", "r6"]),
            ([RECENT_IN_FLIGHT], ["r3", "r4"]),
            ([STALE_QUEUED], ["r3", "r4", "r5", "r6"]),
            ([STALE_QUEUED, RECENT_IN_FLIGHT], ["r3", "r4"]),
        ],
    )
    def test_syncs_only_runs_created_before_the_oldest_recent_in_flight_run(
        self, in_flight_runs: list[dict[str, Any]], expected_run_ids: list[str]
    ) -> None:
        session = _fake_session(TERMINAL_PAGES, in_flight_runs)

        rows = _synced_rows(session, WATERMARK)

        assert [row["run_id"] for row in rows] == expected_run_ids

    @pytest.mark.parametrize(
        "created_after, expected_run_ids, expected_terminal_pages",
        [
            (WATERMARK, ["r3", "r4", "r5", "r6"], 3),
            (_iso(WATERMARK), ["r3", "r4", "r5", "r6"], 3),
            (None, ["r0", "r1", "r2", "r3", "r4", "r5", "r6"], 4),
        ],
    )
    def test_walks_terminal_runs_down_to_the_lower_bound_and_yields_them_oldest_first(
        self, created_after: dt.datetime | str | None, expected_run_ids: list[str], expected_terminal_pages: int
    ) -> None:
        session = _fake_session(TERMINAL_PAGES)

        rows = _synced_rows(session, created_after)

        assert [row["run_id"] for row in rows] == expected_run_ids
        terminal_list_calls = [
            body for method, body in _requests(session) if method == "ListRuns" and body["status"] == TERMINAL
        ]
        assert len(terminal_list_calls) == expected_terminal_pages

    def test_request_shapes(self) -> None:
        session = _fake_session(TERMINAL_PAGES[:2])

        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session) as make_session:
            _batches(depot_source(API_TOKEN, REPOSITORY, None, mock.MagicMock()))

        assert make_session.call_args.kwargs["headers"] == {"Authorization": f"Bearer {API_TOKEN}"}
        assert API_TOKEN in make_session.call_args.kwargs["redact_values"]
        assert _requests(session)[:3] == [
            ("ListRuns", {"repo": REPOSITORY, "status": IN_FLIGHT, "pageSize": 200}),
            ("ListRuns", {"repo": REPOSITORY, "status": TERMINAL, "pageSize": 200}),
            ("ListRuns", {"repo": REPOSITORY, "status": TERMINAL, "pageSize": 200, "pageToken": "1"}),
        ]
        assert _requests(session)[3:5] == [("GetRunMetrics", {"runId": "r3"}), ("GetRunStatus", {"runId": "r3"})]

    def test_flattens_one_row_per_attempt_with_the_job_display_name(self) -> None:
        run = _run("run-1", dt.timedelta(hours=1))
        metrics = {
            "run": {
                "runId": "run-1",
                "repo": REPOSITORY,
                "ref": "refs/heads/main",
                "sha": "abc123",
                "headSha": "def456",
                "trigger": "push",
                "status": "failed",
                "createdAt": run["createdAt"],
                "startedAt": "2026-01-01T00:00:01.000Z",
                "finishedAt": "2026-01-01T00:10:00.000Z",
            },
            "workflows": [
                {
                    "workflow": {
                        "workflowId": "wf-1",
                        "workflowPath": ".depot/workflows/ci-backend.yml",
                        "name": "Backend CI",
                        "status": "failed",
                        "createdAt": "2026-01-01T00:00:00.500Z",
                        "startedAt": "2026-01-01T00:00:02.000Z",
                        "finishedAt": "2026-01-01T00:09:59.000Z",
                    },
                    "jobs": [
                        {
                            "job": {
                                "jobId": "job-matrix",
                                "jobKey": "ci-backend.yml:turbo-tests:matrix-38",
                                "status": "finished",
                                "conclusion": "success",
                                "currentAttempt": 2,
                                "createdAt": "2026-01-01T00:00:03.000Z",
                                "startedAt": "2026-01-01T00:00:04.000Z",
                                "finishedAt": "2026-01-01T00:08:00.000Z",
                            },
                            "attempts": [
                                {
                                    "attempt": {
                                        "attemptId": "attempt-1",
                                        "attempt": 1,
                                        "status": "finished",
                                        "conclusion": "failure",
                                        "sandboxId": "sandbox-1",
                                        "sessionId": "session-1",
                                        "createdAt": "2026-01-01T00:00:03.000Z",
                                        "startedAt": "2026-01-01T00:00:04.000Z",
                                        "finishedAt": "2026-01-01T00:04:00.000Z",
                                    },
                                    "stats": {},
                                },
                                {"attempt": {"attemptId": "attempt-2", "attempt": 2}},
                            ],
                        },
                        {"job": {"jobId": "job-placeholder", "jobKey": "ci-backend.yml:django:_dynamicMatrix"}},
                        {
                            "job": {"jobId": "job-lint", "jobKey": "ci-backend.yml:lint"},
                            "attempts": [{"attempt": {"attemptId": "attempt-3", "attempt": 1}}],
                        },
                    ],
                }
            ],
        }
        status = {
            "runId": "run-1",
            "workflows": [
                {
                    "workflowId": "wf-1",
                    "jobs": [
                        {"jobId": "job-lint", "jobKey": "ci-backend.yml:lint"},
                        {"jobId": "job-matrix", "jobDisplayName": "Product tests (shard 38)"},
                    ],
                }
            ],
        }
        session = _fake_session([[run]], run_metrics={"run-1": metrics}, run_statuses={"run-1": status})

        rows = _synced_rows(session, None)

        assert [(row["attempt_id"], row["job_display_name"]) for row in rows] == [
            ("attempt-1", "Product tests (shard 38)"),
            ("attempt-2", "Product tests (shard 38)"),
            ("attempt-3", None),
        ]
        assert rows[0] == {
            "run_id": "run-1",
            "repo": REPOSITORY,
            "ref": "refs/heads/main",
            "sha": "abc123",
            "head_sha": "def456",
            "trigger": "push",
            "run_status": "failed",
            "run_created_at": run["createdAt"],
            "run_started_at": "2026-01-01T00:00:01.000Z",
            "run_finished_at": "2026-01-01T00:10:00.000Z",
            "workflow_id": "wf-1",
            "workflow_name": "Backend CI",
            "workflow_path": ".depot/workflows/ci-backend.yml",
            "workflow_status": "failed",
            "workflow_created_at": "2026-01-01T00:00:00.500Z",
            "workflow_started_at": "2026-01-01T00:00:02.000Z",
            "workflow_finished_at": "2026-01-01T00:09:59.000Z",
            "job_id": "job-matrix",
            "job_key": "ci-backend.yml:turbo-tests:matrix-38",
            "job_display_name": "Product tests (shard 38)",
            "job_status": "finished",
            "job_conclusion": "success",
            "job_created_at": "2026-01-01T00:00:03.000Z",
            "job_started_at": "2026-01-01T00:00:04.000Z",
            "job_finished_at": "2026-01-01T00:08:00.000Z",
            "attempt_id": "attempt-1",
            "attempt": 1,
            "attempt_status": "finished",
            "attempt_conclusion": "failure",
            "attempt_created_at": "2026-01-01T00:00:03.000Z",
            "attempt_started_at": "2026-01-01T00:00:04.000Z",
            "attempt_finished_at": "2026-01-01T00:04:00.000Z",
            "sandbox_id": "sandbox-1",
        }


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

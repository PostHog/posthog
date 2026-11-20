import gzip
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Literal

import pytest
import time_machine

from products.warehouse_sources.sources.appcues._config import AppcuesSourceConfig
from products.warehouse_sources.sources.appcues.appcues import AppcuesExportError, AppcuesResumeConfig
from products.warehouse_sources.sources.appcues.source import AppcuesSource
from products.warehouse_sources.sources.sdk.testing import DriveResult, Script, ScriptedResponse, SourceDriver

CONFIG = AppcuesSourceConfig(api_key="test-key", api_secret="test-secret", account_id="12345", region="us")


@pytest.mark.parametrize(
    ("table", "path", "region"),
    [
        ("flows", "flows", "us"),
        ("flows_v2", "flows-v2", "eu"),
        ("segments", "segments", "eu"),
        ("tags", "tags", "us"),
        ("pins", "pins", "us"),
        ("mobile", "mobile", "eu"),
        ("launchpads", "launchpads", "us"),
        ("banners", "banners", "eu"),
        ("embeds", "embeds", "us"),
        ("nps", "nps", "eu"),
        ("checklists", "checklists", "us"),
    ],
)
def test_full_refresh_reads_complete_account_array(table: str, path: str, region: Literal["us", "eu"]) -> None:
    rows = [
        {"id": "experience-a", "steps": [{"id": "step-a", "children": []}], "tags": {"tag-a": True}},
        {"id": "experience-b", "steps": [], "tags": {}, "published_at": None},
    ]
    config = AppcuesSourceConfig(api_key="test-key", api_secret="test-secret", account_id="12345", region=region)
    result = SourceDriver(AppcuesSource(), config).run(table, [ScriptedResponse(json=rows)])

    assert result.raised is None
    assert result.rows == rows
    assert result.paths == [f"/v2/accounts/12345/{path}"]
    assert result.requests[0].origin == ("https://api.eu.appcues.com" if region == "eu" else "https://api.appcues.com")
    assert result.requests[0].headers["authorization"] == "Basic dGVzdC1rZXk6dGVzdC1zZWNyZXQ="
    assert result.queries == [{}]


@pytest.mark.parametrize(
    ("created_at", "expected"),
    [
        (1704164645123, datetime(2024, 1, 2, 3, 4, 5, 123000, tzinfo=UTC)),
        (1704164645123.5, datetime(2024, 1, 2, 3, 4, 5, 123500, tzinfo=UTC)),
        (0, datetime(1970, 1, 1, tzinfo=UTC)),
        ("2024-01-02T03:04:05Z", datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)),
        (
            "2024-01-02T03:04:05+02:00",
            datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone(timedelta(hours=2))),
        ),
        (None, None),
    ],
)
def test_creation_timestamp_supports_both_appcues_formats(created_at: Any, expected: datetime | None) -> None:
    config = AppcuesSourceConfig(api_key="test-key", api_secret="test-secret", account_id="12345", region="us")
    result = SourceDriver(AppcuesSource(), config).run(
        "pins", [ScriptedResponse(json=[{"id": "pin-a", "created_at": created_at}])]
    )

    assert result.raised is None
    assert result.rows == [{"id": "pin-a", "created_at": expected}]


@pytest.mark.parametrize("body", [[], {"error": True, "status": 200, "title": "Unexpected response"}])
def test_empty_array_is_valid_but_an_error_object_cannot_replace_a_table(body: Any) -> None:
    config = AppcuesSourceConfig(api_key="test-key", api_secret="test-secret", account_id="12345", region="us")
    result = SourceDriver(AppcuesSource(), config).run("flows", [ScriptedResponse(json=body)])

    assert result.rows == []
    if isinstance(body, list):
        assert result.raised is None
    else:
        assert isinstance(result.raised, ValueError)
        assert "Required a list response body" in str(result.raised)


def _job(job_id: str) -> ScriptedResponse:
    return ScriptedResponse(status=202, json={"job_id": job_id, "job_url": f"https://elsewhere.example.com/{job_id}"})


def _completed(url: str, *, top_level: bool = False) -> ScriptedResponse:
    if top_level:
        return ScriptedResponse(json={"status": "COMPLETED", "signed_s3_url": url, "events": []})
    events = [{"name": "Ingesting", "attributes": {}}, {"name": "Completed", "attributes": {"signed_s3_url": url}}]
    return ScriptedResponse(json={"status": "COMPLETED", "events": events})


def _file(rows: list[dict[str, Any]], encoding: str = "jsonl") -> ScriptedResponse:
    if encoding == "array":
        return ScriptedResponse(body=b"  \n" + json.dumps(rows).encode())
    body = "".join(json.dumps(row) + "\n" for row in rows).encode()
    return ScriptedResponse(body=gzip.compress(body) if encoding == "gzip" else body)


def _run(schema: str, script: Script, *, resume_state: Any = None, watermark: Any = None) -> DriveResult:
    with time_machine.travel(datetime(2026, 3, 3, 1, 0, tzinfo=UTC), tick=False):
        return SourceDriver(AppcuesSource(), CONFIG).run(
            schema,
            script,
            resume_state=resume_state,
            incremental_field="timestamp" if watermark is not None else None,
            db_incremental_field_last_value=watermark,
        )


@pytest.mark.parametrize(("encoding", "top_level"), [("jsonl", False), ("array", False), ("gzip", True)])
def test_event_export_walks_daily_windows_after_the_watermark(encoding: str, top_level: bool) -> None:
    result = _run(
        "events",
        [
            _job("job-1"),
            ScriptedResponse(json={"status": "IN_PROGRESS", "events": []}),
            _completed("https://files.example.com/job-1", top_level=top_level),
            _file(
                [
                    {"name": "appcues:flow_started", "timestamp": "2026-03-01T13:00:00Z", "user_id": "u1"},
                    # Outside the requested window, so the next window or the last sync owns it.
                    {"name": "appcues:flow_started", "timestamp": "2026-03-01T11:00:00Z", "user_id": "u2"},
                    {"name": "appcues:flow_completed", "timestamp": 1772449200000, "user_id": "u3"},
                ],
                encoding,
            ),
            _job("job-2"),
            _completed("https://files.example.com/job-2", top_level=top_level),
            _file([], encoding),
        ],
        watermark="2026-03-01T12:00:00Z",
    )

    assert result.raised is None
    assert result.rows == [
        {"name": "appcues:flow_started", "timestamp": datetime(2026, 3, 1, 13, tzinfo=UTC), "user_id": "u1"},
        {"name": "appcues:flow_completed", "timestamp": datetime(2026, 3, 2, 11, tzinfo=UTC), "user_id": "u3"},
    ]
    assert result.paths == [
        "/v2/accounts/12345/export/events",
        "/v2/accounts/12345/jobs/job-1",
        "/v2/accounts/12345/jobs/job-1",
        "/job-1",
        "/v2/accounts/12345/export/events",
        "/v2/accounts/12345/jobs/job-2",
        "/job-2",
    ]
    created = [request.json() for request in result.requests if request.method == "POST"]
    assert [(body["start_time"], body["end_time"]) for body in created] == [
        ("2026-03-01T12:00:00.001Z", "2026-03-02T12:00:00.001Z"),
        ("2026-03-02T12:00:00.001Z", "2026-03-03T00:00:00.000Z"),
    ]
    assert all(body["conditions"] == [] and body["email"] is None and body["format"] == "json" for body in created)
    download = result.requests[3]
    assert download.origin == "https://files.example.com"
    assert "authorization" not in download.headers
    assert result.response is not None and result.response.primary_keys is None


def test_event_export_without_a_watermark_starts_at_the_initial_lookback() -> None:
    result = _run(
        "events",
        lambda request: (
            _job("job")
            if request.method == "POST"
            else _completed("https://files.example.com/f")
            if "/jobs/" in request.path
            else _file([])
        ),
    )

    assert result.raised is None
    starts = [request.json()["start_time"] for request in result.requests if request.method == "POST"]
    assert len(starts) == 90
    assert starts[0] == "2025-12-03T00:00:00.000Z"


@pytest.mark.parametrize(
    ("status", "error"),
    [
        ({"status": "COMPLETED", "events": [{"name": "Completed", "attributes": {}}]}, "without a signed_s3_url"),
        ({"status": "COMPLETED", "signed_s3_url": "http://files.example.com/f"}, "not HTTPS"),
        ({"status": "FAILED", "events": []}, "failed"),
    ],
)
def test_event_export_job_without_a_usable_file_raises(status: dict[str, Any], error: str) -> None:
    result = _run("events", [_job("job-1"), ScriptedResponse(json=status)], watermark="2026-03-02T12:00:00Z")

    assert isinstance(result.raised, AppcuesExportError)
    assert error in str(result.raised)
    assert result.rows == []


def test_event_export_resume_reuses_the_saved_job_and_skips_written_rows() -> None:
    rows = [{"name": "e", "timestamp": f"2026-03-02T0{n}:00:00Z", "user_id": f"u{n}"} for n in range(3)]
    result = _run(
        "events",
        [_completed("https://files.example.com/saved"), _file(rows)],
        resume_state=AppcuesResumeConfig(
            job_id="saved", rows_done=2, window_start="2026-03-02T00:00:00.000Z", window_end="2026-03-03T00:00:00.000Z"
        ),
        watermark="2026-01-01T00:00:00Z",
    )

    assert result.raised is None
    assert [row["user_id"] for row in result.rows] == ["u2"]
    assert result.paths == ["/v2/accounts/12345/jobs/saved", "/saved"]
    assert result.committed_states[-1].rows_done == 3


def test_event_export_restarts_a_saved_job_that_failed() -> None:
    result = _run(
        "events",
        [
            ScriptedResponse(json={"status": "FAILED"}),
            _job("job-2"),
            _completed("https://files.example.com/job-2"),
            _file([{"name": "e", "timestamp": "2026-03-02T01:00:00Z", "user_id": "u1"}]),
        ],
        resume_state=AppcuesResumeConfig(
            job_id="expired",
            rows_done=4,
            window_start="2026-03-02T00:00:00.000Z",
            window_end="2026-03-03T00:00:00.000Z",
        ),
    )

    assert result.raised is None
    assert [row["user_id"] for row in result.rows] == ["u1"]
    assert result.requests[1].json()["start_time"] == "2026-03-02T00:00:00.000Z"
    assert result.committed_states[-1] == AppcuesResumeConfig(
        job_id="job-2", rows_done=1, window_start="2026-03-02T00:00:00.000Z", window_end="2026-03-03T00:00:00.000Z"
    )


def _segment_vendor(files: dict[str, list[dict[str, Any]]]) -> Callable[[Any], ScriptedResponse]:
    def respond(request: Any) -> ScriptedResponse:
        if request.path == "/v2/accounts/12345/segments":
            return ScriptedResponse(json=[{"id": segment_id} for segment_id in reversed(list(files))])
        if request.method == "POST":
            return _job("job-" + request.path.split("/")[-2])
        if "/jobs/" in request.path:
            return _completed("https://files.example.com/" + request.path.split("/")[-1])
        return _file(files[request.path.removeprefix("/job-")])

    return respond


def test_segment_membership_exports_each_segment_and_tags_its_rows() -> None:
    result = _run("segment_membership", _segment_vendor({"seg-a": [{"user_id": "u1"}], "seg-b": [{"user_id": "u1"}]}))

    assert result.raised is None
    assert result.rows == [{"user_id": "u1", "segment_id": "seg-a"}, {"user_id": "u1", "segment_id": "seg-b"}]
    assert [request.path for request in result.requests if request.method == "POST"] == [
        "/v2/accounts/12345/segments/seg-a/segment_membership_export",
        "/v2/accounts/12345/segments/seg-b/segment_membership_export",
    ]
    assert result.requests[1].json() == {"format": "json", "property_names": []}
    assert result.response is not None and result.response.primary_keys == ["segment_id", "user_id"]


def test_segment_membership_resume_skips_finished_segments() -> None:
    result = _run(
        "segment_membership",
        _segment_vendor({"seg-a": [{"user_id": "u1"}], "seg-b": [{"user_id": "u1"}, {"user_id": "u2"}]}),
        resume_state=AppcuesResumeConfig(segment_id="seg-b", job_id="job-seg-b", rows_done=1),
    )

    assert result.raised is None
    assert result.rows == [{"user_id": "u2", "segment_id": "seg-b"}]
    assert not any(request.method == "POST" for request in result.requests)


@pytest.mark.parametrize(
    ("answer", "rows"),
    [
        (
            ScriptedResponse(json={"account_id": "12345", "type": "deny", "event_rules": ["appcues:page_view"]}),
            [{"account_id": "12345", "type": "deny", "event_rules": ["appcues:page_view"]}],
        ),
        (ScriptedResponse(status=404, json={"error": True, "status": 404}), []),
    ],
)
def test_ingestion_filtering_rules_read_one_object_or_none(answer: ScriptedResponse, rows: list[Any]) -> None:
    result = _run("ingestion_filtering_rules", [answer])

    assert result.raised is None
    assert result.rows == rows
    assert result.paths == ["/v2/accounts/12345/ingestion_filtering_rules"]

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.logrocket import (
    LogrocketSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.logrocket.logrocket import LogrocketResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.logrocket.source import LogrocketSource


def driver() -> SourceDriver:
    return SourceDriver(
        LogrocketSource(),
        LogrocketSourceConfig(
            api_key="fake-logrocket-key", organization_id="example-org", project_id="example-project"
        ),
    )


def manifest(cursor: str | int | None, *urls: str) -> ScriptedResponse:
    return ScriptedResponse(json={"cursor": cursor, "sessions": [{"url": url} for url in urls]})


def jsonl(*rows: dict[str, Any]) -> bytes:
    return b"\n".join(json.dumps(row).encode() for row in rows)


@pytest.mark.parametrize("first_page_empty", [False, True])
def test_audit_pagination_obeys_has_next_and_commits_before_handoff(first_page_empty: bool) -> None:
    row = {
        "created_date": "2025-01-02T03:04:05.123456Z",
        "user": "reader@example.com",
        "action": "Viewed session",
        "description": "fake-session",
    }
    result = driver().run(
        "audit_logs",
        [
            ScriptedResponse(
                json={"has_next": True, "cursor": "opaque:next", "logs": [] if first_page_empty else [row, row]}
            ),
            ScriptedResponse(json={"has_next": False, "cursor": "opaque:next", "logs": [row]}),
        ],
        db_incremental_field_last_value=datetime(2030, 1, 1, tzinfo=UTC),
    )

    assert result.raised is None
    assert result.params("cursor") == ["0", "opaque:next"]
    assert result.paths == ["/v1/orgs/example-org/apps/example-project/audit/logs/"] * 2
    assert result.params("date") == [None, None]
    assert len(result.rows) == (1 if first_page_empty else 3)
    assert result.rows[-1]["created_date"] == datetime(2025, 1, 2, 3, 4, 5, 123456, tzinfo=UTC)
    assert result.committed_states == [
        LogrocketResumeConfig(cursor="opaque:next"),
        LogrocketResumeConfig(finished=True),
    ]


def test_audit_resume_uses_opaque_cursor() -> None:
    result = driver().run(
        "audit_logs",
        [ScriptedResponse(json={"has_next": False, "cursor": 9000, "logs": [{"action": "Viewed session"}]})],
        resume_state=LogrocketResumeConfig(cursor="9000:tie-break"),
    )
    assert result.raised is None
    assert result.params("cursor") == ["9000:tie-break"]
    assert result.committed_states == [LogrocketResumeConfig(finished=True)]


def test_session_events_download_jsonl_and_keep_keys_unique_across_files() -> None:
    event = {"type": "lr.Identify", "seqID": 1, "tabID": "tab-a", "time": 1735689600000, "data": {"plan": "test"}}
    result = driver().run(
        "session_events",
        [
            manifest(1234, "https://storage.example.com/session-a.jsonl?signature=fake-a"),
            ScriptedResponse(body=b"\n" + jsonl(event, event)),
            manifest("opaque:next", "https://storage.example.com/session-b.jsonl?signature=fake-b"),
            ScriptedResponse(body=jsonl({"type": "lr.Metadata", "data": None})),
            manifest("opaque:next"),
        ],
    )
    assert result.raised is None
    assert result.params("cursor") == [None, None, "1234", None, "opaque:next"]
    assert result.paths == [
        "/v1/orgs/example-org/apps/example-project/data-export/",
        "/session-a.jsonl",
        "/v1/orgs/example-org/apps/example-project/data-export/",
        "/session-b.jsonl",
        "/v1/orgs/example-org/apps/example-project/data-export/",
    ]
    assert [row["export_line"] for row in result.rows] == [2, 3, 1]
    assert len({(row["export_file_id"], row["export_line"]) for row in result.rows}) == 3
    assert result.rows[0]["event_time"] == datetime(2025, 1, 1, tzinfo=UTC)
    assert result.rows[0]["data"] == {"plan": "test"}
    assert result.rows[-1]["event_time"] is None
    assert result.rows[-1]["data"] is None
    assert result.requests[0].headers["authorization"] == "token fake-logrocket-key"
    assert "authorization" not in result.requests[1].headers
    assert "authorization" not in result.requests[3].headers
    assert result.committed_states[-1] == LogrocketResumeConfig(finished=True)
    assert all("signature" not in repr(state) for state in result.saved_states)


@pytest.mark.parametrize("bad_line", [b"{broken-json-secret", b'["not-an-event"]'])
def test_session_resume_refreshes_signed_urls_and_skips_durable_lines(bad_line: bytes) -> None:
    first = {"type": "lr.Metadata", "time": 1735689600000, "data": {"device": "test"}}
    second = {"type": "lr.Identify", "time": 1735689601000, "data": {"plan": "test"}}
    interrupted = driver().run(
        "session_events",
        [
            manifest(
                "next",
                "https://storage.example.com/empty.jsonl",
                "https://storage.example.com/session.jsonl?signature=old-fake",
            ),
            ScriptedResponse(body=b"\n"),
            ScriptedResponse(body=jsonl(first) + b"\n" + bad_line),
        ],
        resume_state=LogrocketResumeConfig(cursor="page:two"),
    )
    assert isinstance(interrupted.raised, ValueError)
    assert "line 2" in str(interrupted.raised)
    assert "broken-json-secret" not in str(interrupted.raised)
    assert len(interrupted.rows) == 1
    checkpoint = interrupted.committed_states[-1]
    assert checkpoint.file_id == interrupted.rows[0]["export_file_id"]
    assert checkpoint.line_number == 1
    assert checkpoint.cursor == "page:two"
    assert len(checkpoint.completed_file_ids) == 1

    resumed = driver().run(
        "session_events",
        [
            manifest(
                "next",
                "https://storage.example.com/empty.jsonl",
                "https://storage.example.com/session.jsonl?signature=new-fake",
            ),
            ScriptedResponse(body=jsonl(first, second)),
            manifest("next"),
        ],
        resume_state=checkpoint,
    )
    assert resumed.raised is None
    assert resumed.paths[1:] == ["/session.jsonl", "/v1/orgs/example-org/apps/example-project/data-export/"]
    assert resumed.params("cursor") == ["page:two", None, "next"]
    assert len(resumed.rows) == 1
    assert resumed.rows[0]["type"] == "lr.Identify"
    assert resumed.rows[0]["export_file_id"] == interrupted.rows[0]["export_file_id"]
    assert resumed.rows[0]["export_line"] == 2

    finished = driver().run("session_events", [], resume_state=resumed.committed_states[-1])
    assert finished.raised is None
    assert finished.rows == []
    assert finished.requests == []


@pytest.mark.parametrize(
    ("schema_name", "pages", "error_text"),
    [
        ("audit_logs", [{"logs": [], "cursor": "next"}], "pagination flag"),
        ("audit_logs", [{"logs": [], "has_next": True}], "pagination cursor"),
        ("session_events", [{"sessions": [{"url": "https://storage.example.com/a"}]}], "pagination cursor"),
        (
            "audit_logs",
            [{"logs": [], "has_next": True, "cursor": 123}, {"logs": [], "has_next": True, "cursor": 123}],
            "not advancing",
        ),
    ],
)
def test_invalid_pagination_fails_instead_of_truncating(
    schema_name: str, pages: list[dict[str, Any]], error_text: str
) -> None:
    result = driver().run(schema_name, [ScriptedResponse(json=page) for page in pages])
    assert isinstance(result.raised, ValueError)
    assert error_text in str(result.raised)


@pytest.mark.parametrize("status", [302, 403])
def test_export_download_failure_does_not_commit_unread_file_or_expose_signature(status: int) -> None:
    result = driver().run(
        "session_events",
        [
            manifest("next", "https://storage.example.com/session.jsonl?signature=fake-secret"),
            ScriptedResponse(status=status, headers={"Location": "https://other.example.com/file"}),
        ],
    )
    assert isinstance(result.raised, RuntimeError)
    assert "Retry the sync" in str(result.raised)
    assert "fake-secret" not in str(result.raised)
    assert result.rows == []
    assert result.committed_states == []
    assert len(result.requests) == 2


@pytest.mark.parametrize("url", ["http://storage.example.com/file", "https://user:secret@storage.example.com/file"])
def test_export_refuses_unsafe_download_url(url: str) -> None:
    result = driver().run("session_events", [manifest("next", url)])
    assert isinstance(result.raised, ValueError)
    assert len(result.requests) == 1
    assert result.committed_states == []


def test_resume_fails_when_partial_file_disappears() -> None:
    result = driver().run(
        "session_events",
        [manifest("next", "https://storage.example.com/different.jsonl")],
        resume_state=LogrocketResumeConfig(cursor="page:two", file_id="missing-file", line_number=5),
    )
    assert isinstance(result.raised, RuntimeError)
    assert "no longer available" in str(result.raised)
    assert len(result.requests) == 1

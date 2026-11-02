from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.telli import TelliSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.telli.source import TelliSource
from products.warehouse_sources.backend.temporal.data_imports.sources.telli.telli import TelliResumeConfig


def _driver() -> SourceDriver:
    return SourceDriver(TelliSource(), TelliSourceConfig(api_key="test-telli-key"))


@pytest.mark.parametrize(
    "endpoint,path,selector,primary_key,partition_key",
    [
        ("calls", "/v1/list-calls", "calls", "call_id", "triggered_at_iso"),
        ("contacts", "/v2/contacts", "data", "id", "createdAt"),
        ("agents", "/v2/agents", "data", "id", "createdAt"),
    ],
)
@pytest.mark.parametrize("resume_cursor", [None, "saved+/=cursor"])
def test_cursor_pages_and_resume(
    endpoint: str, path: str, selector: str, primary_key: str, partition_key: str, resume_cursor: str | None
) -> None:
    rows: list[dict[str, Any]] = [
        {primary_key: "record-1", partition_key: "2026-01-02T00:00:00Z", "properties": [{"key": "tier", "value": 2}]},
        {primary_key: "record-2", partition_key: "2025-12-01T00:00:00Z", "transcript": "Synthetic test conversation."},
    ]
    first_params = {"limit": "100", **({"cursor": resume_cursor} if resume_cursor else {})}
    script = []
    for row, cursor in [(rows[0], "next+/=cursor"), (rows[1], None)]:
        pagination = (
            {"next_cursor": cursor}
            if endpoint == "calls"
            else {"pageInfo": {"nextCursor": cursor, "hasNextPage": cursor is not None}}
        )
        script.append(ScriptedResponse(json={selector: [row], **pagination}))

    result = _driver().run(
        endpoint,
        script,
        resume_state=TelliResumeConfig(cursor=resume_cursor) if resume_cursor else None,
    )

    assert result.items == [[rows[0]], [rows[1]]]
    assert result.saved_states == [TelliResumeConfig(cursor="next+/=cursor"), TelliResumeConfig(completed=True)]
    assert [request.path for request in result.requests] == [path, path]
    assert [{name: values[0] for name, values in request.query.items()} for request in result.requests] == [
        first_params,
        {"limit": "100", "cursor": "next+/=cursor"},
    ]
    assert all(request.headers["authorization"] == "Bearer test-telli-key" for request in result.requests)
    assert result.response is not None
    assert result.response.primary_keys == [primary_key]
    assert all(row[primary_key] for row in rows)
    assert result.response.partition_keys == [partition_key]


@pytest.mark.parametrize("body", [{"calls": [], "next_cursor": None}, {"unexpected": []}])
def test_empty_calls_and_missing_envelope(body: dict[str, Any]) -> None:
    result = _driver().run("calls", [ScriptedResponse(json=body)])
    if "calls" in body:
        assert result.rows == []
        assert result.raised is None
        assert result.saved_states == [TelliResumeConfig(completed=True)]
    else:
        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)
        assert result.saved_states == []


def test_completed_resume_does_not_restart_listing() -> None:
    result = _driver().run("calls", [], resume_state=TelliResumeConfig(completed=True))
    assert result.rows == []
    assert result.raised is None
    assert not result.requests


@pytest.mark.parametrize(
    "endpoint,body",
    [
        ("calls", {"calls": [{"call_id": "call-1"}], "next_cursor": "stuck"}),
        ("contacts", {"data": [{"id": "contact-1"}], "pageInfo": {"nextCursor": "stuck"}}),
    ],
)
def test_repeated_cursor_raises_without_clearing_checkpoint(endpoint: str, body: dict[str, Any]) -> None:
    result = _driver().run(endpoint, always(ScriptedResponse(json=body)))

    assert isinstance(result.raised, ValueError)
    assert "not advancing" in str(result.raised)
    assert result.saved_states == [TelliResumeConfig(cursor="stuck")]

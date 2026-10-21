from datetime import UTC, datetime
from typing import Any

import pytest

from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.scrunch import (
    ScrunchSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.scrunch import scrunch
from products.warehouse_sources.backend.temporal.data_imports.sources.scrunch.scrunch import ScrunchResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.scrunch.settings import PERMISSION_ERROR
from products.warehouse_sources.backend.temporal.data_imports.sources.scrunch.source import ScrunchSource


@pytest.fixture(autouse=True)
def small_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scrunch, "PAGE_SIZE", 2)


def page(rows: list[dict[str, Any]], total: int, status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json={"items": rows, "total": total})


def run(schema_name: str, script: Any, **inputs: Any) -> DriveResult:
    result = SourceDriver(ScrunchSource(), ScrunchSourceConfig(api_key="test-key")).run(schema_name, script, **inputs)
    assert all(options["redact_values"] == ("test-key",) for options in result.session_options)
    return result


def query(result: DriveResult, index: int) -> dict[str, list[str]]:
    return {name: list(values) for name, values in result.queries[index].items()}


@pytest.mark.parametrize("terminal", [[], [{"id": 3}], [{"id": 3}, {"id": 4}]])
def test_brand_pagination(terminal: list[dict[str, Any]]) -> None:
    total = 2 + len(terminal) if terminal else 5
    result = run("brands", [page([{"id": 1}, {"id": 2}], total), page(terminal, total)])
    assert result.raised is None
    assert result.items[0] == [{"id": 1}, {"id": 2}]
    assert result.saved_states[0].paginator_state == {"offset": 2}
    assert [row for batch in result.items[1:] for row in batch] == terminal
    assert result.saved_states[-1].complete is True
    assert len(result.requests) == 2
    assert [query(result, index) for index in range(2)] == [
        {"offset": ["0"], "limit": ["2"]},
        {"offset": ["2"], "limit": ["2"]},
    ]
    for request in result.requests:
        assert request.headers["authorization"] == "Bearer test-key"
        assert request.path == "/v1/brands"


@pytest.mark.parametrize(
    "table,path",
    [
        ("prompts", "/v1/11/prompts"),
        ("competitors", "/v1/brands/11/competitors"),
        ("personas", "/v1/brands/11/personas"),
        ("responses", "/v1/11/responses"),
    ],
)
def test_children_keep_brand_identity_and_reset_offsets(table: str, path: str) -> None:
    result = run(
        table,
        [
            page([{"id": 11}, {"id": 22}], 2),
            page([{"id": 1}, {"id": 2}], 3),
            page([{"id": 3}], 3),
            page([{"id": 1}], 1),
        ],
    )
    assert result.rows == [
        {"id": 1, "brand_id": 11},
        {"id": 2, "brand_id": 11},
        {"id": 3, "brand_id": 11},
        {"id": 1, "brand_id": 22},
    ]
    assert result.response is not None
    assert result.response.primary_keys == ["brand_id", "id"]
    assert result.params("offset") == ["0", "0", "2", "0"]
    assert result.paths[1] == path
    assert result.paths[3] == path.replace("11", "22")
    for index in range(1, 4):
        assert "brand_id" not in query(result, index)
        if table == "prompts":
            assert query(result, index)["status"] == ["all"]
        if table != "responses":
            assert "start_date" not in query(result, index)
            assert "end_date" not in query(result, index)


def test_child_requests_reject_off_host_brand_ids() -> None:
    result = run("prompts", [page([{"id": "https://attacker.example/collect"}], 1)])

    assert isinstance(result.raised, ValueError)
    assert "disallowed host" in str(result.raised)
    assert len(result.requests) == 1


@pytest.mark.parametrize(
    "incremental,watermark,expected_start",
    [
        (False, "2026-08-01T10:00:00Z", None),
        (True, None, None),
        (True, "2026-08-01T10:00:00Z", "2026-08-01"),
        (True, datetime(2026, 8, 1, 10, tzinfo=UTC), "2026-08-01"),
        (True, "2026-08-01T23:30:00-05:00", "2026-08-02"),
    ],
)
def test_response_date_filters(incremental: bool, watermark: str | datetime | None, expected_start: str | None) -> None:
    inputs: dict[str, Any] = {"db_incremental_field_last_value": watermark}
    if incremental:
        inputs["incremental_field"] = "created_at"
    today = datetime.now(UTC).date().isoformat()

    result = run(
        "responses",
        [
            page([{"id": 11}], 1),
            page([{"id": 1}, {"id": 2}], 3),
            page([{"id": 3}], 3),
        ],
        **inputs,
    )

    assert result.response is not None
    assert result.response.sort_mode == "desc"
    assert result.response.partition_keys == ["created_at"]
    for index in (1, 2):
        assert query(result, index)["end_date"] == [today]
        assert query(result, index).get("start_date") == ([expected_start] if expected_start else None)
    assert "start_date" not in query(result, 0)


@pytest.mark.parametrize("terminal", [False, True])
def test_child_resume_keeps_window_and_skips_completed_brands(terminal: bool) -> None:
    result = run(
        "responses",
        [page([{"id": 11}, {"id": 22}], 2), page([{"id": 9}], 3 if not terminal else 1)],
        resume_state=ScrunchResumeConfig(
            paginator_state={
                "completed": ["11/responses"],
                "current": None if terminal else "22/responses",
                "child_state": None if terminal else {"offset": 2},
            },
            start_date="2026-08-01",
            end_date="2026-08-03",
        ),
    )
    assert result.items == [[{"id": 9, "brand_id": 22}]]
    assert result.saved_states[-1].paginator_state == {
        "completed": ["11/responses", "22/responses"],
        "current": None,
        "child_state": None,
    }
    assert len(result.requests) == 2
    assert query(result, 1) == {
        "offset": ["0" if terminal else "2"],
        "limit": ["2"],
        "start_date": ["2026-08-01"],
        "end_date": ["2026-08-03"],
    }
    assert result.paths[1] == "/v1/22/responses"


@pytest.mark.parametrize("complete", [False, True])
def test_brand_resume(complete: bool) -> None:
    result = run(
        "brands",
        [page([{"id": 3}], 3)],
        resume_state=ScrunchResumeConfig(
            paginator_state=None if complete else {"offset": 2},
            start_date=None,
            end_date=None,
            complete=complete,
        ),
    )
    assert result.rows == ([] if complete else [{"id": 3}])
    assert len(result.requests) == (0 if complete else 1)
    if not complete:
        assert query(result, 0)["offset"] == ["2"]


def test_a_brand_run_with_no_saved_state_starts_from_the_first_page() -> None:
    result = run("brands", [page([{"id": 3}], 1)])

    assert query(result, 0)["offset"] == ["0"]


@pytest.mark.parametrize("has_brands", [False, True])
def test_empty_children_do_not_stop_parent_pagination(has_brands: bool) -> None:
    result = run(
        "personas",
        (
            [
                page([{"id": 11}, {"id": 22}], 3),
                page([], 0),
                page([], 0),
                page([{"id": 33}], 3),
                page([{"id": 1}], 1),
            ]
            if has_brands
            else [page([], 0)]
        ),
    )
    assert result.rows == ([{"id": 1, "brand_id": 33}] if has_brands else [])
    assert len(result.requests) == (5 if has_brands else 1)
    if has_brands:
        assert query(result, 3)["offset"] == ["2"]
        assert result.saved_states[-1].paginator_state["completed"] == [
            "brands/11/personas",
            "brands/22/personas",
            "brands/33/personas",
        ]
        # The safe point fires after each empty brand, so progress persists without any row.
        assert [state.paginator_state["completed"] for state in result.committed_states] == [
            ["brands/11/personas"],
            ["brands/11/personas", "brands/22/personas"],
            ["brands/11/personas", "brands/22/personas", "brands/33/personas"],
        ]


@pytest.mark.parametrize("status,message", [(402, PERMISSION_ERROR)])
def test_credentials_and_error_mapping(status: int, message: str | None) -> None:
    source = ScrunchSource()
    with scripted_network([page([], 0, status=status)]) as network:
        assert source.validate_credentials(ScrunchSourceConfig(api_key="test-key"), 1) == (status == 200, message)
    assert len(network.requests_log) == 1
    assert dict(network.requests_log[0].query) == {"limit": ("1",)}
    assert network.requests_log[0].headers["authorization"] == "Bearer test-key"
    if status != 200:
        result = run("brands", [page([], 0, status=status)])
        assert isinstance(result.raised, HTTPError)
        assert any(
            pattern in str(result.raised) and value == message
            for pattern, value in source.get_non_retryable_errors().items()
        )


def test_unexpected_validation_failure_propagates() -> None:
    with scripted_network([page([], 0, status=404)]), pytest.raises(HTTPError):
        ScrunchSource().validate_credentials(ScrunchSourceConfig(api_key="test-key"), 1)


def test_invalid_watermark_fails_before_requests() -> None:
    result = run("responses", [], incremental_field="created_at", db_incremental_field_last_value="not-a-date")

    assert isinstance(result.raised, ValueError)
    assert "watermark" in str(result.raised)
    assert result.requests == []

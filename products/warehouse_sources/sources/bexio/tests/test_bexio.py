from datetime import UTC, date, datetime
from typing import Any

import pytest

from products.warehouse_sources.sources.bexio._config import BexioSourceConfig
from products.warehouse_sources.sources.bexio.bexio import BexioResumeConfig, format_bexio_datetime
from products.warehouse_sources.sources.bexio.source import BexioSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver


def _driver() -> SourceDriver:
    return SourceDriver(BexioSource(), BexioSourceConfig(api_token="pat-secret"))


def _rows(start: int, count: int) -> list[dict[str, Any]]:
    return [{"id": i, "updated_at": "2026-01-01 10:00:00"} for i in range(start, start + count)]


def _bills_page(page: int, page_count: int, ids: list[str]) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "data": [{"id": bill_id, "created_at": "2026-01-01T10:00:00+00:00"} for bill_id in ids],
            "paging": {"page": page, "page_size": 500, "page_count": page_count, "item_count": len(ids)},
        }
    )


def test_offset_walk_stops_on_short_page_and_stages_each_next_offset() -> None:
    result = _driver().run(
        "invoices",
        [
            ScriptedResponse(json=_rows(0, 2000)),
            ScriptedResponse(json=_rows(2000, 2000)),
            ScriptedResponse(json=_rows(4000, 3)),
        ],
    )

    assert result.raised is None
    assert result.paths == ["/2.0/kb_invoice"] * 3
    assert result.params("offset") == ["0", "2000", "4000"]
    assert result.params("limit") == ["2000", "2000", "2000"]
    assert result.params("order_by") == ["id", "id", "id"]
    assert result.requests[0].headers["authorization"] == "Bearer pat-secret"
    assert len(result.rows) == 4003
    assert result.committed_states == [BexioResumeConfig(offset=2000), BexioResumeConfig(offset=4000)]


def test_page_walk_reads_the_data_envelope_and_stops_at_page_count() -> None:
    result = _driver().run(
        "bills",
        [_bills_page(1, 2, ["a", "b"]), _bills_page(2, 2, ["c"])],
    )

    assert result.raised is None
    assert result.paths == ["/4.0/purchase/bills", "/4.0/purchase/bills"]
    assert result.params("page") == ["1", "2"]
    assert result.params("limit") == ["500", "500"]
    assert [row["id"] for row in result.rows] == ["a", "b", "c"]
    assert result.committed_states == [BexioResumeConfig(page=2)]
    assert result.response is not None
    assert result.response.partition_keys == ["created_at"]


@pytest.mark.parametrize(
    ("inputs", "method", "path", "order_by", "body", "sort_mode"),
    [
        pytest.param({}, "GET", "/2.0/contact", "id", None, None, id="full_refresh"),
        pytest.param(
            {"incremental_field": "updated_at", "should_use_incremental_field": False},
            "GET",
            "/2.0/contact",
            "id",
            None,
            None,
            id="full_refresh_on_incremental_schema",
        ),
        pytest.param(
            {"incremental_field": "updated_at"},
            "GET",
            "/2.0/contact",
            "updated_at,id",
            None,
            "asc",
            id="first_incremental_run",
        ),
        pytest.param(
            {
                "incremental_field": "updated_at",
                "db_incremental_field_last_value": datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC),
            },
            "POST",
            "/2.0/contact/search",
            "updated_at,id",
            [{"field": "updated_at", "value": "2026-03-04 05:06:07", "criteria": ">="}],
            "asc",
            id="incremental_with_watermark",
        ),
    ],
)
def test_request_shaping(
    inputs: dict[str, Any], method: str, path: str, order_by: str, body: Any, sort_mode: str | None
) -> None:
    result = _driver().run("contacts", [ScriptedResponse(json=_rows(0, 1))], **inputs)

    assert result.raised is None
    request = result.requests[0]
    assert (request.method, request.path) == (method, path)
    assert request.param("order_by") == order_by
    assert (request.json() if request.body else None) == body
    assert result.response is not None
    assert result.response.sort_mode == sort_mode


def test_page_walk_resumes_from_the_saved_page() -> None:
    result = _driver().run("expenses", [_bills_page(3, 3, ["z"])], resume_state=BexioResumeConfig(page=3))

    assert result.raised is None
    assert result.params("page") == ["3"]


@pytest.mark.parametrize(
    ("resume_state", "expected_offsets"),
    [(None, ["0", "2000"]), (BexioResumeConfig(offset=2000), ["2000", "4000"])],
)
def test_search_walk_sends_the_criteria_on_every_page(
    resume_state: BexioResumeConfig | None, expected_offsets: list[str]
) -> None:
    result = _driver().run(
        "orders",
        [ScriptedResponse(json=_rows(0, 2000)), ScriptedResponse(json=_rows(2000, 5))],
        resume_state=resume_state,
        incremental_field="updated_at",
        db_incremental_field_last_value="2026-03-04 05:06:07",
    )

    assert result.raised is None
    assert result.paths == ["/2.0/kb_order/search"] * 2
    assert result.params("offset") == expected_offsets
    assert [request.json() for request in result.requests] == [
        [{"field": "updated_at", "value": "2026-03-04 05:06:07", "criteria": ">="}]
    ] * 2


def test_unauthorized_response_fails_the_sync() -> None:
    result = _driver().run(
        "users",
        [ScriptedResponse(status=401, json={"message": "Unauthorized", "request_id": "0123456789abcdef"})],
    )

    assert result.raised is not None
    assert "401 Client Error: Unauthorized for url" in str(result.raised)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (datetime(2026, 3, 4, 5, 6, 7, 891000, tzinfo=UTC), "2026-03-04 05:06:07"),
        (datetime(2026, 3, 4, 5, 6, 7), "2026-03-04 05:06:07"),
        (date(2026, 3, 4), "2026-03-04 00:00:00"),
        ("2026-03-04T05:06:07Z", "2026-03-04 05:06:07"),
        ("2026-03-04 05:06:07", "2026-03-04 05:06:07"),
        ("not a date", "not a date"),
    ],
)
def test_format_bexio_datetime(value: Any, expected: str) -> None:
    assert format_bexio_datetime(value) == expected

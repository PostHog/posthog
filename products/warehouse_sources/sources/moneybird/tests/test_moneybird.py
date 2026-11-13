from datetime import UTC, datetime
from typing import Any

import pytest

from products.warehouse_sources.sources.moneybird._config import MoneybirdSourceConfig
from products.warehouse_sources.sources.moneybird.moneybird import MoneybirdResumeConfig
from products.warehouse_sources.sources.moneybird.source import MoneybirdSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver

ADMINISTRATION_ID = "123456789"
BASE_PATH = f"/api/v2/{ADMINISTRATION_ID}"
NEXT_LINK = f'<https://moneybird.com{BASE_PATH}/sales_invoices.json?page=2>; rel="next"'
PREV_LINK = f'<https://moneybird.com{BASE_PATH}/sales_invoices.json?page=1>; rel="prev"'


def _driver() -> SourceDriver:
    return SourceDriver(
        MoneybirdSource(),
        MoneybirdSourceConfig(api_token="test-token", administration_id=ADMINISTRATION_ID),
    )


def _rows(prefix: str, count: int) -> list[dict[str, Any]]:
    return [{"id": f"{prefix}{index}", "created_at": "2026-01-01T00:00:00.000Z"} for index in range(count)]


@pytest.mark.parametrize(
    ("first_page_headers", "expected_pages"),
    [
        # A full page with a `next` link continues, and the short page ends the walk.
        ({"Link": NEXT_LINK}, ["1", "2"]),
        # A full page whose `Link` header has no `next` link is the last page.
        ({"Link": PREV_LINK}, ["1"]),
    ],
)
def test_paged_walk_stops_on_the_last_page(first_page_headers: dict[str, str], expected_pages: list[str]) -> None:
    script = [ScriptedResponse(json=_rows("a", 100), headers=first_page_headers)]
    if len(expected_pages) == 2:
        script.append(ScriptedResponse(json=_rows("b", 3), headers={"Link": PREV_LINK}))

    result = _driver().run("sales_invoices", script, should_use_incremental_field=False)

    assert result.raised is None
    assert result.paths == [f"{BASE_PATH}/sales_invoices.json"] * len(expected_pages)
    assert result.params("page") == expected_pages
    assert result.params("per_page") == ["100"] * len(expected_pages)
    assert len(result.rows) == 100 + 3 * (len(expected_pages) - 1)
    assert result.requests[0].headers["authorization"] == "Bearer test-token"


@pytest.mark.parametrize(
    ("schema", "incremental", "watermark", "expected_filter"),
    [
        # Without a filter Moneybird returns only this year's records, so a full refresh sends one.
        ("sales_invoices", False, None, "state:all"),
        ("sales_invoices", True, None, "state:all"),
        (
            "sales_invoices",
            True,
            datetime(2026, 3, 4, 10, 0, 0, tzinfo=UTC),
            "state:all,updated_after:2026-03-04T09:59:59Z",
        ),
        # A watermark with an offset is sent in UTC.
        ("purchase_invoices", True, "2026-03-04T10:00:00+02:00", "state:all,updated_after:2026-03-04T07:59:59Z"),
        ("contacts", True, datetime(2026, 3, 4, 10, 0, 0, tzinfo=UTC), "updated_after:2026-03-04T09:59:59Z"),
        ("contacts", False, None, None),
        ("time_entries", False, None, "state:all,include_nil_contacts:true,include_active:true"),
    ],
)
def test_filter_param(schema: str, incremental: bool, watermark: Any, expected_filter: str | None) -> None:
    inputs: dict[str, Any] = {"should_use_incremental_field": incremental}
    if incremental:
        inputs["incremental_field"] = "updated_at"
        inputs["db_incremental_field_last_value"] = watermark

    result = _driver().run(schema, [ScriptedResponse(json=_rows("a", 1))], **inputs)

    assert result.raised is None
    assert result.params("filter") == [expected_filter]


def test_contacts_include_archived_contacts() -> None:
    result = _driver().run("contacts", [ScriptedResponse(json=_rows("a", 1))], should_use_incremental_field=False)

    assert result.paths == [f"{BASE_PATH}/contacts/filter.json"]
    assert result.params("include_archived") == ["true"]


def test_paged_walk_saves_the_next_page_and_resumes_from_it() -> None:
    first = _driver().run(
        "sales_invoices",
        [ScriptedResponse(json=_rows("a", 100)), ScriptedResponse(json=_rows("b", 1))],
        should_use_incremental_field=False,
    )
    assert first.committed_states[0] == MoneybirdResumeConfig(page=2)

    resumed = _driver().run(
        "sales_invoices",
        [ScriptedResponse(json=_rows("c", 1))],
        should_use_incremental_field=False,
        resume_state=MoneybirdResumeConfig(page=7),
    )
    assert resumed.params("page") == ["7"]


def test_unpaginated_endpoint_reads_one_request() -> None:
    result = _driver().run(
        "ledger_accounts", [ScriptedResponse(json=_rows("a", 150))], should_use_incremental_field=False
    )

    assert result.raised is None
    assert result.paths == [f"{BASE_PATH}/ledger_accounts.json"]
    assert result.params("page") == [None]
    assert len(result.rows) == 150


def _sync_versions(entries: list[tuple[int, int]]) -> ScriptedResponse:
    return ScriptedResponse(json=[{"id": str(record_id), "version": version} for record_id, version in entries])


def _records_for(request: Any) -> ScriptedResponse:
    return ScriptedResponse(json=[{"id": record_id, "version": 1} for record_id in request.json()["ids"]])


SYNC_PATH = f"{BASE_PATH}/recurring_sales_invoices/synchronization.json"


def _recurring_script(listings: list[ScriptedResponse]) -> Any:
    pending = list(listings)

    def respond(request: Any) -> ScriptedResponse:
        assert request.path == SYNC_PATH
        if request.method == "GET":
            return pending.pop(0)
        return _records_for(request)

    return respond


def test_synchronization_joins_every_filter_and_fetches_ids_in_batches() -> None:
    active = [(record_id, 1) for record_id in range(1000, 1150)]
    inactive = [(5, 1), (2000, 1)]

    result = _driver().run(
        "recurring_sales_invoices",
        _recurring_script([_sync_versions(active), _sync_versions(inactive)]),
        should_use_incremental_field=False,
    )

    assert result.raised is None
    get_requests = [request for request in result.requests if request.method == "GET"]
    post_requests = [request for request in result.requests if request.method == "POST"]
    assert [request.param("filter") for request in get_requests] == [
        "state:active,include_subscriptions:true",
        "state:inactive,include_subscriptions:true",
    ]
    batches = [request.json()["ids"] for request in post_requests]
    assert [len(batch) for batch in batches] == [100, 52]
    assert batches[0][:2] == ["5", "1000"]
    assert batches[-1][-1] == "2000"
    assert len(result.rows) == 152
    assert result.committed_states[0] == MoneybirdResumeConfig(last_synchronized_id=1098)


@pytest.mark.parametrize(
    ("watermark", "resume_after", "expected_ids"),
    [
        # Records with the watermark version are read again, older ones are skipped.
        (200, None, ["2", "3"]),
        (None, None, ["1", "2", "3"]),
        (None, 2, ["3"]),
    ],
)
def test_synchronization_reads_only_changed_records_after_the_resume_point(
    watermark: int | None, resume_after: int | None, expected_ids: list[str]
) -> None:
    listing = _sync_versions([(3, 300), (1, 100), (2, 200)])
    sync_path = f"{BASE_PATH}/financial_mutations/synchronization.json"

    def script(request: Any) -> ScriptedResponse:
        assert request.path == sync_path
        return listing if request.method == "GET" else _records_for(request)

    inputs: dict[str, Any] = {"should_use_incremental_field": watermark is not None}
    if watermark is not None:
        inputs["incremental_field"] = "version"
        inputs["db_incremental_field_last_value"] = watermark
    resume_state = MoneybirdResumeConfig(last_synchronized_id=resume_after) if resume_after is not None else None

    result = _driver().run("financial_mutations", script, resume_state=resume_state, **inputs)

    assert result.raised is None
    assert result.requests[0].param("filter") == "state:all"
    assert [request.json()["ids"] for request in result.requests if request.method == "POST"] == [expected_ids]
    assert [row["id"] for row in result.rows] == expected_ids

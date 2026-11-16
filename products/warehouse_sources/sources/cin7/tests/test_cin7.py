from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest

import requests

from products.warehouse_sources.sources.cin7._config import Cin7SourceConfig
from products.warehouse_sources.sources.cin7.cin7 import Cin7ResumeConfig, format_cin7_datetime
from products.warehouse_sources.sources.cin7.source import Cin7Source
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always, scripted_network

ACCOUNT_ID = "6b9d1f0e-0000-4000-8000-000000000001"
APPLICATION_KEY = "test-application-key"


def _driver() -> SourceDriver:
    return SourceDriver(Cin7Source(), Cin7SourceConfig(account_id=ACCOUNT_ID, application_key=APPLICATION_KEY))


def _page(key: str, count: int, total: int | None, start: int = 0) -> ScriptedResponse:
    body: dict[str, Any] = {"Page": 1, key: [{"ID": f"p{i}"} for i in range(start, start + count)]}
    if total is not None:
        body["Total"] = total
    return ScriptedResponse(json=body)


@pytest.mark.parametrize(
    ("pages", "expected_pages"),
    [
        # Full pages until the short last page.
        ([(1000, 2001), (1000, 2001), (1, 2001)], ["1", "2", "3"]),
        # The second page is full, but `Total` says it is the last one.
        ([(1000, 2000), (1000, 2000)], ["1", "2"]),
        # No `Total` in the body: the short page ends the walk.
        ([(1000, None), (10, None)], ["1", "2"]),
        # An endpoint that ignores `Page` returns more rows than `Limit` once.
        ([(1500, 1500)], ["1"]),
        ([(0, 0)], ["1"]),
    ],
)
def test_pagination_walks_pages_to_the_last_one(pages: list[tuple[int, int | None]], expected_pages: list[str]) -> None:
    script = []
    start = 0
    for count, total in pages:
        script.append(_page("Products", count, total, start))
        start += count

    result = _driver().run("products", script)

    assert result.raised is None
    assert result.paths == ["/ExternalApi/v2/product"] * len(expected_pages)
    assert result.params("Page") == expected_pages
    assert result.params("Limit") == ["1000"] * len(expected_pages)
    assert len(result.rows) == start
    for request in result.requests:
        assert request.headers["api-auth-accountid"] == ACCOUNT_ID
        assert request.headers["api-auth-applicationkey"] == APPLICATION_KEY


@pytest.mark.parametrize(
    ("schema", "key", "inputs", "filter_param", "expected_filter"),
    [
        (
            "products",
            "Products",
            {
                "incremental_field": "LastModifiedOn",
                "db_incremental_field_last_value": datetime(2026, 3, 4, 7, 8, 9, 123456, tzinfo=UTC),
            },
            "ModifiedSince",
            "2026-03-04T07:08:09.123",
        ),
        (
            "sales",
            "SaleList",
            {
                "incremental_field": "Updated",
                "db_incremental_field_last_value": datetime(2026, 3, 4, 7, 8, 9, tzinfo=UTC),
            },
            "UpdatedSince",
            "2026-03-04T07:08:09.000",
        ),
        (
            "purchases",
            "PurchaseList",
            {
                "incremental_field": "LastUpdatedDate",
                "db_incremental_field_last_value": datetime(2026, 3, 4, 7, 8, 9, tzinfo=UTC),
            },
            "UpdatedSince",
            "2026-03-04T07:08:09.000",
        ),
        # The first incremental sync has no watermark yet, so it sends no filter and reads every row.
        ("customers", "CustomerList", {"incremental_field": "LastModifiedOn"}, "ModifiedSince", None),
        (
            "products",
            "Products",
            {
                "incremental_field": "LastModifiedOn",
                "should_use_incremental_field": False,
                "db_incremental_field_last_value": datetime(2026, 3, 4, tzinfo=UTC),
            },
            "ModifiedSince",
            None,
        ),
    ],
)
def test_incremental_filter_is_sent_only_with_a_watermark(
    schema: str, key: str, inputs: dict[str, Any], filter_param: str, expected_filter: str | None
) -> None:
    result = _driver().run(schema, [_page(key, 1, 1)], **inputs)

    assert result.raised is None
    assert result.requests[0].param(filter_param) == expected_filter


@pytest.mark.parametrize("schema", ["products", "customers", "suppliers"])
def test_contact_and_product_lists_include_deprecated_records(schema: str) -> None:
    key = {"products": "Products", "customers": "CustomerList", "suppliers": "SupplierList"}[schema]

    result = _driver().run(schema, [_page(key, 1, 1)])

    assert result.requests[0].param("IncludeDeprecated") == "true"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (datetime(2026, 3, 4, 7, 8, 9, 123456), "2026-03-04T07:08:09.123"),
        (datetime(2026, 3, 4, 9, 8, 9, tzinfo=timezone(timedelta(hours=2))), "2026-03-04T07:08:09.000"),
        (date(2026, 3, 4), "2026-03-04T00:00:00.000"),
        ("2026-03-04T07:08:09.52Z", "2026-03-04T07:08:09.520"),
        ("2026-03-04T07:08:09", "2026-03-04T07:08:09.000"),
    ],
)
def test_format_cin7_datetime_sends_utc_with_milliseconds(value: Any, expected: str) -> None:
    assert format_cin7_datetime(value) == expected


def test_resume_starts_from_the_saved_page() -> None:
    result = _driver().run(
        "sales",
        [_page("SaleList", 1000, 4000, 2000), _page("SaleList", 1000, 4000, 3000)],
        resume_state=Cin7ResumeConfig(next_page=3),
    )

    assert result.raised is None
    assert result.params("Page") == ["3", "4"]
    assert result.saved_states == [Cin7ResumeConfig(next_page=4)]


def test_next_page_is_committed_with_the_page_it_follows() -> None:
    result = _driver().run(
        "products",
        [_page("Products", 1000, 2500), _page("Products", 1000, 2500, 1000), _page("Products", 500, 2500, 2000)],
    )

    assert result.raised is None
    assert result.saved_states == [Cin7ResumeConfig(next_page=2), Cin7ResumeConfig(next_page=3)]
    assert result.committed_states == [Cin7ResumeConfig(next_page=2), Cin7ResumeConfig(next_page=3)]


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (ScriptedResponse(status=200, json={"Company": "Example Ltd"}), (True, None)),
        (
            # Cin7 Core answers a wrong account ID or application key with a 403.
            ScriptedResponse(status=403, json=[{"ErrorCode": 403, "Exception": "Incorrect credentials!"}]),
            (
                False,
                "Cin7 Core rejected the account ID or application key. Copy both values from Integrations > API in Cin7 Core.",
            ),
        ),
        (
            ScriptedResponse(status=429, json={}),
            (False, "Cin7 Core rate limited the request. Wait a minute, then try again."),
        ),
        (
            ScriptedResponse(status=500, json={}),
            (False, "Cin7 Core returned an unexpected status (500). Try again in a few minutes."),
        ),
        (
            requests.ConnectionError("connection refused"),
            (False, "Could not connect to Cin7 Core. Try again in a few minutes."),
        ),
    ],
)
def test_validate_credentials_maps_the_probe_answer(answer: Any, expected: tuple[bool, str | None]) -> None:
    config = Cin7SourceConfig(account_id=f" {ACCOUNT_ID} ", application_key=APPLICATION_KEY)

    with scripted_network(always(answer)) as network:
        assert Cin7Source().validate_credentials(config, team_id=1) == expected

    assert {request.path for request in network.requests_log} == {"/ExternalApi/v2/me"}
    assert network.requests_log[0].headers["api-auth-accountid"] == ACCOUNT_ID

from datetime import UTC, date, datetime

import pytest
from time_machine import travel

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.triplewhale import (
    TripleWhaleSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.triple_whale.source import TripleWhaleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.triple_whale.triple_whale import (
    TripleWhaleResumeConfig,
)


@travel("2024-03-02T12:34:56+00:00", tick=False)
def test_orders_paginate_by_total_and_advance_month_without_losing_nested_data() -> None:
    config = TripleWhaleSourceConfig(api_key="test-key", shop="example.myshopify.com", start_date="2024-02-28")
    first = {
        "order_id": 1,
        "created_at": "2024-02-28T12:00:00Z",
        "attribution": {"firstClick": [{"source": "google", "adId": "example-ad"}]},
        "journey": [{"event": "add2c", "productId": None}],
        "total_price": "10.25",
    }
    second = {"order_id": 2, "created_at": "2024-02-29T12:00:00Z", "journey": [], "attribution": None}
    result = SourceDriver(TripleWhaleSource(), config).run(
        "orders_with_journeys",
        [
            ScriptedResponse(json={"totalForRange": 2, "count": 1, "ordersWithJourneys": [first]}),
            ScriptedResponse(json={"totalForRange": 2, "count": 1, "ordersWithJourneys": [second]}),
            ScriptedResponse(json={"totalForRange": 0, "count": 0, "ordersWithJourneys": []}),
        ],
    )
    assert result.raised is None
    assert result.rows == [first, second]
    bodies = [request.json() for request in result.requests]
    assert [(body["page"], body["startDate"], body["endDate"]) for body in bodies] == [
        (1, "2024-02-28T00:00:00.000+00:00", "2024-02-29T23:59:59.999+00:00"),
        (2, "2024-02-28T00:00:00.000+00:00", "2024-02-29T23:59:59.999+00:00"),
        (1, "2024-03-01T00:00:00.000+00:00", "2024-03-02T12:34:56.000+00:00"),
    ]
    assert all(body["shop"] == "example.myshopify.com" and not body["excludeJourneyData"] for body in bodies)
    assert all(request.method == "POST" and request.headers["x-api-key"] == "test-key" for request in result.requests)
    assert result.committed_states == [
        TripleWhaleResumeConfig(window_start="2024-02-28", end_time="2024-03-02T12:34:56+00:00", page=2, seen=1),
        TripleWhaleResumeConfig(window_start="2024-03-01", end_time="2024-03-02T12:34:56+00:00"),
        TripleWhaleResumeConfig(window_start="2024-04-01", end_time="2024-03-02T12:34:56+00:00"),
    ]


@travel("2024-03-02T12:34:56+00:00", tick=False)
@pytest.mark.parametrize("schema_name", ["orders_with_journeys", "summary_page"])
def test_resume_keeps_date_range_and_skips_written_pages(schema_name: str) -> None:
    config = TripleWhaleSourceConfig(api_key="test-key", shop="example.myshopify.com", start_date="2024-01-01")
    is_orders = schema_name == "orders_with_journeys"
    state = TripleWhaleResumeConfig(
        window_start="2024-02-29",
        end_time="2024-02-29T23:59:59+00:00",
        page=2 if is_orders else 1,
        seen=1 if is_orders else 0,
    )
    row = {"order_id": 2} if is_orders else {"metricName": "revenue", "value": 5}
    response = {"totalForRange": 2, "ordersWithJourneys": [row]} if is_orders else {"metrics": [row]}
    result = SourceDriver(TripleWhaleSource(), config).run(
        schema_name, [ScriptedResponse(json=response)], resume_state=state
    )
    assert result.raised is None
    assert len(result.requests) == 1
    body = result.requests[0].json()
    if is_orders:
        assert body["page"] == 2
        assert body["startDate"] == "2024-02-29T00:00:00.000+00:00"
        assert body["endDate"] == "2024-02-29T23:59:59.000+00:00"
        assert result.rows == [row]
    else:
        assert body["period"] == {"start": "2024-02-29", "end": "2024-02-29"}
        assert result.rows == [{**row, "date": "2024-02-29"}]
    assert result.committed_states[-1].window_start == "2024-03-01"


@travel("2024-03-02T12:34:56+00:00", tick=False)
def test_daily_metrics_attach_reporting_date_and_checkpoint_empty_days() -> None:
    config = TripleWhaleSourceConfig(api_key="test-key", shop="example.myshopify.com", start_date="2024-02-29")
    result = SourceDriver(TripleWhaleSource(), config).run(
        "summary_page",
        [
            ScriptedResponse(
                json={"metrics": [{"metricName": "revenue", "value": 5}, {"metricName": "orders", "value": 1}]}
            ),
            ScriptedResponse(json={"metrics": []}),
            ScriptedResponse(json={"metrics": [{"metricName": "revenue", "value": 0}]}),
        ],
    )
    assert result.raised is None
    assert result.rows == [
        {"metricName": "revenue", "value": 5, "date": "2024-02-29"},
        {"metricName": "orders", "value": 1, "date": "2024-02-29"},
        {"metricName": "revenue", "value": 0, "date": "2024-03-02"},
    ]
    assert [request.json() for request in result.requests] == [
        {"shopDomain": "example.myshopify.com", "period": {"start": day, "end": day}, "todayHour": hour}
        for day, hour in [("2024-02-29", 25), ("2024-03-01", 25), ("2024-03-02", 13)]
    ]
    assert [state.window_start for state in result.committed_states] == ["2024-03-01", "2024-03-02", "2024-03-03"]


@travel("2024-03-02T12:34:56+00:00", tick=False)
@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"ordersWithJourneys": [], "totalForRange": 1}, "empty page"),
        ({"ordersWithJourneys": [], "totalForRange": -1}, "invalid order count"),
        ({"ordersWithJourneys": [], "error": "Forbidden"}, "attribution error"),
    ],
)
def test_orders_fail_instead_of_publishing_incomplete_data(body: dict[str, object], message: str) -> None:
    config = TripleWhaleSourceConfig(api_key="test-key", shop="example.myshopify.com", start_date="2024-03-01")
    result = SourceDriver(TripleWhaleSource(), config).run("orders_with_journeys", [ScriptedResponse(json=body)])
    assert isinstance(result.raised, ValueError)
    assert message in str(result.raised)
    assert result.rows == []
    assert result.saved_states == []


@travel("2024-03-02T12:34:56+00:00", tick=False)
def test_order_page_cap_fails_without_marking_the_window_complete() -> None:
    config = TripleWhaleSourceConfig(api_key="test-key", shop="example.myshopify.com", start_date="2024-03-01")
    state = TripleWhaleResumeConfig(
        window_start="2024-03-01", end_time="2024-03-02T12:34:56+00:00", page=10000, seen=999900
    )
    result = SourceDriver(TripleWhaleSource(), config).run(
        "orders_with_journeys",
        [ScriptedResponse(json={"ordersWithJourneys": [{"order_id": 1000000}], "totalForRange": 1000001})],
        resume_state=state,
    )
    assert isinstance(result.raised, ValueError)
    assert "page limit" in str(result.raised)
    assert result.saved_states == []


@travel("2024-03-02T12:34:56+00:00", tick=False)
@pytest.mark.parametrize("schema_name", ["orders_with_journeys", "summary_page"])
def test_reject_incremental_requests_before_reading_data(schema_name: str) -> None:
    config = TripleWhaleSourceConfig(api_key="test-key", shop="example.myshopify.com", start_date="2024-03-01")
    result = SourceDriver(TripleWhaleSource(), config).run(
        schema_name,
        [],
        should_use_incremental_field=True,
        db_incremental_field_last_value=datetime(2024, 3, 1, tzinfo=UTC),
    )
    assert isinstance(result.raised, ValueError)
    assert "full refresh" in str(result.raised)
    assert result.requests == []


def test_unknown_table_uses_rollout_error() -> None:
    config = TripleWhaleSourceConfig(
        api_key="test-key", shop="example.myshopify.com", start_date=date(2024, 1, 1).isoformat()
    )
    result = SourceDriver(TripleWhaleSource(), config).run("unknown", [])
    assert isinstance(result.raised, UnknownResourceError)
    assert result.requests == []

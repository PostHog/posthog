from typing import Any

import pytest
import time_machine

from products.warehouse_sources.backend.temporal.data_imports.sources.adapty.adapty import AdaptyResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.adapty.source import AdaptySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.adapty import AdaptySourceConfig


def driver() -> SourceDriver:
    return SourceDriver(AdaptySource(), AdaptySourceConfig(api_key="secret_live_example", start_date="2024-01-01"))


@time_machine.travel("2024-01-03T12:00:00Z", tick=False)
def test_analytics_walks_all_charts_and_days_without_losing_sibling_metrics() -> None:
    payload = {
        "data": {
            "revenue": {"value": 10, "data": [], "unit": "USD"},
            "proceeds": {"value": 7, "data": [], "unit": "USD"},
        }
    }
    result = driver().run("Analytics", [ScriptedResponse(json=payload)] * 38)

    assert result.raised is None
    assert len(result.rows) == 76
    bodies = [request.json() for request in result.requests]
    assert bodies[0] == {
        "filters": {"date": ["2024-01-01", "2024-01-01"]},
        "chart_id": "revenue",
        "period_unit": "day",
        "date_type": "purchase_date",
        "format": "json",
    }
    assert [body["chart_id"] for body in bodies[:19]] == [
        "revenue",
        "mrr",
        "arr",
        "arppu",
        "subscriptions_active",
        "subscriptions_new",
        "subscriptions_renewal_cancelled",
        "subscriptions_expired",
        "trials_active",
        "trials_new",
        "trials_renewal_cancelled",
        "trials_expired",
        "grace_period",
        "billing_issue",
        "refund_events",
        "refund_money",
        "non_subscriptions",
        "arpu",
        "installs",
    ]
    assert bodies[19]["filters"] == {"date": ["2024-01-02", "2024-01-02"]}
    assert all(
        request.method == "POST" and request.origin == "https://api-admin.adapty.io" for request in result.requests
    )
    assert result.requests[0].headers["authorization"] == "Api-Key secret_live_example"
    assert result.requests[0].headers["adapty-tz"] == "UTC"
    assert result.rows[0] == {
        "date": "2024-01-01",
        "chart_id": "revenue",
        "metric": "revenue",
        "value": 10,
        "data": [],
        "unit": "USD",
    }
    assert len({(row["date"], row["chart_id"], row["metric"]) for row in result.rows}) == len(result.rows)
    assert [row["date"] for row in result.rows] == sorted(row["date"] for row in result.rows)
    assert result.committed_states[-1] == AdaptyResumeConfig(next_date="2024-01-03", end_date="2024-01-02")


@pytest.mark.parametrize(
    ("schema", "payload", "extra"),
    [
        (
            "Cohorts",
            {"data": [{"segment_start_date": "2024-01-01", "values": [{"period": 1, "revenue_usd": 10}]}]},
            {"period_unit": "day", "period_type": "renewals", "value_field": "revenue", "value_type": "absolute"},
        ),
        (
            "Conversions",
            {"data": [], "value": 0, "value_from": None},
            {"period_unit": "day", "date_type": "purchase_date", "from_period": "1", "to_period": "6+"},
        ),
        ("Funnels", {"data": [{"title": "Total", "values": [{"period": -2, "value": 2}]}]}, {"show_value_as": "both"}),
        ("Retention", {"data": [], "value_type": None}, {"use_trial": False}),
        (
            "LTV",
            {"revenue": {"data": [], "value": 10}, "proceeds": {"data": [], "value": 7}},
            {"period_unit": "day", "period_type": "renewals"},
        ),
    ],
)
@time_machine.travel("2024-01-03T12:00:00Z", tick=False)
def test_reports_preserve_nested_values_and_send_endpoint_specific_bodies(
    schema: str, payload: dict[str, Any], extra: dict[str, Any]
) -> None:
    result = driver().run(schema, [ScriptedResponse(json=payload)] * 2, db_incremental_field_last_value="2024-01-02")

    assert result.raised is None
    assert [request.json() for request in result.requests] == [
        {**extra, "filters": {"date": [day, day]}, "format": "json"} for day in ("2024-01-01", "2024-01-02")
    ]
    if schema == "LTV":
        assert result.rows[0] == {**payload["revenue"], "date": "2024-01-01", "metric": "revenue"}
        assert result.rows[1]["metric"] == "proceeds"
    else:
        assert result.rows == [{**payload, "date": day} for day in ("2024-01-01", "2024-01-02")]


@time_machine.travel("2024-02-01T12:00:00Z", tick=False)
def test_report_resume_keeps_the_original_end_and_skips_completed_charts() -> None:
    result = driver().run(
        "Analytics",
        [ScriptedResponse(json={"data": {"count": {"value": 1, "data": []}}})] * 2,
        resume_state=AdaptyResumeConfig(next_date="2024-01-02", end_date="2024-01-02", chart_index=17),
    )

    assert result.raised is None
    assert [request.json()["chart_id"] for request in result.requests] == ["arpu", "installs"]
    assert result.rows[0]["date"] == "2024-01-02"
    assert result.committed_states[-2:] == [
        AdaptyResumeConfig(next_date="2024-01-02", end_date="2024-01-02", chart_index=18),
        AdaptyResumeConfig(next_date="2024-01-03", end_date="2024-01-02"),
    ]


@time_machine.travel("2024-01-03T12:00:00Z", tick=False)
def test_report_checkpoint_survives_a_failure_on_the_next_day() -> None:
    result = driver().run(
        "Cohorts",
        [ScriptedResponse(json={"data": []}), ScriptedResponse(status=400, json={"error_code": "validation_error"})],
    )

    assert result.raised is not None
    assert result.rows == [{"data": [], "date": "2024-01-01"}]
    assert result.committed_states == [AdaptyResumeConfig(next_date="2024-01-02", end_date="2024-01-02")]


@time_machine.travel("2024-01-03T12:00:00Z", tick=False)
def test_empty_metric_reports_commit_progress_without_rows() -> None:
    result = driver().run(
        "Analytics",
        [ScriptedResponse(json={"data": {}})] * 19,
        resume_state=AdaptyResumeConfig(next_date="2024-01-02", end_date="2024-01-02"),
    )

    assert result.raised is None
    assert result.rows == []
    assert result.committed_states[-1] == AdaptyResumeConfig(next_date="2024-01-03", end_date="2024-01-02")


@pytest.mark.parametrize(
    ("schema", "payload"),
    [
        ("Analytics", {"data": []}),
        ("Analytics", {"data": {"revenue": None}}),
        ("Cohorts", {"data": {}}),
        ("LTV", {"revenue": None}),
        ("Retention", []),
        ("Funnels", None),
    ],
)
@time_machine.travel("2024-01-02T12:00:00Z", tick=False)
def test_invalid_reports_fail_without_advancing_progress(schema: str, payload: object) -> None:
    result = driver().run(schema, [ScriptedResponse(json=payload)])

    assert isinstance(result.raised, ValueError)
    assert result.rows == []
    assert result.saved_states == []


@pytest.mark.parametrize("resume_page", [None, 2])
def test_paywall_walk_uses_jsonapi_pages_and_preserves_records(resume_page: int | None) -> None:
    first = {
        "paywall_id": "paywall_1",
        "created_at": "2024-01-01T00:00:00Z",
        "products": [{"product_id": "product_1", "offer": None}],
    }
    last = {"paywall_id": "paywall_2", "created_at": "2024-01-02T00:00:00Z", "is_deleted": True}
    responses = [ScriptedResponse(json={"data": [last], "meta": {"pagination": {"pages": 2}}})]
    if resume_page is None:
        responses.insert(0, ScriptedResponse(json={"data": [first], "meta": {"pagination": {"pages": 2}}}))
    result = driver().run(
        "Paywalls", responses, resume_state=AdaptyResumeConfig(page=resume_page) if resume_page else None
    )

    assert result.raised is None
    assert result.params("page[number]") == (["1", "2"] if resume_page is None else ["2"])
    assert all(
        request.param("page[size]") == "100" and request.origin == "https://api.adapty.io"
        for request in result.requests
    )
    assert result.rows == ([first, last] if resume_page is None else [last])
    if resume_page is None:
        assert result.committed_states == [AdaptyResumeConfig(page=2)]

from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs

import pytest
import time_machine
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.criteo.criteo import CriteoResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.criteo.source import CriteoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.criteo import CriteoSourceConfig


def driver(start_date: str = "2026-10-10") -> SourceDriver:
    return SourceDriver(
        CriteoSource(),
        CriteoSourceConfig(
            client_id="example-client", client_secret="example-secret", start_date=start_date, currency="usd"
        ),
    )


def token() -> ScriptedResponse:
    return ScriptedResponse(json={"access_token": "example-access-token", "expires_in": 900, "token_type": "Bearer"})


def entity(identifier: str, attributes: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"id": identifier, "type": "example", "attributes": attributes}


@pytest.mark.parametrize("schema_name", ["Campaigns", "AdSets", "Advertisers"])
def test_complete_collections_use_the_documented_method_and_preserve_attributes(schema_name: str) -> None:
    result = driver().run(
        schema_name,
        [
            token(),
            ScriptedResponse(json={"data": [entity("1", {"name": "Example", "budget": {"amount": 2}}), entity("2")]}),
        ],
    )
    assert result.raised is None
    assert result.rows == [
        {"id": "1", "type": "example", "name": "Example", "budget": {"amount": 2}},
        {"id": "2", "type": "example"},
    ]
    request = result.requests[1]
    assert request.method == ("GET" if schema_name == "Advertisers" else "POST")
    assert request.query == {}
    if schema_name != "Advertisers":
        assert request.json() == {"filters": {}}
    assert result.committed_states == [CriteoResumeConfig(finished=True)]
    finished = driver().run(schema_name, [], resume_state=result.committed_states[-1])
    assert finished.raised is None
    assert finished.rows == []
    assert finished.requests == []
    assert request.headers["authorization"] == "Bearer example-access-token"
    token_body = result.requests[0].body
    assert token_body is not None
    assert parse_qs(token_body.decode()) == {
        "client_id": ["example-client"],
        "client_secret": ["example-secret"],
        "grant_type": ["client_credentials"],
    }


def test_audiences_walk_offsets_and_resume_after_the_last_written_page() -> None:
    first_page = [entity(str(i)) for i in range(100)]
    result = driver().run(
        "Audiences",
        [
            token(),
            ScriptedResponse(json={"data": first_page, "meta": {"totalItems": 101}}),
            ScriptedResponse(json={"data": [entity("100")], "meta": {"totalItems": 101}}),
        ],
    )
    assert result.raised is None
    assert [row["id"] for row in result.rows] == [str(i) for i in range(101)]
    assert result.params("offset")[1:] == ["0", "100"]
    assert result.committed_states == [CriteoResumeConfig(offset=100), CriteoResumeConfig(finished=True)]
    assert all(
        request.json() == {"data": {"type": "AudienceSearch", "attributes": {}}} for request in result.requests[1:]
    )
    resumed = driver().run(
        "Audiences",
        [token(), ScriptedResponse(json={"data": [entity("100")], "meta": {"totalItems": 101}})],
        resume_state=result.committed_states[0],
    )
    assert resumed.raised is None
    assert resumed.params("offset")[1:] == ["100"]
    assert resumed.rows == [{"id": "100", "type": "example"}]
    finished = driver().run("Audiences", [], resume_state=resumed.committed_states[-1])
    assert finished.raised is None
    assert finished.requests == []


def test_ads_fan_out_and_resume_without_repeating_completed_advertisers() -> None:
    advertisers = ScriptedResponse(json={"data": [entity("10"), entity("20")]})
    result = driver().run(
        "Ads",
        [
            token(),
            advertisers,
            ScriptedResponse(json={"data": [entity(str(i), {"name": "Example"}) for i in range(50)]}),
            ScriptedResponse(json={"data": [entity("50")]}),
            ScriptedResponse(json={"data": [entity("1")]}),
        ],
    )
    assert result.raised is None
    assert result.paths[1:] == [
        "/2026-07/advertisers/me",
        "/2026-07/marketing-solutions/advertisers/10/ads",
        "/2026-07/marketing-solutions/advertisers/10/ads",
        "/2026-07/marketing-solutions/advertisers/20/ads",
    ]
    assert result.params("offset")[1:] == [None, "0", "50", "0"]
    assert {row["advertiserId"] for row in result.rows[:-1]} == {"10"}
    assert result.rows[-1] == {"id": "1", "type": "example", "advertiserId": "20"}
    checkpoint = next(
        state for state in result.committed_states if state.fanout_state and state.fanout_state.get("completed")
    )
    resumed = driver().run(
        "Ads", [token(), advertisers, ScriptedResponse(json={"data": [entity("1")]})], resume_state=checkpoint
    )
    assert resumed.raised is None
    assert resumed.paths[-1] == "/2026-07/marketing-solutions/advertisers/20/ads"
    assert len(resumed.requests) == 3


@pytest.mark.parametrize(
    ("incremental", "watermark", "expected_start"),
    [
        (False, datetime(2026, 10, 12, tzinfo=UTC), "2026-10-10"),
        (True, None, "2026-10-10"),
        (True, date(2026, 10, 11), "2026-10-11"),
        (True, "2026-10-11T12:00:00Z", "2026-10-11"),
        (True, datetime(2026, 10, 13, tzinfo=UTC), None),
    ],
)
@time_machine.travel("2026-10-12T00:00:00Z", tick=False)
def test_reports_send_inclusive_daily_bounds_and_the_effective_watermark(
    incremental: bool, watermark: object, expected_start: str | None
) -> None:
    script = (
        [
            token(),
            *[
                ScriptedResponse(
                    json={
                        "Rows": [
                            {"Day": f"2026/10/{day}", "AdvertiserId": "10", "CampaignId": "1", "AdvertiserCost": "3.5"}
                        ]
                    }
                )
                for day in range(int(expected_start[-2:]), 13)
            ],
        ]
        if expected_start
        else []
    )
    result = driver().run(
        "CampaignStats",
        script,
        should_use_incremental_field=incremental,
        incremental_field="Day" if incremental else None,
        db_incremental_field_last_value=watermark,
    )
    assert result.raised is None
    days = [row["Day"] for row in result.rows]
    assert days == sorted(days)
    if expected_start is None:
        assert result.requests == []
        return
    assert days[0] == expected_start
    for request, row in zip(result.requests[1:], result.rows, strict=True):
        assert request.json() == {
            "advertiserIds": "",
            "startDate": row["Day"],
            "endDate": row["Day"],
            "dimensions": ["Day", "AdvertiserId", "CampaignId"],
            "metrics": [
                "Displays",
                "Clicks",
                "AdvertiserCost",
                "SalesClientAttribution",
                "RevenueGeneratedClientAttribution",
            ],
            "currency": "USD",
            "format": "json",
            "timezone": "UTC",
        }
    assert result.committed_states[-1] == CriteoResumeConfig(next_day="2026-10-13", end_day="2026-10-12")


@time_machine.travel("2026-10-12T00:00:00Z", tick=False)
def test_report_resume_keeps_the_original_end_date_and_commits_empty_days() -> None:
    result = driver().run(
        "CampaignStats",
        [token(), ScriptedResponse(json={"Rows": []})],
        resume_state=CriteoResumeConfig(next_day="2026-10-11", end_day="2026-10-11"),
    )
    assert result.raised is None
    assert result.rows == []
    assert result.requests[1].json()["startDate"] == "2026-10-11"
    assert result.committed_states == [CriteoResumeConfig(next_day="2026-10-12", end_day="2026-10-11")]


@pytest.mark.parametrize(
    ("rows", "error", "limit"),
    [
        ([{"Day": "2026-10-10", "AdvertiserId": "1", "CampaignId": "1"}] * 2, "row limit", 2),
        ([{"Day": "2026-10-09", "AdvertiserId": "1", "CampaignId": "1"}], "outside the requested day", 100000),
        ([{"Day": None, "AdvertiserId": "1", "CampaignId": "1"}], "outside the requested day", 100000),
        (
            [{"Day": "2026-10-10", "AdvertiserId": "1", "CampaignId": None}],
            "without an advertiser or campaign ID",
            100000,
        ),
    ],
)
@time_machine.travel("2026-10-12T00:00:00Z", tick=False)
def test_invalid_reports_fail_before_rows_or_checkpoints_escape(
    rows: list[dict[str, Any]], error: str, limit: int
) -> None:
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.criteo.criteo.REPORT_ROW_LIMIT", limit
    ):
        result = driver().run("CampaignStats", [token(), ScriptedResponse(json={"Rows": rows})])
    assert isinstance(result.raised, ValueError)
    assert error in str(result.raised)
    assert result.rows == []
    assert result.committed_states == []


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"data": [], "errors": [{"type": "authorization", "code": "insufficient-scope"}]}, "Criteo denied access"),
        ({"data": [], "errors": [{"code": "invalid-request"}]}, "Criteo returned an error"),
        ({"unexpected": []}, "data"),
    ],
)
def test_entity_error_envelopes_cannot_replace_tables_with_empty_data(payload: dict[str, Any], expected: str) -> None:
    result = driver().run("Campaigns", [token(), ScriptedResponse(json=payload)])
    assert result.raised is not None
    assert expected in str(result.raised)
    assert result.rows == []

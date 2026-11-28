from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine

import requests

from products.warehouse_sources.sources.sdk.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.sources.unity_ads._config import UnityAdsSourceConfig
from products.warehouse_sources.sources.unity_ads.source import UnityAdsSource
from products.warehouse_sources.sources.unity_ads.unity_ads import UnityAdsResumeConfig, validate_credentials

NOW = datetime(2026, 10, 15, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def frozen_clock() -> Iterator[None]:
    with time_machine.travel(NOW, tick=False):
        yield


def _run(endpoint: str, script: Any, organization_id: str = "5772916123937", **inputs: Any) -> DriveResult:
    config = UnityAdsSourceConfig(organization_id=organization_id, key_id="kid", secret_key="ksecret")
    return SourceDriver(UnityAdsSource(), config).run(endpoint, script, **inputs)


def _window_days(request: RecordedRequest) -> int:
    start, end = str(request.param("start"))[:10], str(request.param("end"))[:10]
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def _rows(*rows: dict[str, Any]) -> ScriptedResponse:
    return ScriptedResponse(json={"data": list(rows)})


def _results(*rows: dict[str, Any], total: int | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"results": list(rows), "total": len(rows) if total is None else total})


class TestWindows:
    def test_campaigns_read_92_day_windows_from_the_watermark_in_date_order(self) -> None:
        result = _run(
            "campaigns_daily",
            [
                _rows(
                    {"timestamp": "2026-09-02", "campaignId": "c1", "installs": 3},
                    {"timestamp": "2026-09-01", "campaignId": "c1", "installs": 5},
                ),
                _rows({"timestamp": "2026-10-02", "campaignId": "c1", "installs": 1}),
            ],
            incremental_field="timestamp",
            db_incremental_field_last_value=date(2026, 7, 1),
        )

        assert result.raised is None
        assert result.paths == ["/advertise/stats/v2/organizations/5772916123937/reports/acquisitions"] * 2
        assert [(r.param("start"), r.param("end")) for r in result.requests] == [
            ("2026-07-01T00:00:00Z", "2026-10-01T00:00:00Z"),
            ("2026-10-01T00:00:00Z", "2026-10-16T00:00:00Z"),
        ]
        first = result.requests[0]
        assert (first.param("scale"), first.param("breakdowns"), first.param("format")) == ("day", "campaign", "json")
        metrics = first.param("metrics")
        assert metrics is not None and "d7TotalRoas" in metrics
        assert first.headers["authorization"] == "Basic a2lkOmtzZWNyZXQ="
        assert [row["timestamp"] for row in result.rows] == ["2026-09-01", "2026-09-02", "2026-10-02"]
        assert result.saved_states == [UnityAdsResumeConfig(next_window_start="2026-10-01", window_days=92)]

    def test_a_resumed_country_run_reads_from_the_saved_window_and_skips_an_empty_one(self) -> None:
        result = _run(
            "campaigns_daily_by_country",
            [ScriptedResponse(status=204)],
            resume_state=UnityAdsResumeConfig(next_window_start="2026-10-10"),
        )

        assert result.raised is None
        assert [(r.param("start"), r.param("end"), r.param("breakdowns")) for r in result.requests] == [
            ("2026-10-10T00:00:00Z", "2026-10-16T00:00:00Z", "campaign,country")
        ]
        assert result.rows == []

    @pytest.mark.parametrize(
        ("endpoint", "expected_requests"),
        [("campaigns_daily", 4), ("campaigns_daily_by_country", 12), ("skan_daily", 12)],
    )
    def test_a_first_sync_keeps_requests_within_the_shared_quota(self, endpoint: str, expected_requests: int) -> None:
        result = _run(endpoint, always(ScriptedResponse(status=204)))

        assert result.raised is None
        assert result.params("start")[0] == "2025-10-15T00:00:00Z"
        assert len(result.requests) == expected_requests

    def test_skan_reads_the_incremental_window_with_conversion_values(self) -> None:
        rows = [
            {"timestamp": "2026-10-14", "campaignId": "campaign-1", "conversionValue": 0, "installs": 11},
            {"timestamp": "2026-10-14", "campaignId": "campaign-1", "conversionValue": 4, "installs": 5},
        ]
        result = _run(
            "skan_daily",
            [_rows(*rows)],
            incremental_field="timestamp",
            db_incremental_field_last_value=date(2026, 10, 14),
        )

        assert result.raised is None
        assert result.paths == ["/advertise/stats/v2/organizations/5772916123937/reports/skan"]
        request = result.requests[0]
        assert (request.param("start"), request.param("end")) == ("2026-10-14T00:00:00Z", "2026-10-16T00:00:00Z")
        assert (request.param("metrics"), request.param("breakdowns")) == ("installs", "campaign,conversionValue")
        assert result.rows == rows

    def test_a_window_that_keeps_timing_out_is_halved_until_it_answers(self) -> None:
        # Unity's report for a large account can outlast the read timeout on every retry of the same window.
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if _window_days(request) > 8:
                raise requests.ReadTimeout("read timed out")
            return _rows({"timestamp": str(request.param("start"))[:10], "campaignId": "c1", "country": "AU"})

        result = _run(
            "campaigns_daily_by_country",
            respond,
            resume_state=UnityAdsResumeConfig(next_window_start="2026-09-15"),
        )

        assert result.raised is None
        answered = [(str(r.param("start")), str(r.param("end"))) for r in result.requests if _window_days(r) <= 8]
        assert answered[0] == ("2026-09-15T00:00:00Z", "2026-09-22T00:00:00Z")
        assert answered[-1][1] == "2026-10-16T00:00:00Z"
        # Later windows keep the halved size, so 31 days take 5 answered requests.
        assert len(answered) == 5
        assert [row["timestamp"] for row in result.rows] == [start[:10] for start, _ in answered]
        assert result.saved_states[-1] == UnityAdsResumeConfig(next_window_start="2026-10-13", window_days=7)

    def test_a_resumed_run_keeps_the_halved_window_size(self) -> None:
        result = _run(
            "campaigns_daily_by_country",
            always(ScriptedResponse(status=204)),
            resume_state=UnityAdsResumeConfig(next_window_start="2026-10-01", window_days=7),
        )

        assert result.raised is None
        assert [_window_days(r) for r in result.requests] == [7, 7, 1]

    @pytest.mark.parametrize("organization_id", ["../../other", "org-1", ""])
    def test_a_non_numeric_organization_id_never_reaches_the_url(self, organization_id: str) -> None:
        result = _run("campaigns_daily", [], organization_id=organization_id)

        assert isinstance(result.raised, ValueError)
        assert result.requests == []

    def test_a_rejected_key_fails_with_the_url_the_error_map_matches(self) -> None:
        result = _run(
            "campaigns_daily",
            always(
                ScriptedResponse(
                    status=401,
                    json={"status": 401, "title": "Unauthorized", "detail": "Authentication Failed", "code": 51},
                )
            ),
        )

        assert result.raised is not None
        assert "401 Client Error: Unauthorized for url: https://services.api.unity.com" in str(result.raised)


class TestManagementTables:
    def test_apps_follow_the_offset_until_the_last_page(self) -> None:
        first_page = [{"id": f"{index:024x}"} for index in range(1000)]
        last_app = {"id": "a" * 24, "storeId": "com.example.game"}
        result = _run("apps", [_results(*first_page, total=1001), _results(last_app, total=1001)])

        assert result.raised is None
        assert result.paths == ["/advertise/v1/organizations/5772916123937/apps"] * 2
        assert [str(request.param("offset")) for request in result.requests] == ["0", "1000"]
        assert result.rows == [*first_page, last_app]

    @pytest.mark.parametrize(
        ("endpoint", "bid_row"),
        [
            ("campaigns", None),
            ("cpi_bids", {"country": "US", "bid": "0.201"}),
            ("source_bids", {"country": "US", "bid": "0.201", "sourceAppId": "exampleApp01"}),
        ],
    )
    def test_management_rows_keep_the_parent_ids(self, endpoint: str, bid_row: dict[str, str] | None) -> None:
        apps = [{"id": "a" * 24}, {"id": "b" * 24}]
        campaigns = [{"id": "c" * 24, "enabled": True}, {"id": "d" * 24, "enabled": False}]
        apps_path = "/advertise/v1/organizations/5772916123937/apps"
        paths = [apps_path]
        responses = [_results(*apps)]
        expected_rows = []
        for app, campaign in zip(apps, campaigns):
            campaign_path = f"{apps_path}/{app['id']}/campaigns"
            paths.append(campaign_path)
            responses.append(_results(campaign))
            if bid_row is None:
                expected_rows.append({**campaign, "campaignSetId": app["id"]})
            else:
                paths.append(f"{campaign_path}/{campaign['id']}/{endpoint.replace('_', '-')}")
                responses.append(_results(bid_row))
                expected_rows.append({**bid_row, "campaignSetId": app["id"], "campaignId": campaign["id"]})

        result = _run(endpoint, responses)

        assert result.raised is None
        assert result.paths == paths
        assert result.rows == expected_rows

    def test_an_invalid_app_id_never_reaches_a_campaign_url(self) -> None:
        result = _run("campaigns", [_results({"id": "../../other"})])

        assert isinstance(result.raised, ValueError)
        assert result.paths == ["/advertise/v1/organizations/5772916123937/apps"]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("response", "expected_valid", "message_fragment"),
        [
            (ScriptedResponse(json={"data": []}), True, None),
            (ScriptedResponse(status=204), True, None),
            (ScriptedResponse(status=404, json={"title": "Not Found"}), False, "no organization"),
        ],
    )
    def test_maps_the_probe_result(self, response: Any, expected_valid: bool, message_fragment: str | None) -> None:
        with scripted_network(always(response)) as network:
            is_valid, message = validate_credentials("5772916123937", "kid", "ksecret")

        assert is_valid is expected_valid
        if message_fragment is None:
            assert message is None
        else:
            assert message is not None and message_fragment in message
        # Setup waits on the probe, so a failed request gets no retry.
        assert len(network.requests_log) == 1

    def test_a_non_numeric_organization_id_is_refused_without_a_request(self) -> None:
        with scripted_network([]) as network:
            is_valid, message = validate_credentials("my-org", "kid", "ksecret")

        assert is_valid is False
        assert message is not None and "Organization core ID" in message
        assert network.requests_log == []

from datetime import date, timedelta
from typing import Any

import pytest
import time_machine
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.extract import validate_incremental_sync
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tenjin import TenjinSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tenjin import tenjin
from products.warehouse_sources.backend.temporal.data_imports.sources.tenjin.settings import TENJIN_REPORTS
from products.warehouse_sources.backend.temporal.data_imports.sources.tenjin.source import TenjinSource
from products.warehouse_sources.backend.temporal.data_imports.sources.tenjin.tenjin import (
    MAX_HISTORY_DAYS,
    TENJIN_BASE_URL,
    TenjinCredentialsError,
    TenjinResumeConfig,
    TenjinRetryableError,
    resolve_start_date,
    validate_credentials,
)

TODAY = date(2026, 6, 30)


def _report_page(rows: list[dict[str, Any]], next_url: str | None = None) -> ScriptedResponse:
    links: dict[str, str] = {"self": f"{TENJIN_BASE_URL}/reports/spend"}
    if next_url:
        links["next"] = next_url
    return ScriptedResponse(
        json={
            "data": [{"type": "report", "attributes": row} for row in rows],
            "links": links,
            "meta": {"count": len(rows)},
        }
    )


def _drive(
    script: Script,
    endpoint: str = "app_report",
    resume_state: TenjinResumeConfig | None = None,
    **inputs: Any,
) -> DriveResult:
    driver = SourceDriver(TenjinSource(), TenjinSourceConfig(api_key="test-key"))
    with mock.patch.object(tenjin, "_today", return_value=TODAY):
        return driver.run(endpoint, script, resume_state=resume_state, **inputs)


class TestResolveStartDate:
    def test_incremental_without_watermark_falls_back_to_full_history(self) -> None:
        assert resolve_start_date(True, None, TODAY) == TODAY - timedelta(days=MAX_HISTORY_DAYS)

    def test_unparseable_watermark_falls_back_to_full_history(self) -> None:
        assert resolve_start_date(True, "not-a-date", TODAY) == TODAY - timedelta(days=MAX_HISTORY_DAYS)


class TestRequestShaping:
    @parameterized.expand(
        [
            ("spend_report", "app_report", "2026-06-28", "2026-06-21"),
            ("ad_revenue_report", "ad_placement_report", "2026-06-28", "2026-06-21"),
            # Day-30 cohort metrics keep changing for 30 days after the install date.
            ("cohort_report", "campaign_cohort_report", "2026-06-28", "2026-05-22"),
            ("cohort_window_clamped_to_history", "campaign_cohort_report", "2024-07-01", "2024-06-30"),
        ]
    )
    def test_incremental_requests_only_the_watermark_range(
        self, _name: str, endpoint: str, watermark: str, expected_start: str
    ) -> None:
        result = _drive(
            [_report_page([{"date": watermark}])],
            endpoint=endpoint,
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        assert result.requests[0].param("start_date") == expected_start
        assert result.requests[0].param("end_date") == "2026-06-30"

    @parameterized.expand([(name,) for name in TENJIN_REPORTS])
    def test_every_report_is_requested_at_daily_granularity(self, endpoint: str) -> None:
        # Rows carry no `date` at totals-daily granularity, which would break the primary key,
        # the partition key, and the incremental cursor at once.
        result = _drive([_report_page([{"date": "2026-06-30"}])], endpoint=endpoint)

        assert result.requests[0].param("granularity") == "daily"
        assert result.requests[0].param("group_by") == TENJIN_REPORTS[endpoint].group_by
        assert result.requests[0].param("metrics") == TENJIN_REPORTS[endpoint].metrics


class TestToday:
    def test_default_end_date_is_the_current_utc_day(self) -> None:
        driver = SourceDriver(TenjinSource(), TenjinSourceConfig(api_key="test-key"))

        with time_machine.travel("2026-07-09T23:30:00Z", tick=False):
            result = driver.run("app_report", [_report_page([])])

        assert result.requests[0].param("end_date") == "2026-07-09"


class TestPaginationAndResume:
    def test_follows_next_link_then_terminates(self) -> None:
        next_url = f"{TENJIN_BASE_URL}/reports/spend?group_by=app&page=2&per_page=1000"
        result = _drive(
            [
                _report_page([{"date": "2026-06-29", "app_id": "a1"}], next_url=next_url),
                _report_page([{"date": "2026-06-30", "app_id": "a1"}]),
            ]
        )

        assert len(result.items) == 2
        assert len(result.requests) == 2
        assert result.requests[1].param("page") == "2"

    def test_resume_starts_at_the_saved_next_url(self) -> None:
        saved_url = f"{TENJIN_BASE_URL}/reports/spend?group_by=app&page=7&per_page=1000"

        result = _drive(
            [_report_page([{"date": "2026-06-30", "app_id": "a1"}])],
            resume_state=TenjinResumeConfig(next_url=saved_url),
        )

        assert len(result.requests) == 1
        assert result.requests[0].param("page") == "7"


class TestTenjinSourceResponse:
    def test_unknown_report_raises(self) -> None:
        result = _drive([], endpoint="nope")

        assert isinstance(result.raised, ValueError)

    @parameterized.expand([(name,) for name in TENJIN_REPORTS])
    def test_source_response_supports_incremental_sync(self, endpoint: str) -> None:
        result = _drive([_report_page([])], endpoint=endpoint)

        response = result.response
        assert response is not None
        # Tenjin documents no row order for report responses, so the watermark must only be
        # persisted at successful job end; asc mode would checkpoint a misleading per-batch max.
        assert response.sort_mode == "desc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["date"]
        assert not response.has_duplicate_primary_keys
        validate_incremental_sync(True, response)


class TestValidateCredentials:
    def _validate(self, answer: ScriptedResponse) -> bool:
        with scripted_network([answer]), mock.patch.object(tenjin, "_today", return_value=TODAY):
            return validate_credentials("token")

    def test_probe_is_one_day_and_one_row(self) -> None:
        with (
            scripted_network([ScriptedResponse(json={"data": []})]) as network,
            mock.patch.object(tenjin, "_today", return_value=TODAY),
        ):
            validate_credentials("token")

        request = network.requests_log[0]
        assert request.param("start_date") == request.param("end_date") == TODAY.isoformat()
        assert request.param("per_page") == "1"

    @parameterized.expand([(429,), (503,)])
    def test_throttle_and_5xx_are_retryable(self, status: int) -> None:
        with (
            scripted_network(always(ScriptedResponse(status=status, json={}))),
            mock.patch.object(tenjin, "_today", return_value=TODAY),
            pytest.raises(TenjinRetryableError),
        ):
            validate_credentials("token")

    @parameterized.expand(
        [
            # Verified against the live API: a missing/unrecognized token returns 401 with
            # {"error":"Unauthorized. Invalid access token provided."}; a token Tenjin can't
            # decode returns 403 with {"error":"AuthHandler::DecodeError"}.
            (401, {"error": "Unauthorized. Invalid access token provided."}),
            (403, {"error": "AuthHandler::DecodeError"}),
        ]
    )
    def test_rejections_are_credential_errors_naming_the_required_permission(
        self, status: int, body: dict[str, Any]
    ) -> None:
        with pytest.raises(TenjinCredentialsError) as exc:
            self._validate(ScriptedResponse(status=status, json=body))
        assert "Reporting Metrics API permission" in str(exc.value)

    def test_unexpected_status_does_not_blame_the_token(self) -> None:
        with pytest.raises(TenjinCredentialsError) as exc:
            self._validate(ScriptedResponse(status=418, json={}))
        assert "unexpected response (HTTP 418)" in str(exc.value)

    def test_transport_errors_propagate(self) -> None:
        with (
            scripted_network(always(ConnectionResetError("reset"))),
            mock.patch.object(tenjin, "_today", return_value=TODAY),
            pytest.raises(requests.ConnectionError),
        ):
            validate_credentials("token")

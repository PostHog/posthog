from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import time_machine

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lemlist import (
    LemlistSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lemlist.lemlist import (
    LEMLIST_API_VERSION_V1,
    LEMLIST_API_VERSION_V2,
    PAGE_SIZE,
    LemlistResumeConfig,
    _clamp_future_value_to_now,
    _format_incremental_value,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lemlist.source import LemlistSource


def _driver() -> SourceDriver:
    return SourceDriver(LemlistSource(), LemlistSourceConfig(api_key="key"))


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 5, 11, 2, 58, 14, tzinfo=UTC), "2026-05-11T02:58:14Z"),
            ("naive_datetime", datetime(2026, 5, 11, 2, 58, 14), "2026-05-11T02:58:14Z"),
            ("date_value", date(2026, 5, 11), "2026-05-11T00:00:00Z"),
            ("string_passthrough", "1715385600", "1715385600"),
        ]
    )
    def test_format_incremental_value(self, _name: str, value: object, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestClampFutureValueToNow:
    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_future_date_clamped(self) -> None:
        assert _clamp_future_value_to_now(date(2027, 2, 5)) == date(2026, 6, 15)

    def test_string_passthrough(self) -> None:
        assert _clamp_future_value_to_now("cursor") == "cursor"


class TestRequestParams:
    def test_campaigns_never_sends_mindate(self) -> None:
        # Campaigns has no server-side date filter, so even an incremental request must not add minDate.
        result = _driver().run(
            "campaigns",
            [ScriptedResponse(json=[{"_id": "cam_1"}])],
            incremental_field="createdAt",
            db_incremental_field_last_value=datetime(2026, 5, 11, tzinfo=UTC),
        )
        assert result.raised is None
        assert result.rows == [{"_id": "cam_1"}]
        assert result.requests[0].param("minDate") is None

    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_activities_first_sync_uses_lookback_window(self) -> None:
        # No stored watermark -> bound the first sync by the configured lookback instead of full history.
        result = _driver().run("activities", [ScriptedResponse(json=[{"_id": "act_1"}])], incremental_field="createdAt")
        assert result.raised is None
        assert result.rows == [{"_id": "act_1"}]
        assert result.requests[0].param("minDate") == "2025-06-15T12:00:00Z"


class TestVersionDispatch:
    @parameterized.expand(
        [
            # campaigns/activities only serve v2, so the param rides either pin (v1 pins byte-for-byte).
            ("campaigns_pin_v1", "campaigns", LEMLIST_API_VERSION_V1, [{"_id": "c"}], "v2"),
            ("campaigns_pin_v2", "campaigns", LEMLIST_API_VERSION_V2, [{"_id": "c"}], "v2"),
            # /team's v2 adds a users array, so version is sent only under a v2 pin.
            ("team_pin_v1", "team", LEMLIST_API_VERSION_V1, {"_id": "t"}, None),
            ("team_pin_v2", "team", LEMLIST_API_VERSION_V2, {"_id": "t"}, "v2"),
            # Endpoints with no version variant never send the param, whatever the pin.
            ("team_senders_pin_v2", "team_senders", LEMLIST_API_VERSION_V2, [{"userId": "u"}], None),
            ("unsubscribes_pin_v2", "unsubscribes", LEMLIST_API_VERSION_V2, [{"_id": "u"}], None),
        ]
    )
    def test_version_param_per_endpoint_and_pin(
        self, _name: str, endpoint: str, api_version: str, payload: Any, expected: str | None
    ) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=payload)], api_version=api_version)
        assert result.raised is None
        assert result.requests[0].param("version") == expected


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("not_found", 404, False)])
    def test_status_mapping(self, _name: str, status_code: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status_code, json={"_id": "team_1"})]) as network:
            assert validate_credentials("key") is expected
        assert [request.path for request in network.requests_log] == ["/api/team"]
        assert network.session_options[0]["redact_values"] == ("key",)


class TestPagination:
    @parameterized.expand(
        [
            ("bare_list", "campaigns", lambda rows: rows),
            ("campaigns_envelope", "campaigns", lambda rows: {"campaigns": rows, "pagination": {}}),
            ("data_envelope", "contacts", lambda rows: {"data": rows, "total": PAGE_SIZE + 1}),
        ]
    )
    def test_paginates_until_short_page(
        self, _name: str, endpoint: str, wrap: Callable[[list[dict[str, str]]], object]
    ) -> None:
        full_page = [{"_id": f"row_{i}"} for i in range(PAGE_SIZE)]
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json=wrap(full_page)), ScriptedResponse(json=wrap([{"_id": "row_last"}]))],
        )
        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE + 1
        assert result.rows[-1] == {"_id": "row_last"}
        assert result.params("offset") == ["0", str(PAGE_SIZE)]
        # State is saved once, after the first full page, pointing at the next offset.
        assert result.saved_states == [LemlistResumeConfig(offset=PAGE_SIZE)]

    def test_resume_starts_from_saved_offset(self) -> None:
        result = _driver().run(
            "campaigns",
            [ScriptedResponse(json=[{"_id": "cam_resumed"}])],
            resume_state=LemlistResumeConfig(offset=PAGE_SIZE),
        )
        assert result.raised is None
        assert result.rows == [{"_id": "cam_resumed"}]
        assert result.params("offset") == [str(PAGE_SIZE)]


class TestCampaignFanout:
    @parameterized.expand(
        [
            (
                "leads_export",
                "campaign_leads",
                [{"_id": "cam_1"}],
                [{"_id": "lea_1", "email": "a@example.com"}],
                "/v2/campaigns/cam_1/export/leads",
                {"state": "all", "format": "json"},
                [{"_id": "lea_1", "email": "a@example.com", "campaignId": "cam_1"}],
            ),
            (
                "reports_bound_by_query",
                "campaign_reports",
                [{"_id": "cam_1"}],
                [{"_id": "cam_1", "emailsSent": 3}],
                "/campaigns/reports",
                {"campaignIds": "cam_1"},
                [{"_id": "cam_1", "emailsSent": 3}],
            ),
            (
                "sequences_keyed_object",
                "campaign_sequences",
                [{"_id": "cam_1"}],
                {"seq_1": {"_id": "seq_1", "steps": []}, "seq_2": {"_id": "seq_2", "steps": [{"_id": "stp_1"}]}},
                "/campaigns/cam_1/sequences",
                {},
                [
                    {"_id": "seq_1", "steps": [], "campaignId": "cam_1"},
                    {"_id": "seq_2", "steps": [{"_id": "stp_1"}], "campaignId": "cam_1"},
                ],
            ),
            (
                "leads_export_campaigns_envelope",
                "campaign_leads",
                {"campaigns": [{"_id": "cam_1"}], "pagination": {}},
                [{"_id": "lea_1", "email": "a@example.com"}],
                "/v2/campaigns/cam_1/export/leads",
                {"state": "all", "format": "json"},
                [{"_id": "lea_1", "email": "a@example.com", "campaignId": "cam_1"}],
            ),
        ]
    )
    def test_child_rows_per_campaign(
        self,
        _name: str,
        endpoint: str,
        parent_payload: Any,
        child_payload: Any,
        child_path: str,
        child_params: dict[str, str],
        expected_rows: list[dict[str, Any]],
    ) -> None:
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json=parent_payload), ScriptedResponse(json=child_payload)],
        )
        assert result.raised is None
        assert result.rows == expected_rows
        assert result.queries[0] == {
            "version": ("v2",),
            "sortBy": ("createdAt",),
            "sortOrder": ("asc",),
            "offset": ("0",),
            "limit": (str(PAGE_SIZE),),
        }
        assert result.paths[1].endswith(child_path)
        assert result.queries[1] == {key: (value,) for key, value in child_params.items()}


class TestRetryClassification:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_status_is_retried_then_succeeds(self, _name: str, status_code: int) -> None:
        # A 429/5xx is retried by the client; a subsequent success completes the sync.
        result = _driver().run(
            "campaigns", [ScriptedResponse(status=status_code, json=[]), ScriptedResponse(json=[{"_id": "cam_1"}])]
        )
        assert result.raised is None
        assert result.rows == [{"_id": "cam_1"}]
        assert len(result.requests) == 2

    def test_client_error_raises_and_is_not_retried(self) -> None:
        # A 4xx (other than 429) is a permanent error surfaced via raise_for_status — no retry.
        result = _driver().run("campaigns", [ScriptedResponse(status=401, json={"error": "unauthorized"})])
        assert isinstance(result.raised, requests.HTTPError)
        assert len(result.requests) == 1

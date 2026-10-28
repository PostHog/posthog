from datetime import UTC, date, datetime
from typing import Any, Optional

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.savvycal import (
    SavvyCalSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.savvycal.savvycal import SavvyCalResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.savvycal.settings import (
    ENDPOINTS,
    SAVVYCAL_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.savvycal.source import SavvyCalSource


def _response(
    entries: Optional[list[dict[str, Any]]], after: Optional[str] = None, *, status: int = 200
) -> ScriptedResponse:
    """A SavvyCal list response: {"entries": [...], "metadata": {"after": ...}}."""
    payload = {"entries": entries or [], "metadata": {"after": after, "before": None, "limit": 100}}
    return ScriptedResponse(status=status, json=payload)


def _raw_response(body: Any, *, status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=body)


def _run(
    responses: Script,
    endpoint: str = "events",
    resume_state: SavvyCalResumeConfig | None = None,
    **inputs: Any,
) -> DriveResult:
    driver = SourceDriver(SavvyCalSource(), SavvyCalSourceConfig(api_key="pt_secret_key"))
    return driver.run(endpoint, responses, resume_state=resume_state, **inputs)


class TestEventFilters:
    @parameterized.expand(
        [
            ("datetime", datetime(2026, 3, 5, 14, 30, tzinfo=UTC), "2026-03-05"),
            ("date", date(2026, 3, 5), "2026-03-05"),
        ]
    )
    def test_events_incremental_maps_watermark_to_fixed_window(
        self, _name: str, watermark: Any, expected_from: str
    ) -> None:
        result = _run(
            [_response([], after=None)],
            incremental_field="start_at",
            db_incremental_field_last_value=watermark,
        )
        assert result.requests[0].param("period") == "fixed"
        assert result.requests[0].param("from") == expected_from

    def test_full_refresh_events_request_all_periods(self) -> None:
        result = _run([_response([], after=None)])

        assert result.requests[0].param("period") == "all"
        assert result.requests[0].param("from") is None

    def test_resume_reuses_saved_from_bound_over_new_watermark(self) -> None:
        # The saved cursor was minted under the original `from` bound; recomputing it from an
        # advanced watermark would pair the cursor with a different query.
        result = _run(
            [_response([{"id": "b"}], after="cur_3"), _response([], after=None)],
            resume_state=SavvyCalResumeConfig(after="cur_2", from_date="2026-01-01"),
            incremental_field="start_at",
            db_incremental_field_last_value=datetime(2026, 6, 1, tzinfo=UTC),
        )
        assert result.params("from") == ["2026-01-01", "2026-01-01"]
        assert result.params("after") == ["cur_2", "cur_3"]
        # The re-saved state carries the same original bound forward.
        assert result.saved_states[-1].from_date == "2026-01-01"

    def test_webhooks_secret_is_redacted(self) -> None:
        # The webhook signing secret must never reach the warehouse table.
        result = _run(
            [_response([{"id": "wbhk_1", "url": "https://x", "secret": "whsec_leak"}], after=None)],
            endpoint="webhooks",
        )
        assert result.rows == [{"id": "wbhk_1", "url": "https://x"}]


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_status_is_retried_and_recovers(self, _name: str, status: int) -> None:
        # A 429/5xx is retried by the client; a following good page completes the sync.
        result = _run([_response(None, status=status), _response([{"id": "a"}], after=None)])
        assert result.rows == [{"id": "a"}]
        assert len(result.requests) == 2

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("bad_request", 400)])
    def test_client_error_raises_and_does_not_retry(self, _name: str, status: int) -> None:
        result = _run([_response(None, status=status)])
        assert isinstance(result.raised, HTTPError)
        assert len(result.requests) == 1

    @parameterized.expand(
        [
            ("bare_list", [{"id": "a"}]),
            ("missing_entries", {"metadata": {"after": None}}),
            ("entries_not_a_list", {"entries": {"id": "a"}, "metadata": {"after": None}}),
        ]
    )
    def test_unexpected_200_payload_is_retried_and_recovers(self, _name: str, malformed_body: Any) -> None:
        # A 200 whose body isn't the {"entries": [...]} shape is treated as transient and retried.
        result = _run([_raw_response(malformed_body), _response([{"id": "a"}], after=None)])
        assert result.rows == [{"id": "a"}]
        assert len(result.requests) == 2


class TestSavvyCalSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        result = _run(always(_response([])), endpoint=endpoint)

        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in SAVVYCAL_ENDPOINTS.values())
        assert set(SAVVYCAL_ENDPOINTS) == set(ENDPOINTS)

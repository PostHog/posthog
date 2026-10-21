from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.plausible import (
    PlausibleSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.plausible import plausible as plausible_module
from products.warehouse_sources.backend.temporal.data_imports.sources.plausible.plausible import (
    PlausibleResumeConfig,
    normalize_host,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.plausible.settings import (
    PLAUSIBLE_ENDPOINTS,
    REPORT_LOOKBACK_DAYS,
    SESSION_SCOPED_DIMENSIONS,
    PlausibleEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.plausible.source import PlausibleSource


def _result(dimensions: list[Any], metrics: list[Any]) -> dict[str, Any]:
    return {"dimensions": dimensions, "metrics": metrics}


def _page(results: list[dict[str, Any]], total_rows: int | None = None) -> ScriptedResponse:
    return ScriptedResponse(
        json={"results": results, "meta": {"total_rows": len(results) if total_rows is None else total_rows}}
    )


def _run(script: Script, *, endpoint: str = "timeseries", **inputs: Any) -> DriveResult:
    driver = SourceDriver(
        PlausibleSource(), PlausibleSourceConfig(api_key="key", site_id="example.com", host="https://plausible.io")
    )
    return driver.run(endpoint, script, **inputs)


class TestNormalizeHost:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("https://plausible.io", "https://plausible.io"),
            ("plausible.example.com", "https://plausible.example.com"),
            ("https://analytics.example.com/", "https://analytics.example.com"),
            ("http://analytics.internal:8080", "http://analytics.internal:8080"),
        ],
    )
    def test_valid_hosts(self, value, expected):
        assert normalize_host(value) == expected

    @pytest.mark.parametrize("value", ["", "   ", "ftp://example.com", "https://"])
    def test_invalid_hosts_raise(self, value):
        with pytest.raises(ValueError):
            normalize_host(value)


class TestValidateCredentials:
    def test_valid_credentials(self):
        with scripted_network([ScriptedResponse(status=200, json={})]) as network:
            ok, error = validate_credentials("https://plausible.io", "example.com", "key")

        assert ok is True
        assert error is None
        request = network.requests_log[0]
        body = request.json()
        assert body["site_id"] == "example.com"
        assert body["metrics"] == ["visitors"]
        assert request.headers["authorization"] == "Bearer key"

    @pytest.mark.parametrize(
        "status_code, fragment",
        [
            (404, "site"),
            (400, "status 400"),
        ],
    )
    def test_failure_status_codes(self, status_code, fragment):
        with scripted_network([ScriptedResponse(status=status_code, json={})]):
            ok, error = validate_credentials("https://plausible.io", "example.com", "bad")

        assert ok is False
        assert error is not None and fragment in error

    def test_unreachable_host(self):
        with scripted_network(always(ConnectionError("dns failure"))):
            ok, error = validate_credentials("https://bad.example", "example.com", "key")

        assert ok is False
        assert error is not None and "reach" in error


class TestGetRows:
    def test_paginates_until_short_page_and_saves_state(self):
        # Shrink the page size so two small pages exercise the offset pagination loop.
        with mock.patch.object(plausible_module, "DEFAULT_PAGE_LIMIT", 2):
            result = _run(
                [
                    _page(
                        [_result(["2024-01-01"], [1, 1, 1, 0, 0, 1]), _result(["2024-01-02"], [2, 2, 2, 0, 0, 2])],
                        total_rows=3,
                    ),
                    _page([_result(["2024-01-03"], [3, 3, 3, 0, 0, 3])], total_rows=3),
                ]
            )

        assert [len(item) for item in result.items] == [2, 1]
        # The second request advances the offset past the first page.
        assert result.requests[1].json()["pagination"]["offset"] == 2
        # State is saved once, after the first page, pointing at the next offset.
        assert [state.offset for state in result.saved_states] == [2]

    def test_incremental_watermark_slides_window_back_by_lookback(self):
        result = _run(
            [_page([], total_rows=0)],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-06-01",
        )

        expected_start = (datetime(2024, 6, 1, tzinfo=UTC).date() - timedelta(days=REPORT_LOOKBACK_DAYS)).isoformat()
        assert result.requests[0].json()["date_range"][0] == expected_start

    def test_resume_state_pins_offset_and_window(self):
        result = _run(
            [_page([], total_rows=0)],
            resume_state=PlausibleResumeConfig(offset=4, date_range_start="2024-01-01", date_range_end="2024-01-31"),
        )

        body = result.requests[0].json()
        assert body["pagination"]["offset"] == 4
        assert body["date_range"] == ["2024-01-01", "2024-01-31"]

    def test_http_error_raises(self):
        result = _run([ScriptedResponse(status=400, json={"error": "bad query"})])

        assert result.raised is not None
        assert "400" in str(result.raised)


# Pinned rather than derived from the scope constants, so tampering with those fails here.
_SESSION_METRICS = ["visitors", "visits", "bounce_rate", "visit_duration"]
_SESSION_SCOPED_ENDPOINT_METRICS = {"entry_pages": _SESSION_METRICS, "exit_pages": _SESSION_METRICS}


class TestEndpointMetricScopes:
    def test_every_session_scoped_endpoint_is_covered(self):
        # Forces a deliberate edit here when an endpoint is added on a session-scoped dimension,
        # instead of the endpoint quietly dropping out of the parametrize list above.
        covered = {
            name
            for name, config in PLAUSIBLE_ENDPOINTS.items()
            if SESSION_SCOPED_DIMENSIONS.intersection(config.breakdown_dimensions)
        }
        assert covered == set(_SESSION_SCOPED_ENDPOINT_METRICS)

    def test_endpoint_left_with_no_session_metrics_is_rejected(self):
        with pytest.raises(ValueError, match="no session-scoped metrics"):
            PlausibleEndpointConfig(
                name="bad", breakdown_dimensions=["visit:exit_page"], metrics=["pageviews", "events"]
            )

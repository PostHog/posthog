from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.triggerdev import (
    TriggerDevSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trigger_dev import trigger_dev
from products.warehouse_sources.backend.temporal.data_imports.sources.trigger_dev.source import TriggerDevSource
from products.warehouse_sources.backend.temporal.data_imports.sources.trigger_dev.trigger_dev import (
    _format_incremental_value,
    _should_stop_desc,
    resolve_base_url,
    validate_base_url,
    validate_credentials,
)

BASE_URL = "https://api.trigger.dev"


def _run(endpoint: str, script: Script, **kwargs: Any) -> DriveResult:
    driver = SourceDriver(TriggerDevSource(), TriggerDevSourceConfig(api_key="tr_prod_x"))
    return driver.run(endpoint, script, **kwargs)


def _json(body: Any) -> ScriptedResponse:
    return ScriptedResponse(json=body)


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("string_passthrough", "run_1234", "run_1234"),
        ]
    )
    def test_format(self, _name: str, value: object, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestResolveBaseUrl:
    @parameterized.expand(
        [
            ("blank", None, "https://api.trigger.dev"),
            ("empty", "", "https://api.trigger.dev"),
            ("trailing_slash", "https://trigger.acme.internal/", "https://trigger.acme.internal"),
            ("custom", "https://trigger.acme.dev", "https://trigger.acme.dev"),
        ]
    )
    def test_resolve(self, _name: str, given: str | None, expected: str) -> None:
        assert resolve_base_url(given) == expected


class TestValidateBaseUrl:
    @parameterized.expand(
        [
            ("default", "https://api.trigger.dev"),
            ("self_hosted_https", "https://trigger.acme.dev"),
        ]
    )
    def test_https_urls_pass(self, _name: str, base_url: str) -> None:
        assert validate_base_url(base_url) is None

    @parameterized.expand(
        [
            # Plaintext would send the secret bearer token in the clear.
            ("http", "http://trigger.acme.dev"),
            # `urlsplit` reads the host as example.com, but requests connects to 169.254.169.254.
            ("backslash_authority_confusion", "https://169.254.169.254\\@example.com"),
        ]
    )
    def test_unsafe_urls_are_rejected(self, _name: str, base_url: str) -> None:
        assert validate_base_url(base_url) is not None


class TestShouldStopDesc:
    def test_no_cutoff_never_stops(self) -> None:
        # First sync has no watermark; stopping early here would truncate the initial backfill.
        items = [{"createdAt": "2020-01-01T00:00:00Z"}]
        assert _should_stop_desc(items, "createdAt", None) is False


class TestRunsCursorPagination:
    def test_incremental_filters_first_page_then_stops_at_watermark(self) -> None:
        # The createdAt filter is only sent on page one; later cursor pages must stop client-side once
        # a page predates the watermark, or every incremental sync re-walks all history.
        responses = [
            _json(
                {
                    "data": [
                        {"id": "r3", "createdAt": "2026-01-12T00:00:00Z"},
                        {"id": "r2", "createdAt": "2026-01-11T00:00:00Z"},
                    ],
                    "pagination": {"next": "r2"},
                }
            ),
            _json(
                {
                    "data": [{"id": "r1", "createdAt": "2026-01-02T00:00:00Z"}],
                    "pagination": {"next": "r0"},
                }
            ),
            # Never fetched: the walk stops after the page containing r1 (older than the cutoff).
            _json({"data": [{"id": "should_not_fetch"}], "pagination": {"next": None}}),
        ]
        result = _run(
            "runs",
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 10, tzinfo=UTC),
        )
        assert [r["id"] for r in result.rows] == ["r3", "r2", "r1"]
        assert len(result.requests) == 2
        assert result.requests[0].param("filter[createdAt][from]") is not None
        assert not any(name.startswith("filter") for name in result.requests[1].query)

    def test_checkpoints_current_page_cursor_after_yield(self) -> None:
        # Resume must re-fetch the last yielded page (checkpoint the CURRENT cursor, not the next one)
        # so a crash can't skip rows; merge dedupes the re-pulled page.
        responses = [
            _json({"data": [{"id": "r3"}], "pagination": {"next": "r2"}}),
            _json({"data": [{"id": "r1"}], "pagination": {"next": None}}),
        ]
        result = _run("runs", responses)
        assert [s.after for s in result.saved_states] == [None, "r2"]


class TestClassicPagination:
    def test_walks_pages_until_total_and_never_checkpoints(self) -> None:
        # schedules/queues are small full-refresh tables: walk page/perPage to the last page and never
        # save resume state (a restart just re-reads from page one).
        responses = [
            _json({"data": [{"id": "sched_1"}], "pagination": {"currentPage": 1, "totalPages": 2, "count": 2}}),
            _json({"data": [{"id": "sched_2"}], "pagination": {"currentPage": 2, "totalPages": 2, "count": 2}}),
        ]
        result = _run("schedules", responses)
        assert [r["id"] for r in result.rows] == ["sched_1", "sched_2"]
        assert result.params("page") == ["1", "2"]
        assert result.saved_states == []

    def test_stops_on_empty_page(self) -> None:
        result = _run("queues", [_json({"data": [], "pagination": {"currentPage": 1, "totalPages": 5, "count": 0}})])
        assert result.rows == []
        assert len(result.requests) == 1

    def test_bails_out_of_a_never_ending_pager(self) -> None:
        # A page endpoint that keeps returning non-empty data with no totalPages must not loop forever.
        with patch.object(trigger_dev, "MAX_CLASSIC_PAGES", 7):
            result = _run("queues", always(_json({"data": [{"id": "q"}], "pagination": {}})))
        assert len(result.requests) == 7


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            ("forbidden", 403, False),
            ("server_error", 500, False),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))):
            valid, error = validate_credentials("tr_prod_x", BASE_URL)
        assert valid is expected_valid
        assert (error is None) is expected_valid

    def test_network_error_is_invalid_not_raised(self) -> None:
        with scripted_network(always(requests.ConnectionError("boom"))):
            valid, error = validate_credentials("tr_prod_x", BASE_URL)
        assert valid is False
        assert error is not None


class TestFetchPageRetries:
    @parameterized.expand(
        [
            ("rate_limited", 429),
            ("server_error", 503),
        ]
    )
    def test_retryable_status_is_retried(self, _name: str, status_code: int) -> None:
        bad = MagicMock()
        bad.status_code = status_code
        good = MagicMock()
        good.status_code = 200
        good.ok = True
        good.json.return_value = {"data": []}
        session = MagicMock()
        session.get.side_effect = [bad, good]

        with patch.object(trigger_dev._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = trigger_dev._fetch_page(session, f"{BASE_URL}/api/v1/runs", {}, MagicMock())

        assert result == {"data": []}
        assert session.get.call_count == 2

    def test_unauthorized_raises_and_is_not_retried(self) -> None:
        response = MagicMock()
        response.status_code = 401
        response.ok = False
        response.raise_for_status.side_effect = requests.HTTPError("401 Client Error: Unauthorized", response=response)
        session = MagicMock()
        session.get.return_value = response

        with pytest.raises(requests.HTTPError):
            trigger_dev._fetch_page(session, f"{BASE_URL}/api/v1/runs", {}, MagicMock())
        assert session.get.call_count == 1


class TestSourceResponseSortMode:
    @parameterized.expand([("runs", "desc"), ("schedules", "asc"), ("queues", "asc")])
    def test_sort_mode_matches_arrival_order(self, endpoint: str, expected: str) -> None:
        # Runs arrive newest-first; declaring asc there would corrupt the incremental watermark.
        response = _run(endpoint, []).response
        assert response is not None
        assert response.sort_mode == expected

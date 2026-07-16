from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.runpod import runpod
from products.warehouse_sources.backend.temporal.data_imports.sources.runpod.runpod import (
    RunPodResumeConfig,
    _row_id,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.runpod.source import RunPodSource


class _FakeResumableManager:
    def __init__(self, state: RunPodResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[RunPodResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> RunPodResumeConfig | None:
        return self._state

    def save_state(self, data: RunPodResumeConfig) -> None:
        self.saved.append(data)


def _collect(
    manager: _FakeResumableManager, responses: list[list[dict]], endpoint: str, **kw: Any
) -> tuple[list[dict], list[dict[str, list[str]]]]:
    """Run get_rows with a stubbed HTTP layer; returns (rows, parsed query params per request)."""
    calls: list[dict[str, list[str]]] = []

    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> list[dict]:
        calls.append(parse_qs(urlparse(url).query))
        return responses[len(calls) - 1] if len(calls) <= len(responses) else []

    rows: list[dict] = []
    with (
        patch.object(runpod, "_fetch_list", fake_fetch),
        patch.object(runpod, "make_tracked_session", MagicMock()),
    ):
        for batch in get_rows(
            api_key="rpa_test",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            **kw,
        ):
            rows.extend(batch)
    return rows, calls


class TestRowId:
    def test_id_is_stable_across_amount_changes(self) -> None:
        # The surrogate key depends only on the bucket start and grouping dims, never the amounts —
        # otherwise a restated bucket would get a new id and merge would insert a duplicate.
        a = _row_id("2025-08-01T00:00:00Z", "pod_1", None, None)
        b = _row_id("2025-08-01T00:00:00Z", "pod_1", None, None)
        assert a == b
        assert a != _row_id("2025-08-01T00:00:00Z", "pod_2", None, None)

    def test_none_and_empty_string_distinguished_positionally(self) -> None:
        assert _row_id(None, "x") != _row_id("", "x")
        assert _row_id(None, "x") != _row_id("x", None)


@freeze_time("2022-05-15T12:00:00Z")
class TestBillingWindows:
    def test_full_refresh_walks_windows_from_launch_date(self) -> None:
        responses = [
            [
                {"time": "2022-02-01T00:00:00Z", "podId": "p1", "amount": 2.0},
                {"time": "2022-01-01T00:00:00Z", "podId": "p1", "amount": 1.0},
            ],
            [{"time": "2022-04-15T00:00:00Z", "podId": "p1", "amount": 3.0}],
        ]
        manager = _FakeResumableManager()
        rows, calls = _collect(manager, responses, "billing_pods")

        # 2022-01-01 + 90 days = 2022-04-01; the second window reaches past "now" so endTime is
        # omitted to include the open bucket, and the walk terminates.
        assert len(calls) == 2
        assert calls[0]["startTime"] == ["2022-01-01T00:00:00Z"]
        assert calls[0]["endTime"] == ["2022-04-01T00:00:00Z"]
        assert calls[1]["startTime"] == ["2022-04-01T00:00:00Z"]
        assert "endTime" not in calls[1]
        assert calls[0]["bucketSize"] == ["day"]

        # Rows within a window are sorted ascending on the bucket start (sort_mode="asc" contract).
        assert [r["time"] for r in rows] == [
            "2022-01-01T00:00:00Z",
            "2022-02-01T00:00:00Z",
            "2022-04-15T00:00:00Z",
        ]
        assert all(r["id"] for r in rows)

        # State is saved after each non-final window so a crash resumes without skipping data.
        assert [s.window_start for s in manager.saved] == ["2022-04-01T00:00:00Z"]

    def test_resumes_from_saved_window_start(self) -> None:
        manager = _FakeResumableManager(RunPodResumeConfig(window_start="2022-04-01T00:00:00Z"))
        _, calls = _collect(manager, [[]], "billing_pods")
        assert len(calls) == 1
        assert calls[0]["startTime"] == ["2022-04-01T00:00:00Z"]

    def test_incremental_watermark_is_floored_to_day_bucket_boundary(self) -> None:
        # A mid-bucket startTime could re-bucket the overlap under shifted `time` values that merge
        # can't dedupe, so the watermark must be aligned to UTC midnight.
        _, calls = _collect(
            _FakeResumableManager(),
            [[]],
            "billing_pods",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2022, 5, 14, 9, 30, tzinfo=UTC),
        )
        assert calls[0]["startTime"] == ["2022-05-14T00:00:00Z"]

    def test_future_watermark_clamped_to_today(self) -> None:
        # A future-dated watermark must not skip syncing entirely; it re-pulls today's open bucket.
        _, calls = _collect(
            _FakeResumableManager(),
            [[]],
            "billing_pods",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2030, 1, 1, tzinfo=UTC),
        )
        assert len(calls) == 1
        assert calls[0]["startTime"] == ["2022-05-15T00:00:00Z"]

    @parameterized.expand(
        [
            ("billing_pods", "podId"),
            ("billing_endpoints", "endpointId"),
            ("billing_network_volumes", None),
        ]
    )
    def test_grouping_param_per_endpoint(self, endpoint: str, grouping: str | None) -> None:
        _, calls = _collect(_FakeResumableManager(), [[]], endpoint)
        if grouping is None:
            assert "grouping" not in calls[0]
        else:
            assert calls[0]["grouping"] == [grouping]


class TestInventoryEndpoints:
    def test_single_unpaginated_request_yields_items_as_is(self) -> None:
        responses = [[{"id": "pod_1", "name": "worker"}, {"id": "pod_2", "name": "trainer"}]]
        rows, calls = _collect(_FakeResumableManager(), responses, "pods")
        assert len(calls) == 1
        assert "startTime" not in calls[0]
        assert [r["id"] for r in rows] == ["pod_1", "pod_2"]

    def test_empty_account_yields_no_batches(self) -> None:
        rows, _ = _collect(_FakeResumableManager(), [[]], "templates")
        assert rows == []


class TestFetchList:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_statuses_exhaust_retry_budget(self, _name: str, status: int) -> None:
        response = MagicMock(status_code=status, ok=False)
        session = MagicMock()
        session.get.return_value = response
        with patch.object(runpod._fetch_list.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(runpod.RunPodRetryableError):
                runpod._fetch_list(session, "https://rest.runpod.io/v1/pods", {}, MagicMock())
        assert session.get.call_count == 5

    def test_client_error_raises_for_status_without_retry(self) -> None:
        response = MagicMock(status_code=401, ok=False, text="unauthorized")
        response.raise_for_status.side_effect = requests.HTTPError("401 Client Error", response=response)
        session = MagicMock()
        session.get.return_value = response
        with pytest.raises(requests.HTTPError):
            runpod._fetch_list(session, "https://rest.runpod.io/v1/pods", {}, MagicMock())
        assert session.get.call_count == 1

    def test_non_list_response_raises(self) -> None:
        response = MagicMock(status_code=200, ok=True)
        response.json.return_value = {"error": "unexpected"}
        session = MagicMock()
        session.get.return_value = response
        with pytest.raises(ValueError):
            runpod._fetch_list(session, "https://rest.runpod.io/v1/pods", {}, MagicMock())


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("forbidden_scope", 403, True), ("unauthorized", 401, False)])
    def test_status_mapping(self, _name: str, status: int, expected: bool) -> None:
        # 403 is accepted at create time (real key restricted to other endpoints); 401 means a bad key.
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=status)
        with patch.object(runpod, "make_tracked_session", return_value=session):
            assert validate_credentials("rpa_test") is expected

    def test_network_error_is_invalid(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(runpod, "make_tracked_session", return_value=session):
            assert validate_credentials("rpa_test") is False


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://rest.runpod.io/v1/billing/pods", True),
            ("forbidden", "403 Client Error: Forbidden for url: https://rest.runpod.io/v1/pods", True),
            ("read_timeout", "HTTPSConnectionPool(host='rest.runpod.io', port=443): Read timed out.", False),
            ("server_error", "500 Server Error: Internal Server Error for url: https://rest.runpod.io/v1/pods", False),
        ]
    )
    def test_only_credential_errors_are_non_retryable(self, _name: str, observed_error: str, expected: bool) -> None:
        non_retryable = RunPodSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable) is expected

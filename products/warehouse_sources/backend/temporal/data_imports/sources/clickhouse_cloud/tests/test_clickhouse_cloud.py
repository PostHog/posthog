from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.clickhouse_cloud import clickhouse_cloud
from products.warehouse_sources.backend.temporal.data_imports.sources.clickhouse_cloud.clickhouse_cloud import (
    ClickhouseCloudResumeConfig,
    _coerce_date,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clickhouse_cloud.source import (
    ClickhouseCloudSource,
)

ORG = {"id": "org-1", "createdAt": "2026-05-01T10:00:00Z", "name": "Acme"}


class _FakeResumableManager:
    def __init__(self, state: ClickhouseCloudResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[ClickhouseCloudResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> ClickhouseCloudResumeConfig | None:
        return self._state

    def save_state(self, data: ClickhouseCloudResumeConfig) -> None:
        self.saved.append(data)


def _collect(
    monkeypatch: Any,
    handler: Any,
    endpoint: str,
    manager: _FakeResumableManager | None = None,
    **kw: Any,
) -> tuple[list[dict], list[str]]:
    calls: list[str] = []

    def fake_fetch(session: Any, url: str, logger: Any) -> dict:
        calls.append(url)
        return handler(url)

    monkeypatch.setattr(clickhouse_cloud, "_fetch", fake_fetch)
    monkeypatch.setattr(clickhouse_cloud, "make_tracked_session", lambda **_: MagicMock())

    rows: list[dict] = []
    for batch in get_rows(
        key_id="test-key-id",
        key_secret="test-key-secret",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager or _FakeResumableManager(),  # type: ignore[arg-type]
        **kw,
    ):
        rows.extend(batch)
    return rows, calls


def _usage_cost_handler(records_by_from_date: dict[str, list[dict]] | None = None) -> Any:
    def handler(url: str) -> dict:
        if url.endswith("/v1/organizations"):
            return {"result": [ORG]}
        params = parse_qs(urlparse(url).query)
        from_date = params["from_date"][0]
        records = (records_by_from_date or {}).get(from_date, [])
        return {"result": {"grandTotalCHC": 0, "costs": records}}

    return handler


def _window_params(calls: list[str]) -> list[tuple[date, date]]:
    windows = []
    for url in calls:
        if "usageCost" not in url:
            continue
        params = parse_qs(urlparse(url).query)
        windows.append((date.fromisoformat(params["from_date"][0]), date.fromisoformat(params["to_date"][0])))
    return windows


@freeze_time("2026-07-15")
class TestUsageCostWindowing:
    def test_full_refresh_windows_are_contiguous_and_capped_at_31_days(self, monkeypatch: Any) -> None:
        # A window longer than 31 days is rejected by the API with a 400, and overlapping windows
        # would yield duplicate rows within a single sync (merge only dedupes across syncs).
        _, calls = _collect(monkeypatch, _usage_cost_handler(), "usage_cost")
        windows = _window_params(calls)

        assert windows[0][0] == date(2026, 5, 1)  # starts at the org's createdAt
        assert windows[-1][1] == date(2026, 7, 15)  # walks all the way to today
        for from_date, to_date in windows:
            assert (to_date - from_date).days <= 30  # to_date is inclusive => at most 31 days
        for previous, current in zip(windows, windows[1:]):
            assert (current[0] - previous[1]).days == 1  # contiguous, no overlap, no gap

    def test_incremental_starts_from_watermark(self, monkeypatch: Any) -> None:
        _, calls = _collect(
            monkeypatch,
            _usage_cost_handler(),
            "usage_cost",
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 7, 1),
        )
        windows = _window_params(calls)
        assert windows == [(date(2026, 7, 1), date(2026, 7, 15))]

    def test_future_watermark_is_clamped_to_today(self, monkeypatch: Any) -> None:
        # A future-dated watermark would make from_date > to_date and 400 on every sync.
        _, calls = _collect(
            monkeypatch,
            _usage_cost_handler(),
            "usage_cost",
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 8, 1),
        )
        windows = _window_params(calls)
        assert windows == [(date(2026, 7, 15), date(2026, 7, 15))]

    def test_resume_state_used_and_saved_only_after_yield(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(ClickhouseCloudResumeConfig(organization_id="org-1", from_date="2026-06-20"))
        _, calls = _collect(monkeypatch, _usage_cost_handler(), "usage_cost", manager=manager)
        windows = _window_params(calls)

        assert windows[0][0] == date(2026, 6, 20)  # resumed from the bookmark, not createdAt
        # One bookmark per completed non-final window, each pointing at the next window start —
        # a crash re-pulls the last yielded window rather than skipping ahead.
        assert len(manager.saved) == len(windows) - 1
        for saved, (_, window_end), (next_start, _) in zip(manager.saved, windows, windows[1:]):
            assert saved.organization_id == "org-1"
            assert saved.from_date == next_start.isoformat()
            assert next_start == window_end + timedelta(days=1)

    def test_rows_flatten_metrics_and_stamp_organization_id(self, monkeypatch: Any) -> None:
        records = [
            {
                "date": "2026-07-02",
                "entityType": "service",
                "entityId": "svc-1",
                "metrics": {"computeCHC": 1.5, "storageCHC": 0.25},
                "totalCHC": 1.75,
            },
            {"date": "2026-07-01", "entityType": "datawarehouse", "entityId": "dw-1", "totalCHC": 0.5},
        ]
        rows, _ = _collect(
            monkeypatch,
            _usage_cost_handler({"2026-07-01": records}),
            "usage_cost",
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 7, 1),
        )
        # Sorted ascending by date so the pipeline's per-batch watermark stays correct.
        assert [r["date"] for r in rows] == ["2026-07-01", "2026-07-02"]
        service_row = rows[1]
        assert service_row["computeCHC"] == 1.5
        assert service_row["storageCHC"] == 0.25
        assert "metrics" not in service_row
        assert all(r["organizationId"] == "org-1" for r in rows)


class TestActivities:
    def test_incremental_passes_from_date_and_sorts_ascending(self, monkeypatch: Any) -> None:
        activities = [
            {"id": "a-2", "createdAt": "2026-07-02T00:00:00Z", "organizationId": "org-1"},
            {"id": "a-1", "createdAt": "2026-07-01T00:00:00Z", "organizationId": "org-1"},
        ]

        def handler(url: str) -> dict:
            if url.endswith("/v1/organizations"):
                return {"result": [ORG]}
            return {"result": activities}

        rows, calls = _collect(
            monkeypatch,
            handler,
            "activities",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 30, tzinfo=UTC),
        )
        assert "from_date=2026-06-30T00%3A00%3A00Z" in calls[1]
        assert [r["id"] for r in rows] == ["a-1", "a-2"]

    def test_full_refresh_omits_from_date(self, monkeypatch: Any) -> None:
        def handler(url: str) -> dict:
            if url.endswith("/v1/organizations"):
                return {"result": [ORG]}
            return {"result": []}

        _, calls = _collect(monkeypatch, handler, "activities")
        assert "from_date" not in calls[1]


class TestEntityRows:
    def test_organizations_endpoint_yields_org_rows(self, monkeypatch: Any) -> None:
        rows, calls = _collect(monkeypatch, lambda url: {"result": [ORG]}, "organizations")
        assert rows == [ORG]
        assert len(calls) == 1

    @parameterized.expand([("services", "/services"), ("api_keys", "/keys"), ("members", "/members")])
    def test_org_id_stamped_onto_child_rows(self, endpoint: str, path_suffix: str) -> None:
        # The composite primary keys ([organizationId, ...]) require every row to carry the parent
        # organization; the API omits it from these list responses.
        def handler(url: str) -> dict:
            if url.endswith("/v1/organizations"):
                return {"result": [ORG]}
            assert url.endswith(path_suffix)
            return {"result": [{"id": "child-1", "userId": "user-1"}]}

        with patch.object(clickhouse_cloud, "make_tracked_session", return_value=MagicMock()):
            with patch.object(clickhouse_cloud, "_fetch", side_effect=lambda _session, url, _logger: handler(url)):
                rows: list[dict] = []
                for batch in get_rows("k", "s", endpoint, MagicMock(), _FakeResumableManager()):  # type: ignore[arg-type]
                    rows.extend(batch)
        assert rows[0]["organizationId"] == "org-1"


class TestBackupsFanOut:
    def test_one_request_per_service_with_ids_stamped(self, monkeypatch: Any) -> None:
        def handler(url: str) -> dict:
            if url.endswith("/v1/organizations"):
                return {"result": [ORG]}
            if url.endswith("/services"):
                return {"result": [{"id": "svc-1"}, {"id": "svc-2"}]}
            if url.endswith("/services/svc-1/backups"):
                return {"result": [{"id": "b-1", "status": "done"}]}
            if url.endswith("/services/svc-2/backups"):
                return {"result": [{"id": "b-2", "status": "done"}]}
            raise AssertionError(f"unexpected url: {url}")

        rows, calls = _collect(monkeypatch, handler, "backups")
        assert [(r["organizationId"], r["serviceId"], r["id"]) for r in rows] == [
            ("org-1", "svc-1", "b-1"),
            ("org-1", "svc-2", "b-2"),
        ]
        assert sum("backups" in url for url in calls) == 2


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("forbidden_scope", 403, True), ("unauthorized", 401, False)])
    def test_status_mapping(self, _name: str, status: int, expected: bool) -> None:
        # 403 is accepted at create time (real key, unprobed scope); 401 means a bad key ID/secret.
        response = MagicMock(status_code=status)
        session = MagicMock()
        session.get.return_value = response
        with patch.object(clickhouse_cloud, "make_tracked_session", return_value=session):
            assert validate_credentials("key-id", "key-secret") is expected

    def test_network_error_is_invalid(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(clickhouse_cloud, "make_tracked_session", return_value=session):
            assert validate_credentials("key-id", "key-secret") is False


class TestFetch:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_statuses_exhaust_retry_budget(self, _name: str, status: int) -> None:
        response = MagicMock(status_code=status, ok=False, headers={})
        session = MagicMock()
        session.get.return_value = response
        with patch.object(clickhouse_cloud._fetch.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(clickhouse_cloud.ClickhouseCloudRetryableError):
                clickhouse_cloud._fetch(session, "https://api.clickhouse.cloud/v1/organizations", MagicMock())
        assert session.get.call_count == 5

    def test_client_error_raises_for_status_without_retry(self) -> None:
        response = MagicMock(status_code=401, ok=False, text="unauthorized")
        response.raise_for_status.side_effect = requests.HTTPError("401 Client Error", response=response)
        session = MagicMock()
        session.get.return_value = response
        with pytest.raises(requests.HTTPError):
            clickhouse_cloud._fetch(session, "https://api.clickhouse.cloud/v1/organizations", MagicMock())
        assert session.get.call_count == 1

    def test_429_honors_retry_after_header(self) -> None:
        # The API allows 10 requests per 10s, so 429s are routine — honoring the server's window
        # beats blind backoff; the cap stops a pathological header from wedging the worker.
        response = MagicMock(status_code=429, ok=False, headers={"retry-after": "7"})
        session = MagicMock()
        session.get.return_value = response
        with patch.object(clickhouse_cloud._fetch.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(clickhouse_cloud.ClickhouseCloudRetryableError) as exc_info:
                clickhouse_cloud._fetch(session, "https://api.clickhouse.cloud/v1/organizations", MagicMock())
        assert exc_info.value.retry_after == 7.0


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.clickhouse.cloud/v1/organizations"),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://api.clickhouse.cloud/v1/organizations/org-1/usageCost?from_date=2026-07-01&to_date=2026-07-15",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = ClickhouseCloudSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='api.clickhouse.cloud', port=443): Read timed out."),
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://api.clickhouse.cloud/v1/organizations",
            ),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = ClickhouseCloudSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)


class TestCoerceDate:
    @parameterized.expand(
        [
            ("date", date(2026, 7, 1), date(2026, 7, 1)),
            ("datetime", datetime(2026, 7, 1, 12, 30, tzinfo=UTC), date(2026, 7, 1)),
            ("iso_date_string", "2026-07-01", date(2026, 7, 1)),
            ("iso_datetime_z_string", "2026-07-01T10:00:00Z", date(2026, 7, 1)),
            ("garbage_string", "not-a-date", None),
            ("empty_string", "", None),
            ("none", None, None),
        ]
    )
    def test_coercion(self, _name: str, value: Any, expected: date | None) -> None:
        assert _coerce_date(value) == expected

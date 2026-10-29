from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
import time_machine
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.clickhouse_cloud import clickhouse_cloud
from products.warehouse_sources.backend.temporal.data_imports.sources.clickhouse_cloud.clickhouse_cloud import (
    ClickhouseCloudResumeConfig,
    _coerce_date,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clickhouse_cloud.source import (
    ClickhouseCloudSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clickhousecloud import (
    ClickhouseCloudSourceConfig,
)

ORG = {"id": "org-1", "createdAt": "2026-05-01T10:00:00Z", "name": "Acme"}


def _driver() -> SourceDriver:
    return SourceDriver(
        ClickhouseCloudSource(), ClickhouseCloudSourceConfig(key_id="test-key-id", key_secret="test-key-secret")
    )


def _usage_cost_handler(
    records_by_from_date: dict[str, list[dict[str, Any]]] | None = None,
) -> Callable[[RecordedRequest], ScriptedResponse]:
    def handler(request: RecordedRequest) -> ScriptedResponse:
        if request.path == "/v1/organizations":
            return ScriptedResponse(json={"result": [ORG]})
        assert request.path == "/v1/organizations/org-1/usageCost"
        records = (records_by_from_date or {}).get(request.param("from_date") or "", [])
        return ScriptedResponse(json={"result": {"grandTotalCHC": 0, "costs": records}})

    return handler


def _window_params(requests_log: list[RecordedRequest]) -> list[tuple[date, date]]:
    windows: list[tuple[date, date]] = []
    for request in requests_log:
        if "usageCost" not in request.path:
            continue
        from_date = request.param("from_date")
        to_date = request.param("to_date")
        assert from_date is not None and to_date is not None
        windows.append((date.fromisoformat(from_date), date.fromisoformat(to_date)))
    return windows


class TestUsageCostWindowing:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        with time_machine.travel("2026-07-15", tick=False):
            yield

    def test_full_refresh_windows_are_contiguous_and_capped_at_31_days(self) -> None:
        # A window longer than 31 days is rejected by the API with a 400, and overlapping windows
        # would yield duplicate rows within a single sync (merge only dedupes across syncs).
        result = _driver().run("usage_cost", _usage_cost_handler())
        assert result.raised is None
        windows = _window_params(result.requests)

        assert windows[0][0] == date(2026, 5, 1)  # starts at the org's createdAt
        assert windows[-1][1] == date(2026, 7, 15)  # walks all the way to today
        for from_date, to_date in windows:
            assert (to_date - from_date).days <= 30  # to_date is inclusive => at most 31 days
        for previous, current in zip(windows, windows[1:]):
            assert (current[0] - previous[1]).days == 1  # contiguous, no overlap, no gap

    def test_resume_state_used_and_saved_only_after_yield(self) -> None:
        result = _driver().run(
            "usage_cost",
            _usage_cost_handler(),
            resume_state=ClickhouseCloudResumeConfig(organization_id="org-1", from_date="2026-06-20"),
        )
        assert result.raised is None
        windows = _window_params(result.requests)

        assert windows[0][0] == date(2026, 6, 20)  # resumed from the bookmark, not createdAt
        # One bookmark per completed non-final window, each pointing at the next window start —
        # a crash re-pulls the last yielded window rather than skipping ahead.
        assert len(result.saved_states) == len(windows) - 1
        for saved, (_, window_end), (next_start, _) in zip(result.saved_states, windows, windows[1:]):
            assert saved.organization_id == "org-1"
            assert saved.from_date == next_start.isoformat()
            assert next_start == window_end + timedelta(days=1)

    def test_rows_flatten_metrics_and_stamp_organization_id(self) -> None:
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
        result = _driver().run(
            "usage_cost",
            _usage_cost_handler({"2026-07-01": records}),
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 7, 1),
        )
        assert result.raised is None
        rows = result.rows
        # Sorted ascending by date so the pipeline's per-batch watermark stays correct.
        assert [r["date"] for r in rows] == ["2026-07-01", "2026-07-02"]
        service_row = rows[1]
        assert service_row["computeCHC"] == 1.5
        assert service_row["storageCHC"] == 0.25
        assert "metrics" not in service_row
        assert all(r["organizationId"] == "org-1" for r in rows)


class TestActivities:
    def test_incremental_passes_from_date_and_sorts_ascending(self) -> None:
        activities = [
            {"id": "a-2", "createdAt": "2026-07-02T00:00:00Z", "organizationId": "org-1"},
            {"id": "a-1", "createdAt": "2026-07-01T00:00:00Z", "organizationId": "org-1"},
        ]

        result = _driver().run(
            "activities",
            [ScriptedResponse(json={"result": [ORG]}), ScriptedResponse(json={"result": activities})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 30, tzinfo=UTC),
        )
        assert result.raised is None
        assert result.requests[1].param("from_date") == "2026-06-30T00:00:00.000Z"
        assert [r["id"] for r in result.rows] == ["a-1", "a-2"]


class TestEntityRows:
    def test_organizations_endpoint_yields_org_rows(self) -> None:
        result = _driver().run("organizations", [ScriptedResponse(json={"result": [ORG]})])
        assert result.raised is None
        assert result.rows == [ORG]
        assert result.paths == ["/v1/organizations"]

    @parameterized.expand([("services", "/services"), ("api_keys", "/keys"), ("members", "/members")])
    def test_org_id_stamped_onto_child_rows(self, endpoint: str, path_suffix: str) -> None:
        # The composite primary keys ([organizationId, ...]) require every row to carry the parent
        # organization; the API omits it from these list responses.
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(json={"result": [ORG]}),
                ScriptedResponse(json={"result": [{"id": "child-1", "userId": "user-1"}]}),
            ],
        )
        assert result.raised is None
        assert result.paths[1].endswith(path_suffix)
        assert result.rows[0]["organizationId"] == "org-1"


class TestBackupsFanOut:
    def test_one_request_per_service_with_ids_stamped(self) -> None:
        result = _driver().run(
            "backups",
            [
                ScriptedResponse(json={"result": [ORG]}),
                ScriptedResponse(json={"result": [{"id": "svc-1"}, {"id": "svc-2"}]}),
                ScriptedResponse(json={"result": [{"id": "b-1", "status": "done"}]}),
                ScriptedResponse(json={"result": [{"id": "b-2", "status": "done"}]}),
            ],
        )
        assert result.raised is None
        assert [(r["organizationId"], r["serviceId"], r["id"]) for r in result.rows] == [
            ("org-1", "svc-1", "b-1"),
            ("org-1", "svc-2", "b-2"),
        ]
        assert sum("backups" in path for path in result.paths) == 2


class TestValidateCredentials:
    @parameterized.expand([("forbidden_scope", 403, True)])
    def test_status_mapping(self, _name: str, status: int, expected: bool) -> None:
        # 403 is accepted at create time (real key, unprobed scope); 401 means a bad key ID/secret.
        with scripted_network([ScriptedResponse(status=status)]) as network:
            assert validate_credentials("key-id", "key-secret") is expected
        assert [request.path for request in network.requests_log] == ["/v1/organizations"]

    def test_network_error_is_invalid(self) -> None:
        with scripted_network(always(requests.ConnectionError("boom"))) as network:
            assert validate_credentials("key-id", "key-secret") is False
        assert {request.path for request in network.requests_log} == {"/v1/organizations"}


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

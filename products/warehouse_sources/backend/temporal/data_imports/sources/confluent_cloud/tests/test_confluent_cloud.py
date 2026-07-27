from datetime import UTC, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.confluent_cloud import confluent_cloud
from products.warehouse_sources.backend.temporal.data_imports.sources.confluent_cloud.confluent_cloud import (
    ConfluentCloudResumeConfig,
    MissingResourceIdsError,
    _build_query_body,
    _normalize_point,
    _sync_range,
    get_rows,
    parse_resource_ids,
)

_NOW = datetime(2026, 7, 15, 12, 0, 0, tzinfo=UTC)


class TestParseResourceIds:
    @parameterized.expand(
        [
            ("comma_separated", "lkc-1, lkc-2", ["lkc-1", "lkc-2"]),
            ("whitespace_separated", "lkc-1 lkc-2", ["lkc-1", "lkc-2"]),
            ("mixed_and_padded", " lkc-1 ,, lkc-2  lkc-3 ", ["lkc-1", "lkc-2", "lkc-3"]),
            ("dedupes_preserving_order", "lkc-2, lkc-1, lkc-2", ["lkc-2", "lkc-1"]),
            ("empty_string", "", []),
            ("none", None, []),
        ]
    )
    def test_parse(self, _name: str, raw: str | None, expected: list[str]) -> None:
        assert parse_resource_ids(raw) == expected


class TestSyncRange:
    @parameterized.expand(
        [
            # No watermark: backfill the full ~7-day retention window.
            ("first_sync", False, None, datetime(2026, 7, 8, 12, 0, tzinfo=UTC)),
            (
                "full_refresh_ignores_watermark",
                False,
                datetime(2026, 7, 14, tzinfo=UTC),
                datetime(2026, 7, 8, 12, 0, tzinfo=UTC),
            ),
            # Watermark minus the 2h restatement overlap.
            ("incremental", True, datetime(2026, 7, 14, 12, 0, tzinfo=UTC), datetime(2026, 7, 14, 10, 0, tzinfo=UTC)),
            # A future-dated watermark is clamped to now before the overlap is applied.
            (
                "future_watermark_clamped",
                True,
                datetime(2027, 1, 1, tzinfo=UTC),
                datetime(2026, 7, 15, 10, 0, tzinfo=UTC),
            ),
            # A stale watermark can't reach past the API's retention floor.
            (
                "stale_watermark_floored",
                True,
                datetime(2026, 6, 1, tzinfo=UTC),
                datetime(2026, 7, 8, 12, 0, tzinfo=UTC),
            ),
            # String watermarks (as persisted) parse too.
            ("string_watermark", True, "2026-07-14T12:00:00Z", datetime(2026, 7, 14, 10, 0, tzinfo=UTC)),
        ]
    )
    def test_range(self, _name: str, incremental: bool, watermark: Any, expected_start: datetime) -> None:
        start, end = _sync_range(incremental, watermark, _NOW)
        assert start == expected_start
        assert end == _NOW


class TestBuildQueryBody:
    def test_single_id_uses_field_filter(self) -> None:
        body = _build_query_body(
            "io.confluent.kafka.server/received_bytes",
            "resource.kafka.id",
            ["lkc-1"],
            "2026-07-14T00:00:00Z/2026-07-15T00:00:00Z",
        )
        assert body == {
            "aggregations": [{"metric": "io.confluent.kafka.server/received_bytes"}],
            "filter": {"field": "resource.kafka.id", "op": "EQ", "value": "lkc-1"},
            "granularity": "PT1H",
            "group_by": ["resource.kafka.id"],
            "intervals": ["2026-07-14T00:00:00Z/2026-07-15T00:00:00Z"],
            "limit": 1000,
            "format": "FLAT",
        }

    def test_multiple_ids_use_or_filter(self) -> None:
        body = _build_query_body(
            "io.confluent.kafka.server/received_bytes",
            "resource.kafka.id",
            ["lkc-1", "lkc-2"],
            "2026-07-14T00:00:00Z/2026-07-15T00:00:00Z",
        )
        assert body["filter"] == {
            "op": "OR",
            "filters": [
                {"field": "resource.kafka.id", "op": "EQ", "value": "lkc-1"},
                {"field": "resource.kafka.id", "op": "EQ", "value": "lkc-2"},
            ],
        }


class TestNormalizePoint:
    def test_resource_label_becomes_resource_id(self) -> None:
        point = {"timestamp": "2026-07-14T00:00:00Z", "value": 42.5, "resource.kafka.id": "lkc-1"}
        assert _normalize_point(point, "io.confluent.kafka.server/received_bytes", "resource.kafka.id") == {
            "metric": "io.confluent.kafka.server/received_bytes",
            "resource_id": "lkc-1",
            "timestamp": "2026-07-14T00:00:00Z",
            "value": 42.5,
        }


class _FakeResumableManager:
    def __init__(self, state: ConfluentCloudResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[ConfluentCloudResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> ConfluentCloudResumeConfig | None:
        return self._state

    def save_state(self, data: ConfluentCloudResumeConfig) -> None:
        self.saved.append(data)


class _FakeApi:
    """Routes `_fetch_json` calls: serves a metric-descriptor catalog and records queries."""

    def __init__(
        self,
        metric_descriptors: list[dict] | None = None,
        query_pages: list[dict] | None = None,
        descriptor_pages: list[dict] | None = None,
    ) -> None:
        self.metric_descriptors = metric_descriptors or []
        # Consumed one per query request; the last one repeats if queries outnumber pages.
        self.query_pages = query_pages or [{"data": []}]
        self.descriptor_pages = descriptor_pages or []
        self.queries: list[dict] = []  # {"body": ..., "params": ...} per POST

    def __call__(
        self,
        session: Any,
        method: str,
        url: str,
        logger: Any,
        json_body: dict | None = None,
        params: dict | None = None,
    ) -> dict:
        if method == "POST":
            self.queries.append({"body": json_body, "params": params})
            index = min(len(self.queries) - 1, len(self.query_pages) - 1)
            return self.query_pages[index]
        if "descriptors/metrics" in url and params and "resource_type" in params:
            return {"data": self.metric_descriptors, "meta": {"pagination": {}}}
        # Plain descriptor listing (metric_descriptors / resource_descriptors tables).
        token = (params or {}).get("page_token")
        page_index = 0 if token is None else int(token)
        page = self.descriptor_pages[page_index]
        return page


def _collect(monkeypatch: Any, api: _FakeApi, manager: _FakeResumableManager, **kwargs: Any) -> list[dict]:
    monkeypatch.setattr(confluent_cloud, "_fetch_json", api)
    rows: list[dict] = []
    for batch in get_rows(
        api_key="key",
        api_secret="secret",
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **kwargs,
    ):
        rows.extend(batch)
    return rows


_GA_METRIC = {"name": "io.confluent.kafka.server/received_bytes", "lifecycle_stage": "GENERAL_AVAILABILITY"}
_DEPRECATED_METRIC = {"name": "io.confluent.kafka.server/old_metric", "lifecycle_stage": "DEPRECATED"}


class TestDescriptorRows:
    def test_paginates_descriptor_pages_with_page_token(self, monkeypatch: Any) -> None:
        api = _FakeApi(
            descriptor_pages=[
                {"data": [{"name": "m1"}], "meta": {"pagination": {"next_page_token": "1"}}},
                {"data": [{"name": "m2"}], "meta": {"pagination": {}}},
            ]
        )
        rows = _collect(monkeypatch, api, _FakeResumableManager(), endpoint="metric_descriptors", resource_ids=[])

        assert [r["name"] for r in rows] == ["m1", "m2"]


class TestMetricsRows:
    def test_raises_when_no_resource_ids_configured(self, monkeypatch: Any) -> None:
        api = _FakeApi()
        with pytest.raises(MissingResourceIdsError):
            _collect(monkeypatch, api, _FakeResumableManager(), endpoint="kafka_metrics", resource_ids=[])

    @freeze_time(_NOW)
    def test_windows_metrics_and_rows(self, monkeypatch: Any) -> None:
        api = _FakeApi(
            metric_descriptors=[_GA_METRIC, _DEPRECATED_METRIC],
            query_pages=[{"data": [{"timestamp": "2026-07-14T10:00:00Z", "value": 1.0, "resource.kafka.id": "lkc-1"}]}],
        )
        rows = _collect(
            monkeypatch,
            api,
            _FakeResumableManager(),
            endpoint="kafka_metrics",
            resource_ids=["lkc-1"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 7, 14, 12, 0, tzinfo=UTC),
        )

        # Watermark 14T12:00 minus 2h overlap = 14T10:00, walked in day windows to now (15T12:00):
        # [14T10:00 → 15T10:00] then [15T10:00 → 15T12:00], one query per window for the one
        # non-deprecated metric.
        intervals = [q["body"]["intervals"] for q in api.queries]
        assert intervals == [
            ["2026-07-14T10:00:00Z/2026-07-15T10:00:00Z"],
            ["2026-07-15T10:00:00Z/2026-07-15T12:00:00Z"],
        ]
        for query in api.queries:
            assert query["body"]["aggregations"] == [{"metric": "io.confluent.kafka.server/received_bytes"}]

        assert rows[0] == {
            "metric": "io.confluent.kafka.server/received_bytes",
            "resource_id": "lkc-1",
            "timestamp": "2026-07-14T10:00:00Z",
            "value": 1.0,
        }

    @freeze_time(_NOW)
    def test_saves_state_after_each_completed_window_except_last(self, monkeypatch: Any) -> None:
        api = _FakeApi(metric_descriptors=[_GA_METRIC])
        manager = _FakeResumableManager()
        _collect(
            monkeypatch,
            api,
            manager,
            endpoint="kafka_metrics",
            resource_ids=["lkc-1"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 7, 14, 12, 0, tzinfo=UTC),
        )

        assert manager.saved == [ConfluentCloudResumeConfig(window_start="2026-07-15T10:00:00Z")]

    @freeze_time(_NOW)
    def test_resumes_from_saved_window(self, monkeypatch: Any) -> None:
        api = _FakeApi(metric_descriptors=[_GA_METRIC])
        manager = _FakeResumableManager(ConfluentCloudResumeConfig(window_start="2026-07-15T10:00:00Z"))
        _collect(
            monkeypatch,
            api,
            manager,
            endpoint="kafka_metrics",
            resource_ids=["lkc-1"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 7, 14, 12, 0, tzinfo=UTC),
        )

        intervals = [q["body"]["intervals"] for q in api.queries]
        assert intervals == [["2026-07-15T10:00:00Z/2026-07-15T12:00:00Z"]]

    @freeze_time(_NOW)
    def test_query_pagination_reposts_identical_body_with_page_token(self, monkeypatch: Any) -> None:
        api = _FakeApi(
            metric_descriptors=[_GA_METRIC],
            query_pages=[
                {
                    "data": [{"timestamp": "2026-07-15T10:00:00Z", "value": 1.0, "resource.kafka.id": "lkc-1"}],
                    "meta": {"pagination": {"next_page_token": "tok-1"}},
                },
                {"data": [{"timestamp": "2026-07-15T11:00:00Z", "value": 2.0, "resource.kafka.id": "lkc-2"}]},
            ],
        )
        rows = _collect(
            monkeypatch,
            api,
            _FakeResumableManager(),
            endpoint="kafka_metrics",
            resource_ids=["lkc-1", "lkc-2"],
            should_use_incremental_field=True,
            # One 2h window (after the overlap), so both queries belong to the same request body.
            db_incremental_field_last_value=datetime(2026, 7, 15, 12, 0, tzinfo=UTC),
        )

        assert len(api.queries) == 2
        assert api.queries[0]["params"] is None
        assert api.queries[1]["params"] == {"page_token": "tok-1"}
        assert api.queries[0]["body"] == api.queries[1]["body"]
        assert [r["value"] for r in rows] == [1.0, 2.0]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", 200, (True, 200)),
            ("bad_key", 401, (False, 401)),
            ("unauthorized_resource", 403, (False, 403)),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected: tuple[bool, int | None]) -> None:
        session = MagicMock()
        session.post.return_value.status_code = status_code
        with (
            freeze_time(_NOW),
            pytest.MonkeyPatch.context() as mp,
        ):
            mp.setattr(confluent_cloud, "_make_session", lambda *a, **k: session)
            result = confluent_cloud.validate_credentials(
                "key", "secret", "io.confluent.kafka.server/received_bytes", "resource.kafka.id", "lkc-1"
            )
        assert result == expected

        body = session.post.call_args.kwargs["json"]
        assert body["intervals"] == ["2026-07-15T11:00:00Z/2026-07-15T12:00:00Z"]
        assert body["filter"] == {"field": "resource.kafka.id", "op": "EQ", "value": "lkc-1"}

    def test_transport_error_returns_none_status(self) -> None:
        session = MagicMock()
        session.post.side_effect = ConnectionError("boom")
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(confluent_cloud, "_make_session", lambda *a, **k: session)
            assert confluent_cloud.validate_credentials(
                "key", "secret", "io.confluent.kafka.server/received_bytes", "resource.kafka.id", "lkc-1"
            ) == (False, None)

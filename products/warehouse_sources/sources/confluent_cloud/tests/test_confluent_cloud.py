from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urlencode

import pytest
import time_machine
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.sources.confluent_cloud import confluent_cloud
from products.warehouse_sources.sources.confluent_cloud.confluent_cloud import (
    ConfluentCloudResumeConfig,
    MissingResourceIdsError,
    _costs_range,
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
        window = _sync_range(incremental, watermark, _NOW)
        assert window.start == expected_start
        assert window.end == _NOW


class TestCostsRange:
    @parameterized.expand(
        [
            ("first_sync", False, None, date(2025, 7, 16)),
            ("full_refresh_ignores_watermark", False, date(2026, 7, 1), date(2025, 7, 16)),
            ("incremental_minus_overlap", True, date(2026, 7, 10), date(2026, 7, 7)),
            ("string_watermark", True, "2026-07-10", date(2026, 7, 7)),
            ("future_watermark_clamped", True, date(2027, 1, 1), date(2026, 7, 12)),
            ("stale_watermark_floored", True, date(2024, 1, 1), date(2025, 7, 16)),
        ]
    )
    def test_range(self, _name: str, incremental: bool, watermark: Any, expected_start: date) -> None:
        window = _costs_range(incremental, watermark, _NOW.date())
        assert window.start == expected_start
        assert window.end == _NOW.date()


class _FakeResumableManager:
    def __init__(self, state: ConfluentCloudResumeConfig | None = None, events: list[Any] | None = None) -> None:
        self._state = state
        self.saved: list[ConfluentCloudResumeConfig] = []
        self.events = events if events is not None else []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> ConfluentCloudResumeConfig | None:
        return self._state

    def save_state(self, data: ConfluentCloudResumeConfig) -> None:
        self.saved.append(data)
        self.events.append(("save", data.window_start))

    def safe_point(self) -> None:
        self.events.append(("safe_point",))


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

    @time_machine.travel(_NOW, tick=False)
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

    @time_machine.travel(_NOW, tick=False)
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


class _FakeCloudApi:
    """Serves Cloud API list pages keyed by (path, filters); `metadata.next` carries only a page_token."""

    def __init__(self, pages: dict[tuple[str, tuple[tuple[str, str], ...]], list[list[dict]]]) -> None:
        self.pages = pages
        self.requests: list[tuple[str, dict]] = []

    def __call__(
        self,
        session: Any,
        method: str,
        url: str,
        logger: Any,
        json_body: dict | None = None,
        params: dict | None = None,
    ) -> dict:
        assert method == "GET"
        self.requests.append((url, dict(params or {})))
        params = dict(params or {})
        token = params.pop("page_token", None)
        params.pop("page_size", None)
        path = url.removeprefix("https://api.confluent.cloud/")
        pages = self.pages.get((path, tuple(sorted(params.items()))), [[]])
        index = int(token) if token else 0
        has_next = index + 1 < len(pages)
        next_url = f"https://api.confluent.cloud/{path}?{urlencode({'page_token': index + 1})}" if has_next else None
        return {"data": pages[index], "metadata": {"next": next_url}}


def _collect_batches(monkeypatch: Any, api: Any, manager: _FakeResumableManager, **kwargs: Any) -> list[list[dict]]:
    monkeypatch.setattr(confluent_cloud, "_fetch_json", api)
    batches: list[list[dict]] = []
    for batch in get_rows(
        api_key="key",
        api_secret="secret",
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        resource_ids=[],
        **kwargs,
    ):
        batches.append(batch)
        manager.events.append(("rows", [row["id"] for row in batch]))
    return batches


class TestCloudApiRows:
    def test_environments_follow_next_page_token_to_the_last_page(self, monkeypatch: Any) -> None:
        api = _FakeCloudApi({("org/v2/environments", ()): [[{"id": "env-1"}, {"id": "env-2"}], [{"id": "env-3"}]]})

        batches = _collect_batches(monkeypatch, api, _FakeResumableManager(), endpoint="environments")

        assert [row["id"] for batch in batches for row in batch] == ["env-1", "env-2", "env-3"]
        assert [params for _, params in api.requests] == [{"page_size": 100}, {"page_size": 100, "page_token": "1"}]

    def test_kafka_clusters_fan_out_over_every_environment(self, monkeypatch: Any) -> None:
        api = _FakeCloudApi(
            {
                ("org/v2/environments", ()): [[{"id": "env-1"}, {"id": "env-empty"}], [{"id": "env-2"}]],
                ("cmk/v2/clusters", (("environment", "env-1"),)): [[{"id": "lkc-1"}], [{"id": "lkc-2"}]],
                ("cmk/v2/clusters", (("environment", "env-2"),)): [[{"id": "lkc-3"}]],
            }
        )
        manager = _FakeResumableManager()

        batches = _collect_batches(monkeypatch, api, manager, endpoint="kafka_clusters")

        assert [(row["environment_id"], row["id"]) for batch in batches for row in batch] == [
            ("env-1", "lkc-1"),
            ("env-1", "lkc-2"),
            ("env-2", "lkc-3"),
        ]
        # The second clusters page keeps its environment filter next to the page token.
        assert (
            "https://api.confluent.cloud/cmk/v2/clusters",
            {
                "environment": "env-1",
                "page_size": 100,
                "page_token": "1",
            },
        ) in api.requests
        # An environment with no clusters still gives the pipeline a safe point.
        assert manager.events[2] == ("safe_point",)

    @time_machine.travel(_NOW, tick=False)
    def test_costs_walk_month_bounded_windows_and_stage_state_before_the_last_page(self, monkeypatch: Any) -> None:
        api = _FakeCloudApi(
            {
                ("billing/v1/costs", (("end_date", "2026-07-15"), ("start_date", "2026-06-17"))): [
                    [{"id": "c-1"}],
                    [{"id": "c-2"}],
                ],
            }
        )
        manager = _FakeResumableManager()

        _collect_batches(
            monkeypatch,
            api,
            manager,
            endpoint="costs",
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 5, 23),
        )

        # Watermark 2026-05-23 minus the 3-day overlap = 2026-05-20, walked in 28-day windows to today.
        windows = [
            (params["start_date"], params["end_date"]) for _, params in api.requests if "page_token" not in params
        ]
        assert windows == [("2026-05-20", "2026-06-17"), ("2026-06-17", "2026-07-15")]
        assert manager.events == [
            ("save", "2026-06-17"),
            ("safe_point",),
            ("rows", ["c-1"]),
            ("rows", ["c-2"]),
        ]

    @time_machine.travel(_NOW, tick=False)
    def test_costs_resume_from_saved_window(self, monkeypatch: Any) -> None:
        api = _FakeCloudApi({})
        manager = _FakeResumableManager(ConfluentCloudResumeConfig(window_start="2026-07-01"))

        _collect_batches(monkeypatch, api, manager, endpoint="costs")

        assert [(params["start_date"], params["end_date"]) for _, params in api.requests] == [
            ("2026-07-01", "2026-07-15")
        ]


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
            time_machine.travel(_NOW, tick=False),
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

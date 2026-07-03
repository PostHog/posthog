import json
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.sources.chargedesk import chargedesk
from products.warehouse_sources.backend.temporal.data_imports.sources.chargedesk.chargedesk import (
    ChargedeskResumeConfig,
    _iter_pages,
    _run_pass,
    chargedesk_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.chargedesk.settings import (
    CHARGEDESK_ENDPOINTS,
    ChargedeskEndpointConfig,
)


def _cfg(**overrides: Any) -> ChargedeskEndpointConfig:
    base: dict[str, Any] = {
        "name": "charges",
        "path": "/charges",
        "primary_keys": ["charge_id"],
        "timestamp_field": "occurred",
        "filter_param": "occurred",
        "max_offset": 50000,
        "page_size": 2,
    }
    base.update(overrides)
    return ChargedeskEndpointConfig(**base)


class _FakeResponse:
    def __init__(self, payload: dict, status: int = 200):
        self._payload = payload
        self.status_code = status
        self.ok = 200 <= status < 300
        self.text = json.dumps(payload)

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if not self.ok:
            response = requests.Response()
            response.status_code = self.status_code
            raise requests.HTTPError(f"{self.status_code} Client Error", response=response)


class _PagedSession:
    """Fake session that slices a fixed (newest-first) dataset by offset, honoring [min]/[max] filters."""

    def __init__(self, rows: list[dict], filter_param: str = "occurred", ts_field: str = "occurred"):
        self.rows = rows
        self.filter_param = filter_param
        self.ts_field = ts_field
        self.calls: list[dict] = []

    def get(self, url: str, auth: Any = None, params: dict | None = None, timeout: Any = None) -> _FakeResponse:
        params = params or {}
        self.calls.append(params)
        mn = params.get(f"{self.filter_param}[min]")
        mx = params.get(f"{self.filter_param}[max]")
        selected = [
            r for r in self.rows if (mn is None or r[self.ts_field] >= mn) and (mx is None or r[self.ts_field] <= mx)
        ]
        offset = params["offset"]
        count = params["count"]
        page = selected[offset : offset + count]
        return _FakeResponse({"count": count, "offset": offset, "data": page})


class _FakeManager:
    def __init__(self, state: ChargedeskResumeConfig | None = None):
        self._state = state
        self.saved: list[ChargedeskResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> ChargedeskResumeConfig | None:
        return self._state

    def save_state(self, state: ChargedeskResumeConfig) -> None:
        self.saved.append(state)


def _charges(ids_and_ts: list[tuple[str, int]]) -> list[dict]:
    # Newest first, matching ChargeDesk's default list ordering.
    return [{"charge_id": cid, "occurred": ts} for cid, ts in ids_and_ts]


class TestIterPages:
    def test_single_short_page_is_terminal(self) -> None:
        session = _PagedSession(_charges([("a", 30), ("b", 20)]))
        cfg = _cfg(page_size=5)
        results = list(
            _iter_pages(session, ("k", ""), cfg, MagicMock(), min_value=None, start_offset=0, start_window_max=None)  # type: ignore[arg-type]
        )

        assert len(results) == 1
        items, resume_state = results[0]
        assert [r["charge_id"] for r in items] == ["a", "b"]
        assert resume_state is None  # short page -> no next page

    def test_multi_page_offsets_and_termination(self) -> None:
        session = _PagedSession(_charges([("a", 50), ("b", 40), ("c", 30), ("d", 20), ("e", 10)]))
        cfg = _cfg(page_size=2)
        results = list(
            _iter_pages(session, ("k", ""), cfg, MagicMock(), min_value=None, start_offset=0, start_window_max=None)  # type: ignore[arg-type]
        )

        # 5 rows / page_size 2 => full pages [a,b],[c,d] then terminal short page [e]
        all_ids = [r["charge_id"] for items, _ in results for r in items]
        assert all_ids == ["a", "b", "c", "d", "e"]
        # offsets requested are 0, 2, 4
        assert [c["offset"] for c in session.calls] == [0, 2, 4]
        assert results[-1][1] is None  # last page terminal
        assert results[0][1] == (2, None)  # resume from offset 2 next

    def test_window_shift_at_offset_cap(self) -> None:
        # max_offset=2 forces a window shift after the first full page (offset would step to 2; 2+2 > 2).
        session = _PagedSession(_charges([("a", 50), ("b", 40), ("c", 30), ("d", 20)]))
        cfg = _cfg(page_size=2, max_offset=2)
        results = list(
            _iter_pages(session, ("k", ""), cfg, MagicMock(), min_value=None, start_offset=0, start_window_max=None)  # type: ignore[arg-type]
        )

        # First page [a,b]; cap hit -> shift occurred[max] to oldest seen (40), reset offset 0.
        first_items, first_resume = results[0]
        assert [r["charge_id"] for r in first_items] == ["a", "b"]
        assert first_resume == (0, 40)
        # Subsequent calls carry occurred[max]=40 and start at offset 0.
        shifted_calls = [c for c in session.calls if c.get("occurred[max]") == 40]
        assert shifted_calls and shifted_calls[0]["offset"] == 0
        # Every row is still surfaced (boundary row b re-fetched, deduped downstream on primary key).
        all_ids = [r["charge_id"] for items, _ in results for r in items]
        assert set(all_ids) == {"a", "b", "c", "d"}

    def test_stops_when_offset_cap_window_collapses_to_one_timestamp(self) -> None:
        # More rows than the offset cap can reach all share the same timestamp. Re-pinning [max] to that
        # timestamp would re-fetch the same page forever; pagination must terminate instead of spinning.
        session = _PagedSession(_charges([("a", 100), ("b", 100), ("c", 100), ("d", 100)]))
        cfg = _cfg(page_size=2, max_offset=2)
        results = list(
            _iter_pages(session, ("k", ""), cfg, MagicMock(), min_value=None, start_offset=0, start_window_max=None)  # type: ignore[arg-type]
        )

        # Terminates (the final page carries no resume state) rather than looping indefinitely.
        assert results[-1][1] is None
        # It shifted [max] to 100 exactly once, then stopped on the next identical-timestamp page.
        assert sum(1 for c in session.calls if c.get("occurred[max]") == 100) >= 1

    def test_min_filter_passed_through(self) -> None:
        session = _PagedSession(_charges([("a", 50), ("b", 40), ("c", 30)]))
        cfg = _cfg(page_size=5)
        list(_iter_pages(session, ("k", ""), cfg, MagicMock(), min_value=35, start_offset=0, start_window_max=None))  # type: ignore[arg-type]
        assert session.calls[0]["occurred[min]"] == 35

    def test_filter_param_differs_from_timestamp_field(self) -> None:
        # Subscriptions filter on `created` but the row timestamp column is `first_seen`.
        rows = [{"subscription_id": "s1", "first_seen": 100}, {"subscription_id": "s2", "first_seen": 50}]
        session = _PagedSession(rows, filter_param="created", ts_field="first_seen")
        cfg = _cfg(
            name="subscriptions",
            path="/subscriptions",
            primary_keys=["subscription_id"],
            timestamp_field="first_seen",
            filter_param="created",
            page_size=5,
        )
        list(_iter_pages(session, ("k", ""), cfg, MagicMock(), min_value=60, start_offset=0, start_window_max=None))  # type: ignore[arg-type]
        assert session.calls[0]["created[min]"] == 60


class TestRunPass:
    def test_saves_state_after_yielding_each_batch(self) -> None:
        session = _PagedSession(_charges([("a", 50), ("b", 40), ("c", 30), ("d", 20), ("e", 10)]))
        cfg = _cfg(page_size=2)
        manager = _FakeManager()
        batcher = Batcher(logger=MagicMock(), chunk_size=2, chunk_size_bytes=10**9)

        tables = list(
            _run_pass(
                session,  # type: ignore[arg-type]
                ("k", ""),
                cfg,
                MagicMock(),
                batcher,
                manager,  # type: ignore[arg-type]
                phase="full",
                min_value=None,
                start_offset=0,
                start_window_max=None,
            )
        )

        # chunk_size=2 -> a batch yields after each 2-row page that has a following page.
        assert len(tables) >= 1
        assert manager.saved  # state persisted after yielding
        # Saved offsets advance and stay tagged with the current phase.
        assert all(s.phase == "full" for s in manager.saved)
        assert manager.saved[0].offset == 2


class TestGetRows:
    def _collect(self, gen: Any) -> list[dict]:
        return [row for table in gen for row in table.to_pylist()]

    def test_full_scan_when_not_incremental(self) -> None:
        session = _PagedSession(_charges([("a", 50), ("b", 40), ("c", 30)]))
        manager = _FakeManager()
        with patch.object(chargedesk, "make_tracked_session", return_value=session):
            rows = self._collect(
                get_rows("k", "charges", MagicMock(), manager, should_use_incremental_field=False)  # type: ignore[arg-type]
            )
        assert {r["charge_id"] for r in rows} == {"a", "b", "c"}
        # No incremental filters on a full scan.
        assert all("occurred[min]" not in c for c in session.calls)

    def test_latest_pass_uses_min_filter(self) -> None:
        session = _PagedSession(_charges([("a", 50), ("b", 40)]))
        manager = _FakeManager()
        with patch.object(chargedesk, "make_tracked_session", return_value=session):
            self._collect(
                get_rows(
                    "k",
                    "charges",
                    MagicMock(),
                    manager,  # type: ignore[arg-type]
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=45,
                    db_incremental_field_earliest_value=None,
                )
            )
        assert session.calls[0]["occurred[min]"] == 45

    def test_earliest_pass_then_latest_pass(self) -> None:
        session = _PagedSession(_charges([("a", 50), ("b", 40), ("c", 30), ("d", 20)]))
        manager = _FakeManager()
        with patch.object(chargedesk, "make_tracked_session", return_value=session):
            self._collect(
                get_rows(
                    "k",
                    "charges",
                    MagicMock(),
                    manager,  # type: ignore[arg-type]
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=50,
                    db_incremental_field_earliest_value=20,
                )
            )
        # Earliest backfill runs first with occurred[max]=20, then latest with occurred[min]=50.
        assert session.calls[0].get("occurred[max]") == 20
        assert any(c.get("occurred[min]") == 50 for c in session.calls)

    def test_incremental_ignored_for_full_refresh_endpoint(self) -> None:
        session = _PagedSession([{"product_id": "p1", "first_seen": 10}], filter_param="created", ts_field="first_seen")
        manager = _FakeManager()
        with patch.object(chargedesk, "make_tracked_session", return_value=session):
            self._collect(
                get_rows(
                    "k",
                    "products",
                    MagicMock(),
                    manager,  # type: ignore[arg-type]
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=5,
                )
            )
        # products is full-refresh only, so the [min] filter must never be sent.
        assert all("created[min]" not in c for c in session.calls)

    def test_resume_from_saved_full_state(self) -> None:
        session = _PagedSession(_charges([("a", 50), ("b", 40), ("c", 30), ("d", 20)]))
        manager = _FakeManager(state=ChargedeskResumeConfig(offset=2, window_max=None, phase="full"))
        with patch.object(chargedesk, "make_tracked_session", return_value=session):
            self._collect(
                get_rows("k", "charges", MagicMock(), manager, should_use_incremental_field=False)  # type: ignore[arg-type]
            )
        # First fetch resumes from the saved offset, not 0.
        assert session.calls[0]["offset"] == 2


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_mapping(self, _name: str, status: int, expected: bool) -> None:
        session = MagicMock()
        session.get.return_value = _FakeResponse({}, status=status)
        with patch.object(chargedesk, "make_tracked_session", return_value=session):
            assert validate_credentials("k") is expected

    def test_network_error_is_invalid(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(chargedesk, "make_tracked_session", return_value=session):
            assert validate_credentials("k") is False


class TestChargedeskSource:
    @parameterized.expand(list(CHARGEDESK_ENDPOINTS.keys()))
    def test_source_response_shape(self, endpoint: str) -> None:
        cfg = CHARGEDESK_ENDPOINTS[endpoint]
        response = chargedesk_source("k", endpoint, MagicMock(), MagicMock())
        assert response.name == endpoint
        assert response.primary_keys == cfg.primary_keys
        # ChargeDesk returns rows newest-first.
        assert response.sort_mode == "desc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [cfg.timestamp_field]

    def test_primary_keys_are_resource_specific(self) -> None:
        assert chargedesk_source("k", "charges", MagicMock(), MagicMock()).primary_keys == ["charge_id"]
        assert chargedesk_source("k", "customers", MagicMock(), MagicMock()).primary_keys == ["customer_id"]


if __name__ == "__main__":
    pytest.main([__file__])

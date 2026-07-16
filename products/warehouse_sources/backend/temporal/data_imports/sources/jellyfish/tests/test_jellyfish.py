from datetime import date
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.jellyfish import jellyfish
from products.warehouse_sources.backend.temporal.data_imports.sources.jellyfish.jellyfish import (
    JellyfishRateLimitError,
    JellyfishResumeConfig,
    _build_url,
    _extract_rows,
    _get_headers,
    _month_windows,
    get_rows,
    jellyfish_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jellyfish.settings import JELLYFISH_ENDPOINTS


class TestHeaders:
    def test_uses_token_auth_scheme(self) -> None:
        # Jellyfish uses `Token <token>` (verified against the live API), not `Bearer`.
        assert _get_headers("abc")["Authorization"] == "Token abc"


class TestMonthWindows:
    def test_windows_cover_lookback_and_clip_current_month_to_today(self) -> None:
        windows = _month_windows(date(2026, 3, 10), lookback_months=24)
        assert len(windows) == 24
        assert windows[0] == (date(2024, 4, 1), date(2024, 4, 30))
        # Complete months span first through last day (no gaps or overlaps at boundaries).
        assert windows[-2] == (date(2026, 2, 1), date(2026, 2, 28))
        # The in-progress month never asks for future dates.
        assert windows[-1] == (date(2026, 3, 1), date(2026, 3, 10))

    def test_first_of_month_today_produces_single_day_window(self) -> None:
        windows = _month_windows(date(2026, 3, 1), lookback_months=2)
        assert windows[-1] == (date(2026, 3, 1), date(2026, 3, 1))


class TestExtractRows:
    @parameterized.expand(
        [
            ("bare_list", [{"id": 1}, {"id": 2}], None, [{"id": 1}, {"id": 2}]),
            ("bare_list_drops_non_dicts", [{"id": 1}, "junk"], None, [{"id": 1}]),
            ("known_data_key", {"deliverables": [{"id": 1}], "meta": {"x": 1}}, "deliverables", [{"id": 1}]),
            ("single_list_value_autodetected", {"teams": [{"id": 7}]}, None, [{"id": 7}]),
            ("scalar_payload", "not json rows", None, []),
        ]
    )
    def test_extract(self, _name: str, payload: Any, data_key: str | None, expected: list[dict]) -> None:
        assert _extract_rows(payload, data_key) == expected

    def test_ambiguous_dict_is_kept_whole_as_one_row(self) -> None:
        # Two list-of-dict values means we can't tell which holds the rows — keep the payload
        # intact rather than guessing and silently dropping half the data.
        payload = {"a": [{"x": 1}], "b": [{"y": 2}]}
        assert _extract_rows(payload) == [payload]

    def test_missing_data_key_falls_back_to_autodetection(self) -> None:
        assert _extract_rows({"items": [{"id": 1}]}, data_key="deliverables") == [{"id": 1}]


class _FakeResumableManager:
    def __init__(self, state: JellyfishResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[JellyfishResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> JellyfishResumeConfig | None:
        return self._state

    def save_state(self, data: JellyfishResumeConfig) -> None:
        self.saved.append(data)


def _install_fake_fetch(monkeypatch: Any, responder: Any) -> list[dict[str, Any]]:
    """Route `_fetch` to `responder(path, params)`; returns the list of captured requests."""
    calls: list[dict[str, Any]] = []

    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> Any:
        parsed = urlparse(url)
        params = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(parsed.query).items()}
        path = parsed.path.removeprefix("/endpoints/export/v0/")
        calls.append({"path": path, "params": params})
        return responder(path, params)

    monkeypatch.setattr(jellyfish, "_fetch", fake_fetch)
    return calls


def _collect(endpoint: str, manager: _FakeResumableManager, today: date, monkeypatch: Any) -> list[dict]:
    class _FixedDatetime:
        @staticmethod
        def now(tz: Any = None) -> Any:
            return MagicMock(date=lambda: today)

    monkeypatch.setattr(jellyfish, "datetime", _FixedDatetime)

    rows: list[dict] = []
    for batch in get_rows(
        api_token="t",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
    ):
        rows.extend(batch)
    return rows


class TestGetRowsReference:
    def test_single_request_with_static_params_and_json_format(self, monkeypatch: Any) -> None:
        calls = _install_fake_fetch(monkeypatch, lambda path, params: {"teams": [{"id": 7, "name": "Core"}]})
        rows = _collect("teams", _FakeResumableManager(), date(2026, 3, 10), monkeypatch)

        assert rows == [{"id": 7, "name": "Core"}]
        assert calls == [
            {
                "path": "teams/list_teams",
                # `format=json` is mandatory (the API otherwise defaults to CSV); hierarchy params
                # are what makes list_teams return the whole tree.
                "params": {"format": "json", "hierarchy_level": "1", "include_children": "true"},
            }
        ]


class TestGetRowsMonthWindowed:
    def test_walks_every_window_injects_window_fields_and_saves_state_after_yield(self, monkeypatch: Any) -> None:
        calls = _install_fake_fetch(monkeypatch, lambda path, params: [{"metric": "x"}])
        manager = _FakeResumableManager()
        rows = _collect("company_metrics", manager, date(2026, 3, 10), monkeypatch)

        assert len(calls) == 24
        assert all(c["path"] == "metrics/company_metrics" for c in calls)
        assert calls[0]["params"]["start_date"] == "2024-04-01"
        assert calls[0]["params"]["end_date"] == "2024-04-30"
        assert calls[0]["params"]["unit"] == "month"
        assert calls[-1]["params"] == {
            "format": "json",
            "start_date": "2026-03-01",
            "end_date": "2026-03-10",
            "unit": "month",
        }
        # Each aggregate row keeps its period.
        assert rows[0] == {"metric": "x", "window_start_date": "2024-04-01", "window_end_date": "2024-04-30"}
        assert rows[-1]["window_start_date"] == "2026-03-01"
        # State points at the NEXT window and is saved after each yielded window except the last —
        # a crash re-fetches the current window instead of skipping it.
        assert len(manager.saved) == 23
        assert manager.saved[0] == JellyfishResumeConfig(next_window_start="2024-05-01")
        assert manager.saved[-1] == JellyfishResumeConfig(next_window_start="2026-03-01")

    def test_resume_skips_windows_before_saved_watermark(self, monkeypatch: Any) -> None:
        calls = _install_fake_fetch(monkeypatch, lambda path, params: [{"metric": "x"}])
        manager = _FakeResumableManager(JellyfishResumeConfig(next_window_start="2026-02-01"))
        _collect("company_metrics", manager, date(2026, 3, 10), monkeypatch)

        assert [c["params"]["start_date"] for c in calls] == ["2026-02-01", "2026-03-01"]


class TestGetRowsFanOut:
    @staticmethod
    def _responder(path: str, params: dict[str, Any]) -> Any:
        if path == "delivery/work_categories":
            return [{"slug": "roadmap"}, {"slug": "kt"}]
        assert path == "delivery/work_category_contents"
        return {"deliverables": [{"name": f"deliverable-{params['work_category_slug']}"}]}

    def test_fans_out_per_work_category_and_injects_slug(self, monkeypatch: Any) -> None:
        calls = _install_fake_fetch(monkeypatch, self._responder)
        manager = _FakeResumableManager()
        rows = _collect("deliverables", manager, date(2026, 3, 10), monkeypatch)

        assert rows == [
            {"name": "deliverable-roadmap", "work_category_slug": "roadmap"},
            {"name": "deliverable-kt", "work_category_slug": "kt"},
        ]
        content_calls = [c for c in calls if c["path"] == "delivery/work_category_contents"]
        # One wide window over the whole lookback range — deliverables are discrete records, not
        # per-period aggregates.
        assert content_calls[0]["params"]["start_date"] == "2024-04-01"
        assert content_calls[0]["params"]["end_date"] == "2026-03-10"
        assert manager.saved == [
            JellyfishResumeConfig(completed_slugs=["roadmap"]),
            JellyfishResumeConfig(completed_slugs=["kt", "roadmap"]),
        ]

    def test_resume_skips_completed_work_categories(self, monkeypatch: Any) -> None:
        calls = _install_fake_fetch(monkeypatch, self._responder)
        manager = _FakeResumableManager(JellyfishResumeConfig(completed_slugs=["roadmap"]))
        rows = _collect("deliverables", manager, date(2026, 3, 10), monkeypatch)

        assert [r["work_category_slug"] for r in rows] == ["kt"]
        content_slugs = [
            c["params"]["work_category_slug"] for c in calls if c["path"] == "delivery/work_category_contents"
        ]
        assert content_slugs == ["kt"]

    def test_work_category_rows_without_slug_fall_back_to_id(self, monkeypatch: Any) -> None:
        def responder(path: str, params: dict[str, Any]) -> Any:
            if path == "delivery/work_categories":
                return [{"id": 42, "display_name": "Roadmap"}]
            return {"deliverables": [{"name": "d"}]}

        calls = _install_fake_fetch(monkeypatch, responder)
        _collect("deliverables", _FakeResumableManager(), date(2026, 3, 10), monkeypatch)
        content_calls = [c for c in calls if c["path"] == "delivery/work_category_contents"]
        assert content_calls[0]["params"]["work_category_slug"] == "42"


class TestJellyfishSourceResponse:
    def test_windowed_endpoint_partitions_on_injected_window_start(self) -> None:
        response = jellyfish_source("t", "company_metrics", MagicMock(), MagicMock())
        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"
        assert response.partition_keys == ["window_start_date"]

    def test_reference_endpoint_has_primary_key_and_no_partitioning(self) -> None:
        response = jellyfish_source("t", "engineers", MagicMock(), MagicMock())
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None

    def test_every_declared_endpoint_builds_a_response(self) -> None:
        for endpoint in JELLYFISH_ENDPOINTS:
            assert jellyfish_source("t", endpoint, MagicMock(), MagicMock()).name == endpoint


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code,expected", [(200, True), (401, False), (403, False)])
    def test_status_maps_to_bool(self, status_code: int, expected: bool, monkeypatch: Any) -> None:
        response = MagicMock()
        response.status_code = status_code
        session = MagicMock()
        session.get.return_value = response
        monkeypatch.setattr(jellyfish, "make_tracked_session", lambda *a, **k: session)
        assert validate_credentials("t") is expected

    def test_network_error_is_not_valid(self, monkeypatch: Any) -> None:
        session = MagicMock()
        session.get.side_effect = Exception("boom")
        monkeypatch.setattr(jellyfish, "make_tracked_session", lambda *a, **k: session)
        assert validate_credentials("t") is False


class TestFetch:
    def test_429_raises_rate_limit_with_retry_after(self) -> None:
        response = MagicMock()
        response.status_code = 429
        response.headers = {"Retry-After": "12"}
        session = MagicMock()
        session.get.return_value = response
        # Call the undecorated body (bypassing tenacity) to assert the error carries Retry-After.
        with pytest.raises(JellyfishRateLimitError) as exc:
            jellyfish._fetch.__wrapped__(session, _build_url("metrics/company_metrics", {}), {}, MagicMock())  # type: ignore[attr-defined]
        assert exc.value.retry_after == 12.0

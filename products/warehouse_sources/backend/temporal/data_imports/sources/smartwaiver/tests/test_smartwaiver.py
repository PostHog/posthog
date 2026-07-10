from datetime import UTC, date, datetime
from typing import Any

from freezegun import freeze_time
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.smartwaiver import smartwaiver
from products.warehouse_sources.backend.temporal.data_imports.sources.smartwaiver.smartwaiver import (
    CHECKINS_MAX_OFFSET,
    PAGE_SIZE,
    SmartwaiverResumeConfig,
    _clamp_before_current_hour,
    _format_dts,
    _parse_retry_after,
    get_rows,
    smartwaiver_source,
    validate_credentials,
)

_NOW = datetime(2026, 7, 8, 15, 42, 30, tzinfo=UTC)
# `fromDts` must not be within the current hour, so recent cursors clamp to 14:59:59.
_HOUR_BOUNDARY = "2026-07-08T14:59:59"


class _FakeResumableManager:
    def __init__(self, state: SmartwaiverResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[SmartwaiverResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> SmartwaiverResumeConfig | None:
        return self._state

    def save_state(self, data: SmartwaiverResumeConfig) -> None:
        self.saved.append(data)


def _patch_fetch(monkeypatch: Any, pages: dict[str, Any]) -> list[str]:
    fetched: list[str] = []

    def fake_fetch(session: Any, url: str, logger: Any) -> dict:
        fetched.append(url)
        return pages[url]

    monkeypatch.setattr(smartwaiver, "_fetch_page", fake_fetch)
    return fetched


def _collect(monkeypatch: Any, manager: _FakeResumableManager, **kwargs: Any) -> list[dict]:
    rows: list[dict] = []
    for batch in get_rows(api_key="key", logger=MagicMock(), resumable_source_manager=manager, **kwargs):  # type: ignore[arg-type]
        rows.extend(batch)
    return rows


def _waiver_page(ids: list[str]) -> dict:
    return {"type": "waivers", "waivers": [{"waiverId": i} for i in ids]}


def _checkin_page(ids: list[int], more: bool) -> dict:
    return {
        "type": "checkins",
        "checkins": {"moreCheckins": more, "checkins": [{"checkinId": i, "position": 0} for i in ids]},
    }


class TestFormatDts:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00"),
            # Smartwaiver responses carry naive space-separated timestamps; they must round-trip
            # into the `T`-separated form the API accepts for `fromDts`.
            ("api_response_string", "2018-01-01 12:32:16", "2018-01-01T12:32:16"),
            ("iso_string", "2018-01-01T12:32:16", "2018-01-01T12:32:16"),
            ("unparseable_string_passthrough", "not-a-date", "not-a-date"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_dts(value) == expected


class TestClampBeforeCurrentHour:
    @parameterized.expand(
        [
            ("old_value_untouched", "2026-01-01 10:00:00", "2026-01-01T10:00:00"),
            ("within_current_hour_clamped", "2026-07-08 15:30:00", _HOUR_BOUNDARY),
            ("future_value_clamped", datetime(2026, 7, 9, 1, 0, 0, tzinfo=UTC), _HOUR_BOUNDARY),
        ]
    )
    def test_clamp(self, _name: str, value: Any, expected: str) -> None:
        assert _clamp_before_current_hour(value, _NOW) == expected


class TestParseRetryAfter:
    @parameterized.expand(
        [
            ("normal", "37", 37),
            ("missing_header", None, 60),
            ("garbage", "soon", 60),
            ("zero_floored", "0", 1),
            ("huge_capped", "86400", 120),
        ]
    )
    def test_parse(self, _name: str, header: str | None, expected: int) -> None:
        assert _parse_retry_after(header) == expected


class TestGetWaivers:
    def test_paginates_until_partial_page(self, monkeypatch: Any) -> None:
        full_page = [str(i) for i in range(PAGE_SIZE)]
        pages = {
            f"https://api.smartwaiver.com/v4/waivers?limit={PAGE_SIZE}&offset=0": _waiver_page(full_page),
            f"https://api.smartwaiver.com/v4/waivers?limit={PAGE_SIZE}&offset=1": _waiver_page(["last"]),
        }
        fetched = _patch_fetch(monkeypatch, pages)
        rows = _collect(monkeypatch, _FakeResumableManager(), endpoint="waivers")

        assert len(rows) == PAGE_SIZE + 1
        assert fetched == list(pages)

    def test_saves_resume_state_after_each_yielded_page(self, monkeypatch: Any) -> None:
        full_page = [str(i) for i in range(PAGE_SIZE)]
        pages = {
            f"https://api.smartwaiver.com/v4/waivers?limit={PAGE_SIZE}&offset=0": _waiver_page(full_page),
            f"https://api.smartwaiver.com/v4/waivers?limit={PAGE_SIZE}&offset=1": _waiver_page([]),
        }
        _patch_fetch(monkeypatch, pages)
        manager = _FakeResumableManager()
        _collect(monkeypatch, manager, endpoint="waivers")

        # State is saved only while more pages may remain, never on the final partial page.
        assert manager.saved == [SmartwaiverResumeConfig(next_offset=1, from_dts=None)]

    def test_resumes_from_saved_offset_and_window(self, monkeypatch: Any) -> None:
        pages = {
            f"https://api.smartwaiver.com/v4/waivers?limit={PAGE_SIZE}&offset=3&fromDts=2026-01-01T00%3A00%3A00": _waiver_page(
                ["w1"]
            ),
        }
        fetched = _patch_fetch(monkeypatch, pages)
        manager = _FakeResumableManager(SmartwaiverResumeConfig(next_offset=3, from_dts="2026-01-01T00:00:00"))
        rows = _collect(monkeypatch, manager, endpoint="waivers")

        assert [r["waiverId"] for r in rows] == ["w1"]
        assert fetched == list(pages)

    @freeze_time(_NOW)
    def test_incremental_cursor_added_and_clamped(self, monkeypatch: Any) -> None:
        pages = {
            f"https://api.smartwaiver.com/v4/waivers?limit={PAGE_SIZE}&offset=0&fromDts=2026-01-01T10%3A00%3A00": _waiver_page(
                ["w1"]
            ),
        }
        fetched = _patch_fetch(monkeypatch, pages)
        _collect(
            monkeypatch,
            _FakeResumableManager(),
            endpoint="waivers",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01 10:00:00",
        )
        assert "fromDts=2026-01-01T10%3A00%3A00" in fetched[0]

    def test_full_refresh_omits_time_filter(self, monkeypatch: Any) -> None:
        pages = {
            f"https://api.smartwaiver.com/v4/waivers?limit={PAGE_SIZE}&offset=0": _waiver_page(["w1"]),
        }
        fetched = _patch_fetch(monkeypatch, pages)
        _collect(monkeypatch, _FakeResumableManager(), endpoint="waivers")

        assert "fromDts" not in fetched[0]


class TestGetCheckins:
    @freeze_time(_NOW)
    def test_full_sync_uses_default_window(self, monkeypatch: Any) -> None:
        pages = {
            f"https://api.smartwaiver.com/v4/checkins?fromDts=2000-01-01T00%3A00%3A00&toDts=2026-07-08T14%3A59%3A59&limit={PAGE_SIZE}&offset=0": _checkin_page(
                [1], more=False
            ),
        }
        fetched = _patch_fetch(monkeypatch, pages)
        rows = _collect(monkeypatch, _FakeResumableManager(), endpoint="checkins")

        assert [r["checkinId"] for r in rows] == [1]
        # Both bounds are required by the API: an old default lower bound and an upper bound
        # strictly before the current hour.
        assert fetched == list(pages)

    @freeze_time(_NOW)
    def test_incremental_sync_starts_window_at_watermark(self, monkeypatch: Any) -> None:
        pages = {
            f"https://api.smartwaiver.com/v4/checkins?fromDts=2026-06-01T08%3A00%3A00&toDts=2026-07-08T14%3A59%3A59&limit={PAGE_SIZE}&offset=0": _checkin_page(
                [1], more=False
            ),
        }
        fetched = _patch_fetch(monkeypatch, pages)
        _collect(
            monkeypatch,
            _FakeResumableManager(),
            endpoint="checkins",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-06-01 08:00:00",
        )
        assert fetched == list(pages)

    @freeze_time(_NOW)
    def test_paginates_while_more_checkins_and_saves_state(self, monkeypatch: Any) -> None:
        window = f"fromDts=2000-01-01T00%3A00%3A00&toDts=2026-07-08T14%3A59%3A59&limit={PAGE_SIZE}"
        pages = {
            f"https://api.smartwaiver.com/v4/checkins?{window}&offset=0": _checkin_page([1], more=True),
            f"https://api.smartwaiver.com/v4/checkins?{window}&offset=1": _checkin_page([2], more=False),
        }
        fetched = _patch_fetch(monkeypatch, pages)
        manager = _FakeResumableManager()
        rows = _collect(monkeypatch, manager, endpoint="checkins")

        assert [r["checkinId"] for r in rows] == [1, 2]
        assert fetched == list(pages)
        assert manager.saved == [
            SmartwaiverResumeConfig(next_offset=1, from_dts="2000-01-01T00:00:00", to_dts="2026-07-08T14:59:59")
        ]

    def test_stops_at_offset_cap(self, monkeypatch: Any) -> None:
        # A window with more results past the API's offset cap must terminate, not loop.
        state = SmartwaiverResumeConfig(
            next_offset=CHECKINS_MAX_OFFSET, from_dts="2000-01-01T00:00:00", to_dts="2026-07-08T14:59:59"
        )
        window = f"fromDts=2000-01-01T00%3A00%3A00&toDts=2026-07-08T14%3A59%3A59&limit={PAGE_SIZE}"
        pages = {
            f"https://api.smartwaiver.com/v4/checkins?{window}&offset={CHECKINS_MAX_OFFSET}": _checkin_page(
                [1], more=True
            ),
        }
        fetched = _patch_fetch(monkeypatch, pages)
        manager = _FakeResumableManager(state)
        rows = _collect(monkeypatch, manager, endpoint="checkins")

        assert [r["checkinId"] for r in rows] == [1]
        assert fetched == list(pages)
        assert manager.saved == []


class TestGetTemplates:
    def test_single_fetch_yields_templates(self, monkeypatch: Any) -> None:
        pages = {
            "https://api.smartwaiver.com/v4/templates": {
                "type": "templates",
                "templates": [{"templateId": "t1"}, {"templateId": "t2"}],
            },
        }
        fetched = _patch_fetch(monkeypatch, pages)
        rows = _collect(monkeypatch, _FakeResumableManager(), endpoint="templates")

        assert [r["templateId"] for r in rows] == ["t1", "t2"]
        assert fetched == list(pages)


class TestSmartwaiverSource:
    @parameterized.expand(
        [
            ("templates", ["templateId"], None),
            ("waivers", ["waiverId"], ["createdOn"]),
            ("checkins", ["checkinId", "position"], ["date"]),
        ]
    )
    def test_source_response_keys_and_partitioning(
        self, endpoint: str, expected_pks: list[str], expected_partition_keys: list[str] | None
    ) -> None:
        response = smartwaiver_source(
            api_key="key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == expected_pks
        assert response.partition_keys == expected_partition_keys
        # List order is undocumented, so the watermark must only advance on completed syncs.
        assert response.sort_mode == "desc"


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", (200, None), True, None),
            ("unauthorized", (401, None), False, "Invalid Smartwaiver API key"),
            ("forbidden", (403, None), False, "Invalid Smartwaiver API key"),
            ("server_error", (500, "Smartwaiver returned HTTP 500"), False, "Smartwaiver returned HTTP 500"),
            (
                "connection_error",
                (0, "Could not connect to Smartwaiver: boom"),
                False,
                "Could not connect to Smartwaiver: boom",
            ),
        ]
    )
    def test_status_mapping(
        self, _name: str, check_result: tuple[int, str | None], expected_valid: bool, expected_message: str | None
    ) -> None:
        with patch.object(smartwaiver, "check_access", return_value=check_result):
            is_valid, message = validate_credentials("key")
        assert is_valid is expected_valid
        assert message == expected_message

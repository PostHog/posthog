from datetime import UTC, date, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.mailersend import mailersend
from products.warehouse_sources.backend.temporal.data_imports.sources.mailersend.mailersend import (
    MailerSendResumeConfig,
    _activity_date_window,
    _to_datetime,
    check_credentials,
    get_rows,
    mailersend_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailersend.settings import MAILERSEND_ENDPOINTS


class _FakeResumableManager:
    def __init__(self, state: MailerSendResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[MailerSendResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> MailerSendResumeConfig | None:
        return self._state

    def save_state(self, data: MailerSendResumeConfig) -> None:
        self.saved.append(data)


def _fake_session_returning(status_code: int) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    session = MagicMock()
    session.get.return_value = response
    return session


class TestToDatetime:
    @parameterized.expand(
        [
            (
                "aware_datetime",
                datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
                datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            ),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC)),
            ("date_value", date(2026, 3, 4), datetime(2026, 3, 4, 0, 0, 0, tzinfo=UTC)),
            ("unix_int", 1443651141, datetime(2015, 9, 30, 22, 12, 21, tzinfo=UTC)),
            ("iso_z_suffix", "2021-08-31T13:43:35.000000Z", datetime(2021, 8, 31, 13, 43, 35, tzinfo=UTC)),
            ("iso_offset", "2021-08-31T13:43:35+00:00", datetime(2021, 8, 31, 13, 43, 35, tzinfo=UTC)),
        ]
    )
    def test_to_datetime(self, _name: str, value: Any, expected: datetime) -> None:
        assert _to_datetime(value) == expected


class TestActivityDateWindow:
    @freeze_time("2026-06-23T00:00:00Z")
    def test_first_sync_uses_lookback_window(self) -> None:
        date_from, date_to = _activity_date_window(
            should_use_incremental_field=True, db_incremental_field_last_value=None, lookback_days=30
        )
        # 30 days of seconds between the bounds.
        assert date_to - date_from == 30 * 24 * 60 * 60
        assert date_to == int(datetime(2026, 6, 23, tzinfo=UTC).timestamp())

    @freeze_time("2026-06-23T00:00:00Z")
    def test_full_refresh_uses_lookback_window(self) -> None:
        # Activity requires a date window even without an incremental cursor, so a full refresh still
        # falls back to the lookback window rather than omitting the bounds.
        date_from, date_to = _activity_date_window(
            should_use_incremental_field=False, db_incremental_field_last_value=None, lookback_days=30
        )
        assert date_to - date_from == 30 * 24 * 60 * 60

    @freeze_time("2026-06-23T00:00:00Z")
    def test_incremental_starts_from_last_value(self) -> None:
        last = datetime(2026, 6, 20, 12, 0, 0, tzinfo=UTC)
        date_from, date_to = _activity_date_window(
            should_use_incremental_field=True, db_incremental_field_last_value=last, lookback_days=30
        )
        assert date_from == int(last.timestamp())
        assert date_to == int(datetime(2026, 6, 23, tzinfo=UTC).timestamp())

    @freeze_time("2026-06-23T00:00:00Z")
    def test_future_cursor_is_clamped_below_date_to(self) -> None:
        # A future-dated cursor would make date_from >= date_to and 422 the request; it must be clamped.
        future = datetime(2027, 1, 1, tzinfo=UTC)
        date_from, date_to = _activity_date_window(
            should_use_incremental_field=True, db_incremental_field_last_value=future, lookback_days=30
        )
        assert date_from < date_to


class TestCheckCredentials:
    @pytest.mark.parametrize(
        ("status_code", "schema_name", "expected_ok"),
        [
            (200, None, True),
            (401, None, False),
            (403, None, True),  # valid token, missing scope — accepted at source-create
            (403, "activity", False),  # scope gap surfaced for a specific schema
            (500, None, False),
        ],
    )
    def test_status_mapping(
        self, status_code: int, schema_name: str | None, expected_ok: bool, monkeypatch: Any
    ) -> None:
        monkeypatch.setattr(mailersend, "make_tracked_session", lambda: _fake_session_returning(status_code))
        ok, _error = check_credentials("mlsn.token", schema_name)
        assert ok is expected_ok

    def test_network_error_is_not_valid(self, monkeypatch: Any) -> None:
        session = MagicMock()
        session.get.side_effect = Exception("boom")
        monkeypatch.setattr(mailersend, "make_tracked_session", lambda: session)
        ok, error = check_credentials("mlsn.token")
        assert ok is False
        assert error is not None


def _collect(
    endpoint: str, manager: _FakeResumableManager, monkeypatch: Any, pages: dict[tuple[str, int], Any], **kw: Any
) -> list[dict]:
    """Run get_rows with `_fetch_page` mocked from a {(url, page): body} map and flatten the tables."""

    def fake_fetch(session: Any, url: str, headers: dict[str, str], params: dict[str, Any], logger: Any) -> dict:
        return pages[(url, params["page"])]

    monkeypatch.setattr(mailersend, "make_tracked_session", lambda: MagicMock())
    monkeypatch.setattr(mailersend, "_fetch_page", fake_fetch)

    rows: list[dict] = []
    for table in get_rows(
        api_token="mlsn.token",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **kw,
    ):
        rows.extend(table.to_pylist())
    return rows


class TestTopLevelPagination:
    def test_single_page(self, monkeypatch: Any) -> None:
        pages = {
            ("https://api.mailersend.com/v1/domains", 1): {
                "data": [{"id": "d1", "name": "a.com"}, {"id": "d2", "name": "b.com"}],
                "links": {"next": None},
            },
        }
        rows = _collect("domains", _FakeResumableManager(), monkeypatch, pages)
        assert [r["id"] for r in rows] == ["d1", "d2"]

    def test_follows_pagination_until_links_next_is_null(self, monkeypatch: Any) -> None:
        pages = {
            ("https://api.mailersend.com/v1/recipients", 1): {
                "data": [{"id": "r1"}],
                "links": {"next": "https://api.mailersend.com/v1/recipients?page=2"},
            },
            ("https://api.mailersend.com/v1/recipients", 2): {
                "data": [{"id": "r2"}],
                "links": {"next": None},
            },
        }
        rows = _collect("recipients", _FakeResumableManager(), monkeypatch, pages)
        assert [r["id"] for r in rows] == ["r1", "r2"]

    def test_stops_on_empty_page(self, monkeypatch: Any) -> None:
        pages = {
            ("https://api.mailersend.com/v1/templates", 1): {"data": [], "links": {"next": None}},
        }
        rows = _collect("templates", _FakeResumableManager(), monkeypatch, pages)
        assert rows == []

    def test_resumes_from_saved_page(self, monkeypatch: Any) -> None:
        # A saved state must skip already-synced earlier pages and pick up where it left off.
        manager = _FakeResumableManager(MailerSendResumeConfig(next_page=2))
        pages = {
            ("https://api.mailersend.com/v1/messages", 2): {
                "data": [{"id": "m2"}],
                "links": {"next": None},
            },
        }
        rows = _collect("messages", manager, monkeypatch, pages)
        assert [r["id"] for r in rows] == ["m2"]


class TestActivityFanOut:
    @staticmethod
    def _domains_page(*ids: str) -> dict:
        return {"data": [{"id": i} for i in ids], "links": {"next": None}}

    def test_fans_out_over_domains_and_stamps_domain_id(self, monkeypatch: Any) -> None:
        pages = {
            ("https://api.mailersend.com/v1/domains", 1): self._domains_page("d1", "d2"),
            ("https://api.mailersend.com/v1/activity/d1", 1): {
                "data": [{"id": "a1", "type": "sent"}],
                "links": {"next": None},
            },
            ("https://api.mailersend.com/v1/activity/d2", 1): {
                "data": [{"id": "a2", "type": "opened"}],
                "links": {"next": None},
            },
        }
        rows = _collect(
            "activity",
            _FakeResumableManager(),
            monkeypatch,
            pages,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 1, tzinfo=UTC),
        )
        assert rows == [
            {"id": "a1", "type": "sent", "domain_id": "d1"},
            {"id": "a2", "type": "opened", "domain_id": "d2"},
        ]

    def test_sends_required_date_window_params(self, monkeypatch: Any) -> None:
        captured: list[dict[str, Any]] = []

        def fake_fetch(session: Any, url: str, headers: dict[str, str], params: dict[str, Any], logger: Any) -> dict:
            captured.append({"url": url, **params})
            if url.endswith("/domains"):
                return self._domains_page("d1")
            return {"data": [{"id": "a1"}], "links": {"next": None}}

        monkeypatch.setattr(mailersend, "make_tracked_session", lambda: MagicMock())
        monkeypatch.setattr(mailersend, "_fetch_page", fake_fetch)

        list(
            get_rows(
                api_token="mlsn.token",
                endpoint="activity",
                logger=MagicMock(),
                resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 6, 1, tzinfo=UTC),
            )
        )

        activity_call = next(c for c in captured if "activity" in c["url"])
        assert activity_call["date_from"] == int(datetime(2026, 6, 1, tzinfo=UTC).timestamp())
        assert "date_to" in activity_call

    def test_resumes_from_saved_domain(self, monkeypatch: Any) -> None:
        # State pointing at d2 must skip d1 entirely and resume at d2's saved page.
        manager = _FakeResumableManager(MailerSendResumeConfig(next_page=1, domain_id="d2"))
        pages = {
            ("https://api.mailersend.com/v1/domains", 1): self._domains_page("d1", "d2"),
            ("https://api.mailersend.com/v1/activity/d2", 1): {
                "data": [{"id": "a2"}],
                "links": {"next": None},
            },
        }
        rows = _collect(
            "activity",
            manager,
            monkeypatch,
            pages,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 1, tzinfo=UTC),
        )
        assert [r["id"] for r in rows] == ["a2"]

    def test_no_checkpoint_skips_unflushed_small_domains(self, monkeypatch: Any) -> None:
        # Domains smaller than one batcher chunk never yield mid-domain, so their rows are still
        # buffered when the domain's loop ends. A cross-domain bookmark saved there would skip those
        # un-flushed rows on a crash. With only after-yield checkpoints, nothing is saved at all here.
        manager = _FakeResumableManager()
        pages = {
            ("https://api.mailersend.com/v1/domains", 1): self._domains_page("d1", "d2"),
            ("https://api.mailersend.com/v1/activity/d1", 1): {"data": [{"id": "a1"}], "links": {"next": None}},
            ("https://api.mailersend.com/v1/activity/d2", 1): {"data": [{"id": "a2"}], "links": {"next": None}},
        }
        rows = _collect(
            "activity",
            manager,
            monkeypatch,
            pages,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 1, tzinfo=UTC),
        )
        assert [r["id"] for r in rows] == ["a1", "a2"]
        assert manager.saved == []


class TestSourceResponseShape:
    @parameterized.expand(["domains", "recipients", "templates", "messages", "activity"])
    def test_primary_keys_match_settings(self, endpoint: str) -> None:
        resource = mailersend_source(
            api_token="mlsn.token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
        )
        assert resource.name == endpoint
        assert resource.primary_keys == MAILERSEND_ENDPOINTS[endpoint].primary_keys

    def test_activity_primary_key_includes_domain_id(self) -> None:
        # Activity ids are only unique within a domain, so the table-wide key must include domain_id.
        assert MAILERSEND_ENDPOINTS["activity"].primary_keys == ["domain_id", "id"]

    @parameterized.expand(
        [
            ("activity", "desc"),
            ("domains", "asc"),
        ]
    )
    def test_sort_mode(self, endpoint: str, expected_sort: str) -> None:
        resource = mailersend_source(
            api_token="mlsn.token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
        )
        assert resource.sort_mode == expected_sort

    @parameterized.expand(["domains", "recipients", "templates", "messages", "activity"])
    def test_partitions_on_created_at(self, endpoint: str) -> None:
        resource = mailersend_source(
            api_token="mlsn.token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
        )
        assert resource.partition_keys == ["created_at"]
        assert resource.partition_mode == "datetime"

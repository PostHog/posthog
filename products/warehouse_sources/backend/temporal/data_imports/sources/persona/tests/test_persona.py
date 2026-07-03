from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.persona import persona
from products.warehouse_sources.backend.temporal.data_imports.sources.persona.persona import (
    PersonaResumeConfig,
    PersonaRetryableError,
    _build_params,
    _flatten_item,
    _format_datetime_z,
    _to_datetime,
    get_rows,
    persona_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.persona.settings import PERSONA_ENDPOINTS


class _FakeResumableManager:
    def __init__(self, state: PersonaResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[PersonaResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> PersonaResumeConfig | None:
        return self._state

    def save_state(self, data: PersonaResumeConfig) -> None:
        self.saved.append(data)


class TestFormatDatetimeZ:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            ("microseconds", datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC), "2026-01-15T10:30:45.123Z"),
            ("naive_treated_as_utc", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
        ]
    )
    def test_format(self, _name: str, value: datetime, expected: str) -> None:
        assert _format_datetime_z(value) == expected

    def test_no_plus_offset(self) -> None:
        # Persona expects the Z suffix, not the +00:00 offset isoformat() produces.
        assert "+00:00" not in _format_datetime_z(datetime(2026, 3, 4, tzinfo=UTC))


class TestToDatetime:
    @parameterized.expand(
        [
            ("iso_z_string", "2026-01-15T10:30:45.000Z", datetime(2026, 1, 15, 10, 30, 45, tzinfo=UTC)),
            ("aware_datetime", datetime(2026, 1, 15, tzinfo=UTC), datetime(2026, 1, 15, tzinfo=UTC)),
            ("date_value", date(2026, 1, 15), datetime(2026, 1, 15, tzinfo=UTC)),
        ]
    )
    def test_parses(self, _name: str, value: Any, expected: datetime) -> None:
        assert _to_datetime(value) == expected

    def test_naive_string_becomes_utc_aware(self) -> None:
        result = _to_datetime("2026-01-15T10:30:45")
        assert result is not None and result.tzinfo is not None

    @parameterized.expand([("none", None), ("garbage", "not-a-date")])
    def test_unparseable_returns_none(self, _name: str, value: Any) -> None:
        assert _to_datetime(value) is None


class TestBuildParams:
    def test_full_refresh_only_page_size(self) -> None:
        params = _build_params(PERSONA_ENDPOINTS["inquiries"], watermark=None, after=None)
        assert params == {"page[size]": persona.PAGE_SIZE}

    def test_watermark_sets_created_at_start_filter(self) -> None:
        params = _build_params(PERSONA_ENDPOINTS["inquiries"], watermark=datetime(2026, 1, 15, tzinfo=UTC), after=None)
        assert params["filter[created-at-start]"] == "2026-01-15T00:00:00.000Z"

    def test_after_sets_cursor(self) -> None:
        params = _build_params(PERSONA_ENDPOINTS["inquiries"], watermark=None, after="inq_123")
        assert params["page[after]"] == "inq_123"


class TestFlattenItem:
    def test_lifts_attributes_and_keeps_id(self) -> None:
        row = _flatten_item(
            {"type": "inquiry", "id": "inq_1", "attributes": {"status": "completed", "created-at": "2026-01-01"}}
        )
        assert row["id"] == "inq_1"
        assert row["status"] == "completed"
        assert row["created-at"] == "2026-01-01"
        assert "attributes" not in row


class TestFetchPageRetryClassification:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        # 429 / 5xx are transient — they must raise the retryable type so tenacity retries them.
        response = MagicMock()
        response.status_code = status
        session = MagicMock()
        session.get.return_value = response

        with pytest.raises(PersonaRetryableError):
            persona._fetch_page(session, "https://api.withpersona.com/api/v1/inquiries", {}, MagicMock())
        # tenacity retries 5 times before giving up.
        assert session.get.call_count == 5

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_immediately(self, _name: str, status: int) -> None:
        # Auth/permission errors can never be fixed by retrying, so they must surface at once.
        response = requests.Response()
        response.status_code = status
        response.url = "https://api.withpersona.com/api/v1/inquiries"
        session = MagicMock()
        session.get.return_value = response

        with pytest.raises(requests.HTTPError):
            persona._fetch_page(session, "https://api.withpersona.com/api/v1/inquiries", {}, MagicMock())
        assert session.get.call_count == 1


def _collect(manager: _FakeResumableManager, monkeypatch: Any, pages: list[dict], **kwargs: Any) -> list[dict]:
    """Feed canned pages to get_rows in order and return the flattened rows."""
    calls: list[str] = []
    iterator = iter(pages)

    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
        calls.append(url)
        return next(iterator)

    monkeypatch.setattr(persona, "_fetch_page", fake_fetch)

    rows: list[dict] = []
    for table in get_rows(
        api_key="persona_test",
        endpoint="inquiries",
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **kwargs,
    ):
        rows.extend(table.to_pylist())
    manager.fetched_urls = calls  # type: ignore[attr-defined]
    return rows


class TestPagination:
    def test_follows_cursor_until_links_next_is_null(self, monkeypatch: Any) -> None:
        pages = [
            {
                "data": [
                    {"type": "inquiry", "id": "inq_1", "attributes": {"created-at": "2026-01-03T00:00:00.000Z"}},
                    {"type": "inquiry", "id": "inq_2", "attributes": {"created-at": "2026-01-02T00:00:00.000Z"}},
                ],
                "links": {"next": "/api/v1/inquiries?page[after]=inq_2"},
            },
            {
                "data": [
                    {"type": "inquiry", "id": "inq_3", "attributes": {"created-at": "2026-01-01T00:00:00.000Z"}},
                ],
                "links": {"next": None},
            },
        ]
        manager = _FakeResumableManager()
        rows = _collect(manager, monkeypatch, pages)

        assert [r["id"] for r in rows] == ["inq_1", "inq_2", "inq_3"]
        # Second request must advance the cursor to the last id of page one.
        assert "page[after]=inq_2" in manager.fetched_urls[1]  # type: ignore[attr-defined]

    def test_stops_on_empty_first_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = _collect(manager, monkeypatch, [{"data": [], "links": {"next": None}}])
        assert rows == []


class TestIncrementalWatermarkGuard:
    def test_stops_once_rows_predate_watermark(self, monkeypatch: Any) -> None:
        # Guards against re-walking full history: even though links.next is present, once a row older
        # than the watermark appears (newest-first ordering) we stop and never fetch the next page.
        pages = [
            {
                "data": [
                    {"type": "inquiry", "id": "inq_new", "attributes": {"created-at": "2026-01-20T00:00:00.000Z"}},
                    {"type": "inquiry", "id": "inq_old", "attributes": {"created-at": "2026-01-05T00:00:00.000Z"}},
                ],
                "links": {"next": "/api/v1/inquiries?page[after]=inq_old"},
            },
            {"data": [{"type": "inquiry", "id": "inq_never"}], "links": {"next": None}},
        ]
        manager = _FakeResumableManager()
        rows = _collect(
            manager,
            monkeypatch,
            pages,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 10, tzinfo=UTC),
        )

        assert [r["id"] for r in rows] == ["inq_new"]
        assert len(manager.fetched_urls) == 1  # type: ignore[attr-defined]

    def test_first_page_windowed_by_watermark(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        _collect(
            manager,
            monkeypatch,
            [{"data": [], "links": {"next": None}}],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 10, tzinfo=UTC),
        )
        assert "filter[created-at-start]=2026-01-10T00:00:00.000Z" in manager.fetched_urls[0]  # type: ignore[attr-defined]


class TestResume:
    def test_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(state=PersonaResumeConfig(after="inq_saved"))
        _collect(manager, monkeypatch, [{"data": [], "links": {"next": None}}])
        # First request on resume must carry the saved page[after] cursor.
        assert "page[after]=inq_saved" in manager.fetched_urls[0]  # type: ignore[attr-defined]


class TestPersonaSourceResponse:
    @parameterized.expand([("inquiries", "created_at"), ("events", "created_at")])
    def test_incremental_endpoint_partitions_on_created_at_desc(self, endpoint: str, partition_key: str) -> None:
        response = persona_source(
            api_key="persona_test",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # sort_mode must be desc — Persona returns newest-first, and the pipeline relies on this to
        # defer the incremental watermark advance to end-of-sync.
        assert response.sort_mode == "desc"
        assert response.partition_keys == [partition_key]
        assert response.partition_mode == "datetime"

    def test_full_refresh_endpoint_has_no_partitioning(self) -> None:
        response = persona_source(
            api_key="persona_test",
            endpoint="inquiry_templates",
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.partition_mode is None
        assert response.partition_keys is None

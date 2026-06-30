from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.emailoctopus import emailoctopus
from products.warehouse_sources.backend.temporal.data_imports.sources.emailoctopus.emailoctopus import (
    EMAILOCTOPUS_BASE_URL as BASE,
    EmailOctopusResumeConfig,
    _build_contact_params,
    _format_incremental_value,
    _get_headers,
    _next_url,
    emailoctopus_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.emailoctopus.settings import (
    EMAILOCTOPUS_ENDPOINTS,
)


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("microseconds_dropped", datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC), "2026-01-15T10:30:45Z"),
            ("naive_datetime_assumed_utc", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2024-01-19T12:14:28Z", "2024-01-19T12:14:28Z"),
        ]
    )
    def test_format(self, _name: str, value: object, expected: str) -> None:
        assert _format_incremental_value(value) == expected

    def test_no_offset_suffix(self) -> None:
        # EmailOctopus's ISO 8601 filters use a Z suffix, never the +00:00 offset isoformat() emits.
        result = _format_incremental_value(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))
        assert "+00:00" not in result
        assert result.endswith("Z")


class TestNextUrl:
    @parameterized.expand(
        [
            (
                "has_next",
                {"paging": {"next": {"url": f"{BASE}/lists?starting_after=abc&limit=100"}}},
                f"{BASE}/lists?starting_after=abc&limit=100",
            ),
            ("next_is_null", {"paging": {"next": None}}, None),
            ("no_next_key", {"paging": {}}, None),
            ("no_paging_key", {"data": []}, None),
            ("paging_is_null", {"paging": None}, None),
        ]
    )
    def test_next_url(self, _name: str, data: dict, expected: str | None) -> None:
        assert _next_url(data) == expected


class TestHeaders:
    def test_bearer_token(self) -> None:
        headers = _get_headers("eo_secret")
        assert headers["Authorization"] == "Bearer eo_secret"
        assert headers["Accept"] == "application/json"


class TestBuildContactParams:
    def test_status_only_when_no_incremental(self) -> None:
        params = _build_contact_params("subscribed", incremental_field=None, filter_value=None)
        assert params == {"limit": 100, "status": "subscribed"}

    def test_no_filter_when_value_missing(self) -> None:
        params = _build_contact_params("pending", incremental_field="created_at", filter_value=None)
        assert "created_at.gte" not in params

    @parameterized.expand(
        [
            ("last_updated", "last_updated_at", "last_updated_at.gte"),
            ("created", "created_at", "created_at.gte"),
        ]
    )
    def test_server_side_filter(self, _name: str, field: str, expected_param: str) -> None:
        params = _build_contact_params("subscribed", incremental_field=field, filter_value="2026-01-01T00:00:00Z")
        assert params[expected_param] == "2026-01-01T00:00:00Z"
        assert params["status"] == "subscribed"


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_mapping(self, _name: str, status_code: int, expected: bool) -> None:
        response = MagicMock()
        response.status_code = status_code
        session = MagicMock()
        session.get.return_value = response
        with patch.object(emailoctopus, "make_tracked_session", return_value=session):
            assert validate_credentials("eo_key") is expected

    def test_network_error_is_invalid(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(emailoctopus, "make_tracked_session", return_value=session):
            assert validate_credentials("eo_key") is False

    def test_tracked_session_redacts_api_key(self) -> None:
        response = MagicMock()
        response.status_code = 200
        session = MagicMock()
        session.get.return_value = response
        with patch.object(emailoctopus, "make_tracked_session", return_value=session) as make_session:
            validate_credentials("eo_secret")
        # The key must be passed as a redaction value so it can't leak into tracked HTTP logs.
        make_session.assert_called_once_with(redact_values=("eo_secret",))


class _FakeResumableManager:
    def __init__(self, state: EmailOctopusResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[EmailOctopusResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> EmailOctopusResumeConfig | None:
        return self._state

    def save_state(self, data: EmailOctopusResumeConfig) -> None:
        self.saved.append(data)


def _response_with_status(status_code: int) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    return response


def _make_fake_fetch(pages: dict[str, Any], calls: list[tuple[str, Any]] | None = None):
    """Route a fetch to a canned response, keyed by url (plus status param for the contacts first page)."""

    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any, params: Any = None) -> dict:
        if calls is not None:
            calls.append((url, params))
        key = url
        if params and "status" in params:
            key = f"{url}?status={params['status']}"
        result = pages[key]
        if isinstance(result, Exception):
            raise result
        return result

    return fake_fetch


def _collect(
    endpoint: str, manager: _FakeResumableManager, monkeypatch: Any, pages: dict[str, Any], **kwargs: Any
) -> list[dict]:
    monkeypatch.setattr(emailoctopus, "_fetch_page", _make_fake_fetch(pages))
    rows: list[dict] = []
    for table in get_rows(
        api_key="eo_key",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **kwargs,
    ):
        rows.extend(table.to_pylist())
    return rows


class TestTopLevelRows:
    def test_paginates_following_next_url(self, monkeypatch: Any) -> None:
        next_url = f"{BASE}/lists?starting_after=cur1&limit=100"
        pages = {
            f"{BASE}/lists": {"data": [{"id": "L1"}], "paging": {"next": {"url": next_url}}},
            next_url: {"data": [{"id": "L2"}], "paging": {"next": None}},
        }
        rows = _collect("lists", _FakeResumableManager(), monkeypatch, pages)
        assert rows == [{"id": "L1"}, {"id": "L2"}]

    def test_resumes_from_saved_next_url(self, monkeypatch: Any) -> None:
        resume_url = f"{BASE}/campaigns?starting_after=cur5&limit=100"
        pages = {resume_url: {"data": [{"id": "C9"}], "paging": {"next": None}}}
        manager = _FakeResumableManager(EmailOctopusResumeConfig(next_url=resume_url))
        rows = _collect("campaigns", manager, monkeypatch, pages)
        # The initial /campaigns URL is never fetched — we jump straight to the saved cursor.
        assert rows == [{"id": "C9"}]


class TestContactsFanOut:
    def test_fans_out_over_lists_and_statuses_attaching_list_id(self, monkeypatch: Any) -> None:
        # One list, three statuses; each status query returns one contact.
        pages = {
            f"{BASE}/lists": {"data": [{"id": "L1"}], "paging": {"next": None}},
            f"{BASE}/lists/L1/contacts?status=subscribed": {"data": [{"id": "c-sub"}], "paging": {"next": None}},
            f"{BASE}/lists/L1/contacts?status=unsubscribed": {"data": [{"id": "c-unsub"}], "paging": {"next": None}},
            f"{BASE}/lists/L1/contacts?status=pending": {"data": [{"id": "c-pend"}], "paging": {"next": None}},
        }
        rows = _collect("contacts", _FakeResumableManager(), monkeypatch, pages)
        assert rows == [
            {"id": "c-sub", "list_id": "L1"},
            {"id": "c-unsub", "list_id": "L1"},
            {"id": "c-pend", "list_id": "L1"},
        ]

    def test_applies_server_side_incremental_filter_on_first_page(self, monkeypatch: Any) -> None:
        calls: list[tuple[str, Any]] = []
        pages = {
            f"{BASE}/lists": {"data": [{"id": "L1"}], "paging": {"next": None}},
            f"{BASE}/lists/L1/contacts?status=subscribed": {"data": [], "paging": {"next": None}},
            f"{BASE}/lists/L1/contacts?status=unsubscribed": {"data": [], "paging": {"next": None}},
            f"{BASE}/lists/L1/contacts?status=pending": {"data": [], "paging": {"next": None}},
        }
        monkeypatch.setattr(emailoctopus, "_fetch_page", _make_fake_fetch(pages, calls))
        list(
            get_rows(
                api_key="eo_key",
                endpoint="contacts",
                logger=MagicMock(),
                resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
                incremental_field="last_updated_at",
            )
        )
        contact_calls = [params for url, params in calls if "contacts" in url]
        assert all(params["last_updated_at.gte"] == "2026-01-01T00:00:00Z" for params in contact_calls)

    def test_no_filter_on_first_sync_without_watermark(self, monkeypatch: Any) -> None:
        calls: list[tuple[str, Any]] = []
        pages = {
            f"{BASE}/lists": {"data": [{"id": "L1"}], "paging": {"next": None}},
            f"{BASE}/lists/L1/contacts?status=subscribed": {"data": [], "paging": {"next": None}},
            f"{BASE}/lists/L1/contacts?status=unsubscribed": {"data": [], "paging": {"next": None}},
            f"{BASE}/lists/L1/contacts?status=pending": {"data": [], "paging": {"next": None}},
        }
        monkeypatch.setattr(emailoctopus, "_fetch_page", _make_fake_fetch(pages, calls))
        list(
            get_rows(
                api_key="eo_key",
                endpoint="contacts",
                logger=MagicMock(),
                resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                should_use_incremental_field=True,
                db_incremental_field_last_value=None,
                incremental_field="last_updated_at",
            )
        )
        contact_calls = [params for url, params in calls if "contacts" in url]
        assert all("last_updated_at.gte" not in params for params in contact_calls)

    def test_list_deleted_mid_fan_out_is_skipped(self, monkeypatch: Any) -> None:
        not_found = requests.HTTPError(response=_response_with_status(404))
        pages = {
            f"{BASE}/lists": {"data": [{"id": "L1"}, {"id": "GONE"}], "paging": {"next": None}},
            f"{BASE}/lists/L1/contacts?status=subscribed": {"data": [{"id": "c1"}], "paging": {"next": None}},
            f"{BASE}/lists/L1/contacts?status=unsubscribed": {"data": [], "paging": {"next": None}},
            f"{BASE}/lists/L1/contacts?status=pending": {"data": [], "paging": {"next": None}},
            # A deleted list 404s independently for each status query; all are skipped.
            f"{BASE}/lists/GONE/contacts?status=subscribed": not_found,
            f"{BASE}/lists/GONE/contacts?status=unsubscribed": not_found,
            f"{BASE}/lists/GONE/contacts?status=pending": not_found,
        }
        rows = _collect("contacts", _FakeResumableManager(), monkeypatch, pages)
        assert rows == [{"id": "c1", "list_id": "L1"}]

    def test_non_404_error_propagates(self, monkeypatch: Any) -> None:
        server_error = requests.HTTPError(response=_response_with_status(500))
        pages = {
            f"{BASE}/lists": {"data": [{"id": "L1"}], "paging": {"next": None}},
            f"{BASE}/lists/L1/contacts?status=subscribed": server_error,
        }
        with pytest.raises(requests.HTTPError):
            _collect("contacts", _FakeResumableManager(), monkeypatch, pages)

    def test_buffered_rows_flushed_before_advancing_pair_bookmark(self, monkeypatch: Any) -> None:
        # A crash right after the bookmark advances to the next list must not lose rows still
        # buffered (below a full chunk) from the previous list — so they must be yielded first.
        events: list[tuple[str, Any]] = []

        class _RecordingManager(_FakeResumableManager):
            def save_state(self, data: EmailOctopusResumeConfig) -> None:
                super().save_state(data)
                events.append(("save", (data.list_id, data.status, data.next_url)))

        pages = {
            f"{BASE}/lists": {"data": [{"id": "L1"}, {"id": "L2"}], "paging": {"next": None}},
            f"{BASE}/lists/L1/contacts?status=subscribed": {"data": [{"id": "a"}], "paging": {"next": None}},
            f"{BASE}/lists/L1/contacts?status=unsubscribed": {"data": [], "paging": {"next": None}},
            f"{BASE}/lists/L1/contacts?status=pending": {"data": [], "paging": {"next": None}},
            f"{BASE}/lists/L2/contacts?status=subscribed": {"data": [{"id": "b"}], "paging": {"next": None}},
            f"{BASE}/lists/L2/contacts?status=unsubscribed": {"data": [], "paging": {"next": None}},
            f"{BASE}/lists/L2/contacts?status=pending": {"data": [], "paging": {"next": None}},
        }
        manager = _RecordingManager()
        monkeypatch.setattr(emailoctopus, "_fetch_page", _make_fake_fetch(pages))
        for table in get_rows(
            api_key="eo_key",
            endpoint="contacts",
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            for row in table.to_pylist():
                events.append(("row", row["id"]))

        l1_row = events.index(("row", "a"))
        advance_to_l2 = next(
            i for i, (kind, payload) in enumerate(events) if kind == "save" and payload[:2] == ("L2", "subscribed")
        )
        assert l1_row < advance_to_l2

    def test_resume_from_deleted_bookmark_restarts(self, monkeypatch: Any) -> None:
        # Bookmark points at a list that no longer exists -> start over from the first pair.
        pages = {
            f"{BASE}/lists": {"data": [{"id": "L1"}], "paging": {"next": None}},
            f"{BASE}/lists/L1/contacts?status=subscribed": {"data": [{"id": "c1"}], "paging": {"next": None}},
            f"{BASE}/lists/L1/contacts?status=unsubscribed": {"data": [], "paging": {"next": None}},
            f"{BASE}/lists/L1/contacts?status=pending": {"data": [], "paging": {"next": None}},
        }
        manager = _FakeResumableManager(EmailOctopusResumeConfig(list_id="DELETED", status="subscribed", next_url=None))
        rows = _collect("contacts", manager, monkeypatch, pages)
        assert rows == [{"id": "c1", "list_id": "L1"}]


class TestResumeStateSaving:
    def test_saves_next_url_after_yielding_when_more_pages_remain(self, monkeypatch: Any) -> None:
        # Force a yield per row by shrinking the batcher thresholds.
        next_url = f"{BASE}/lists?starting_after=cur1&limit=100"
        pages = {
            f"{BASE}/lists": {"data": [{"id": "L1"}], "paging": {"next": {"url": next_url}}},
            next_url: {"data": [{"id": "L2"}], "paging": {"next": None}},
        }
        manager = _FakeResumableManager()
        monkeypatch.setattr(emailoctopus, "_fetch_page", _make_fake_fetch(pages))

        class _ImmediateBatcher:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                self._rows: list[dict] = []

            def batch(self, row: dict) -> None:
                self._rows.append(row)

            def should_yield(self, include_incomplete_chunk: bool = False) -> bool:
                return len(self._rows) > 0

            def get_table(self) -> Any:
                table = MagicMock()
                rows = list(self._rows)
                table.to_pylist.return_value = rows
                self._rows = []
                return table

        monkeypatch.setattr(emailoctopus, "Batcher", _ImmediateBatcher)
        list(
            get_rows(
                api_key="eo_key",
                endpoint="lists",
                logger=MagicMock(),
                resumable_source_manager=manager,  # type: ignore[arg-type]
            )
        )
        # The first page has a next URL, so its cursor is saved; the last page does not.
        assert any(s.next_url == next_url for s in manager.saved)


class TestSourceResponse:
    @parameterized.expand(
        [
            ("lists", ["id"]),
            ("campaigns", ["id"]),
            ("contacts", ["list_id", "id"]),
        ]
    )
    def test_primary_keys_and_partitioning(self, endpoint: str, expected_pks: list[str]) -> None:
        response = emailoctopus_source(
            api_key="eo_key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == expected_pks
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [EMAILOCTOPUS_ENDPOINTS[endpoint].partition_key]
        assert EMAILOCTOPUS_ENDPOINTS[endpoint].partition_key == "created_at"

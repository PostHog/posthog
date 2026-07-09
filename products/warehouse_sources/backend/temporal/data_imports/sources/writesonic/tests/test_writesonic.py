from datetime import UTC, date, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.writesonic import writesonic
from products.warehouse_sources.backend.temporal.data_imports.sources.writesonic.settings import WRITESONIC_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.writesonic.writesonic import (
    WritesonicResumeConfig,
    WritesonicRetryableError,
    _check_response,
    _to_date,
    get_rows,
    validate_credentials,
    writesonic_source,
)


class _FakeManager:
    def __init__(self, state: WritesonicResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[WritesonicResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> WritesonicResumeConfig | None:
        return self._state

    def save_state(self, data: WritesonicResumeConfig) -> None:
        self.saved.append(data)


class _FakeApi:
    """Canned paginated Writesonic responses plus a record of every request made."""

    def __init__(
        self,
        daily_pages: dict[str, list[list[dict[str, Any]]]] | None = None,
        config_pages: list[list[dict[str, Any]]] | None = None,
    ) -> None:
        self.daily_pages = daily_pages or {}
        self.config_pages = config_pages or []
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, path: str, *, api_key: str, logger: Any, params: dict[str, Any] | None = None) -> Any:
        params = params or {}
        self.calls.append((path, params))
        pages = self.daily_pages.get(params["date"], []) if "date" in params else self.config_pages
        page = params["page"]
        items = pages[page - 1] if 1 <= page <= len(pages) else []
        data = {
            "items": items,
            "page": page,
            "size": params["size"],
            "total": sum(len(p) for p in pages),
            "count": len(items),
            "total_pages": len(pages),
        }
        return mock.Mock(json=lambda data=data: data)


def _collect(endpoint: str, manager: _FakeManager, monkeypatch: Any, api: _FakeApi, **kwargs: Any) -> list[dict]:
    monkeypatch.setattr(writesonic, "_get", api.get)
    rows: list[dict] = []
    for batch in get_rows(
        api_key="key",
        site_url="https://example.com",
        project_id=None,
        endpoint=endpoint,
        logger=mock.MagicMock(),
        manager=manager,  # type: ignore[arg-type]
        **kwargs,
    ):
        rows.extend(batch)
    return rows


class TestToDate:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (date(2026, 7, 1), date(2026, 7, 1)),
            (datetime(2026, 7, 1, 12, 30, tzinfo=UTC), date(2026, 7, 1)),
            ("2026-07-01", date(2026, 7, 1)),
            ("2026-07-01T12:30:00Z", date(2026, 7, 1)),
            (1782950400, date(2026, 7, 2)),
            ("not-a-date", None),
            (None, None),
            (True, None),
        ],
    )
    def test_to_date(self, value, expected):
        assert _to_date(value) == expected


class TestConfigEndpoints:
    def test_paginates_until_total_pages(self, monkeypatch):
        api = _FakeApi(config_pages=[[{"topic_id": "t1"}], [{"topic_id": "t2"}]])
        rows = _collect("topics", _FakeManager(), monkeypatch, api)
        assert [r["topic_id"] for r in rows] == ["t1", "t2"]
        assert [p["page"] for (_, p) in api.calls] == [1, 2]

    def test_sends_site_url_and_page_size(self, monkeypatch):
        api = _FakeApi(config_pages=[[{"topic_id": "t1"}]])
        _collect("topics", _FakeManager(), monkeypatch, api)
        _, params = api.calls[0]
        assert params["url"] == "https://example.com"
        assert params["size"] == 100
        assert "project_id" not in params

    def test_sends_project_id_when_configured(self, monkeypatch):
        api = _FakeApi(config_pages=[[{"topic_id": "t1"}]])
        monkeypatch.setattr(writesonic, "_get", api.get)
        list(
            get_rows(
                api_key="key",
                site_url="https://example.com",
                project_id="proj-1",
                endpoint="topics",
                logger=mock.MagicMock(),
                manager=_FakeManager(),  # type: ignore[arg-type]
            )
        )
        assert api.calls[0][1]["project_id"] == "proj-1"

    def test_resumes_from_saved_page(self, monkeypatch):
        api = _FakeApi(config_pages=[[{"topic_id": "t1"}], [{"topic_id": "t2"}]])
        rows = _collect("topics", _FakeManager(WritesonicResumeConfig(page=2)), monkeypatch, api)
        # Page 1 was already yielded before the crash; only page 2 is re-fetched.
        assert [r["topic_id"] for r in rows] == ["t2"]
        assert [p["page"] for (_, p) in api.calls] == [2]

    def test_saves_state_after_each_page(self, monkeypatch):
        api = _FakeApi(config_pages=[[{"topic_id": "t1"}], [{"topic_id": "t2"}]])
        manager = _FakeManager()
        _collect("topics", manager, monkeypatch, api)
        assert [(s.date, s.page) for s in manager.saved] == [(None, 2), (None, 3)]

    def test_unknown_endpoint_raises(self, monkeypatch):
        with pytest.raises(ValueError):
            _collect("nonexistent", _FakeManager(), monkeypatch, _FakeApi())


@freeze_time("2026-07-09T12:00:00Z")
class TestDailyEndpoints:
    def test_walks_days_from_watermark_to_today_inclusive(self, monkeypatch):
        # The watermark day is re-fetched: its previous sync may have run mid-day and captured
        # partial data. Skipping it would permanently freeze that day's rows.
        api = _FakeApi(daily_pages={"2026-07-08": [[{"date": "2026-07-08", "website_id": "w1"}]]})
        rows = _collect(
            "performance_summary",
            _FakeManager(),
            monkeypatch,
            api,
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 7, 8),
        )
        assert [p["date"] for (_, p) in api.calls] == ["2026-07-08", "2026-07-09"]
        assert rows == [{"date": "2026-07-08", "website_id": "w1"}]

    def test_first_sync_starts_at_default_lookback(self, monkeypatch):
        api = _FakeApi()
        _collect(
            "performance_summary",
            _FakeManager(),
            monkeypatch,
            api,
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )
        assert api.calls[0][1]["date"] == "2025-07-09"
        assert api.calls[-1][1]["date"] == "2026-07-09"

    def test_future_cursor_clamped_to_today(self, monkeypatch):
        api = _FakeApi()
        _collect(
            "performance_summary",
            _FakeManager(),
            monkeypatch,
            api,
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2027, 1, 1),
        )
        assert [p["date"] for (_, p) in api.calls] == ["2026-07-09"]

    def test_paginates_within_a_day(self, monkeypatch):
        api = _FakeApi(
            daily_pages={
                "2026-07-09": [
                    [{"date": "2026-07-09", "website_id": "w1"}],
                    [{"date": "2026-07-09", "website_id": "w2"}],
                ]
            }
        )
        rows = _collect(
            "performance_summary",
            _FakeManager(),
            monkeypatch,
            api,
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 7, 9),
        )
        assert [r["website_id"] for r in rows] == ["w1", "w2"]
        assert [p["page"] for (_, p) in api.calls] == [1, 2]

    def test_injects_date_into_content_rows(self, monkeypatch):
        # Content export rows don't carry the export date, but it's part of the primary key,
        # the partition key, and the incremental cursor — a missing column breaks all three.
        api = _FakeApi(daily_pages={"2026-07-09": [[{"citation_id": "c1"}]]})
        rows = _collect(
            "content_citations",
            _FakeManager(),
            monkeypatch,
            api,
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 7, 9),
        )
        assert rows == [{"citation_id": "c1", "date": "2026-07-09"}]

    def test_resumes_from_saved_day_and_page(self, monkeypatch):
        api = _FakeApi(
            daily_pages={
                "2026-07-07": [[{"date": "2026-07-07", "website_id": "w1"}]],
                "2026-07-08": [
                    [{"date": "2026-07-08", "website_id": "w1"}],
                    [{"date": "2026-07-08", "website_id": "w2"}],
                ],
            }
        )
        manager = _FakeManager(WritesonicResumeConfig(date="2026-07-08", page=2))
        rows = _collect(
            "performance_summary",
            manager,
            monkeypatch,
            api,
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 7, 7),
        )
        # Completed days and pages are skipped; the resume day continues at its saved page.
        assert [(p["date"], p["page"]) for (_, p) in api.calls] == [("2026-07-08", 2), ("2026-07-09", 1)]
        assert [r["website_id"] for r in rows] == ["w2"]

    def test_saves_state_after_each_page_and_day(self, monkeypatch):
        api = _FakeApi(
            daily_pages={
                "2026-07-08": [
                    [{"date": "2026-07-08", "website_id": "w1"}],
                    [{"date": "2026-07-08", "website_id": "w2"}],
                ]
            }
        )
        manager = _FakeManager()
        _collect(
            "performance_summary",
            manager,
            monkeypatch,
            api,
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 7, 8),
        )
        saved = [(s.date, s.page) for s in manager.saved]
        # Page-level saves point at the next page of the in-flight day; day-level saves point
        # at the next day with page reset, so a crash never skips unread rows.
        assert ("2026-07-08", 2) in saved
        assert ("2026-07-08", 3) in saved
        assert ("2026-07-09", 1) in saved
        assert saved[-1] == ("2026-07-10", 1)


class TestCheckResponse:
    def _response(self, status_code: int, headers: dict[str, str] | None = None) -> Any:
        response = mock.MagicMock()
        response.status_code = status_code
        response.ok = 200 <= status_code < 300
        response.headers = headers or {}
        response.text = "body"
        if not response.ok:
            response.raise_for_status.side_effect = requests.HTTPError(f"{status_code} error", response=response)
        return response

    @pytest.mark.parametrize("status", [429, 500, 502, 503])
    def test_retryable_statuses_raise_retryable_error(self, status):
        with pytest.raises(WritesonicRetryableError):
            _check_response(self._response(status), "https://api.writesonic.com/x", mock.MagicMock())

    def test_retry_after_header_is_carried(self):
        with pytest.raises(WritesonicRetryableError) as exc_info:
            _check_response(
                self._response(429, headers={"Retry-After": "30"}),
                "https://api.writesonic.com/x",
                mock.MagicMock(),
            )
        assert exc_info.value.retry_after == 30.0

    @pytest.mark.parametrize("status", [401, 403, 404, 422])
    def test_terminal_statuses_raise_http_error(self, status):
        with pytest.raises(requests.HTTPError):
            _check_response(self._response(status), "https://api.writesonic.com/x", mock.MagicMock())

    def test_ok_returns_response(self):
        response = self._response(200)
        assert _check_response(response, "https://api.writesonic.com/x", mock.MagicMock()) is response


class TestValidateCredentials:
    def _mock_session(self, status_code: int) -> Any:
        response = mock.MagicMock()
        response.status_code = status_code
        session = mock.MagicMock()
        session.get.return_value = response
        return session

    @pytest.mark.parametrize(
        "status,expected_ok",
        [
            (200, True),
            (401, False),
            (403, False),
            (404, False),
            (422, False),
            (500, False),
        ],
    )
    def test_status_mapping(self, status, expected_ok):
        with mock.patch.object(writesonic, "make_tracked_session", return_value=self._mock_session(status)):
            ok, message = validate_credentials(api_key="key", site_url="https://example.com")
            assert ok is expected_ok
            if not expected_ok:
                assert message

    def test_unreachable_api_fails_gracefully(self):
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with mock.patch.object(writesonic, "make_tracked_session", return_value=session):
            ok, message = validate_credentials(api_key="key", site_url="https://example.com")
            assert ok is False
            assert message is not None and "reach" in message


class TestSourceResponse:
    @pytest.mark.parametrize("endpoint", list(WRITESONIC_ENDPOINTS))
    def test_source_response_matches_endpoint_config(self, endpoint):
        config = WRITESONIC_ENDPOINTS[endpoint]
        response = writesonic_source(
            api_key="key",
            site_url="https://example.com",
            project_id=None,
            endpoint=endpoint,
            logger=mock.MagicMock(),
            manager=mock.MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None

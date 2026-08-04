from datetime import UTC, date, datetime, timedelta

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.openrouter import openrouter
from products.warehouse_sources.backend.temporal.data_imports.sources.openrouter.openrouter import (
    OpenRouterResumeConfig,
    _activity_days,
    _to_date,
    get_rows,
    openrouter_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openrouter.settings import (
    ACTIVITY_RETENTION_DAYS,
    OPENROUTER_ENDPOINTS,
)


def _response(status_code: int, body: dict | None = None, text: str = "") -> mock.Mock:
    response = mock.Mock(spec=requests.Response)
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.text = text
    response.json.return_value = body or {}
    response.request = None
    if not response.ok:
        response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            f"{status_code} Client Error for url: https://openrouter.ai", response=response
        )
    return response


def _no_resume() -> mock.Mock:
    manager = mock.Mock()
    manager.can_resume.return_value = False
    manager.load_state.return_value = None
    return manager


class TestFetch:
    @pytest.fixture(autouse=True)
    def _instant_retry(self):
        # Zero the tenacity backoff so retry tests don't actually sleep.
        with mock.patch.object(openrouter._fetch.retry, "wait", return_value=0):  # type: ignore[attr-defined]
            yield

    @pytest.mark.parametrize("status_code", [429, 500, 502, 503])
    def test_retries_then_succeeds_on_transient_status(self, status_code):
        session = mock.Mock()
        session.get.side_effect = [_response(status_code), _response(200, {"data": []})]

        result = openrouter._fetch(session, "https://openrouter.ai/api/v1/models", {}, mock.Mock())

        assert result == {"data": []}
        assert session.get.call_count == 2

    @pytest.mark.parametrize("status_code", [400, 401, 403, 404])
    def test_client_errors_raise(self, status_code):
        session = mock.Mock()
        session.get.return_value = _response(status_code, text="nope")

        with pytest.raises(requests.exceptions.HTTPError):
            openrouter._fetch(session, "https://openrouter.ai/api/v1/keys", {}, mock.Mock())


class TestGetKeyInfo:
    def test_returns_data_on_200(self):
        session = mock.Mock()
        session.get.return_value = _response(200, {"data": {"is_management_key": True}})
        with mock.patch.object(openrouter, "make_tracked_session", return_value=session):
            assert openrouter.get_key_info("sk-or-x") == {"is_management_key": True}

    @pytest.mark.parametrize("status_code", [401, 403, 500])
    def test_returns_none_on_non_200(self, status_code):
        session = mock.Mock()
        session.get.return_value = _response(status_code)
        with mock.patch.object(openrouter, "make_tracked_session", return_value=session):
            assert openrouter.get_key_info("sk-or-x") is None

    def test_validate_credentials_wraps_get_key_info(self):
        with mock.patch.object(openrouter, "get_key_info", return_value={"is_management_key": False}):
            assert openrouter.validate_credentials("sk-or-x") is True
        with mock.patch.object(openrouter, "get_key_info", return_value=None):
            assert openrouter.validate_credentials("sk-or-x") is False


class TestToDate:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("2026-06-15", date(2026, 6, 15)),
            ("2026-06-15T12:00:00Z", date(2026, 6, 15)),
            (date(2026, 6, 15), date(2026, 6, 15)),
            (datetime(2026, 6, 15, 8, tzinfo=UTC), date(2026, 6, 15)),
            ("not-a-date", None),
            (None, None),
        ],
    )
    def test_coercion(self, value, expected):
        assert _to_date(value) == expected


class TestActivityDays:
    def test_full_window_when_no_watermark(self):
        yesterday = datetime.now(UTC).date() - timedelta(days=1)
        days = list(_activity_days(should_use_incremental_field=False, db_incremental_field_last_value=None))
        assert len(days) == ACTIVITY_RETENTION_DAYS
        assert days[-1] == yesterday
        assert days[0] == yesterday - timedelta(days=ACTIVITY_RETENTION_DAYS - 1)
        assert days == sorted(days)  # ascending

    def test_watermark_inside_window_refetches_from_watermark(self):
        yesterday = datetime.now(UTC).date() - timedelta(days=1)
        watermark = yesterday - timedelta(days=3)
        days = list(_activity_days(True, watermark))
        # The watermark day itself is re-fetched (it may have been partial); merge dedupes.
        assert days[0] == watermark
        assert days[-1] == yesterday

    def test_stale_watermark_clamped_to_retention_window(self):
        watermark = datetime.now(UTC).date() - timedelta(days=90)
        days = list(_activity_days(True, watermark))
        assert len(days) == ACTIVITY_RETENTION_DAYS

    def test_future_watermark_yields_nothing(self):
        watermark = datetime.now(UTC).date() + timedelta(days=5)
        assert list(_activity_days(True, watermark)) == []


class TestActivityRows:
    def test_pulls_each_day_and_saves_state_after_yield(self):
        manager = _no_resume()
        calls: list[str] = []

        def fake_fetch(session, url, headers, logger):
            calls.append(url)
            return {"data": [{"date": "2026-06-01", "endpoint_id": "e1"}]}

        with mock.patch.object(openrouter, "_fetch", side_effect=fake_fetch):
            batches = list(
                get_rows(
                    "sk-or-x",
                    "activity",
                    mock.Mock(),
                    manager,
                    should_use_incremental_field=False,
                    db_incremental_field_last_value=None,
                )
            )

        assert len(batches) == ACTIVITY_RETENTION_DAYS
        assert all("date=" in url for url in calls)
        # State saved once per day, after each yield.
        assert manager.save_state.call_count == ACTIVITY_RETENTION_DAYS
        assert isinstance(manager.save_state.call_args.args[0], OpenRouterResumeConfig)

    def test_resume_skips_already_completed_days(self):
        yesterday = datetime.now(UTC).date() - timedelta(days=1)
        already_done = yesterday - timedelta(days=1)

        manager = mock.Mock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = OpenRouterResumeConfig(date=already_done.isoformat())

        fetched_dates: list[str] = []

        def fake_fetch(session, url, headers, logger):
            fetched_dates.append(url.split("date=")[1])
            return {"data": []}

        with mock.patch.object(openrouter, "_fetch", side_effect=fake_fetch):
            list(
                get_rows(
                    "sk-or-x",
                    "activity",
                    mock.Mock(),
                    manager,
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=(yesterday - timedelta(days=10)).isoformat(),
                )
            )

        # Only the day after the completed bookmark (yesterday) is fetched.
        assert fetched_dates == [yesterday.isoformat()]


class TestOffsetPagination:
    def test_offset_limit_stops_on_short_page(self):
        # organization_members sends `limit`, so a page shorter than the limit is the last page.
        manager = _no_resume()
        page1 = {"data": [{"id": f"m{i}"} for i in range(100)]}
        page2 = {"data": [{"id": "m100"}]}

        def fake_fetch(session, url, headers, logger):
            return page1 if "offset=0" in url else page2

        with mock.patch.object(openrouter, "_fetch", side_effect=fake_fetch):
            batches = list(get_rows("sk-or-x", "organization_members", mock.Mock(), manager))

        assert [len(b) for b in batches] == [100, 1]
        # State saved after the first full page, not after the short page.
        assert manager.save_state.call_count == 1

    def test_offset_only_stops_on_empty_page(self):
        # api_keys doesn't send `limit` (unknown server page size), so it walks until an empty page.
        manager = _no_resume()
        seen: list[str] = []

        def fake_fetch(session, url, headers, logger):
            seen.append(url)
            return {"data": [{"hash": f"k{i}"} for i in range(100)]} if "offset=0" in url else {"data": []}

        with mock.patch.object(openrouter, "_fetch", side_effect=fake_fetch):
            batches = list(get_rows("sk-or-x", "api_keys", mock.Mock(), manager))

        assert [len(b) for b in batches] == [100]
        assert any("offset=100" in u for u in seen)
        assert manager.save_state.call_count == 1

    def test_resume_from_saved_offset(self):
        manager = mock.Mock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = OpenRouterResumeConfig(offset=100)
        seen: list[str] = []

        def fake_fetch(session, url, headers, logger):
            seen.append(url)
            return {"data": [{"hash": "k"}]} if "offset=100" in url else {"data": []}

        with mock.patch.object(openrouter, "_fetch", side_effect=fake_fetch):
            list(get_rows("sk-or-x", "api_keys", mock.Mock(), manager))

        assert "offset=100" in seen[0]

    def test_offset_limit_endpoints_send_limit(self):
        manager = _no_resume()
        urls: list[str] = []

        def fake_fetch(session, url, headers, logger):
            urls.append(url)
            return {"data": []}

        with mock.patch.object(openrouter, "_fetch", side_effect=fake_fetch):
            list(get_rows("sk-or-x", "organization_members", mock.Mock(), manager))

        assert "limit=" in urls[0]


class TestSingleAndSingleton:
    def test_models_yields_list(self):
        manager = _no_resume()
        with mock.patch.object(openrouter, "_fetch", return_value={"data": [{"id": "a"}, {"id": "b"}]}):
            batches = list(get_rows("sk-or-x", "models", mock.Mock(), manager))
        assert batches == [[{"id": "a"}, {"id": "b"}]]

    def test_credits_singleton_wrapped_in_list(self):
        manager = _no_resume()
        with mock.patch.object(openrouter, "_fetch", return_value={"data": {"total_credits": 10, "total_usage": 3}}):
            batches = list(get_rows("sk-or-x", "credits", mock.Mock(), manager))
        assert batches == [[{"total_credits": 10, "total_usage": 3}]]


class TestSourceResponse:
    @pytest.mark.parametrize(
        "endpoint,expected_keys", [(name, cfg.primary_keys) for name, cfg in OPENROUTER_ENDPOINTS.items()]
    )
    def test_primary_keys_match_settings(self, endpoint, expected_keys):
        response = openrouter_source("sk-or-x", endpoint, mock.Mock(), _no_resume())
        assert response.primary_keys == expected_keys
        assert response.sort_mode == "asc"

    def test_activity_partitions_on_date(self):
        response = openrouter_source("sk-or-x", "activity", mock.Mock(), _no_resume())
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["date"]

    def test_catalog_tables_not_partitioned(self):
        response = openrouter_source("sk-or-x", "models", mock.Mock(), _no_resume())
        assert response.partition_mode is None
        assert response.partition_keys is None

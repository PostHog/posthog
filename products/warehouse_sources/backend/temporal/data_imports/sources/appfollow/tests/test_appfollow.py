from datetime import UTC, date, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.appfollow import appfollow
from products.warehouse_sources.backend.temporal.data_imports.sources.appfollow.appfollow import (
    APPFOLLOW_BASE_URL,
    AppfollowResumeConfig,
    _clamp_future_value_to_now,
    _extract_rows,
    _to_date_str,
    _to_datetime_str,
    appfollow_source,
    get_rows,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appfollow.settings import APPFOLLOW_ENDPOINTS


class _FakeManager:
    def __init__(self, state: AppfollowResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[AppfollowResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> AppfollowResumeConfig | None:
        return self._state

    def save_state(self, data: AppfollowResumeConfig) -> None:
        self.saved.append(data)


class _FakeApi:
    """Canned AppFollow responses plus a record of every request the transport made."""

    def __init__(
        self,
        collections: list[dict[str, Any]],
        apps_by_collection: dict[Any, list[dict[str, Any]]],
        reviews_pages: dict[str, list[list[dict[str, Any]]]] | None = None,
        ratings_pages: dict[str, list[list[dict[str, Any]]]] | None = None,
    ) -> None:
        self.collections = collections
        self.apps_by_collection = apps_by_collection
        self.reviews_pages = reviews_pages or {}
        self.ratings_pages = ratings_pages or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def fetch(self, session: Any, url: str, params: dict[str, Any], logger: Any) -> Any:
        self.calls.append((url, params))
        if url.endswith("/account/apps/app"):
            return {"apps_app": self.apps_by_collection.get(params["apps_id"], [])}
        if url.endswith("/account/apps"):
            return {"apps": self.collections}
        if url.endswith("/reviews"):
            pages = self.reviews_pages.get(params["ext_id"], [])
            page = params["page"]
            rows = pages[page - 1] if 1 <= page <= len(pages) else []
            return {"reviews": rows, "pages_count": len(pages)}
        if url.endswith("/meta/ratings/history"):
            pages = self.ratings_pages.get(params["ext_id"], [])
            index = params["offset"] // params["limit"]
            return {"ratings": pages[index] if 0 <= index < len(pages) else []}
        raise AssertionError(f"unexpected url {url}")


def _collect(endpoint: str, manager: _FakeManager, monkeypatch: Any, api: _FakeApi, **kwargs: Any) -> list[dict]:
    monkeypatch.setattr(appfollow, "_fetch", api.fetch)
    monkeypatch.setattr(appfollow, "make_tracked_session", lambda **k: mock.MagicMock())
    rows: list[dict] = []
    for batch in get_rows(
        api_key="tok",
        endpoint=endpoint,
        logger=mock.MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **kwargs,
    ):
        rows.extend(batch)
    return rows


class TestExtractRows:
    @pytest.mark.parametrize(
        "data,key,expected",
        [
            ([{"a": 1}], None, [{"a": 1}]),
            ({"reviews": [{"a": 1}]}, "reviews", [{"a": 1}]),
            ({"other": [1]}, "reviews", []),
            ({"detail": "Invalid API token"}, "reviews", []),
            ("boom", None, []),
            ({"reviews": None}, "reviews", []),
        ],
    )
    def test_extract_rows(self, data, key, expected):
        assert _extract_rows(data, key) == expected


class TestDateFormatting:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (datetime(2024, 3, 4, 2, 58, 14, tzinfo=UTC), "2024-03-04"),
            (date(2024, 3, 4), "2024-03-04"),
            ("2024-03-04T05:06:07", "2024-03-04"),
            ("not-a-date", None),
            (None, None),
        ],
    )
    def test_to_date_str(self, value, expected):
        assert _to_date_str(value) == expected

    @pytest.mark.parametrize(
        "value,expected",
        [
            (datetime(2024, 3, 4, 2, 58, 14, tzinfo=UTC), "2024-03-04 02:58:14"),
            (datetime(2024, 3, 4, 2, 58, 14), "2024-03-04 02:58:14"),
            (date(2024, 3, 4), "2024-03-04 00:00:00"),
            (None, None),
        ],
    )
    def test_to_datetime_str(self, value, expected):
        assert _to_datetime_str(value) == expected


class TestClampFutureValueToNow:
    @freeze_time("2026-06-15T12:00:00Z")
    def test_future_datetime_is_clamped(self):
        assert _clamp_future_value_to_now(datetime(2027, 1, 1, tzinfo=UTC)) == datetime(2026, 6, 15, 12, 0, tzinfo=UTC)

    @freeze_time("2026-06-15T12:00:00Z")
    def test_past_datetime_is_unchanged(self):
        value = datetime(2024, 3, 4, tzinfo=UTC)
        assert _clamp_future_value_to_now(value) == value

    @freeze_time("2026-06-15T12:00:00Z")
    def test_future_date_is_clamped(self):
        assert _clamp_future_value_to_now(date(2027, 1, 1)) == date(2026, 6, 15)


def _one_app_api(
    reviews_pages: dict[str, list[list[dict[str, Any]]]] | None = None,
    ratings_pages: dict[str, list[list[dict[str, Any]]]] | None = None,
    ext_id: str = "111",
    store: str | None = "gp",
) -> _FakeApi:
    return _FakeApi(
        collections=[{"id": 10, "title": "Team", "title_normalized": "team"}],
        apps_by_collection={10: [{"app_id": 1, "ext_id": ext_id, "store": store, "app": {}}]},
        reviews_pages=reviews_pages,
        ratings_pages=ratings_pages,
    )


class TestAppDiscovery:
    def test_iter_apps_enriches_ext_id_store_and_collection(self, monkeypatch):
        # ext_id/store nested under `app` must be lifted to the top level, and collection context stamped.
        api = _FakeApi(
            collections=[{"id": 10, "title": "Team", "title_normalized": "team"}],
            apps_by_collection={10: [{"app_id": 1, "app": {"ext_id": "999", "store": "as"}}]},
        )
        rows = _collect("app_lists", _FakeManager(), monkeypatch, api)
        assert len(rows) == 1
        assert rows[0]["ext_id"] == "999"
        assert rows[0]["store"] == "as"
        assert rows[0]["app_collection_id"] == 10
        assert rows[0]["collection_name"] == "team"


class TestReviewsFanOut:
    def test_paginates_and_injects_ext_id(self, monkeypatch):
        api = _one_app_api(reviews_pages={"111": [[{"review_id": "r1"}], [{"review_id": "r2"}]]})
        rows = _collect(
            "reviews",
            _FakeManager(),
            monkeypatch,
            api,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        assert [r["review_id"] for r in rows] == ["r1", "r2"]
        # ext_id is injected so the [ext_id, review_id] primary key is always populated.
        assert all(r["ext_id"] == "111" for r in rows)
        review_calls = [p for (u, p) in api.calls if u.endswith("/reviews")]
        assert [p["page"] for p in review_calls] == [1, 2]
        assert all(p["ext_id"] == "111" for p in review_calls)

    def test_first_sync_sends_no_last_modified(self, monkeypatch):
        api = _one_app_api(reviews_pages={"111": [[{"review_id": "r1"}]]})
        _collect(
            "reviews",
            _FakeManager(),
            monkeypatch,
            api,
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )
        review_params = next(p for (u, p) in api.calls if u.endswith("/reviews"))
        assert "last_modified" not in review_params

    def test_incremental_sync_sends_last_modified(self, monkeypatch):
        api = _one_app_api(reviews_pages={"111": [[{"review_id": "r1"}]]})
        _collect(
            "reviews",
            _FakeManager(),
            monkeypatch,
            api,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 3, 4, 5, 6, 7, tzinfo=UTC),
        )
        review_params = next(p for (u, p) in api.calls if u.endswith("/reviews"))
        assert review_params["last_modified"] == "2024-03-04 05:06:07"

    def test_same_app_in_two_collections_fetched_once(self, monkeypatch):
        # Reviews key on ext_id alone; an app shared across collections must not be paid for twice.
        api = _FakeApi(
            collections=[{"id": 10, "title_normalized": "a"}, {"id": 20, "title_normalized": "b"}],
            apps_by_collection={
                10: [{"app_id": 1, "ext_id": "111", "store": "gp", "app": {}}],
                20: [{"app_id": 1, "ext_id": "111", "store": "gp", "app": {}}],
            },
            reviews_pages={"111": [[{"review_id": "r1"}]]},
        )
        _collect(
            "reviews",
            _FakeManager(),
            monkeypatch,
            api,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        review_calls = [p for (u, p) in api.calls if u.endswith("/reviews")]
        assert len(review_calls) == 1

    def test_resume_starts_from_saved_page(self, monkeypatch):
        api = _one_app_api(reviews_pages={"111": [[{"review_id": "r1"}], [{"review_id": "r2"}]]})
        manager = _FakeManager(AppfollowResumeConfig(ext_id="111", cursor=2))
        rows = _collect(
            "reviews",
            manager,
            monkeypatch,
            api,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        # Page 1 is skipped on resume; only page 2 is re-fetched.
        assert [r["review_id"] for r in rows] == ["r2"]
        assert [p["page"] for (u, p) in api.calls if u.endswith("/reviews")] == [2]

    def test_saves_state_after_yielding_each_page(self, monkeypatch):
        api = _one_app_api(reviews_pages={"111": [[{"review_id": "r1"}], [{"review_id": "r2"}]]})
        manager = _FakeManager()
        _collect(
            "reviews",
            manager,
            monkeypatch,
            api,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        # State is saved so a mid-sync crash resumes at the next page rather than restarting the app.
        assert AppfollowResumeConfig(ext_id="111", cursor=2) in manager.saved


class TestRatingsFanOut:
    def test_offset_pagination_injects_ext_id_and_store(self, monkeypatch):
        api = _one_app_api(ratings_pages={"111": [[{"date": "2024-01-01"}] * 100, [{"date": "2024-02-01"}]]})
        rows = _collect(
            "ratings_history",
            _FakeManager(),
            monkeypatch,
            api,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        assert len(rows) == 101
        assert all(r["ext_id"] == "111" and r["store"] == "gp" for r in rows)
        offsets = [p["offset"] for (u, p) in api.calls if u.endswith("/meta/ratings/history")]
        # Second page fetched at offset=100 because the first returned a full page.
        assert offsets == [0, 100]

    def test_incremental_from_uses_watermark(self, monkeypatch):
        api = _one_app_api(ratings_pages={"111": [[{"date": "2024-05-02"}]]})
        _collect(
            "ratings_history",
            _FakeManager(),
            monkeypatch,
            api,
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2024, 5, 1),
        )
        params = next(p for (u, p) in api.calls if u.endswith("/meta/ratings/history"))
        assert params["from"] == "2024-05-01"
        assert params["store"] == "gp"

    def test_app_without_store_is_skipped(self, monkeypatch):
        # Ratings history requires a store; an app we can't resolve one for must not 422 the whole sync.
        api = _one_app_api(ratings_pages={"111": [[{"date": "2024-01-01"}]]}, store=None)
        rows = _collect(
            "ratings_history",
            _FakeManager(),
            monkeypatch,
            api,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        assert rows == []
        assert not any(u.endswith("/meta/ratings/history") for (u, _) in api.calls)


class TestFetchRetryClassification:
    def _session_returning(self, status_code: int, json_body: Any = None) -> Any:
        response = mock.MagicMock()
        response.status_code = status_code
        response.ok = 200 <= status_code < 300
        response.json.return_value = json_body if json_body is not None else {}
        if not response.ok:
            response.raise_for_status.side_effect = requests.HTTPError(f"{status_code} error", response=response)
        session = mock.MagicMock()
        session.get.return_value = response
        return session

    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_retryable_statuses_raise_retryable_error(self, status):
        session = self._session_returning(status)
        with mock.patch.object(appfollow._fetch.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(appfollow.AppfollowRetryableError):
                appfollow._fetch(session, f"{APPFOLLOW_BASE_URL}/reviews", {}, mock.MagicMock())

    @pytest.mark.parametrize("status", [401, 402, 403])
    def test_credential_statuses_raise_http_error(self, status):
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            appfollow._fetch(session, f"{APPFOLLOW_BASE_URL}/account/apps", {}, mock.MagicMock())

    def test_ok_returns_json(self):
        session = self._session_returning(200, {"apps": []})
        assert appfollow._fetch(session, f"{APPFOLLOW_BASE_URL}/account/apps", {}, mock.MagicMock()) == {"apps": []}


class TestSourceResponse:
    @pytest.mark.parametrize("endpoint", list(APPFOLLOW_ENDPOINTS))
    def test_source_response_matches_endpoint_config(self, endpoint):
        config = APPFOLLOW_ENDPOINTS[endpoint]
        response = appfollow_source(
            api_key="tok",
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=mock.MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None

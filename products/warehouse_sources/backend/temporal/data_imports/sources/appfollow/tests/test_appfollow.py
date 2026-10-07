from datetime import UTC, date, datetime
from typing import Any, Protocol

import pytest
import time_machine
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.appfollow import appfollow
from products.warehouse_sources.backend.temporal.data_imports.sources.appfollow.appfollow import (
    APPFOLLOW_BASE_URL,
    APPFOLLOW_V3_BASE_URL,
    AppfollowResumeConfig,
    _clamp_future_value_to_now,
    _extract_rows,
    _resolve_country,
    _to_date_str,
    _to_datetime_str,
    appfollow_source,
    get_rows,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appfollow.settings import (
    APPFOLLOW_ENDPOINTS,
    APPFOLLOW_V2,
    APPFOLLOW_V3,
    DEFAULT_START_DATE,
    endpoints_for_version,
)


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


class _CannedApi(Protocol):
    def fetch(self, session: Any, url: str, params: dict[str, Any], logger: Any) -> Any: ...


def _collect(
    endpoint: str,
    manager: _FakeManager,
    monkeypatch: Any,
    api: _CannedApi,
    api_version: str = APPFOLLOW_V2,
    **kwargs: Any,
) -> list[dict]:
    monkeypatch.setattr(appfollow, "_fetch", api.fetch)
    monkeypatch.setattr(appfollow, "make_tracked_session", lambda **k: mock.MagicMock())
    rows: list[dict] = []
    for batch in get_rows(
        api_key="tok",
        endpoint=endpoint,
        api_version=api_version,
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
            # Endpoints whose envelope AppFollow does not publish pass candidate keys, in order.
            ({"rankings": [{"a": 1}]}, ("ranks", "rankings"), [{"a": 1}]),
            ({"ranks": [{"a": 1}], "rankings": [{"b": 2}]}, ("ranks", "rankings"), [{"a": 1}]),
            # ...and fall back to a root list rather than syncing nothing on a key we guessed wrong.
            ([{"a": 1}], ("ranks", "rankings"), [{"a": 1}]),
            ({"detail": "Not enough credits."}, ("ranks", "rankings"), []),
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
    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_future_datetime_is_clamped(self):
        assert _clamp_future_value_to_now(datetime(2027, 1, 1, tzinfo=UTC)) == datetime(2026, 6, 15, 12, 0, tzinfo=UTC)

    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_past_datetime_is_unchanged(self):
        value = datetime(2024, 3, 4, tzinfo=UTC)
        assert _clamp_future_value_to_now(value) == value

    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
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
    @pytest.mark.parametrize("api_version", [APPFOLLOW_V2, APPFOLLOW_V3])
    @pytest.mark.parametrize("endpoint", list(APPFOLLOW_ENDPOINTS))
    def test_source_response_matches_endpoint_config(self, endpoint, api_version):
        config = endpoints_for_version(api_version)[endpoint]
        response = appfollow_source(
            api_key="tok",
            endpoint=endpoint,
            api_version=api_version,
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


class _FanoutApi:
    """Canned responses for the per-app fan-out endpoints, plus a record of every request made."""

    def __init__(
        self,
        collections: list[dict[str, Any]],
        apps_by_collection: dict[Any, list[dict[str, Any]]],
        pages: list[list[dict[str, Any]]],
        envelope: str,
    ) -> None:
        self.collections = collections
        self.apps_by_collection = apps_by_collection
        self.pages = pages
        self.envelope = envelope
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def fetch(self, session: Any, url: str, params: dict[str, Any], logger: Any) -> Any:
        self.calls.append((url, params))
        if url.endswith("/account/apps/app"):
            return {"apps_app": self.apps_by_collection.get(params["apps_id"], [])}
        if url.endswith("/account/apps"):
            return {"apps": self.collections}
        page = params.get("page", 1)
        rows = self.pages[page - 1] if 1 <= page <= len(self.pages) else []
        return {self.envelope: rows}


def _fanout_api(
    pages: list[list[dict[str, Any]]],
    envelope: str,
    collection: dict[str, Any] | None = None,
    app: dict[str, Any] | None = None,
) -> _FanoutApi:
    return _FanoutApi(
        collections=[collection or {"id": 10, "title_normalized": "team"}],
        apps_by_collection={10: [app or {"app_id": 1, "ext_id": "111", "store": "gp", "app": {}}]},
        pages=pages,
        envelope=envelope,
    )


def _calls_to(api: _FanoutApi, suffix: str) -> list[dict[str, Any]]:
    return [p for (u, p) in api.calls if u.endswith(suffix)]


class TestResolveCountry:
    @pytest.mark.parametrize(
        "collection,app,expected",
        [
            ({}, {"country": "DE"}, "de"),
            ({}, {"app": {"country": "fr"}}, "fr"),
            ({"default_country": "gb"}, {}, "gb"),
            ({"countries": ["jp", "kr"]}, {}, "jp"),
            # `/meta/versions` rejects a request with no country, so there is always a last resort.
            ({}, {}, "us"),
            ({"default_country": "gb", "countries": ["jp"]}, {"country": "de"}, "de"),
        ],
    )
    def test_resolution_order(self, collection, app, expected):
        assert _resolve_country(collection, app) == expected


class TestSnapshotFanOut:
    @time_machine.travel("2026-06-15T09:00:00Z", tick=False)
    def test_rankings_requests_today_once_per_app_and_stamps_the_key_fields(self, monkeypatch):
        # `/meta/rankings` has no pagination and no date range, so one request per app is the whole
        # walk. `ext_id` and `date` are stamped because the primary key and partition key need them.
        api = _fanout_api([[{"position": 3, "genre_id": "6003"}]], envelope="ranks")
        rows = _collect("rankings", _FakeManager(), monkeypatch, api)
        assert rows == [{"position": 3, "genre_id": "6003", "ext_id": "111", "date": "2026-06-15"}]
        params = _calls_to(api, "/meta/rankings")
        assert len(params) == 1
        assert params[0] == {"ext_id": "111", "date": "2026-06-15"}

    @time_machine.travel("2026-06-15T09:00:00Z", tick=False)
    def test_a_row_that_carries_its_own_date_is_not_overwritten(self, monkeypatch):
        api = _fanout_api([[{"keyword": "photos", "date": "2026-06-14"}]], envelope="keywords")
        rows = _collect("keywords", _FakeManager(), monkeypatch, api)
        assert rows[0]["date"] == "2026-06-14"

    def test_keywords_pages_until_a_page_comes_back_empty(self, monkeypatch):
        # The endpoint publishes neither a page count nor a total, so an empty page is the only signal.
        api = _fanout_api([[{"keyword": "a"}], [{"keyword": "b"}]], envelope="keywords")
        rows = _collect("keywords", _FakeManager(), monkeypatch, api)
        assert [r["keyword"] for r in rows] == ["a", "b"]
        assert [p["page"] for p in _calls_to(api, "/aso/keywords")] == [1, 2, 3]

    def test_paging_stops_at_the_cap(self, monkeypatch):
        # An endpoint that never returns an empty page must not spend credits forever.
        monkeypatch.setattr(appfollow, "MAX_PAGES_PER_APP", 3)
        api = _fanout_api([[{"keyword": "a"}]] * 50, envelope="keywords")
        logger = mock.MagicMock()
        monkeypatch.setattr(appfollow, "_fetch", api.fetch)
        monkeypatch.setattr(appfollow, "make_tracked_session", lambda **k: mock.MagicMock())
        list(
            get_rows(
                api_key="tok",
                endpoint="keywords",
                api_version=APPFOLLOW_V2,
                logger=logger,
                resumable_source_manager=_FakeManager(),  # type: ignore[arg-type]
            )
        )
        assert [p["page"] for p in _calls_to(api, "/aso/keywords")] == [1, 2, 3]
        assert logger.warning.called

    def test_resume_starts_from_the_saved_page(self, monkeypatch):
        api = _fanout_api([[{"keyword": "a"}], [{"keyword": "b"}]], envelope="keywords")
        rows = _collect("keywords", _FakeManager(AppfollowResumeConfig(ext_id="111", cursor=2)), monkeypatch, api)
        assert [r["keyword"] for r in rows] == ["b"]


class TestCountryScopedFanOut:
    def test_app_versions_sends_and_stamps_the_resolved_country(self, monkeypatch):
        # `country` is required by the endpoint and is part of the primary key, so it must be both
        # sent and present on every row.
        api = _fanout_api(
            [[{"version": "2.1.0"}]],
            envelope="versions",
            collection={"id": 10, "title_normalized": "team", "countries": ["gb"]},
        )
        rows = _collect("app_versions", _FakeManager(), monkeypatch, api)
        assert rows[0] == {"version": "2.1.0", "ext_id": "111", "country": "gb"}
        assert _calls_to(api, "/meta/versions")[0] == {"ext_id": "111", "country": "gb", "page": 1}

    def test_one_app_tracked_in_two_countries_is_fetched_per_country(self, monkeypatch):
        # Unlike reviews, versions vary by country, so de-duplicating on ext_id alone would drop data.
        api = _FanoutApi(
            collections=[
                {"id": 10, "title_normalized": "eu", "countries": ["gb"]},
                {"id": 20, "title_normalized": "us", "countries": ["us"]},
            ],
            apps_by_collection={
                10: [{"app_id": 1, "ext_id": "111", "store": "as", "app": {}}],
                20: [{"app_id": 1, "ext_id": "111", "store": "as", "app": {}}],
            },
            pages=[[{"version": "2.1.0"}]],
            envelope="versions",
        )
        _collect("app_versions", _FakeManager(), monkeypatch, api)
        assert sorted(p["country"] for p in _calls_to(api, "/meta/versions") if p["page"] == 1) == ["gb", "us"]


class TestWindowedFanOut:
    @time_machine.travel("2026-06-15T09:00:00Z", tick=False)
    def test_full_refresh_opens_the_whole_window(self, monkeypatch):
        api = _fanout_api([[{"date": "2026-06-01", "reviews": 4}]], envelope="stats")
        _collect(
            "reviews_stats",
            _FakeManager(),
            monkeypatch,
            api,
            should_use_incremental_field=False,
            db_incremental_field_last_value=date(2026, 6, 10),
        )
        params = _calls_to(api, "/reviews/stats")[0]
        assert params == {"ext_id": "111", "from": DEFAULT_START_DATE, "to": "2026-06-15"}

    @time_machine.travel("2026-06-15T09:00:00Z", tick=False)
    def test_incremental_sync_moves_from_to_the_watermark(self, monkeypatch):
        api = _fanout_api([[{"date": "2026-06-11", "reviews": 4}]], envelope="stats")
        _collect(
            "reviews_stats",
            _FakeManager(),
            monkeypatch,
            api,
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 6, 10),
        )
        assert _calls_to(api, "/reviews/stats")[0]["from"] == "2026-06-10"

    @time_machine.travel("2026-06-15T09:00:00Z", tick=False)
    def test_a_future_watermark_is_clamped_so_the_table_cannot_freeze(self, monkeypatch):
        api = _fanout_api([[{"date": "2026-06-11"}]], envelope="stats")
        _collect(
            "reviews_stats",
            _FakeManager(),
            monkeypatch,
            api,
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2027, 1, 1),
        )
        assert _calls_to(api, "/reviews/stats")[0]["from"] == "2026-06-15"


class _FakeV3Api:
    """Canned AppFollow v3 responses, shaped from the v3 reference, plus a record of every request."""

    def __init__(
        self,
        workspaces: list[dict[str, Any]],
        apps_by_workspace: dict[int, list[dict[str, Any]]] | None = None,
        review_pages_by_workspace: dict[int, list[list[dict[str, Any]]]] | None = None,
    ) -> None:
        self.workspaces = workspaces
        self.apps_by_workspace = apps_by_workspace or {}
        self.review_pages_by_workspace = review_pages_by_workspace or {}
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def fetch(self, session: Any, url: str, params: dict[str, Any], logger: Any) -> Any:
        self.calls.append(("GET", url, params))
        if url == f"{APPFOLLOW_V3_BASE_URL}/workspaces":
            # Reverse the map order so only `sortedCollections` can produce creation order.
            return {
                "collections": {w["collectionCode"]: w for w in reversed(self.workspaces)},
                "sortedCollections": [w["collectionCode"] for w in self.workspaces],
            }
        if url == f"{APPFOLLOW_V3_BASE_URL}/workspaces/apps":
            return {"apps": [dict(app) for app in self.apps_by_workspace.get(params["appsId"], [])]}
        raise AssertionError(f"unexpected GET {url}")

    def post(self, session: Any, url: str, body: dict[str, Any], logger: Any) -> Any:
        self.calls.append(("POST", url, body))
        assert url == f"{APPFOLLOW_V3_BASE_URL}/reviews/feed", url
        pages = self.review_pages_by_workspace.get(body["appsId"], [])
        index = int(body.get("cursor", "0"))
        rows = [dict(row) for row in pages[index]] if index < len(pages) else []
        return {"reviews": rows, "nextCursor": str(index + 1) if index + 1 < len(pages) else None}

    def requests_to(self, path: str) -> list[dict[str, Any]]:
        return [payload for (_, url, payload) in self.calls if url == f"{APPFOLLOW_V3_BASE_URL}{path}"]


def _v3_review(review_id: int, created: str, version: str = "1.0") -> dict[str, Any]:
    return {
        "id": review_id,
        "reviewId": f"store-{review_id}",
        "itemId": 7,
        "content": "Great app",
        "metaInformation": {"store": "as", "extId": "111", "rating": 5, "created": created, "version": version},
        "tags": {"tagDetails": []},
    }


def _collect_v3(
    endpoint: str, api: _FakeV3Api, monkeypatch: Any, manager: _FakeManager | None = None, **kwargs: Any
) -> list[dict]:
    monkeypatch.setattr(appfollow, "_post", api.post)
    return _collect(endpoint, manager or _FakeManager(), monkeypatch, api, api_version=APPFOLLOW_V3, **kwargs)


_WORKSPACES = [
    {"collectionId": 10, "collectionCode": "first", "collectionName": "First"},
    {"collectionId": 20, "collectionCode": "second", "collectionName": "Second"},
]


class TestV3Wire:
    def test_app_collections_reads_the_workspace_map_in_creation_order(self, monkeypatch):
        api = _FakeV3Api(_WORKSPACES)
        rows = _collect_v3("app_collections", api, monkeypatch)
        assert [r["collectionId"] for r in rows] == [10, 20]
        assert not any(url.startswith(APPFOLLOW_BASE_URL) for (_, url, _) in api.calls)

    def test_app_lists_fans_out_per_workspace_and_stamps_the_workspace_key(self, monkeypatch):
        api = _FakeV3Api(
            _WORKSPACES,
            apps_by_workspace={10: [{"itemId": 1, "extId": "111"}], 20: [{"itemId": 1, "extId": "222"}]},
        )
        rows = _collect_v3("app_lists", api, monkeypatch)
        assert [(r["collectionId"], r["itemId"], r["extId"]) for r in rows] == [(10, 1, "111"), (20, 1, "222")]
        assert [p["appsId"] for p in api.requests_to("/workspaces/apps")] == [10, 20]

    def test_reviews_follow_the_cursor_and_lift_the_v2_key_columns(self, monkeypatch):
        api = _FakeV3Api(
            _WORKSPACES[:1],
            review_pages_by_workspace={
                10: [[_v3_review(1, "2024-01-02T00:00:00Z")], [_v3_review(2, "2024-01-03T00:00:00Z", "2.0")]]
            },
        )
        rows = _collect_v3("reviews", api, monkeypatch, should_use_incremental_field=False)
        assert [(r["id"], r["date"], r["app_version"], r["rating"]) for r in rows] == [
            (1, "2024-01-02T00:00:00Z", "1.0", 5),
            (2, "2024-01-03T00:00:00Z", "2.0", 5),
        ]
        assert all("metaInformation" not in r for r in rows)
        bodies = api.requests_to("/reviews/feed")
        assert [b.get("cursor") for b in bodies] == [None, "1"]
        assert all(b["appsId"] == 10 and b["from"] == DEFAULT_START_DATE for b in bodies)

    @time_machine.travel("2026-06-15T09:00:00Z", tick=False)
    def test_incremental_reviews_move_from_to_the_watermark(self, monkeypatch):
        api = _FakeV3Api(_WORKSPACES[:1], review_pages_by_workspace={10: [[_v3_review(1, "2026-06-12T00:00:00Z")]]})
        _collect_v3(
            "reviews",
            api,
            monkeypatch,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 10, 8, tzinfo=UTC),
        )
        body = api.requests_to("/reviews/feed")[0]
        assert (body["from"], body["to"]) == ("2026-06-10", "2026-06-15")

    def test_reviews_resume_at_the_saved_workspace_and_cursor(self, monkeypatch):
        api = _FakeV3Api(
            _WORKSPACES,
            review_pages_by_workspace={
                10: [[_v3_review(1, "2024-01-01T00:00:00Z")]],
                20: [[_v3_review(2, "2024-01-01T00:00:00Z")], [_v3_review(3, "2024-01-02T00:00:00Z")]],
            },
        )
        manager = _FakeManager(AppfollowResumeConfig(collection_id=20, page_cursor="1"))
        rows = _collect_v3("reviews", api, monkeypatch, manager=manager)
        assert [r["id"] for r in rows] == [3]
        assert [(b["appsId"], b.get("cursor")) for b in api.requests_to("/reviews/feed")] == [(20, "1")]

    def test_reviews_stage_the_next_bookmark_before_each_batch(self, monkeypatch):
        api = _FakeV3Api(
            _WORKSPACES,
            review_pages_by_workspace={
                10: [[_v3_review(1, "2024-01-01T00:00:00Z")], [_v3_review(2, "2024-01-02T00:00:00Z")]],
                20: [[_v3_review(3, "2024-01-01T00:00:00Z")]],
            },
        )
        manager = _FakeManager()
        monkeypatch.setattr(appfollow, "_post", api.post)
        monkeypatch.setattr(appfollow, "_fetch", api.fetch)
        monkeypatch.setattr(appfollow, "make_tracked_session", lambda **k: mock.MagicMock())
        saved_before_batch = []
        for _ in get_rows(
            api_key="tok",
            endpoint="reviews",
            api_version=APPFOLLOW_V3,
            logger=mock.MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            saved_before_batch.append(manager.saved[-1] if manager.saved else None)
        assert saved_before_batch == [
            AppfollowResumeConfig(collection_id=10, page_cursor="1"),
            AppfollowResumeConfig(collection_id=20),
            AppfollowResumeConfig(collection_id=20),
        ]

    def test_reviews_paging_stops_at_the_cap(self, monkeypatch):
        monkeypatch.setattr(appfollow, "MAX_REVIEW_FEED_PAGES_PER_WORKSPACE", 3)
        api = _FakeV3Api(
            _WORKSPACES[:1],
            review_pages_by_workspace={10: [[_v3_review(n, "2024-01-01T00:00:00Z")] for n in range(50)]},
        )
        rows = _collect_v3("reviews", api, monkeypatch)
        assert [r["id"] for r in rows] == [0, 1, 2]

    def test_tables_without_a_v3_endpoint_stay_on_the_v2_wire(self, monkeypatch):
        api = _one_app_api(ratings_pages={"111": [[{"date": "2024-01-01"}]]})
        rows = _collect("ratings_history", _FakeManager(), monkeypatch, api, api_version=APPFOLLOW_V3)
        assert len(rows) == 1
        assert {url for (url, _) in api.calls} == {
            f"{APPFOLLOW_BASE_URL}/account/apps",
            f"{APPFOLLOW_BASE_URL}/account/apps/app",
            f"{APPFOLLOW_BASE_URL}/meta/ratings/history",
        }

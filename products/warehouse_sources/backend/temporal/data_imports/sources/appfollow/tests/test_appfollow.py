from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.appfollow import appfollow
from products.warehouse_sources.backend.temporal.data_imports.sources.appfollow.appfollow import (
    APPFOLLOW_BASE_URL,
    AppfollowResumeConfig,
    _extract_rows,
    _to_date_str,
    _to_datetime_str,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appfollow.settings import (
    APPFOLLOW_ENDPOINTS,
    APPFOLLOW_V2,
    APPFOLLOW_V3,
    DEFAULT_START_DATE,
    endpoints_for_version,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appfollow.source import AppfollowSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    Script,
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.appfollow import (
    AppfollowSourceConfig,
)


def _run(
    endpoint: str,
    script: Script,
    *,
    api_version: str = APPFOLLOW_V2,
    resume_state: AppfollowResumeConfig | None = None,
    **inputs: Any,
) -> DriveResult:
    return SourceDriver(AppfollowSource(), AppfollowSourceConfig(api_key="tok")).run(
        endpoint, script, api_version=api_version, resume_state=resume_state, **inputs
    )


def _requests_to(result: DriveResult, suffix: str) -> list[RecordedRequest]:
    return [request for request in result.requests if request.path.endswith(suffix)]


class _V2Api:
    def __init__(
        self,
        collections: list[dict[str, Any]],
        apps_by_collection: dict[int, list[dict[str, Any]]],
        *,
        reviews_pages: dict[str, list[list[dict[str, Any]]]] | None = None,
        ratings_pages: dict[str, list[list[dict[str, Any]]]] | None = None,
        fanout_pages: list[list[dict[str, Any]]] | None = None,
        fanout_envelope: str = "",
    ) -> None:
        self.collections = collections
        self.apps_by_collection = apps_by_collection
        self.reviews_pages = reviews_pages or {}
        self.ratings_pages = ratings_pages or {}
        self.fanout_pages = fanout_pages or []
        self.fanout_envelope = fanout_envelope

    def __call__(self, request: RecordedRequest) -> ScriptedResponse:
        assert request.method == "GET"
        if request.path.endswith("/account/apps/app"):
            return ScriptedResponse(
                json={"apps_app": self.apps_by_collection.get(int(request.param("apps_id") or 0), [])}
            )
        if request.path.endswith("/account/apps"):
            return ScriptedResponse(json={"apps": self.collections})
        ext_id = request.param("ext_id") or ""
        if request.path.endswith("/reviews"):
            pages = self.reviews_pages.get(ext_id, [])
            page = int(request.param("page") or 1)
            rows = pages[page - 1] if 1 <= page <= len(pages) else []
            return ScriptedResponse(json={"reviews": rows, "pages_count": len(pages)})
        if request.path.endswith("/meta/ratings/history"):
            pages = self.ratings_pages.get(ext_id, [])
            index = int(request.param("offset") or 0) // int(request.param("limit") or 100)
            rows = pages[index] if 0 <= index < len(pages) else []
            return ScriptedResponse(json={"ratings": rows})
        if self.fanout_envelope:
            page = int(request.param("page") or 1)
            rows = self.fanout_pages[page - 1] if 1 <= page <= len(self.fanout_pages) else []
            return ScriptedResponse(json={self.fanout_envelope: rows})
        raise AssertionError(f"unexpected request {request.path}")


def _one_app_api(
    reviews_pages: dict[str, list[list[dict[str, Any]]]] | None = None,
    ratings_pages: dict[str, list[list[dict[str, Any]]]] | None = None,
    ext_id: str = "111",
    store: str | None = "gp",
) -> _V2Api:
    return _V2Api(
        collections=[{"id": 10, "title": "Team", "title_normalized": "team"}],
        apps_by_collection={10: [{"app_id": 1, "ext_id": ext_id, "store": store, "app": {}}]},
        reviews_pages=reviews_pages,
        ratings_pages=ratings_pages,
    )


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
    def test_extract_rows(self, data: Any, key: str | tuple[str, ...] | None, expected: list[dict[str, Any]]) -> None:
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
    def test_to_date_str(self, value: Any, expected: str | None) -> None:
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
    def test_to_datetime_str(self, value: Any, expected: str | None) -> None:
        assert _to_datetime_str(value) == expected


class TestAppDiscovery:
    def test_iter_apps_enriches_ext_id_store_and_collection(self) -> None:
        # ext_id/store nested under `app` must be lifted to the top level, and collection context stamped.
        api = _V2Api(
            collections=[{"id": 10, "title": "Team", "title_normalized": "team"}],
            apps_by_collection={10: [{"app_id": 1, "app": {"ext_id": "999", "store": "as"}}]},
        )
        result = _run("app_lists", api)
        assert result.raised is None
        assert len(result.rows) == 1
        assert result.rows[0]["ext_id"] == "999"
        assert result.rows[0]["store"] == "as"
        assert result.rows[0]["app_collection_id"] == 10
        assert result.rows[0]["collection_name"] == "team"


class TestReviewsFanOut:
    def test_paginates_and_injects_ext_id(self) -> None:
        api = _one_app_api(reviews_pages={"111": [[{"review_id": "r1"}], [{"review_id": "r2"}]]})
        result = _run("reviews", api, should_use_incremental_field=False)
        assert result.raised is None
        assert [row["review_id"] for row in result.rows] == ["r1", "r2"]
        # ext_id is injected so the [ext_id, review_id] primary key is always populated.
        assert all(row["ext_id"] == "111" for row in result.rows)
        review_requests = _requests_to(result, "/reviews")
        assert [request.param("page") for request in review_requests] == ["1", "2"]
        assert all(request.param("ext_id") == "111" for request in review_requests)

    def test_incremental_sync_sends_last_modified(self) -> None:
        api = _one_app_api(reviews_pages={"111": [[{"review_id": "r1"}]]})
        result = _run(
            "reviews",
            api,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 3, 4, 5, 6, 7, tzinfo=UTC),
        )
        assert result.raised is None
        assert _requests_to(result, "/reviews")[0].param("last_modified") == "2024-03-04 05:06:07"

    def test_same_app_in_two_collections_fetched_once(self) -> None:
        # Reviews key on ext_id alone; an app shared across collections must not be paid for twice.
        api = _V2Api(
            collections=[{"id": 10, "title_normalized": "a"}, {"id": 20, "title_normalized": "b"}],
            apps_by_collection={
                10: [{"app_id": 1, "ext_id": "111", "store": "gp", "app": {}}],
                20: [{"app_id": 1, "ext_id": "111", "store": "gp", "app": {}}],
            },
            reviews_pages={"111": [[{"review_id": "r1"}]]},
        )
        result = _run("reviews", api, should_use_incremental_field=False)
        assert result.raised is None
        assert len(_requests_to(result, "/reviews")) == 1

    def test_resume_starts_from_saved_page(self) -> None:
        api = _one_app_api(reviews_pages={"111": [[{"review_id": "r1"}], [{"review_id": "r2"}]]})
        result = _run(
            "reviews",
            api,
            resume_state=AppfollowResumeConfig(ext_id="111", cursor=2),
            should_use_incremental_field=False,
        )
        # Page 1 is skipped on resume; only page 2 is re-fetched.
        assert result.raised is None
        assert [row["review_id"] for row in result.rows] == ["r2"]
        assert [request.param("page") for request in _requests_to(result, "/reviews")] == ["2"]


class TestRatingsFanOut:
    def test_offset_pagination_injects_ext_id_and_store(self) -> None:
        api = _one_app_api(ratings_pages={"111": [[{"date": "2024-01-01"}] * 100, [{"date": "2024-02-01"}]]})
        result = _run("ratings_history", api, should_use_incremental_field=False)
        assert result.raised is None
        assert len(result.rows) == 101
        assert all(row["ext_id"] == "111" and row["store"] == "gp" for row in result.rows)
        # Second page fetched at offset=100 because the first returned a full page.
        assert [request.param("offset") for request in _requests_to(result, "/meta/ratings/history")] == ["0", "100"]

    def test_incremental_from_uses_watermark(self) -> None:
        api = _one_app_api(ratings_pages={"111": [[{"date": "2024-05-02"}]]})
        result = _run(
            "ratings_history", api, should_use_incremental_field=True, db_incremental_field_last_value=date(2024, 5, 1)
        )
        assert result.raised is None
        request = _requests_to(result, "/meta/ratings/history")[0]
        assert request.param("from") == "2024-05-01"
        assert request.param("store") == "gp"

    def test_app_without_store_is_skipped(self) -> None:
        # Ratings history requires a store; an app we can't resolve one for must not 422 the whole sync.
        api = _one_app_api(ratings_pages={"111": [[{"date": "2024-01-01"}]]}, store=None)
        result = _run("ratings_history", api, should_use_incremental_field=False)
        assert result.raised is None
        assert result.rows == []
        assert not _requests_to(result, "/meta/ratings/history")


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
    def test_retryable_statuses_raise_retryable_error(self, status: int) -> None:
        session = self._session_returning(status)
        with mock.patch.object(appfollow._fetch.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(appfollow.AppfollowRetryableError):
                appfollow._fetch(session, f"{APPFOLLOW_BASE_URL}/reviews", {}, mock.MagicMock())

    @pytest.mark.parametrize("status", [401, 402, 403])
    def test_credential_statuses_raise_http_error(self, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            appfollow._fetch(session, f"{APPFOLLOW_BASE_URL}/account/apps", {}, mock.MagicMock())

    def test_ok_returns_json(self) -> None:
        session = self._session_returning(200, {"apps": []})
        assert appfollow._fetch(session, f"{APPFOLLOW_BASE_URL}/account/apps", {}, mock.MagicMock()) == {"apps": []}


class TestSourceResponse:
    @pytest.mark.parametrize("api_version", [APPFOLLOW_V2, APPFOLLOW_V3])
    @pytest.mark.parametrize("endpoint", list(APPFOLLOW_ENDPOINTS))
    def test_source_response_matches_endpoint_config(self, endpoint: str, api_version: str) -> None:
        config = endpoints_for_version(api_version)[endpoint]
        result = _run(endpoint, lambda _: ScriptedResponse(json={}), api_version=api_version)
        response = result.response
        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None


class TestSnapshotFanOut:
    def test_paging_stops_at_the_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # An endpoint that never returns an empty page must not spend credits forever.
        monkeypatch.setattr(appfollow, "MAX_PAGES_PER_APP", 3)
        api = _V2Api(
            collections=[{"id": 10, "title_normalized": "team"}],
            apps_by_collection={10: [{"app_id": 1, "ext_id": "111", "store": "gp", "app": {}}]},
            fanout_pages=[[{"keyword": "a"}]] * 50,
            fanout_envelope="keywords",
        )
        logger = mock.MagicMock()
        result = _run("keywords", api, logger=logger)
        assert result.raised is None
        assert [request.param("page") for request in _requests_to(result, "/aso/keywords")] == ["1", "2", "3"]
        assert logger.warning.called


class TestCountryScopedFanOut:
    def test_one_app_tracked_in_two_countries_is_fetched_per_country(self) -> None:
        # Unlike reviews, versions vary by country, so de-duplicating on ext_id alone would drop data.
        api = _V2Api(
            collections=[
                {"id": 10, "title_normalized": "eu", "countries": ["gb"]},
                {"id": 20, "title_normalized": "us", "countries": ["us"]},
            ],
            apps_by_collection={
                10: [{"app_id": 1, "ext_id": "111", "store": "as", "app": {}}],
                20: [{"app_id": 1, "ext_id": "111", "store": "as", "app": {}}],
            },
            fanout_pages=[[{"version": "2.1.0"}]],
            fanout_envelope="versions",
        )
        result = _run("app_versions", api)
        assert result.raised is None
        assert sorted(
            str(request.param("country"))
            for request in _requests_to(result, "/meta/versions")
            if request.param("page") == "1"
        ) == ["gb", "us"]


class TestWindowedFanOut:
    @time_machine.travel("2026-06-15T09:00:00Z", tick=False)
    def test_a_future_watermark_is_clamped_so_the_table_cannot_freeze(self) -> None:
        api = _V2Api(
            collections=[{"id": 10, "title_normalized": "team"}],
            apps_by_collection={10: [{"app_id": 1, "ext_id": "111", "store": "gp", "app": {}}]},
            fanout_pages=[[{"date": "2026-06-11"}]],
            fanout_envelope="stats",
        )
        result = _run(
            "reviews_stats", api, should_use_incremental_field=True, db_incremental_field_last_value=date(2027, 1, 1)
        )
        assert result.raised is None
        assert _requests_to(result, "/reviews/stats")[0].param("from") == "2026-06-15"


class _V3Api:
    def __init__(
        self,
        workspaces: list[dict[str, Any]],
        apps_by_workspace: dict[int, list[dict[str, Any]]] | None = None,
        review_pages_by_workspace: dict[int, list[list[dict[str, Any]]]] | None = None,
    ) -> None:
        self.workspaces = workspaces
        self.apps_by_workspace = apps_by_workspace or {}
        self.review_pages_by_workspace = review_pages_by_workspace or {}

    def __call__(self, request: RecordedRequest) -> ScriptedResponse:
        if request.path == "/api/v3/workspaces":
            # Reverse the map order so only `sortedCollections` can produce creation order.
            return ScriptedResponse(
                json={
                    "collections": {workspace["collectionCode"]: workspace for workspace in reversed(self.workspaces)},
                    "sortedCollections": [workspace["collectionCode"] for workspace in self.workspaces],
                }
            )
        if request.path == "/api/v3/workspaces/apps":
            assert request.method == "GET"
            return ScriptedResponse(json={"apps": self.apps_by_workspace.get(int(request.param("appsId") or 0), [])})
        if request.path == "/api/v3/reviews/feed":
            assert request.method == "POST"
            body = request.json()
            pages = self.review_pages_by_workspace.get(body["appsId"], [])
            index = int(body.get("cursor", "0"))
            rows = pages[index] if index < len(pages) else []
            next_cursor = str(index + 1) if index + 1 < len(pages) else None
            return ScriptedResponse(json={"reviews": rows, "nextCursor": next_cursor})
        raise AssertionError(f"unexpected request {request.path}")


def _v3_review(review_id: int, created: str, version: str = "1.0") -> dict[str, Any]:
    return {
        "id": review_id,
        "reviewId": f"store-{review_id}",
        "itemId": 7,
        "content": "Great app",
        "metaInformation": {"store": "as", "extId": "111", "rating": 5, "created": created, "version": version},
        "tags": {"tagDetails": []},
    }


_WORKSPACES = [
    {"collectionId": 10, "collectionCode": "first", "collectionName": "First"},
    {"collectionId": 20, "collectionCode": "second", "collectionName": "Second"},
]


class TestV3Wire:
    def test_app_collections_reads_the_workspace_map_in_creation_order(self) -> None:
        api = _V3Api(_WORKSPACES)
        result = _run("app_collections", api, api_version=APPFOLLOW_V3)
        assert result.raised is None
        assert [row["collectionId"] for row in result.rows] == [10, 20]
        assert not any(url.startswith(APPFOLLOW_BASE_URL) for url in result.urls)

    def test_app_lists_fans_out_per_workspace_and_stamps_the_workspace_key(self) -> None:
        api = _V3Api(
            _WORKSPACES,
            apps_by_workspace={10: [{"itemId": 1, "extId": "111"}], 20: [{"itemId": 1, "extId": "222"}]},
        )
        result = _run("app_lists", api, api_version=APPFOLLOW_V3)
        assert result.raised is None
        assert [(row["collectionId"], row["itemId"], row["extId"]) for row in result.rows] == [
            (10, 1, "111"),
            (20, 1, "222"),
        ]
        assert [request.param("appsId") for request in _requests_to(result, "/workspaces/apps")] == ["10", "20"]

    def test_reviews_follow_the_cursor_and_lift_the_v2_key_columns(self) -> None:
        api = _V3Api(
            _WORKSPACES[:1],
            review_pages_by_workspace={
                10: [[_v3_review(1, "2024-01-02T00:00:00Z")], [_v3_review(2, "2024-01-03T00:00:00Z", "2.0")]]
            },
        )
        result = _run("reviews", api, api_version=APPFOLLOW_V3, should_use_incremental_field=False)
        assert result.raised is None
        assert [(row["id"], row["date"], row["app_version"], row["rating"]) for row in result.rows] == [
            (1, "2024-01-02T00:00:00Z", "1.0", 5),
            (2, "2024-01-03T00:00:00Z", "2.0", 5),
        ]
        assert all("metaInformation" not in row for row in result.rows)
        bodies = [request.json() for request in _requests_to(result, "/reviews/feed")]
        assert [body.get("cursor") for body in bodies] == [None, "1"]
        assert all(body["appsId"] == 10 and body["from"] == DEFAULT_START_DATE for body in bodies)

    @time_machine.travel("2026-06-15T09:00:00Z", tick=False)
    def test_incremental_reviews_move_from_to_the_watermark(self) -> None:
        api = _V3Api(_WORKSPACES[:1], review_pages_by_workspace={10: [[_v3_review(1, "2026-06-12T00:00:00Z")]]})
        result = _run(
            "reviews",
            api,
            api_version=APPFOLLOW_V3,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 10, 8, tzinfo=UTC),
        )
        assert result.raised is None
        body = _requests_to(result, "/reviews/feed")[0].json()
        assert (body["from"], body["to"]) == ("2026-06-10", "2026-06-15")

    def test_reviews_resume_at_the_saved_workspace_and_cursor(self) -> None:
        api = _V3Api(
            _WORKSPACES,
            review_pages_by_workspace={
                10: [[_v3_review(1, "2024-01-01T00:00:00Z")]],
                20: [[_v3_review(2, "2024-01-01T00:00:00Z")], [_v3_review(3, "2024-01-02T00:00:00Z")]],
            },
        )
        result = _run(
            "reviews",
            api,
            api_version=APPFOLLOW_V3,
            resume_state=AppfollowResumeConfig(collection_id=20, page_cursor="1"),
        )
        assert result.raised is None
        assert [row["id"] for row in result.rows] == [3]
        assert [
            (request.json()["appsId"], request.json().get("cursor"))
            for request in _requests_to(result, "/reviews/feed")
        ] == [(20, "1")]

    def test_reviews_stage_the_next_bookmark_before_each_batch(self) -> None:
        api = _V3Api(
            _WORKSPACES,
            review_pages_by_workspace={
                10: [[_v3_review(1, "2024-01-01T00:00:00Z")], [_v3_review(2, "2024-01-02T00:00:00Z")]],
                20: [[_v3_review(3, "2024-01-01T00:00:00Z")]],
            },
        )
        result = _run("reviews", api, api_version=APPFOLLOW_V3)
        assert result.raised is None
        assert [[row["id"] for row in batch] for batch in result.items] == [[1], [2], [3]]
        assert result.saved_states == [
            AppfollowResumeConfig(collection_id=10, page_cursor="1"),
            AppfollowResumeConfig(collection_id=20),
        ]
        assert result.committed_states == result.saved_states

    def test_reviews_paging_stops_at_the_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(appfollow, "MAX_REVIEW_FEED_PAGES_PER_WORKSPACE", 3)
        api = _V3Api(
            _WORKSPACES[:1],
            review_pages_by_workspace={10: [[_v3_review(n, "2024-01-01T00:00:00Z")] for n in range(50)]},
        )
        result = _run("reviews", api, api_version=APPFOLLOW_V3)
        assert result.raised is None
        assert [row["id"] for row in result.rows] == [0, 1, 2]

    def test_tables_without_a_v3_endpoint_stay_on_the_v2_wire(self) -> None:
        api = _one_app_api(ratings_pages={"111": [[{"date": "2024-01-01"}]]})
        result = _run("ratings_history", api, api_version=APPFOLLOW_V3)
        assert result.raised is None
        assert len(result.rows) == 1
        assert {request.url.split("?")[0] for request in result.requests} == {
            f"{APPFOLLOW_BASE_URL}/account/apps",
            f"{APPFOLLOW_BASE_URL}/account/apps/app",
            f"{APPFOLLOW_BASE_URL}/meta/ratings/history",
        }

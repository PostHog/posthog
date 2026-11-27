from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
import time_machine
from unittest import mock

import requests

from products.warehouse_sources.sources.appfollow import appfollow
from products.warehouse_sources.sources.appfollow._config import AppfollowSourceConfig
from products.warehouse_sources.sources.appfollow.appfollow import (
    APPFOLLOW_BASE_URL,
    AppfollowResumeConfig,
    AppfollowScanCursor,
    _extract_rows,
    _to_date_str,
    _to_datetime_str,
)
from products.warehouse_sources.sources.appfollow.settings import (
    APPFOLLOW_ENDPOINTS,
    APPFOLLOW_V2,
    APPFOLLOW_V3,
    DEFAULT_START_DATE,
    endpoints_for_version,
)
from products.warehouse_sources.sources.appfollow.source import AppfollowSource
from products.warehouse_sources.sources.sdk import SourceCursorManager
from products.warehouse_sources.sources.sdk.testing import (
    DriveResult,
    RecordedRequest,
    Script,
    ScriptedResponse,
    SourceDriver,
    activate_safe_point,
    scripted_network,
    source_inputs,
)


def _run(
    endpoint: str,
    script: Script,
    *,
    api_version: str = APPFOLLOW_V2,
    resume_state: AppfollowResumeConfig | None = None,
    **inputs: Any,
) -> DriveResult:
    if endpoint == "console_ratings":
        inputs.setdefault("source_cursor", SourceCursorManager(AppfollowScanCursor, None, AppfollowSource()))
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
        assert response.sort_mode == (None if config.kind in ("dated_fanout", "console_ratings") else "asc")
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


def _dated_api(
    respond: Callable[[RecordedRequest], dict[str, Any] | ScriptedResponse], ext_ids: tuple[str, ...] = ("111",)
) -> Script:
    discovery = _V2Api(
        collections=[{"id": 10, "title_normalized": "team"}],
        apps_by_collection={
            10: [{"app_id": n, "ext_id": ext_id, "store": "as", "app": {}} for n, ext_id in enumerate(ext_ids)]
        },
    )

    def script(request: RecordedRequest) -> ScriptedResponse:
        if request.path.endswith(("/account/apps", "/account/apps/app")):
            return discovery(request)
        response = respond(request)
        return response if isinstance(response, ScriptedResponse) else ScriptedResponse(json=response)

    return script


class TestDatedFanOut:
    @pytest.mark.parametrize(
        "endpoint,path,body",
        [
            (
                "reviews_replies_speed",
                "/reviews/stats/replies/speed",
                {"replies_time_stat": [{"answer_user_id": "10"}]},
            ),
            ("reviews_version_stats", "/reviews/stats/version", {"tags_stat": {"versions": ["0.1"], "tags": []}}),
        ],
    )
    @time_machine.travel("2026-06-15T09:00:00Z", tick=False)
    def test_daily_walk_requests_each_day_from_the_lookback_and_stamps_the_day(
        self, endpoint: str, path: str, body: dict[str, Any]
    ) -> None:
        api = _dated_api(lambda request: body)
        result = _run(
            endpoint,
            api,
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 6, 13),
        )
        assert result.raised is None
        days = [request.param("date") for request in _requests_to(result, path)]
        assert days == [(date(2026, 6, 6) + timedelta(days=n)).isoformat() for n in range(10)]
        assert [row["date"] for row in result.rows] == days
        assert all(row["ext_id"] == "111" for row in result.rows)

    @pytest.mark.parametrize(
        "endpoint,path,window_days",
        [
            ("reviews_version_stats", "/reviews/stats/version", 1),
            ("console_ratings", "/meta/ratings/console/gp", 14),
        ],
    )
    @pytest.mark.parametrize("watermark", [None, date(2026, 4, 15)])
    @time_machine.travel("2026-06-15T09:00:00Z", tick=False)
    def test_initial_backfill_does_not_cut_off_dates_after_an_interruption(
        self, endpoint: str, path: str, window_days: int, watermark: date | None
    ) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            return ScriptedResponse(
                json={
                    "tags_stat": {"tags": []},
                    "fields": {request.param("fields"): [{"date": request.param("from"), "value": 1}]},
                }
            )

        script = _console_api(respond) if endpoint == "console_ratings" else _dated_api(respond)
        result = _run(endpoint, script, should_use_incremental_field=True, db_incremental_field_last_value=watermark)
        assert result.raised is None
        requests_ = _requests_to(result, path)
        if endpoint == "console_ratings":
            requests_ = [
                r for r in requests_ if r.param("collection_name") == "first" and r.param("fields") == "ratings"
            ]
        windows = [
            (
                date.fromisoformat(r.param("from") or r.param("date") or ""),
                date.fromisoformat(r.param("to") or r.param("date") or ""),
            )
            for r in requests_
        ]
        assert windows[0][0] == (date(2026, 4, 8) if watermark else date(2026, 5, 16))
        assert windows[-1][1] == date(2026, 6, 15)
        assert all((end - start).days < window_days for start, end in windows)
        assert all(nxt[0] == prev[1] + timedelta(days=1) for prev, nxt in zip(windows, windows[1:]))

    @time_machine.travel("2026-06-15T09:00:00Z", tick=False)
    def test_window_backfill_is_split_into_requests_of_one_month_at_most(self) -> None:
        api = _dated_api(lambda request: {"data": [{"date": request.param("from"), "channel": "Web Referrer"}]})
        result = _run("aso_reports", api, should_use_incremental_field=True, db_incremental_field_last_value=None)
        assert result.raised is None
        requests_ = _requests_to(result, "/reports/aso")
        windows = [
            (date.fromisoformat(r.param("from") or ""), date.fromisoformat(r.param("to") or "")) for r in requests_
        ]
        assert windows[0][0] == date(2025, 6, 15)
        assert windows[-1][1] == date(2026, 6, 15)
        assert all((end - start).days < 30 for start, end in windows)
        assert all(nxt[0] == prev[1] + timedelta(days=1) for prev, nxt in zip(windows, windows[1:]))
        assert all(r.param("channel") == "channel" and r.param("period") == "daily" for r in requests_)

    @time_machine.travel("2026-06-15T09:00:00Z", tick=False)
    def test_a_stale_watermark_scans_no_further_back_than_the_backfill_window(self) -> None:
        # An app with no rows for months keeps the watermark still; the daily scan must not grow with it.
        api = _dated_api(lambda request: {"rating_stat": []})
        result = _run(
            "reviews_ratings_stats",
            api,
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 1, 1),
        )
        assert result.raised is None
        days = [request.param("date") for request in _requests_to(result, "/reviews/stats/ratings")]
        assert days[0] == "2026-05-16"
        assert len(days) == 31

    @time_machine.travel("2026-06-15T09:00:00Z", tick=False)
    def test_an_app_without_the_aso_integration_is_skipped_not_fatal(self) -> None:
        def respond(request: RecordedRequest) -> dict[str, Any] | ScriptedResponse:
            if request.param("ext_id") == "111":
                return ScriptedResponse(status=424, body=b"Check you settings: App Store Connect")
            return {"data": [{"date": "2026-06-10", "channel": "Web Referrer"}]}

        result = _run(
            "aso_reports",
            _dated_api(respond, ext_ids=("111", "222")),
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 6, 14),
        )
        assert result.raised is None
        assert [row["ext_id"] for row in result.rows] == ["222"]
        assert [request.param("ext_id") for request in _requests_to(result, "/reports/aso")] == ["111", "222"]

    @time_machine.travel("2026-06-15T09:00:00Z", tick=False)
    def test_resume_starts_at_the_saved_app_and_day_and_stages_the_next_bookmark_before_each_batch(self) -> None:
        api = _dated_api(
            lambda request: {"rating_stat": [{"answer_user_id": "10", "ext_id": request.param("ext_id")}]},
            ext_ids=("111", "222"),
        )
        result = _run(
            "reviews_ratings_stats",
            api,
            resume_state=AppfollowResumeConfig(ext_id="222", slice_start="2026-06-14"),
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 6, 14),
        )
        assert result.raised is None
        assert [
            (request.param("ext_id"), request.param("date"))
            for request in _requests_to(result, "/reviews/stats/ratings")
        ] == [("222", "2026-06-14"), ("222", "2026-06-15")]
        assert result.saved_states == [AppfollowResumeConfig(ext_id="222", slice_start="2026-06-15")]

    @pytest.mark.parametrize(
        "endpoint,body,expected",
        [
            (
                "reviews_replies_stats",
                {"store": "as", "user_stat": {"tags": 16, "replies": [{"answer_user_id": "10", "cnt": 3}]}},
                [{"tags": 16, "replies": [{"answer_user_id": "10", "cnt": 3}], "ext_id": "111", "date": "2026-06-15"}],
            ),
            ("reviews_replies_stats", {"detail": "Not enough credits."}, []),
            (
                "reviews_replies_count",
                {"list": {"became_worse": [{"id": 1}], "became_better": [{"id": 2}, "junk"]}, "query": {}},
                [
                    {"id": 1, "rating_change": "became_worse", "ext_id": "111"},
                    {"id": 2, "rating_change": "became_better", "ext_id": "111"},
                ],
            ),
            (
                "reviews_semantic",
                {"reviews": [{"review_id": 5, "sentiment": "Negative", "tags": ["Bugs"]}]},
                [{"review_id": 5, "sentiment": "Negative", "tags": ["Bugs"], "ext_id": "111"}],
            ),
            (
                "reviews_version_stats",
                {"tags_stat": {"tags": [{"version": "0.1", "count": 2}], "bt_tags": [], "versions": ["0.1"]}},
                [
                    {
                        "tags": [{"version": "0.1", "count": 2}],
                        "bt_tags": [],
                        "versions": ["0.1"],
                        "ext_id": "111",
                        "date": "2026-06-15",
                    }
                ],
            ),
        ],
    )
    @time_machine.travel("2026-06-15T09:00:00Z", tick=False)
    def test_rows_are_shaped_from_each_envelope(
        self, endpoint: str, body: dict[str, Any], expected: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(appfollow, "DATED_FANOUT_LOOKBACK_DAYS", 0)
        result = _run(
            endpoint,
            _dated_api(lambda request: body),
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 6, 22),
        )
        assert result.raised is None
        assert result.rows == expected


class TestFeaturedApps:
    @pytest.mark.parametrize("resume_country", [None, "gb"])
    @time_machine.travel("2026-06-15T09:00:00Z", tick=False)
    def test_features_keep_the_app_and_country_scope_when_resuming(self, resume_country: str | None) -> None:
        discovery = _V2Api(
            collections=[{"id": 10, "countries": ["us"]}, {"id": 20, "countries": ["gb"]}],
            apps_by_collection={
                10: [{"ext_id": "111", "store": "as"}, {"ext_id": "example.app", "store": "gp"}],
                20: [{"ext_id": "111", "store": "as"}, {"ext_id": "111", "store": "as"}],
            },
        )

        def script(request: RecordedRequest) -> ScriptedResponse:
            if not request.path.endswith("/aso/featured"):
                return discovery(request)
            return ScriptedResponse(
                json={
                    "data": {
                        "111": {"data": [{"title": "Example collection", "date": "2026-06-10", "pos": 2}, None]},
                        "other.app": {"data": [{"title": "Unrelated app"}]},
                    }
                }
            )

        resume = AppfollowResumeConfig(ext_id="111", country=resume_country) if resume_country else None
        result = _run("featured_apps", script, resume_state=resume)
        assert result.raised is None
        expected_countries = ["gb"] if resume_country else ["us", "gb"]
        requests_ = _requests_to(result, "/aso/featured")
        assert [r.param("country") for r in requests_] == expected_countries
        assert all(r.param("ext_id") == "111" for r in requests_)
        assert all((r.param("from"), r.param("to")) == ("2025-06-15", "2026-06-15") for r in requests_)
        assert result.rows == [
            {"title": "Example collection", "date": "2026-06-10", "pos": 2, "ext_id": "111", "country": country}
            for country in expected_countries
        ]
        assert result.saved_states == ([] if resume_country else [AppfollowResumeConfig(ext_id="111", country="gb")])
        assert result.committed_states == ([resume] if resume else result.saved_states)

    @pytest.mark.parametrize("body", [{"data": {}}, {"data": {"111": {"data": []}}}, {"data": None}])
    def test_empty_feature_history_yields_no_rows(self, body: dict[str, Any]) -> None:
        result = _run("featured_apps", _dated_api(lambda _: body))
        assert result.raised is None
        assert result.rows == []


def _console_api(respond: Callable[[RecordedRequest], ScriptedResponse]) -> Script:
    discovery = _V2Api(
        collections=[{"id": 10, "title_normalized": "first"}, {"id": 20, "title_normalized": "second"}],
        apps_by_collection={
            10: [{"ext_id": "example.app", "store": "gp"}, {"ext_id": "111", "store": "as"}],
            20: [{"ext_id": "example.app", "store": "gp"}, {"ext_id": "example.app", "store": "gp"}],
        },
    )

    def script(request: RecordedRequest) -> ScriptedResponse:
        return respond(request) if request.path.endswith("/meta/ratings/console/gp") else discovery(request)

    return script


class TestConsoleRatings:
    @pytest.mark.parametrize(
        "watermark,next_day,next_watermark",
        [
            (None, date(2026, 6, 16), None),
            (date(2026, 4, 15), date(2026, 6, 16), date(2026, 4, 15)),
            (None, date(2026, 7, 31), None),
            (date(2026, 4, 15), date(2026, 7, 31), date(2026, 7, 30)),
        ],
    )
    @time_machine.travel("2026-06-15T09:00:00Z", tick=False)
    def test_empty_scans_persist_coverage_across_jobs(
        self, watermark: date | None, next_day: date, next_watermark: date | None
    ) -> None:
        source = AppfollowSource()
        cursor = SourceCursorManager(AppfollowScanCursor, None, source)
        script = _console_api(lambda _: ScriptedResponse(json={"fields": {"ratings": None, "users": None}}))
        first = _run(
            "console_ratings",
            script,
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
            source_cursor=cursor,
        )
        assert first.raised is None
        assert first.rows == []
        assert _requests_to(first, "/meta/ratings/console/gp")[0].param("from") == (
            "2026-04-08" if watermark else "2026-05-16"
        )
        payload = cursor.staged_payload()
        assert payload is not None
        next_cursor = SourceCursorManager.from_sync_type_config(
            source, {"source_cursor": payload}, source_inputs("console_ratings").logger
        )
        with time_machine.travel(next_day, tick=False):
            second = _run(
                "console_ratings",
                script,
                job_id="00000000-0000-4000-8000-000000000004",
                should_use_incremental_field=True,
                db_incremental_field_last_value=next_watermark,
                source_cursor=next_cursor,
            )
        assert second.raised is None
        assert second.rows == []
        requests_ = _requests_to(second, "/meta/ratings/console/gp")
        windows = [
            (start.isoformat(), min(start + timedelta(days=13), next_day).isoformat())
            for start in (
                date(2026, 6, 8) + timedelta(days=offset)
                for offset in range(0, (next_day - date(2026, 6, 8)).days + 1, 14)
            )
        ]
        assert [(r.param("from"), r.param("to")) for r in requests_] == [
            window for _ in range(2) for window in windows for _ in range(2)
        ]

    @time_machine.travel("2026-06-15T09:00:00Z", tick=False)
    def test_failed_scan_does_not_advance_coverage(self) -> None:
        source = AppfollowSource()
        cursor = SourceCursorManager(AppfollowScanCursor, None, source)

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.param("collection_name") == "second":
                return ScriptedResponse(status=403, json={"detail": "Forbidden"})
            return ScriptedResponse(json={"fields": {"ratings": None, "users": None}})

        failed = _run(
            "console_ratings",
            _console_api(respond),
            source_cursor=cursor,
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 4, 15),
        )
        assert isinstance(failed.raised, requests.HTTPError)
        assert cursor.staged_payload() is None
        retry = _run(
            "console_ratings",
            _console_api(lambda _: ScriptedResponse(json={"fields": {}})),
            source_cursor=SourceCursorManager(AppfollowScanCursor, cursor.load(), source),
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 4, 15),
        )
        assert retry.raised is None
        assert _requests_to(retry, "/meta/ratings/console/gp")[0].param("from") == "2026-04-08"

    @pytest.mark.parametrize("incremental", [False, True])
    @time_machine.travel("2026-06-16T09:00:00Z", tick=False)
    def test_scan_coverage_is_specific_to_each_app_and_ignored_for_full_refresh(self, incremental: bool) -> None:
        source = AppfollowSource()
        stored = AppfollowScanCursor(completed_through={"10:example.app": "2026-06-15"})
        discovery = _V2Api(
            collections=[{"id": 10, "title_normalized": "first"}],
            apps_by_collection={10: [{"ext_id": ext_id, "store": "gp"} for ext_id in ("example.app", "new.app")]},
        )

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path.endswith("/meta/ratings/console/gp"):
                return ScriptedResponse(json={"fields": {}})
            return discovery(request)

        result = _run(
            "console_ratings",
            respond,
            source_cursor=SourceCursorManager(AppfollowScanCursor, stored, source),
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=date(2026, 4, 15),
        )
        assert result.raised is None
        first_dates: dict[str, str | None] = {}
        for request in _requests_to(result, "/meta/ratings/console/gp"):
            first_dates.setdefault(request.param("ext_id") or "", request.param("from"))
        assert first_dates == {
            "example.app": "2026-06-08" if incremental else "2026-05-17",
            "new.app": "2026-04-08" if incremental else "2026-05-17",
        }

    @pytest.mark.parametrize("failed_metric", ["ratings", "users"])
    @time_machine.travel("2026-06-15T09:00:00Z", tick=False)
    def test_missing_integration_skips_to_the_next_collection(self, failed_metric: str) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.param("collection_name") == "first" and request.param("fields") == failed_metric:
                return ScriptedResponse(status=424, json={"detail": "Failed Dependency"})
            return ScriptedResponse(json={"fields": {request.param("fields"): [{"date": "2026-06-15", "value": 1}]}})

        cursor = SourceCursorManager(AppfollowScanCursor, None, AppfollowSource())
        result = _run(
            "console_ratings",
            _console_api(respond),
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 6, 14),
            source_cursor=cursor,
        )
        assert result.raised is None
        assert [(row["collection_name"], row["metric"]) for row in result.rows] == [
            ("second", "ratings"),
            ("second", "users"),
        ]
        assert result.committed_states == [AppfollowResumeConfig(ext_id="example.app", collection_id=20)]
        assert cursor.staged == AppfollowScanCursor(completed_through={"20:example.app": "2026-06-15"})

    @pytest.mark.parametrize("has_google_play_app", [False, True])
    @time_machine.travel("2026-06-15T09:00:00Z", tick=False)
    def test_discovery_reaches_safe_points_between_empty_collections(self, has_google_play_app: bool) -> None:
        discovery = _V2Api(
            collections=[{"id": n, "title_normalized": f"collection-{n}"} for n in range(8)],
            apps_by_collection={7: [{"ext_id": "example.app", "store": "gp"}]} if has_google_play_app else {},
        )

        def script(request: RecordedRequest) -> ScriptedResponse:
            if request.path.endswith("/meta/ratings/console/gp"):
                return ScriptedResponse(
                    json={"fields": {request.param("fields"): [{"date": "2026-06-15", "value": 1}]}}
                )
            return discovery(request)

        source = AppfollowSource()
        inputs = source_inputs("console_ratings", source_cursor=SourceCursorManager(AppfollowScanCursor, None, source))
        manager = source.get_resumable_source_manager(inputs)
        with (
            scripted_network(script) as network,
            activate_safe_point(network.note_progress, covers_framework_checkpoints=False),
        ):
            response = source.source_for_pipeline(AppfollowSourceConfig(api_key="tok"), manager, inputs)
            rows = []
            batches = response.items()
            assert isinstance(batches, Iterable)
            for batch in batches:
                rows.extend(batch)
                network.note_progress()
            assert network.longest_run_without_progress <= 3
            assert len(network.requests_log) >= 9
        assert bool(rows) == has_google_play_app

    @pytest.mark.parametrize("incremental", [False, True])
    @time_machine.travel("2026-06-15T09:00:00Z", tick=False)
    def test_both_metrics_keep_the_collection_and_walk_the_date_windows(self, incremental: bool) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            metric = request.param("fields")
            return ScriptedResponse(
                json={
                    "fields": {metric: [{"date": request.param("from"), "value": 4.25 if metric == "ratings" else 7}]}
                }
            )

        result = _run(
            "console_ratings",
            _console_api(respond),
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=date(2026, 6, 14),
        )
        assert result.raised is None
        windows = (
            [("2026-06-07", "2026-06-15")]
            if incremental
            else [("2026-05-16", "2026-05-29"), ("2026-05-30", "2026-06-12"), ("2026-06-13", "2026-06-15")]
        )
        requests_ = _requests_to(result, "/meta/ratings/console/gp")
        assert [(r.param("collection_name"), r.param("from"), r.param("to"), r.param("fields")) for r in requests_] == [
            (collection, start, end, metric)
            for collection in ("first", "second")
            for start, end in windows
            for metric in ("ratings", "users")
        ]
        assert all(r.param("ext_id") == "example.app" and r.param("period") == "daily" for r in requests_)
        assert result.rows == [
            {"collection_name": collection, "ext_id": "example.app", "date": start, "metric": metric, "value": value}
            for collection in ("first", "second")
            for start, _ in windows
            for metric, value in (("ratings", 4.25), ("users", 7))
        ]
        assert result.saved_states == [
            *[
                AppfollowResumeConfig(ext_id="example.app", collection_id=10, slice_start=start)
                for start, _ in windows[1:]
            ],
            AppfollowResumeConfig(ext_id="example.app", collection_id=20),
            *[
                AppfollowResumeConfig(ext_id="example.app", collection_id=20, slice_start=start)
                for start, _ in windows[1:]
            ],
        ]
        assert result.committed_states == result.saved_states

    @pytest.mark.parametrize("completed_through", [{}, {"20:example.app": "2026-05-01"}])
    @time_machine.travel("2026-06-15T09:00:00Z", tick=False)
    def test_resume_keeps_the_saved_collection_and_day_with_nullable_metrics(
        self, completed_through: dict[str, str]
    ) -> None:
        result = _run(
            "console_ratings",
            _console_api(lambda _: ScriptedResponse(json={"fields": {"ratings": None}})),
            resume_state=AppfollowResumeConfig(ext_id="example.app", collection_id=20, slice_start="2026-06-14"),
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 6, 14),
            source_cursor=SourceCursorManager(
                AppfollowScanCursor, AppfollowScanCursor(completed_through=completed_through), AppfollowSource()
            ),
        )
        assert result.raised is None
        requests_ = _requests_to(result, "/meta/ratings/console/gp")
        assert [(r.param("collection_name"), r.param("from"), r.param("fields")) for r in requests_] == [
            ("second", "2026-06-14", "ratings"),
            ("second", "2026-06-14", "users"),
        ]
        assert result.rows == []


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

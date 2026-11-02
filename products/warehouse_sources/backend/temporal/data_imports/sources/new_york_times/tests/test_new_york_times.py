from datetime import UTC, date, datetime
from typing import Any

import time_machine
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.newyorktimes import (
    NewYorkTimesSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.new_york_times.new_york_times import (
    ARTICLE_SEARCH_MAX_PAGES,
    NewYorkTimesPageCapError,
    NewYorkTimesResumeConfig,
    NewYorkTimesRetryableError,
    _format_begin_date,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.new_york_times.source import NewYorkTimesSource


def _driver(article_search_query: str | None = None) -> SourceDriver:
    return SourceDriver(
        NewYorkTimesSource(), NewYorkTimesSourceConfig(api_key="KEY", article_search_query=article_search_query)
    )


class TestFormatBeginDate:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "20260304"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "20260304"),
            ("date_value", date(2026, 1, 15), "20260115"),
            ("string_passthrough", "20250101", "20250101"),
        ]
    )
    def test_format_begin_date(self, _name: str, value: object, expected: str) -> None:
        assert _format_begin_date(value) == expected


class TestValidateCredentials:
    @parameterized.expand(
        [
            # A 403 means the key is genuine but the app hasn't enabled this API — must not block create.
            ("forbidden", 403, True),
            ("rate_limited", 429, True),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            assert validate_credentials("KEY") is expected
        assert network.requests_log[0].path == "/svc/mostpopular/v2/viewed/1.json"
        assert network.requests_log[0].param("api-key") == "KEY"


class TestGetRowsSnapshot:
    def test_single_request_yields_results(self) -> None:
        result = _driver().run("top_stories", [ScriptedResponse(json={"results": [{"uri": "u1"}, {"uri": "u2"}]})])

        assert result.raised is None
        assert result.items == [[{"uri": "u1"}, {"uri": "u2"}]]
        assert result.paths == ["/svc/topstories/v2/home.json"]


class TestGetRowsArticleSearch:
    @staticmethod
    def _docs(n: int, start: int = 0) -> dict[str, object]:
        return {"response": {"docs": [{"_id": f"a{start + i}"} for i in range(n)]}}

    def test_pages_until_short_page_and_saves_state(self) -> None:
        # A full page (10) then a short page (2) → two fetches, then stop.
        with time_machine.travel("2026-07-02", tick=False):
            result = _driver().run(
                "article_search",
                [ScriptedResponse(json=self._docs(10, 0)), ScriptedResponse(json=self._docs(2, 10))],
            )

        assert result.raised is None
        assert [len(batch) for batch in result.items] == [10, 2]
        assert result.params("page") == ["0", "1"]
        # State saved after each yielded page, advancing the page cursor with a stable begin_date.
        assert result.saved_states == [
            NewYorkTimesResumeConfig(page=1, begin_date="20260602"),
            NewYorkTimesResumeConfig(page=2, begin_date="20260602"),
        ]
        assert result.committed_states == [NewYorkTimesResumeConfig(page=1, begin_date="20260602")]

    def test_respects_page_cap(self) -> None:
        # Always-full pages must stop at the 100-page hard cap rather than loop forever.
        with time_machine.travel("2026-07-02", tick=False):
            result = _driver().run("article_search", always(ScriptedResponse(json=self._docs(10, 0))))

        assert result.raised is None
        assert len(result.items) == ARTICLE_SEARCH_MAX_PAGES
        assert len(result.requests) == ARTICLE_SEARCH_MAX_PAGES
        assert result.params("page") == [str(page) for page in range(ARTICLE_SEARCH_MAX_PAGES)]

    def test_resumes_from_saved_page_and_window(self) -> None:
        result = _driver().run(
            "article_search",
            [ScriptedResponse(json={"response": {"docs": []}})],
            resume_state=NewYorkTimesResumeConfig(page=7, begin_date="20250101"),
        )

        assert result.raised is None
        assert result.params("page") == ["7"]
        assert result.params("begin_date") == ["20250101"]

    def test_passes_query_and_sort(self) -> None:
        with time_machine.travel("2026-07-02", tick=False):
            result = _driver("climate").run(
                "article_search",
                [ScriptedResponse(json={"response": {"docs": []}})],
                incremental_field="pub_date",
                db_incremental_field_last_value=datetime(2026, 6, 1, tzinfo=UTC),
            )

        assert result.raised is None
        assert result.params("sort") == ["oldest"]
        assert result.params("q") == ["climate"]
        assert result.params("begin_date") == ["20260601"]


class TestGetRowsArchive:
    @parameterized.expand(
        [
            (
                "incremental_starts_at_watermark_month",
                datetime(2026, 5, 15, tzinfo=UTC),
                "2026-07-02",
                ["/svc/archive/v1/2026/5.json", "/svc/archive/v1/2026/6.json", "/svc/archive/v1/2026/7.json"],
            ),
            (
                "crosses_year_boundary",
                datetime(2025, 12, 31, tzinfo=UTC),
                "2026-01-10",
                ["/svc/archive/v1/2025/12.json", "/svc/archive/v1/2026/1.json"],
            ),
            (
                "first_sync_uses_lookback",
                None,
                "2026-07-02",
                [f"/svc/archive/v1/2025/{m}.json" for m in range(7, 13)]
                + [f"/svc/archive/v1/2026/{m}.json" for m in range(1, 8)],
            ),
        ]
    )
    def test_walks_months_to_current(
        self, _name: str, last_value: datetime | None, now: str, expected_paths: list[str]
    ) -> None:
        with time_machine.travel(now, tick=False):
            result = _driver().run(
                "archive",
                always(ScriptedResponse(json={"response": {"docs": [{"_id": "a"}]}})),
                incremental_field="pub_date" if last_value else None,
                db_incremental_field_last_value=last_value,
            )

        assert result.raised is None
        assert result.paths == expected_paths
        assert len(result.items) == len(expected_paths)

    def test_stages_next_month_and_resumes_from_it(self) -> None:
        with time_machine.travel("2026-07-02", tick=False):
            result = _driver().run(
                "archive",
                [
                    ScriptedResponse(json={"response": {"docs": []}}),
                    ScriptedResponse(json={"response": {"docs": [{"_id": "a"}]}}),
                ],
                resume_state=NewYorkTimesResumeConfig(month="2026-06"),
            )

        assert result.raised is None
        assert result.paths == ["/svc/archive/v1/2026/6.json", "/svc/archive/v1/2026/7.json"]
        assert result.items == [[{"_id": "a"}]]
        assert result.saved_states[-2:] == [
            NewYorkTimesResumeConfig(month="2026-07"),
            NewYorkTimesResumeConfig(month="2026-08"),
        ]


class TestGetRowsTimesWire:
    @staticmethod
    def _items(n: int) -> dict[str, object]:
        return {"results": [{"url": f"https://www.nytimes.com/{i}"} for i in range(n)]}

    @parameterized.expand(
        [
            (
                "watermark_window_in_hours",
                datetime(2026, 7, 1, 19, 30, tzinfo=UTC),
                "/svc/news/v3/content/all/all/5.json",
            ),
            ("first_sync_uses_lookback", None, "/svc/news/v3/content/all/all/72.json"),
            ("caps_at_30_days", datetime(2026, 1, 1, tzinfo=UTC), "/svc/news/v3/content/all/all/720.json"),
        ]
    )
    def test_pages_window_until_short_page(self, _name: str, last_value: datetime | None, expected_path: str) -> None:
        with time_machine.travel(datetime(2026, 7, 2, 0, 0, tzinfo=UTC), tick=False):
            result = _driver().run(
                "times_wire",
                [ScriptedResponse(json=self._items(20)), ScriptedResponse(json=self._items(3))],
                incremental_field="published_date" if last_value else None,
                db_incremental_field_last_value=last_value,
            )

        assert result.raised is None
        assert result.paths == [expected_path, expected_path]
        assert result.params("offset") == ["0", "20"]
        assert [len(batch) for batch in result.items] == [20, 3]
        assert [state.page for state in result.saved_states] == [1, 2]

    def test_page_cap_fails_the_run_instead_of_completing_it(self) -> None:
        with (
            time_machine.travel(datetime(2026, 7, 2, 0, 0, tzinfo=UTC), tick=False),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.new_york_times.new_york_times.TIMES_WIRE_MAX_PAGES",
                3,
            ),
        ):
            result = _driver().run(
                "times_wire",
                always(ScriptedResponse(json=self._items(20))),
                incremental_field="published_date",
                db_incremental_field_last_value=datetime(2026, 6, 1, tzinfo=UTC),
            )

        assert isinstance(result.raised, NewYorkTimesPageCapError)
        assert len(result.items) == 3

    def test_resume_keeps_window_start(self) -> None:
        with time_machine.travel(datetime(2026, 7, 2, 0, 0, tzinfo=UTC), tick=False):
            result = _driver().run(
                "times_wire",
                [ScriptedResponse(json=self._items(0))],
                resume_state=NewYorkTimesResumeConfig(page=4, begin_date="2026-07-01T14:00:00+00:00"),
            )

        assert result.raised is None
        assert result.paths == ["/svc/news/v3/content/all/all/10.json"]
        assert result.params("offset") == ["80"]


class TestGetRowsBooksBestSellers:
    NAMES = {
        "results": [
            {"list_name_encoded": "hardcover-fiction", "newest_published_date": "2026-06-28"},
            {"list_name_encoded": "advice", "newest_published_date": "2026-06-28"},
            {"list_name_encoded": "discontinued", "newest_published_date": "2017-01-29"},
        ]
    }

    @staticmethod
    def _edition(published_date: str, previous: str, ranks: int = 2) -> ScriptedResponse:
        return ScriptedResponse(
            json={
                "num_results": ranks,
                "results": {
                    "list_name": "List",
                    "published_date": published_date,
                    "previous_published_date": previous,
                    "updated": "WEEKLY",
                    "books": [{"rank": r, "title": f"Book {r}"} for r in range(1, ranks + 1)],
                },
            }
        )

    def test_full_refresh_fetches_newest_edition_of_every_list(self) -> None:
        result = _driver().run(
            "books_best_sellers",
            route(
                {
                    "/lists/names.json": [ScriptedResponse(json=self.NAMES)],
                    "/2026-06-28/advice.json": [self._edition("2026-06-28", "2026-06-21")],
                    "/2026-06-28/hardcover-fiction.json": [self._edition("2026-06-28", "2026-06-21")],
                    "/2017-01-29/discontinued.json": [self._edition("2017-01-29", "2017-01-22", ranks=1)],
                }
            ),
        )

        assert result.raised is None
        assert result.paths == [
            "/svc/books/v3/lists/names.json",
            "/svc/books/v3/lists/2026-06-28/advice.json",
            "/svc/books/v3/lists/2017-01-29/discontinued.json",
            "/svc/books/v3/lists/2026-06-28/hardcover-fiction.json",
        ]
        assert result.rows[0] == {
            "rank": 1,
            "title": "Book 1",
            "list_name": "List",
            "list_name_encoded": "advice",
            "display_name": None,
            "published_date": "2026-06-28",
            "bestsellers_date": None,
            "updated": "WEEKLY",
        }

    def test_incremental_walks_back_to_watermark_and_skips_stale_lists(self) -> None:
        result = _driver().run(
            "books_best_sellers",
            route(
                {
                    "/lists/names.json": [ScriptedResponse(json=self.NAMES)],
                    "/2026-06-28/advice.json": [self._edition("2026-06-28", "2026-06-21")],
                    "/2026-06-21/advice.json": [self._edition("2026-06-21", "2026-06-14")],
                    "/2026-06-14/advice.json": [self._edition("2026-06-14", "2026-06-07")],
                    "/2026-06-28/hardcover-fiction.json": [self._edition("2026-06-28", "2026-06-21")],
                    "/2026-06-21/hardcover-fiction.json": [self._edition("2026-06-21", "2026-06-14")],
                    "/2026-06-14/hardcover-fiction.json": [self._edition("2026-06-14", "2026-06-07")],
                }
            ),
            incremental_field="published_date",
            db_incremental_field_last_value=date(2026, 6, 14),
        )

        assert result.raised is None
        assert [path.removeprefix("/svc/books/v3/lists/") for path in result.paths] == [
            "names.json",
            "2026-06-28/advice.json",
            "2026-06-21/advice.json",
            "2026-06-14/advice.json",
            "2026-06-28/hardcover-fiction.json",
            "2026-06-21/hardcover-fiction.json",
            "2026-06-14/hardcover-fiction.json",
        ]
        assert result.saved_states[2] == NewYorkTimesResumeConfig(list_name_encoded="advice", published_date=None)

    def test_walk_back_stops_when_previous_date_does_not_move_back(self) -> None:
        result = _driver().run(
            "books_best_sellers",
            route(
                {
                    "/lists/names.json": [ScriptedResponse(json={"results": [self.NAMES["results"][1]]})],
                    "/2026-06-28/advice.json": [self._edition("2026-06-28", "2026-06-28")],
                }
            ),
            incremental_field="published_date",
            db_incremental_field_last_value=date(2026, 6, 1),
        )

        assert result.raised is None
        assert len(result.paths) == 2

    def test_paginates_lists_longer_than_one_page(self) -> None:
        result = _driver().run(
            "books_best_sellers",
            route(
                {
                    "/lists/names.json": [ScriptedResponse(json={"results": [self.NAMES["results"][1]]})],
                    "/2026-06-28/advice.json": [
                        self._edition("2026-06-28", "2026-06-21", ranks=20),
                        self._edition("2026-06-28", "2026-06-21", ranks=5),
                    ],
                }
            ),
        )

        assert result.raised is None
        assert result.params("offset") == [None, "0", "20"]
        assert [len(batch) for batch in result.items] == [25]

    def test_resume_skips_finished_lists(self) -> None:
        result = _driver().run(
            "books_best_sellers",
            route(
                {
                    "/lists/names.json": [ScriptedResponse(json=self.NAMES)],
                    "/2026-06-28/hardcover-fiction.json": [self._edition("2026-06-28", "2026-06-21")],
                }
            ),
            resume_state=NewYorkTimesResumeConfig(list_name_encoded="discontinued", published_date=None),
        )

        assert result.raised is None
        assert result.paths[-1] == "/svc/books/v3/lists/2026-06-28/hardcover-fiction.json"
        assert len(result.paths) == 2


class TestFetchPageRetry:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_statuses_retry(self, _name: str, status_code: int) -> None:
        result = _driver().run(
            "top_stories",
            [ScriptedResponse(status=status_code), ScriptedResponse(json={"results": [{"uri": "u1"}]})],
        )

        assert result.raised is None
        assert result.rows == [{"uri": "u1"}]
        assert result.paths == ["/svc/topstories/v2/home.json"] * 2

    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_persistent_retryable_status_raises_retryable_error(self, _name: str, status_code: int) -> None:
        result = _driver().run("top_stories", always(ScriptedResponse(status=status_code)))

        assert isinstance(result.raised, NewYorkTimesRetryableError)

    def test_client_error_raises_without_leaking_api_key(self) -> None:
        # The api-key rides in the query string; a client-error must never surface it in the raised
        # message (it's stored on the schema and shown to users). The message must still start with the
        # non-retryable-error key prefix so the sync stops instead of retrying forever.
        driver = SourceDriver(NewYorkTimesSource(), NewYorkTimesSourceConfig(api_key="SECRETKEY"))
        result = driver.run("top_stories", [ScriptedResponse(status=401)])

        assert isinstance(result.raised, requests.HTTPError)
        message = str(result.raised)
        assert "SECRETKEY" not in message
        assert message.startswith("401 Client Error: Unauthorized for url: https://api.nytimes.com")


class TestSourceResponse:
    @parameterized.expand(
        [
            ("article_search", ["_id"], "pub_date", "asc"),
            ("archive", ["_id"], "pub_date", None),
            ("times_wire", ["url"], "created_date", None),
            ("books_best_sellers", ["list_name_encoded", "published_date", "rank"], "published_date", None),
            ("most_popular_viewed", ["uri"], "published_date", None),
            ("most_popular_emailed", ["uri"], "published_date", None),
            ("most_popular_shared", ["uri"], "published_date", None),
            ("top_stories", ["uri"], "created_date", None),
        ]
    )
    def test_response_metadata(
        self, endpoint: str, primary_keys: list[str], partition_key: str, sort_mode: str | None
    ) -> None:
        body: dict[str, Any] = {"response": {"docs": []}, "results": []}
        result = _driver().run(endpoint, always(ScriptedResponse(json=body)))
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_keys == [partition_key]
        assert response.partition_mode == "datetime"
        assert response.sort_mode == sort_mode

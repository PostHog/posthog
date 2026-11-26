from datetime import UTC, date, datetime, timedelta

import pytest
import time_machine

from requests import HTTPError

from products.warehouse_sources.sources.sdk.testing import RecordedRequest, ScriptedResponse, SourceDriver
from products.warehouse_sources.sources.watchmode._config import WatchmodeSourceConfig
from products.warehouse_sources.sources.watchmode.source import WatchmodeSource
from products.warehouse_sources.sources.watchmode.watchmode import WatchmodeResumeConfig


def _titles_page(title_ids: list[int], total_pages: int) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "titles": [{"id": title_id, "title": f"t{title_id}"} for title_id in title_ids],
            "total_pages": total_pages,
        }
    )


def _per_title_body(endpoint: str, title_id: int) -> object:
    if endpoint == "title_details":
        return {"id": title_id, "runtime_minutes": 90}
    if endpoint == "title_sources":
        return [{"source_id": 203, "region": "US", "type": "sub", "format": "HD"}]
    if endpoint == "title_seasons":
        return [{"id": title_id * 10, "number": 1, "episode_count": 8}]
    if endpoint == "title_episodes":
        return [{"id": title_id * 100, "season_number": 1, "episode_number": 1, "sources": []}]
    return [{"person_id": 7110004, "type": "Cast", "role": "Lead"}]


_PER_TITLE_PATHS = {
    "title_sources": "sources",
    "title_details": "details",
    "title_cast_crew": "cast-crew",
    "title_seasons": "seasons",
    "title_episodes": "episodes",
}

_TODAY = date(2026, 3, 15)


def _release_window(request: RecordedRequest) -> tuple[date, date]:
    start, end = request.param("start_date"), request.param("end_date")
    assert start is not None and end is not None
    return datetime.strptime(start, "%Y%m%d").date(), datetime.strptime(end, "%Y%m%d").date()


class TestWatchmodeSourceResumeBehavior:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(WatchmodeSource(), WatchmodeSourceConfig(api_key="test-key"))

    def test_resume_seeds_paginator_with_saved_page(self) -> None:
        result = self._driver().run(
            "titles",
            [ScriptedResponse(json={"titles": [{"id": 50}], "total_pages": 5})],
            resume_state=WatchmodeResumeConfig(page=5),
        )

        assert result.params("page") == ["5"]
        assert result.rows == [{"id": 50}]
        assert result.raised is None

    def test_endpoint_ignoring_page_param_terminates_without_duplicate_rows(self) -> None:
        body = {"releases": [{"id": 1, "source_id": 203}, {"id": 1, "source_id": 57}]}
        result = self._driver().run("releases", [ScriptedResponse(json=body), ScriptedResponse(json=body)])

        assert len(result.requests) == 2
        assert result.rows == [{"id": 1, "source_id": 203}, {"id": 1, "source_id": 57}]
        assert result.raised is None

    def test_sync_requests_do_not_follow_redirects(self) -> None:
        # `requests` replays the `X-API-Key` header across a cross-host redirect, so a
        # dropped `allow_redirects=False` would forward the customer's key off-host.
        result = self._driver().run(
            "titles",
            [ScriptedResponse(status=302, headers={"Location": "https://example.com/redirect"})],
        )

        assert result.paths == ["/v1/list-titles/"]
        assert result.requests[0].headers["x-api-key"] == "test-key"
        assert isinstance(result.raised, ValueError)

    @pytest.mark.parametrize("endpoint", ["sources", "regions", "networks", "genres"])
    def test_reference_endpoints_fetch_a_single_unpaginated_page(self, endpoint: str) -> None:
        row = {"id": 1, "country": "US", "name": "row"}
        result = self._driver().run(endpoint, [ScriptedResponse(json=[row])])

        assert len(result.requests) == 1
        assert result.requests[0].param("page") is None
        assert result.rows == [row]
        assert result.saved_states == []
        assert result.raised is None

    @pytest.mark.parametrize(
        "endpoint,title_types,child_limit",
        [
            ("title_sources", None, None),
            ("title_details", None, None),
            ("title_cast_crew", None, None),
            ("title_seasons", "tv_series,tv_miniseries", None),
            ("title_episodes", "tv_series,tv_miniseries", "500"),
        ],
    )
    def test_per_title_tables_fan_out_over_every_titles_page(
        self, endpoint: str, title_types: str | None, child_limit: str | None
    ) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/v1/list-titles/":
                return _titles_page([1, 2], 2) if request.param("page") == "1" else _titles_page([3], 2)
            title_id = int(request.path.split("/")[3])
            return ScriptedResponse(json=_per_title_body(endpoint, title_id))

        result = self._driver().run(endpoint, respond)

        assert result.raised is None
        suffix = _PER_TITLE_PATHS[endpoint]
        assert result.paths == [
            "/v1/list-titles/",
            "/v1/title/1/" + suffix + "/",
            "/v1/title/2/" + suffix + "/",
            "/v1/list-titles/",
            "/v1/title/3/" + suffix + "/",
        ]
        assert result.params("sort_by")[0] == "release_date_asc"
        assert result.params("types")[0] == title_types
        assert result.params("limit")[1] == child_limit
        if endpoint == "title_details":
            assert [row["id"] for row in result.rows] == [1, 2, 3]
        else:
            assert [row["title_id"] for row in result.rows] == [1, 2, 3]
            assert all("_titles_id" not in row for row in result.rows)

    def test_title_removed_after_listing_is_skipped(self) -> None:
        result = self._driver().run(
            "title_sources",
            [
                _titles_page([1, 2], 1),
                ScriptedResponse(status=404, json={"success": False}),
                ScriptedResponse(json=[{"source_id": 203, "region": "US", "type": "sub", "format": "HD"}]),
            ],
        )

        assert result.raised is None
        assert [row["title_id"] for row in result.rows] == [2]

    def test_per_title_resume_starts_at_saved_titles_page_and_skips_finished_titles(self) -> None:
        resume = WatchmodeResumeConfig(
            fanout_state={
                "completed": ["/v1/title/5/cast-crew/"],
                "current": None,
                "child_state": None,
                "parent": {"page": 3},
            }
        )
        result = self._driver().run(
            "title_cast_crew",
            [
                _titles_page([5, 6], 3),
                ScriptedResponse(json=[{"person_id": 7110004, "type": "Crew", "role": "Director"}]),
            ],
            resume_state=resume,
        )

        assert result.raised is None
        assert result.paths == ["/v1/list-titles/", "/v1/title/6/cast-crew/"]
        assert result.params("page")[0] == "3"
        assert [row["title_id"] for row in result.rows] == [6]

    def test_episodes_page_through_a_long_series_before_the_next_title(self) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/v1/list-titles/":
                return _titles_page([1, 2], 1)
            title_id = int(request.path.split("/")[3])
            offset = int(request.param("offset") or 0)
            count = 500 if title_id == 1 and offset == 0 else 2
            return ScriptedResponse(json=[{"id": title_id * 10_000 + offset + i} for i in range(count)])

        result = self._driver().run("title_episodes", respond)

        assert result.raised is None
        assert result.paths[1:] == ["/v1/title/1/episodes/", "/v1/title/1/episodes/", "/v1/title/2/episodes/"]
        assert result.params("offset")[1:] == ["0", "500", "0"]
        assert len(result.rows) == 504
        assert [row["title_id"] for row in result.rows[-2:]] == [2, 2]

    @time_machine.travel(datetime(2026, 3, 15, 12, tzinfo=UTC), tick=False)
    def test_release_dates_cover_the_range_in_contiguous_windows_and_split_truncated_ones(self) -> None:
        first_day = _TODAY - timedelta(days=365)

        def respond(request: RecordedRequest) -> ScriptedResponse:
            start, end = _release_window(request)
            truncated = start == first_day and (end - start).days > 14
            return ScriptedResponse(
                json=[{"id": 1, "region": "US", "release_date": start.isoformat()}],
                headers={"X-Watchmode-Truncated": "1"} if truncated else {},
            )

        result = self._driver().run("title_release_dates", respond)

        assert result.raised is None
        windows = [_release_window(request) for request in result.requests]
        assert windows[0] == (first_day, first_day + timedelta(days=29))
        # The truncated first window is read again as two halves, and its own rows are not kept.
        assert windows[1:3] == [
            (first_day, first_day + timedelta(days=14)),
            (first_day + timedelta(days=15), first_day + timedelta(days=29)),
        ]
        read = windows[1:]
        assert all(nxt[0] == prev[1] + timedelta(days=1) for prev, nxt in zip(read, read[1:]))
        assert read[-1][1] == _TODAY + timedelta(days=180)
        assert [row["release_date"] for row in result.rows] == [start.isoformat() for start, _ in read]
        assert result.final_state == WatchmodeResumeConfig(
            release_dates_start=(_TODAY + timedelta(days=181)).isoformat()
        )

    @time_machine.travel(datetime(2026, 3, 15, 12, tzinfo=UTC), tick=False)
    def test_release_dates_resume_from_the_first_unread_day(self) -> None:
        resume_day = _TODAY + timedelta(days=170)
        result = self._driver().run(
            "title_release_dates",
            [ScriptedResponse(json=[])],
            resume_state=WatchmodeResumeConfig(release_dates_start=resume_day.isoformat()),
        )

        assert result.raised is None
        assert [_release_window(request) for request in result.requests] == [(resume_day, _TODAY + timedelta(days=180))]
        assert result.requests[0].headers["x-api-key"] == "test-key"

    @pytest.mark.parametrize(
        "response,expected_error",
        [
            (ScriptedResponse(json={"success": False, "statusMessage": "x"}), ValueError),
            (ScriptedResponse(status=401, json={"success": False}), HTTPError),
        ],
    )
    @time_machine.travel(datetime(2026, 3, 15, 12, tzinfo=UTC), tick=False)
    def test_release_dates_fail_on_an_unexpected_body_or_an_error_status(
        self, response: ScriptedResponse, expected_error: type[BaseException]
    ) -> None:
        result = self._driver().run("title_release_dates", [response])

        assert isinstance(result.raised, expected_error)
        assert result.rows == []

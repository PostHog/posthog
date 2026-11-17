import pytest

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
    return [{"person_id": 7110004, "type": "Cast", "role": "Lead"}]


_PER_TITLE_PATHS = {
    "title_sources": "sources",
    "title_details": "details",
    "title_cast_crew": "cast-crew",
}


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

    @pytest.mark.parametrize("endpoint", ["title_sources", "title_details", "title_cast_crew"])
    def test_per_title_tables_fan_out_over_every_titles_page(self, endpoint: str) -> None:
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
        assert result.params("limit")[1] is None
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

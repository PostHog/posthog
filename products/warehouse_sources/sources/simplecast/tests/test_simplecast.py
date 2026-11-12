from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import requests
from parameterized import parameterized

from products.warehouse_sources.sources.sdk.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    UnexpectedRequest,
    always,
)
from products.warehouse_sources.sources.simplecast._config import SimpleCastSourceConfig
from products.warehouse_sources.sources.simplecast.settings import ENDPOINTS, SIMPLECAST_ENDPOINTS
from products.warehouse_sources.sources.simplecast.simplecast import (
    PAGE_SIZE,
    SIMPLECAST_BASE_URL,
    SimpleCastResumeConfig,
)
from products.warehouse_sources.sources.simplecast.source import SimpleCastSource


def _envelope(items: list[dict[str, Any]], *, total: int = 1, current: int = 1) -> ScriptedResponse:
    return ScriptedResponse(json={"collection": items, "pages": {"total": total, "current": current}})


def _full_page(start_id: int) -> list[dict[str, Any]]:
    return [{"id": f"p_{start_id + i}"} for i in range(PAGE_SIZE)]


def _driver() -> SourceDriver:
    return SourceDriver(SimpleCastSource(), SimpleCastSourceConfig(api_key="sc-token"))


def _by_url(responses_by_url: dict[str, list[ScriptedResponse]]) -> Callable[[RecordedRequest], ScriptedResponse]:
    def _norm(url: str) -> tuple[str, tuple[tuple[str, str], ...]]:
        parts = urlsplit(url)
        return parts.path, tuple(sorted(parse_qsl(parts.query)))

    queues = {_norm(url): list(queue) for url, queue in responses_by_url.items()}

    def respond(request: RecordedRequest) -> ScriptedResponse:
        queue = queues.get(_norm(request.url))
        if not queue:
            raise UnexpectedRequest(f"unexpected request url {request.url!r}")
        return queue.pop(0)

    return respond


def _url(path: str, **params: Any) -> str:
    query = "&".join(f"{key}={value}" for key, value in params.items())
    return (
        f"{SIMPLECAST_BASE_URL}{path}{'&' if '?' in path else '?'}{query}" if query else f"{SIMPLECAST_BASE_URL}{path}"
    )


def _paged(path: str, offset: int = 0, **params: Any) -> str:
    return _url(path, limit=PAGE_SIZE, offset=offset, **params)


def _podcasts(*ids: str) -> dict[str, list[ScriptedResponse]]:
    return {_paged("/podcasts"): [_envelope([{"id": podcast_id, "title": podcast_id} for podcast_id in ids])]}


def _interval_report(rows: list[dict[str, Any]]) -> ScriptedResponse:
    # Analytics reports return one object per podcast with the daily series under `by_interval`.
    return ScriptedResponse(json={"href": "https://api.simplecast.com/analytics", "total": 0, "by_interval": rows})


class TestEpisodesFanout:
    def test_walks_every_page_of_each_podcast_sorted_by_creation(self) -> None:
        full_page = [{"id": f"e_{i}"} for i in range(PAGE_SIZE)]
        responses = {
            **_podcasts("pod_a", "pod_b"),
            _paged("/podcasts/pod_a/episodes", sort="created_at_asc"): [_envelope(full_page, total=2, current=1)],
            _paged("/podcasts/pod_a/episodes", offset=PAGE_SIZE, sort="created_at_asc"): [
                _envelope([{"id": "e_last"}], total=2, current=2)
            ],
            _paged("/podcasts/pod_b/episodes", sort="created_at_asc"): [_envelope([{"id": "e_b"}])],
        }

        result = _driver().run("episodes", _by_url(responses))

        assert result.raised is None
        assert [r["id"] for r in result.rows] == [*(r["id"] for r in full_page), "e_last", "e_b"]
        assert [r["podcast_id"] for r in result.rows] == ["pod_a"] * (PAGE_SIZE + 1) + ["pod_b"]
        assert all("_podcasts_id" not in r for r in result.rows)

    def test_podcast_deleted_before_its_episodes_are_fetched_is_skipped(self) -> None:
        responses = {
            **_podcasts("gone", "pod_b"),
            _paged("/podcasts/gone/episodes", sort="created_at_asc"): [ScriptedResponse(status=404, json={})],
            _paged("/podcasts/pod_b/episodes", sort="created_at_asc"): [_envelope([{"id": "e_b"}])],
        }

        result = _driver().run("episodes", _by_url(responses))

        assert result.raised is None
        assert [(r["id"], r["podcast_id"]) for r in result.rows] == [("e_b", "pod_b")]

    @parameterized.expand([("parent_listing_from_start", None, 0), ("parent_listing_from_saved_offset", 100, 100)])
    def test_resumes_mid_podcast_from_the_saved_offset(
        self, _name: str, saved_parent_offset: int | None, expected_parent_offset: int
    ) -> None:
        responses = {
            _paged("/podcasts", offset=expected_parent_offset): [_envelope([{"id": "pod_a"}, {"id": "pod_b"}])],
            _paged("/podcasts/pod_b/episodes", offset=2 * PAGE_SIZE, sort="created_at_asc"): [
                _envelope([{"id": "e_resumed"}])
            ],
        }
        fanout_state: dict[str, Any] = {
            "completed": ["/podcasts/pod_a/episodes"],
            "current": "/podcasts/pod_b/episodes",
            "child_state": {"offset": 2 * PAGE_SIZE},
        }
        if saved_parent_offset is not None:
            fanout_state["parent"] = {"offset": saved_parent_offset}

        result = _driver().run(
            "episodes", _by_url(responses), resume_state=SimpleCastResumeConfig(fanout_state=fanout_state)
        )

        assert result.raised is None
        assert [(r["id"], r["podcast_id"]) for r in result.rows] == [("e_resumed", "pod_b")]


class TestIntervalReports:
    @parameterized.expand(
        [
            (
                "downloads",
                "/analytics/downloads",
                {"interval": "2020-07-30", "downloads_total": 4, "downloads_percent": 50},
            ),
            ("listeners", "/analytics/listeners", {"interval": "2020-07-30", "total": 3, "percent": 60}),
        ]
    )
    def test_flattens_the_daily_series_of_each_podcast_in_one_request(
        self, endpoint: str, path: str, row: dict[str, Any]
    ) -> None:
        responses = {
            **_podcasts("pod_a", "pod_b"),
            _url(f"{path}?podcast=pod_a", interval="day"): [_interval_report([row, {**row, "interval": "2020-07-31"}])],
            _url(f"{path}?podcast=pod_b", interval="day"): [_interval_report([])],
        }

        result = _driver().run(endpoint, _by_url(responses))

        assert result.raised is None
        assert result.rows == [
            {**row, "podcast_id": "pod_a"},
            {**row, "interval": "2020-07-31", "podcast_id": "pod_a"},
        ]
        # The reports are unpaginated: no page params and exactly one request per podcast.
        assert len(result.requests) == 3

    @parameterized.expand([("downloads",), ("listeners",)])
    def test_report_without_series_is_retried_then_raises(self, endpoint: str) -> None:
        path = SIMPLECAST_ENDPOINTS[endpoint].path.replace("{podcast_id}", "pod_a")
        responses = {
            **_podcasts("pod_a"),
            _url(path, interval="day"): [ScriptedResponse(json={"error": "no"})] * 5,
        }

        result = _driver().run(endpoint, _by_url(responses))

        assert result.raised is not None
        assert len(result.requests) == 6


class TestPerEpisodeAnalytics:
    @parameterized.expand(
        [
            ("episode_downloads", "/analytics/episodes", "downloads"),
            ("episode_listeners", "/analytics/episodes/listeners", "listeners"),
        ]
    )
    def test_walks_every_page_although_the_path_ends_in_the_podcast_id(
        self, endpoint: str, path: str, metric: str
    ) -> None:
        full_page = [{"id": f"e_{i}", metric: {"total": i}} for i in range(PAGE_SIZE)]
        child = f"{path}?podcast=pod_a"
        responses = {
            **_podcasts("pod_a"),
            # `total` here is a download count, not a row count, so it must not end the walk.
            _paged(child): [
                ScriptedResponse(json={"total": 1, "collection": full_page, "pages": {"total": 2, "current": 1}})
            ],
            _paged(child, offset=PAGE_SIZE): [_envelope([{"id": "e_last", metric: {"total": 7}}], total=2, current=2)],
        }

        result = _driver().run(endpoint, _by_url(responses))

        assert result.raised is None
        assert [r["id"] for r in result.rows] == [*(r["id"] for r in full_page), "e_last"]
        assert {r["podcast_id"] for r in result.rows} == {"pod_a"}


class TestPagination:
    def test_paginates_and_progresses_offset(self) -> None:
        result = _driver().run(
            "podcasts",
            [_envelope(_full_page(0), total=2, current=1), _envelope([{"id": "p_last"}], total=2, current=2)],
        )

        assert [r["id"] for r in result.rows] == [*(f"p_{i}" for i in range(PAGE_SIZE)), "p_last"]
        assert result.params("offset") == ["0", str(PAGE_SIZE)]
        assert result.params("limit")[0] == str(PAGE_SIZE)
        # Checkpoint saved once after the first full page (points at the next page); short page ends it.
        assert result.saved_states == [SimpleCastResumeConfig(offset=PAGE_SIZE)]

    def test_full_last_page_stops_on_pages_metadata_without_extra_request(self) -> None:
        # A full page whose `pages` metadata marks it as the last page must terminate without paying
        # for an extra empty-page request, and without persisting a resume checkpoint.
        result = _driver().run("podcasts", [_envelope(_full_page(0), total=1, current=1)])

        assert len(result.rows) == PAGE_SIZE
        assert len(result.requests) == 1
        assert result.saved_states == []

    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run(
            "podcasts",
            [_envelope([{"id": "p_101"}], total=2, current=2)],
            resume_state=SimpleCastResumeConfig(offset=PAGE_SIZE),
        )

        # Offset 0 must never be fetched on resume; the first (only) request starts at the saved offset.
        assert result.params("offset") == [str(PAGE_SIZE)]
        assert [r["id"] for r in result.rows] == ["p_101"]


class TestErrorHandling:
    @parameterized.expand(
        [
            ("bare_list", [{"id": 1}]),
            ("missing_collection", {"pages": {}}),
            ("error_envelope", {"error": "no"}),
        ]
    )
    def test_unexpected_200_body_is_retried_then_raises(self, _name, body) -> None:
        # The client retries a malformed 200 body up to 5 attempts, then reraises.
        result = _driver().run("podcasts", always(ScriptedResponse(json=body)))

        assert result.raised is not None
        assert len(result.requests) == 5

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_status_is_retried_then_raises(self, _name, status) -> None:
        result = _driver().run("podcasts", always(ScriptedResponse(status=status, json={})))

        assert result.raised is not None
        assert len(result.requests) == 5

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_error_raises_without_retry(self, _name, status) -> None:
        result = _driver().run("podcasts", [ScriptedResponse(status=status, json={})])

        assert isinstance(result.raised, requests.HTTPError)
        # 4xx is a permanent failure — issued exactly once, never retried.
        assert len(result.requests) == 1


class TestSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _driver().run(endpoint, always(_envelope([]))).response

        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == SIMPLECAST_ENDPOINTS[endpoint].primary_keys
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None

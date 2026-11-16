from typing import Any, cast

import requests
from parameterized import parameterized

from products.warehouse_sources.sources.rss._config import RssSourceConfig
from products.warehouse_sources.sources.rss.rss import PAGE_SIZE, RSS_BASE_URL, RssResumeConfig, validate_credentials
from products.warehouse_sources.sources.rss.settings import ENDPOINTS, RSS_ENDPOINTS
from products.warehouse_sources.sources.rss.source import RssSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always, scripted_network


def _response(body: Any, status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=body)


def _driver() -> SourceDriver:
    return SourceDriver(RssSource(), RssSourceConfig(api_key="rss-key"))


def _episodes(start_id: int, count: int) -> list[dict[str, Any]]:
    return [{"id": start_id + i, "title": f"ep {start_id + i}"} for i in range(count)]


class TestValidateCredentials:
    @parameterized.expand(
        [
            (
                "payment_required",
                402,
                False,
                "The RSS.com API is only available on RSS.com Network plans. Upgrade your plan, then reconnect.",
            ),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_ok: bool, expected_msg: str | None) -> None:
        with scripted_network(always(ScriptedResponse(status=status))):
            ok, message = validate_credentials("rss-key")
        assert ok is expected_ok
        assert message == expected_msg


class TestTopLevelEndpoints:
    @parameterized.expand([("podcasts", "/podcasts"), ("categories", "/categories")])
    def test_unpaginated_endpoints_are_a_single_request(self, _name: str, path: str) -> None:
        result = _driver().run(_name, [_response([{"id": 1}, {"id": 2}])])

        assert result.rows == [{"id": 1}, {"id": 2}]
        # A single unpaginated request returns the whole collection; no extra page is requested.
        assert len(result.requests) == 1
        assert result.urls[0] == f"{RSS_BASE_URL}{path}"
        # No pagination params on the single request.
        assert result.queries[0] == {}
        # Single-page endpoints leave no resume checkpoint behind.
        assert result.saved_states == []


class TestEpisodesFanOut:
    def test_injects_podcast_id_into_every_row(self) -> None:
        result = _driver().run(
            "episodes",
            [
                _response([{"id": 1}, {"id": 2}]),
                _response(_episodes(10, 2)),
                _response(_episodes(20, 1)),
            ],
        )

        # Parent id is injected (kept as the raw int) and is part of the composite primary key.
        assert [(r["podcast_id"], r["id"]) for r in result.rows] == [(1, 10), (1, 11), (2, 20)]
        assert [url.split("?")[0] for url in result.urls] == [
            f"{RSS_BASE_URL}/podcasts",
            f"{RSS_BASE_URL}/podcasts/1/episodes",
            f"{RSS_BASE_URL}/podcasts/2/episodes",
        ]

    def test_resume_page_only_applies_to_the_podcast_in_flight(self) -> None:
        result = _driver().run(
            "episodes",
            [
                _response([{"id": 1}, {"id": 2}]),
                _response(_episodes(10, 1)),
                _response(_episodes(20, 1)),
            ],
            resume_state=RssResumeConfig(
                fanout_state={"completed": [], "current": "/podcasts/1/episodes", "child_state": {"page": 2}}
            ),
        )

        assert [(r["podcast_id"], r["id"]) for r in result.rows] == [(1, 10), (2, 20)]
        # The saved page only seeds the in-flight podcast; the next podcast starts at page 1.
        episode_pages = {
            request.path: request.param("page") for request in result.requests if "/episodes" in request.path
        }
        assert episode_pages["/v4/podcasts/1/episodes"] == "2"
        assert episode_pages["/v4/podcasts/2/episodes"] == "1"

    def test_non_list_episode_body_raises_loudly(self) -> None:
        result = _driver().run("episodes", [_response([{"id": 1}]), _response({"error": "unexpected"})])

        # A 200 episode page that isn't a bare array means the response shape changed — fail loud.
        assert isinstance(result.raised, ValueError)
        assert "list response body" in str(result.raised)

    def test_client_error_propagates(self) -> None:
        result = _driver().run("episodes", [_response([{"id": 1}]), _response({"error": "forbidden"}, status=403)])

        # Auth/permission failures surface as an HTTPError so the sync fails loud (they're in
        # get_non_retryable_errors) rather than retrying forever.
        assert isinstance(result.raised, requests.HTTPError)

    def test_old_shape_saved_state_still_parses(self) -> None:
        # ResumableSourceManager._load_json does dataclass(**saved) — state saved before the
        # migration must still construct.
        state = RssResumeConfig(
            **cast("dict[str, Any]", {"completed_podcast_ids": [1], "current_podcast_id": 2, "next_page": 3})
        )
        assert state.completed_podcast_ids == [1]
        assert state.current_podcast_id == 2
        assert state.next_page == 3
        assert state.fanout_state is None


class TestPerPodcastFanOut:
    @parameterized.expand([("collaborators",), ("keywords",)])
    def test_unpaginated_child_is_one_request_per_podcast(self, endpoint: str) -> None:
        result = _driver().run(
            endpoint,
            [
                _response([{"id": 1}, {"id": 2}]),
                _response([{"id": "a"}, {"id": "b"}]),
                _response([{"id": "a"}]),
            ],
        )

        assert [(r["podcast_id"], r["id"]) for r in result.rows] == [(1, "a"), (1, "b"), (2, "a")]
        assert all("_podcasts_id" not in r for r in result.rows)
        assert [url.split("?")[0] for url in result.urls] == [
            f"{RSS_BASE_URL}/podcasts",
            f"{RSS_BASE_URL}/podcasts/1/{endpoint}",
            f"{RSS_BASE_URL}/podcasts/2/{endpoint}",
        ]
        # These endpoints take no pagination params, so none are sent.
        assert result.queries[1:] == [{}, {}]

    @parameterized.expand([("collaborators",), ("keywords",)])
    def test_empty_podcast_list_requests_no_child(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_response([])])

        assert result.rows == []
        assert result.urls == [f"{RSS_BASE_URL}/podcasts"]

    @parameterized.expand([("collaborators",), ("keywords",)])
    def test_resume_skips_completed_podcasts(self, endpoint: str) -> None:
        result = _driver().run(
            endpoint,
            [_response([{"id": 1}, {"id": 2}]), _response([{"id": "b"}])],
            resume_state=RssResumeConfig(
                fanout_state={"completed": [f"/podcasts/1/{endpoint}"], "current": None, "child_state": None}
            ),
        )

        assert [(r["podcast_id"], r["id"]) for r in result.rows] == [(2, "b")]
        assert [url.split("?")[0] for url in result.urls] == [
            f"{RSS_BASE_URL}/podcasts",
            f"{RSS_BASE_URL}/podcasts/2/{endpoint}",
        ]

    @parameterized.expand([("collaborators",), ("keywords",)])
    def test_non_list_child_body_raises_loudly(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_response([{"id": 1}]), _response({"error": "unexpected"})])

        assert isinstance(result.raised, ValueError)
        assert "list response body" in str(result.raised)


class TestMidrollsChainedFanOut:
    def test_injects_podcast_and_episode_ids(self) -> None:
        result = _driver().run(
            "midrolls",
            [
                _response([{"id": 1}, {"id": 2}]),
                _response(_episodes(10, 2)),
                _response([{"id": 100, "start_time_ms": 5000}]),
                _response([{"id": 101, "start_time_ms": 0}, {"id": 102, "start_time_ms": 9000}]),
                _response(_episodes(20, 1)),
                _response([{"id": 100, "start_time_ms": 1000}]),
            ],
        )

        # Midroll ids are only unique within an episode, so both parent ids stay on every row.
        assert [(r["podcast_id"], r["episode_id"], r["id"]) for r in result.rows] == [
            (1, 10, 100),
            (1, 11, 101),
            (1, 11, 102),
            (2, 20, 100),
        ]
        assert all(not key.startswith("_") for r in result.rows for key in r)
        assert [url.split("?")[0] for url in result.urls] == [
            f"{RSS_BASE_URL}/podcasts",
            f"{RSS_BASE_URL}/podcasts/1/episodes",
            f"{RSS_BASE_URL}/podcasts/1/episodes/10/midrolls",
            f"{RSS_BASE_URL}/podcasts/1/episodes/11/midrolls",
            f"{RSS_BASE_URL}/podcasts/2/episodes",
            f"{RSS_BASE_URL}/podcasts/2/episodes/20/midrolls",
        ]

    def test_paginates_episodes_before_fetching_midrolls(self) -> None:
        result = _driver().run(
            "midrolls",
            [
                _response([{"id": 1}]),
                _response(_episodes(0, PAGE_SIZE)),
                *[_response([]) for _ in range(PAGE_SIZE)],
                _response(_episodes(PAGE_SIZE, 1)),
                _response([{"id": 7, "start_time_ms": 0}]),
            ],
        )

        assert [(r["podcast_id"], r["episode_id"], r["id"]) for r in result.rows] == [(1, PAGE_SIZE, 7)]
        episode_pages = [request.param("page") for request in result.requests if request.path.endswith("/episodes")]
        assert episode_pages == ["1", "2"]
        assert len([r for r in result.requests if r.path.endswith("/midrolls")]) == PAGE_SIZE + 1

    def test_deleted_episode_404_is_skipped(self) -> None:
        result = _driver().run(
            "midrolls",
            [
                _response([{"id": 1}]),
                _response(_episodes(10, 2)),
                _response({"error": "not found"}, status=404),
                _response([{"id": 100, "start_time_ms": 0}]),
            ],
        )

        assert [(r["podcast_id"], r["episode_id"], r["id"]) for r in result.rows] == [(1, 11, 100)]
        assert result.raised is None

    def test_client_error_propagates(self) -> None:
        result = _driver().run(
            "midrolls",
            [_response([{"id": 1}]), _response(_episodes(10, 1)), _response({"error": "forbidden"}, status=403)],
        )

        assert isinstance(result.raised, requests.HTTPError)

    def test_chain_saves_no_resume_state(self) -> None:
        result = _driver().run(
            "midrolls",
            [_response([{"id": 1}]), _response(_episodes(10, 1)), _response([{"id": 100, "start_time_ms": 0}])],
        )

        # A multi-level fan-out cannot checkpoint; a retry re-fetches and merge dedupes.
        assert result.saved_states == []


class TestRssSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        result = _driver().run(endpoint, always(_response([])))

        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == RSS_ENDPOINTS[endpoint].primary_keys
        # Episodes carry no stable creation timestamp, so no endpoint is partitioned.
        assert response.partition_mode is None

    @parameterized.expand(
        [
            ("episodes", ["podcast_id", "id"]),
            ("collaborators", ["podcast_id", "id"]),
            ("keywords", ["podcast_id", "id"]),
            ("midrolls", ["podcast_id", "episode_id", "id"]),
        ]
    )
    def test_fan_out_keys_include_parent_ids(self, endpoint: str, expected: list[str]) -> None:
        # Fan-out child rows aggregate every parent's rows into one table; the spec doesn't document
        # child ids as globally unique, so the key must include the parent ids.
        assert RSS_ENDPOINTS[endpoint].primary_keys == expected

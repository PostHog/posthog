import json
from typing import Any, cast

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.rss.rss import (
    PAGE_SIZE,
    RSS_BASE_URL,
    RssResumeConfig,
    rss_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rss.settings import ENDPOINTS, RSS_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the rss module.
RSS_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.rss.rss.make_tracked_session"


def _response(body: Any, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp.url = f"{RSS_BASE_URL}/mock"
    resp.reason = "Error" if status >= 400 else "OK"
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: RssResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[tuple[str, dict[str, Any]]]:
    """Wire a mock session, returning (url, params) snapshots captured AT PREPARE TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when each
    request is prepared instead of inspecting the shared dict after the run.
    """
    session.headers = {}
    snapshots: list[tuple[str, dict[str, Any]]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append((request.url, dict(request.params or {})))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock | None = None):
    return rss_source(
        api_key="rss-key",
        endpoint=endpoint,
        team_id=1,
        job_id="job",
        resumable_source_manager=manager or _make_manager(),
    )


def _episodes(start_id: int, count: int) -> list[dict[str, Any]]:
    return [{"id": start_id + i, "title": f"ep {start_id + i}"} for i in range(count)]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid RSS.com API key"),
            ("forbidden", 403, False, "Invalid RSS.com API key"),
            (
                "payment_required",
                402,
                False,
                "The RSS.com API is only available on RSS.com Network plans. Upgrade your plan, then reconnect.",
            ),
            ("server_error", 500, False, "RSS.com returned HTTP 500"),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_ok: bool, expected_msg: str | None) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=status)
        with mock.patch(RSS_SESSION_PATCH, return_value=session):
            ok, message = validate_credentials("rss-key")
        assert ok is expected_ok
        assert message == expected_msg

    def test_transport_error_is_inconclusive_not_invalid(self) -> None:
        # A transport failure must not be reported as an invalid key (would prompt a needless rotation).
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with mock.patch(RSS_SESSION_PATCH, return_value=session):
            ok, message = validate_credentials("rss-key")
        assert ok is False
        assert message == "Could not validate RSS.com API key"

    def test_probe_sends_api_key_header(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=200)
        with mock.patch(RSS_SESSION_PATCH, return_value=session):
            validate_credentials("rss-key")
        args, kwargs = session.get.call_args
        assert args[0] == f"{RSS_BASE_URL}/podcasts"
        assert kwargs["headers"]["X-Api-Key"] == "rss-key"


class TestTopLevelEndpoints:
    @parameterized.expand([("podcasts", "/podcasts"), ("categories", "/categories")])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unpaginated_endpoints_are_a_single_request(self, _name: str, path: str, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": 1}, {"id": 2}])])

        manager = _make_manager()
        rows = _rows(_source(_name, manager=manager))

        assert rows == [{"id": 1}, {"id": 2}]
        # A single unpaginated request returns the whole collection; no extra page is requested.
        assert session.send.call_count == 1
        assert snapshots[0][0] == f"{RSS_BASE_URL}{path}"
        # No pagination params on the single request.
        assert snapshots[0][1] == {}
        # Single-page endpoints leave no resume checkpoint behind.
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_collection_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        assert _rows(_source("podcasts")) == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_body_is_retried_then_recovers(self, MockSession) -> None:
        session = MockSession.return_value
        # A 200 whose body isn't a bare array is an unexpected/transient shape — reissue it rather
        # than syncing 0 rows. The good page on the retry is what ends up ingested.
        _wire(session, [_response({"message": "unexpected"}), _response([{"id": 1}])])

        assert _rows(_source("podcasts")) == [{"id": 1}]
        assert session.send.call_count == 2


class TestEpisodesFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_injects_podcast_id_into_every_row(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": 1}, {"id": 2}]),
                _response(_episodes(10, 2)),
                _response(_episodes(20, 1)),
            ],
        )

        rows = _rows(_source("episodes"))

        # Parent id is injected (kept as the raw int) and is part of the composite primary key.
        assert [(r["podcast_id"], r["id"]) for r in rows] == [(1, 10), (1, 11), (2, 20)]
        assert [url for url, _ in snapshots] == [
            f"{RSS_BASE_URL}/podcasts",
            f"{RSS_BASE_URL}/podcasts/1/episodes",
            f"{RSS_BASE_URL}/podcasts/2/episodes",
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_with_stable_oldest_order_and_stops_on_short_page(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": 7}]),
                _response(_episodes(0, PAGE_SIZE)),
                _response(_episodes(PAGE_SIZE, 3)),
            ],
        )

        rows = _rows(_source("episodes"))

        assert len(rows) == PAGE_SIZE + 3
        # Stops after the short second page; never requests a third (empty) page.
        assert session.send.call_count == 3
        episode_snaps = [s for s in snapshots if s[0] == f"{RSS_BASE_URL}/podcasts/7/episodes"]
        assert all(s[1]["order"] == "oldest" and s[1]["limit"] == PAGE_SIZE for s in episode_snaps)
        assert [s[1]["page"] for s in episode_snaps] == [1, 2]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoints_fanout_state_after_full_page_and_as_podcasts_complete(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": 7}]),
                _response(_episodes(0, PAGE_SIZE)),
                _response(_episodes(PAGE_SIZE, 3)),
            ],
        )

        manager = _make_manager()
        _rows(_source("episodes", manager=manager))

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert all(isinstance(state, RssResumeConfig) and state.fanout_state is not None for state in saved)
        fanout_states = [state.fanout_state for state in saved]
        # The full first page checkpoints the next page for the in-flight podcast; the final
        # checkpoint records the podcast as fully synced with no child mid-stream.
        assert {"completed": [], "current": "/podcasts/7/episodes", "child_state": {"page": 2}} in fanout_states
        assert fanout_states[-1] == {"completed": ["/podcasts/7/episodes"], "current": None, "child_state": None}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_skips_completed_podcasts_and_resumes_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": 1}, {"id": 2}]), _response(_episodes(30, 1))])

        manager = _make_manager(
            RssResumeConfig(
                fanout_state={
                    "completed": ["/podcasts/1/episodes"],
                    "current": "/podcasts/2/episodes",
                    "child_state": {"page": 3},
                }
            )
        )
        rows = _rows(_source("episodes", manager=manager))

        assert [(r["podcast_id"], r["id"]) for r in rows] == [(2, 30)]
        # Podcast 1 (completed) is never re-fetched; podcast 2 resumes at the saved page.
        assert [url for url, _ in snapshots] == [f"{RSS_BASE_URL}/podcasts", f"{RSS_BASE_URL}/podcasts/2/episodes"]
        assert snapshots[1][1]["page"] == 3

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_page_only_applies_to_the_podcast_in_flight(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": 1}, {"id": 2}]),
                _response(_episodes(10, 1)),
                _response(_episodes(20, 1)),
            ],
        )

        manager = _make_manager(
            RssResumeConfig(
                fanout_state={"completed": [], "current": "/podcasts/1/episodes", "child_state": {"page": 2}}
            )
        )
        rows = _rows(_source("episodes", manager=manager))

        assert [(r["podcast_id"], r["id"]) for r in rows] == [(1, 10), (2, 20)]
        # The saved page only seeds the in-flight podcast; the next podcast starts at page 1.
        episode_snaps = {url: params for url, params in snapshots if "/episodes" in url}
        assert episode_snaps[f"{RSS_BASE_URL}/podcasts/1/episodes"]["page"] == 2
        assert episode_snaps[f"{RSS_BASE_URL}/podcasts/2/episodes"]["page"] == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_podcasts_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([])])

        rows = _rows(_source("episodes"))
        assert rows == []
        assert [url for url, _ in snapshots] == [f"{RSS_BASE_URL}/podcasts"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_episode_body_raises_loudly(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}]), _response({"error": "unexpected"})])

        # A 200 episode page that isn't a bare array means the response shape changed — fail loud.
        with pytest.raises(ValueError, match="list response body"):
            _rows(_source("episodes"))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_propagates(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}]), _response({"error": "forbidden"}, status=403)])

        # Auth/permission failures surface as an HTTPError so the sync fails loud (they're in
        # get_non_retryable_errors) rather than retrying forever.
        with pytest.raises(requests.HTTPError):
            _rows(_source("episodes"))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_old_shape_resume_state_restarts_fanout(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": 1}, {"id": 2}]),
                _response(_episodes(10, 1)),
                _response(_episodes(20, 1)),
            ],
        )

        # A pre-migration bookmark can't seed the framework fan-out — start it fresh; merge dedupes
        # the re-pulled rows.
        manager = _make_manager(RssResumeConfig(completed_podcast_ids=[1], current_podcast_id=2, next_page=3))
        rows = _rows(_source("episodes", manager=manager))

        assert [(r["podcast_id"], r["id"]) for r in rows] == [(1, 10), (2, 20)]
        episode_snaps = [s for s in snapshots if "/episodes" in s[0]]
        assert all(s[1]["page"] == 1 for s in episode_snaps)

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


class TestRssSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(self, endpoint: str, MockSession) -> None:
        response = _source(endpoint)
        assert response.name == endpoint
        assert response.primary_keys == RSS_ENDPOINTS[endpoint].primary_keys
        # Episodes carry no stable creation timestamp, so no endpoint is partitioned.
        assert response.partition_mode is None

    def test_episodes_key_includes_parent_id(self) -> None:
        # Fan-out child rows aggregate every podcast's episodes into one table; the spec doesn't
        # document episode ids as globally unique, so the key must include the parent id.
        assert RSS_ENDPOINTS["episodes"].primary_keys == ["podcast_id", "id"]

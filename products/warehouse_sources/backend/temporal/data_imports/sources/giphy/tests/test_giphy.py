import json
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.giphy.giphy import (
    PAGE_SIZE,
    GiphyResumeConfig,
    giphy_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.giphy.settings import GIPHY_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the giphy module.
GIPHY_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.giphy.giphy.make_tracked_session"
)


def _response(
    body: dict[str, Any],
    *,
    status_code: int = 200,
    url: str = "https://api.giphy.com/v1/gifs/trending",
    reason: str = "OK",
) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp.reason = reason
    resp.url = url
    resp._content = json.dumps(body).encode()
    return resp


def _gif_page(ids: list[str], total_count: int) -> Response:
    return _response(
        {
            "data": [{"id": i, "type": "gif"} for i in ids],
            "pagination": {"count": len(ids), "total_count": total_count},
            "meta": {"status": 200, "msg": "OK"},
        }
    )


def _make_manager(resume_state: GiphyResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's query params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so inspecting it after the run shows
    only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _run(endpoint: str, manager: mock.MagicMock, **kwargs: Any) -> list[dict[str, Any]]:
    return _rows(
        giphy_source(
            api_key="KEY",
            endpoint=endpoint,
            team_id=1,
            job_id="j",
            resumable_source_manager=manager,
            **kwargs,
        )
    )


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_total_count_reached(self, MockSession) -> None:
        session = MockSession.return_value
        full = [str(i) for i in range(PAGE_SIZE)]
        params = _wire(
            session, [_gif_page(full, total_count=PAGE_SIZE + 2), _gif_page(["x", "y"], total_count=PAGE_SIZE + 2)]
        )

        rows = _run("gifs_trending", _make_manager())

        assert len(rows) == PAGE_SIZE + 2
        assert rows[-1] == {"id": "y", "type": "gif"}
        assert params[0]["offset"] == 0
        assert params[0]["limit"] == PAGE_SIZE
        assert params[1]["offset"] == PAGE_SIZE

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_short_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_gif_page(["a", "b"], total_count=999)])

        rows = _run("gifs_trending", _make_manager())

        assert [r["id"] for r in rows] == ["a", "b"]
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_empty_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_gif_page([], total_count=0)])

        rows = _run("gifs_trending", _make_manager())

        assert rows == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_at_offset_cap_without_requesting_beyond_it(self, MockSession) -> None:
        # gifs_trending caps at offset 499. Every page is full and total_count is far larger, so only
        # the offset cap can stop us — and it must stop before an offset GIPHY would reject is requested.
        session = MockSession.return_value
        cap = GIPHY_ENDPOINTS["gifs_trending"].max_offset
        assert cap == 499
        # offsets 0, 50, ..., 450 -> 10 full pages, then 500 >= 499 halts pagination.
        params = _wire(
            session,
            [_gif_page([f"{o}_{i}" for i in range(PAGE_SIZE)], total_count=10_000) for o in range(0, 500, PAGE_SIZE)],
        )

        _run("gifs_trending", _make_manager())

        requested = [p["offset"] for p in params]
        assert max(requested) <= cap
        assert max(requested) + PAGE_SIZE > cap


class TestResume:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_gif_page(["x", "y"], total_count=PAGE_SIZE + 2)])

        rows = _run("gifs_trending", _make_manager(GiphyResumeConfig(offset=PAGE_SIZE)))

        assert [r["id"] for r in rows] == ["x", "y"]
        assert params[0]["offset"] == PAGE_SIZE

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoint_saved_after_full_page_then_short_page_ends(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _gif_page([str(i) for i in range(PAGE_SIZE)], total_count=PAGE_SIZE + 1),
                _gif_page(["last"], total_count=PAGE_SIZE + 1),
            ],
        )

        manager = _make_manager()
        _run("gifs_trending", manager)

        # Saved once, advancing to the second page's offset, before that page ends the sync.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == GiphyResumeConfig(offset=PAGE_SIZE)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_first_page_saves_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_gif_page(["a", "b"], total_count=999)])

        manager = _make_manager()
        _run("gifs_trending", manager)

        manager.save_state.assert_not_called()


class TestSearch:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_search_includes_query_param(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_gif_page(["a"], total_count=1)])

        _run("gifs_search", _make_manager(), search_query="cats")

        assert params[0]["q"] == "cats"
        assert params[0]["limit"] == PAGE_SIZE
        assert params[0]["offset"] == 0

    @parameterized.expand(["gifs_search", "stickers_search"])
    def test_search_without_query_raises(self, endpoint: str) -> None:
        with pytest.raises(ValueError, match="requires a search query"):
            _run(endpoint, _make_manager(), search_query="   ")


class TestTermList:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_term_list_explodes_strings_single_fetch(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"data": ["cats", "dogs", "memes"], "meta": {"status": 200}})])

        manager = _make_manager()
        rows = _run("trending_search_terms", manager)

        assert rows == [{"search_term": "cats"}, {"search_term": "dogs"}, {"search_term": "memes"}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_term_list_missing_data_key_yields_no_rows(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"meta": {"status": 200}})])

        rows = _run("trending_search_terms", _make_manager())

        assert rows == []


class TestRedaction:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_api_key_registered_for_value_redaction(self, MockSession) -> None:
        # The key rides in the query string, so it must reach make_tracked_session as a redacted value
        # or it leaks into tracked URLs, samples, and raised error messages.
        session = MockSession.return_value
        _wire(session, [_gif_page(["a"], total_count=1)])

        _run("gifs_trending", _make_manager())

        assert MockSession.call_args.kwargs["redact_values"] == ("KEY",)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_message_does_not_leak_api_key(self, MockSession) -> None:
        api_key = "super-secret-key"
        session = MockSession.return_value
        session.headers = {}
        error = _response(
            {"meta": {"status": 400, "msg": "Bad Request"}},
            status_code=400,
            reason="Bad Request",
            url=f"https://api.giphy.com/v1/gifs/search?api_key={api_key}&q=cats&limit=50&offset=0",
        )
        session.prepare_request.side_effect = lambda request: mock.MagicMock()
        session.send.side_effect = [error]

        with pytest.raises(HTTPError) as exc_info:
            _rows(
                giphy_source(
                    api_key=api_key,
                    endpoint="gifs_search",
                    team_id=1,
                    job_id="j",
                    resumable_source_manager=_make_manager(),
                    search_query="cats",
                )
            )

        assert api_key not in str(exc_info.value)
        assert "api.giphy.com/v1/gifs/search" in str(exc_info.value)


class TestSourceResponse:
    @parameterized.expand(
        [
            ("gifs_trending", ["id"]),
            ("stickers_trending", ["id"]),
            ("gifs_search", ["id"]),
            ("stickers_search", ["id"]),
            ("categories", ["name_encoded"]),
            ("trending_search_terms", ["search_term"]),
        ]
    )
    def test_primary_keys_per_endpoint(self, endpoint: str, expected_keys: list[str]) -> None:
        response = giphy_source(
            api_key="KEY",
            endpoint=endpoint,
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
            search_query="cats",
        )
        assert response.name == endpoint
        assert response.primary_keys == expected_keys

    def test_full_refresh_sort_mode_default_ascending(self) -> None:
        response = giphy_source(
            api_key="KEY",
            endpoint="gifs_trending",
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
        )
        assert response.sort_mode == "asc"


class TestValidateCredentials:
    @parameterized.expand([(200, True), (401, False), (403, False), (500, False)])
    @mock.patch(GIPHY_SESSION_PATCH)
    def test_status_maps_to_validity(self, status_code: int, expected: bool, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("KEY") is expected

    @mock.patch(GIPHY_SESSION_PATCH)
    def test_network_error_is_invalid(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("KEY") is False

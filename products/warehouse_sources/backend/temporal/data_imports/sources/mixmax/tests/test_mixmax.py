import json
from typing import Any

from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.mixmax.mixmax import (
    MixmaxResumeConfig,
    _build_url,
    mixmax_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mixmax.settings import MIXMAX_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


def _resp(body: Any, *, status: int = 200, url: str = "https://api.mixmax.com/v1/sequences") -> Response:
    resp = Response()
    resp.status_code = status
    resp.url = url
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: MixmaxResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Any]) -> list[dict[str, Any]]:
    """Wire the mock session; return a list capturing each request's (url, params) AT SEND TIME.

    The paginator carries the next-page cursor inside a self-contained URL and clears ``params``, so
    both are snapshotted per prepared request (the single ``Request`` object is mutated in place).
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _run(session: mock.MagicMock, endpoint: str, manager: mock.MagicMock) -> list[dict[str, Any]]:
    return _rows(
        mixmax_source(api_key="tok", endpoint=endpoint, team_id=1, job_id="j", resumable_source_manager=manager)
    )


class TestBuildUrl:
    def test_collection_url_has_page_limit(self) -> None:
        assert _build_url("/sequences", single_object=False) == "https://api.mixmax.com/v1/sequences?limit=100"

    def test_collection_url_carries_next_cursor(self) -> None:
        url = _build_url("/sequences", single_object=False, next_cursor="abc123")
        assert url == "https://api.mixmax.com/v1/sequences?limit=100&next=abc123"

    def test_single_object_url_has_no_pagination_params(self) -> None:
        assert _build_url("/users/me", single_object=True) == "https://api.mixmax.com/v1/users/me"


class TestExtractionShapes:
    """The old `_extract_page` heuristic (now `_reshape_row` + the cursor paginator), asserted end to
    end: each body shape produces the same rows and terminates after a single request."""

    @parameterized.expand(
        [
            # Wrapped collection on its last page: hasNext False stops even though `next` echoes a value.
            (
                "wrapped_last_page",
                "sequences",
                {"results": [{"_id": "1"}], "next": "cur2", "hasNext": False},
                [{"_id": "1"}],
            ),
            # `hasNext` missing is treated as no more pages.
            ("wrapped_no_flag", "sequences", {"results": [{"_id": "1"}]}, [{"_id": "1"}]),
            # Empty wrapped page yields no rows.
            ("wrapped_empty", "sequences", {"results": [], "hasNext": False}, []),
            # `/…/me` single-object endpoints return the object directly — one record, no pagination.
            ("single_object", "users", {"_id": "u1", "email": "a@b.com"}, [{"_id": "u1", "email": "a@b.com"}]),
            # A dict-without-results on a defensive collection endpoint maps to one record.
            ("dict_without_results", "appointment_links", {"_id": "x"}, [{"_id": "x"}]),
            # A bare array (defensive) is treated as a full, unpaginated page.
            ("bare_list", "appointment_links", [{"_id": "1"}, {"_id": "2"}], [{"_id": "1"}, {"_id": "2"}]),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_shape(
        self, _name: str, endpoint: str, body: Any, expected: list[dict[str, Any]], MockSession: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        _wire(session, [_resp(body)])
        manager = _make_manager()

        assert _run(session, endpoint, manager) == expected
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_walks_cursor_pages_and_checkpoints_after_each_yield(self, MockSession: mock.MagicMock) -> None:
        next_url = "https://api.mixmax.com/v1/sequences?limit=100&next=cur2"
        session = MockSession.return_value
        snaps = _wire(
            session,
            [
                _resp({"results": [{"_id": "1"}], "next": "cur2", "hasNext": True}),
                _resp({"results": [{"_id": "2"}], "hasNext": False}),
            ],
        )
        manager = _make_manager()

        rows = _run(session, "sequences", manager)

        assert rows == [{"_id": "1"}, {"_id": "2"}]
        # First request hits the base collection path with the page limit; the second targets the
        # self-contained next-page URL with params cleared.
        assert snaps[0] == {"url": "https://api.mixmax.com/v1/sequences", "params": {"limit": 100}}
        assert snaps[1] == {"url": next_url, "params": {}}
        # Checkpoint saved only when another page follows, pointing at that next page — so a crash
        # re-yields the last page rather than skipping it.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == MixmaxResumeConfig(next_url=next_url)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession: mock.MagicMock) -> None:
        resume_url = "https://api.mixmax.com/v1/sequences?limit=100&next=cur2"
        session = MockSession.return_value
        snaps = _wire(session, [_resp({"results": [{"_id": "2"}], "hasNext": False})])
        manager = _make_manager(MixmaxResumeConfig(next_url=resume_url))

        rows = _run(session, "sequences", manager)

        # The first page is skipped entirely — only the saved cursor's page is fetched.
        assert rows == [{"_id": "2"}]
        assert snaps[0] == {"url": resume_url, "params": {}}
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_object_endpoint_targets_bare_path_without_limit(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_resp({"_id": "u1"})])
        manager = _make_manager()

        _run(session, "users", manager)

        assert snaps[0] == {"url": "https://api.mixmax.com/v1/users/me", "params": {}}


class TestRetryClassification:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_is_retried_then_succeeds(
        self, _name: str, status: int, MockSession: mock.MagicMock, _sleep: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        _wire(session, [_resp({}, status=status), _resp({"results": [], "hasNext": False})])
        manager = _make_manager()

        rows = _run(session, "sequences", manager)

        assert rows == []
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_raises_immediately(self, MockSession: mock.MagicMock) -> None:
        # A 401 is not retryable — it must surface as an HTTPError so the sync fails fast.
        session = MockSession.return_value
        _wire(session, [_resp({"error": "unauthorized"}, status=401)])
        manager = _make_manager()

        with mock.patch("tenacity.nap.time.sleep"):
            try:
                _run(session, "sequences", manager)
            except requests.HTTPError:
                pass
            else:
                raise AssertionError("expected an HTTPError")

        assert session.send.call_count == 1


class TestSourceResponse:
    @parameterized.expand(
        [
            ("sequences", ["_id"]),
            ("messages", ["_id"]),
            ("live_feed", ["uid"]),
            ("appointment_links", ["_id"]),
        ]
    )
    def test_source_response_carries_endpoint_primary_keys(self, endpoint: str, expected_pks: list[str]) -> None:
        response = mixmax_source(
            api_key="tok",
            endpoint=endpoint,
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
        )
        assert response.name == endpoint
        assert response.primary_keys == expected_pks
        # Collections arrive newest-first; declared honestly so full-refresh ordering isn't misread.
        assert response.sort_mode == "desc"

    def test_every_endpoint_declares_a_unique_primary_key(self) -> None:
        # A non-unique/empty primary key seeds duplicate rows and makes every merge multi-match (OOM risk).
        for config in MIXMAX_ENDPOINTS.values():
            assert config.primary_keys, f"{config.name} has no primary key"

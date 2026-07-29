import json
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.heroku.heroku import (
    HEROKU_API_ACCEPT,
    HerokuResumeConfig,
    heroku_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.heroku.settings import (
    DEFAULT_PAGE_SIZE,
    HEROKU_ENDPOINTS,
    MAX_PAGES_PER_LIST,
)

# heroku_source builds the client session (capture=False) via make_tracked_session in the heroku
# module, and validate_credentials builds its probe session there too — one patch covers both.
SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.heroku.heroku.make_tracked_session"

INITIAL_RANGE = f"id ..; order=asc,max={DEFAULT_PAGE_SIZE}"


def _response(
    status_code: int = 200, json_data: list[dict[str, Any]] | None = None, next_range: str | None = None
) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(json_data if json_data is not None else []).encode()
    if next_range:
        resp.headers["Next-Range"] = next_range
    return resp


def _make_manager(resume: HerokuResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _wire(session: mock.MagicMock, responses: list[Response] | Any) -> tuple[list[dict[str, Any]], list[str]]:
    """Wire a mock session; capture each request's headers and URL AT PREPARE TIME.

    The Range header is mutated in place on the shared request across pages, so snapshot a copy
    when each request is prepared rather than inspecting the final state.
    """
    session.headers = {}
    header_snapshots: list[dict[str, Any]] = []
    url_snapshots: list[str] = []

    def _prepare(request: Any) -> mock.MagicMock:
        header_snapshots.append(dict(request.headers or {}))
        url_snapshots.append(request.url)
        prepared = mock.MagicMock()
        prepared.url = request.url
        prepared.is_redirect = False
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return header_snapshots, url_snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock) -> Any:
    return heroku_source("key", endpoint, team_id=1, job_id="j", resumable_source_manager=manager)


class TestPagination:
    @mock.patch(SESSION_PATCH)
    def test_follows_next_range_header_until_absent(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        headers, _urls = _wire(
            session,
            [
                _response(206, [{"id": "a"}], next_range="id ]a..; order=asc,max=1000"),
                _response(200, [{"id": "b"}]),
            ],
        )

        rows = _rows(_source("apps", _make_manager()))

        assert rows == [{"id": "a"}, {"id": "b"}]
        assert headers[0]["Range"] == INITIAL_RANGE
        assert headers[1]["Range"] == "id ]a..; order=asc,max=1000"
        assert session.headers.get("Accept") == HEROKU_API_ACCEPT

    @mock.patch(SESSION_PATCH)
    def test_saves_cursor_once_and_only_while_pages_remain(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(206, [{"id": "a"}], next_range="id ]a..; order=asc,max=1000"),
                _response(200, [{"id": "b"}]),
            ],
        )
        manager = _make_manager()

        _rows(_source("apps", manager))

        # One checkpoint pointing at the next page after the first (206) page; the final page saves
        # nothing (no next range).
        manager.save_state.assert_called_once_with(HerokuResumeConfig(next_range="id ]a..; order=asc,max=1000"))

    @mock.patch(SESSION_PATCH)
    def test_resumes_top_level_from_saved_cursor(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        headers, _urls = _wire(session, [_response(200, [{"id": "b"}])])
        manager = _make_manager(HerokuResumeConfig(next_range="id ]a..; order=asc,max=1000"))

        rows = _rows(_source("apps", manager))

        assert rows == [{"id": "b"}]
        assert headers[0]["Range"] == "id ]a..; order=asc,max=1000"

    @mock.patch(SESSION_PATCH)
    def test_page_cap_stops_unbounded_scans(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        session.headers = {}
        session.prepare_request.side_effect = lambda request: mock.MagicMock(url=request.url, is_redirect=False)
        session.send.side_effect = lambda *a, **k: _response(
            206, [{"id": "a"}], next_range="id ]a..; order=asc,max=1000"
        )

        pages = list(_source("apps", _make_manager()).items())

        assert len(pages) == MAX_PAGES_PER_LIST
        assert session.send.call_count == MAX_PAGES_PER_LIST


class TestRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 502)])
    @mock.patch("time.sleep")
    @mock.patch(SESSION_PATCH)
    def test_retries_transient_statuses_then_succeeds(
        self, _name: str, status_code: int, MockSession: mock.MagicMock, _sleep: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        _wire(session, [_response(status_code), _response(200, [{"id": "a"}])])

        rows = _rows(_source("apps", _make_manager()))

        assert rows == [{"id": "a"}]
        assert session.send.call_count == 2

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    @mock.patch(SESSION_PATCH)
    def test_credential_errors_raise_without_retry(
        self, _name: str, status_code: int, MockSession: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        _wire(session, [_response(status_code)])

        with pytest.raises(requests.HTTPError):
            _rows(_source("apps", _make_manager()))

        assert session.send.call_count == 1


class TestFanOut:
    @mock.patch(SESSION_PATCH)
    def test_fans_out_over_every_app(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _headers, urls = _wire(
            session,
            [
                _response(200, [{"id": "app-1"}, {"id": "app-2"}]),
                _response(200, [{"id": "rel-1", "app": {"id": "app-1"}}]),
                _response(200, [{"id": "rel-2", "app": {"id": "app-2"}}]),
            ],
        )

        rows = _rows(_source("releases", _make_manager()))

        assert rows == [
            {"id": "rel-1", "app": {"id": "app-1"}},
            {"id": "rel-2", "app": {"id": "app-2"}},
        ]
        assert urls == [
            "https://api.heroku.com/apps",
            "https://api.heroku.com/apps/app-1/releases",
            "https://api.heroku.com/apps/app-2/releases",
        ]

    @mock.patch(SESSION_PATCH)
    def test_app_deleted_mid_sync_is_skipped(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(200, [{"id": "app-1"}, {"id": "app-2"}]),
                _response(404),
                _response(200, [{"id": "rel-2", "app": {"id": "app-2"}}]),
            ],
        )

        rows = _rows(_source("releases", _make_manager()))

        assert rows == [{"id": "rel-2", "app": {"id": "app-2"}}]

    @mock.patch(SESSION_PATCH)
    def test_resumes_from_bookmarked_app_with_saved_cursor(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        headers, urls = _wire(
            session,
            [
                _response(200, [{"id": "app-1"}, {"id": "app-2"}, {"id": "app-3"}]),
                _response(200, [{"id": "rel-2"}]),
                _response(200, [{"id": "rel-3"}]),
            ],
        )
        saved_cursor = "id ]rel-1..; order=asc,max=1000"
        manager = _make_manager(
            HerokuResumeConfig(
                fanout_state={
                    "completed": ["/apps/app-1/releases"],
                    "current": "/apps/app-2/releases",
                    "child_state": {"next_range": saved_cursor},
                }
            )
        )

        rows = _rows(_source("releases", manager))

        assert rows == [{"id": "rel-2"}, {"id": "rel-3"}]
        # The already-completed app is never re-fetched.
        assert "https://api.heroku.com/apps/app-1/releases" not in urls
        # The resumed app starts from the saved cursor; the next app starts from a fresh first page.
        assert headers[1]["Range"] == saved_cursor
        assert headers[2]["Range"] == INITIAL_RANGE

    @mock.patch(SESSION_PATCH)
    def test_pre_migration_bookmark_restarts_fan_out(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        headers, urls = _wire(
            session,
            [
                _response(200, [{"id": "app-1"}]),
                _response(200, [{"id": "rel-1"}]),
            ],
        )
        # Old-shape state (positional app bookmark, no fanout snapshot) can't be reconstructed, so the
        # fan-out restarts from the first app on a fresh first page.
        manager = _make_manager(HerokuResumeConfig(next_range="id ]x..; order=asc,max=1000", app_id="app-gone"))

        rows = _rows(_source("releases", manager))

        assert rows == [{"id": "rel-1"}]
        assert "https://api.heroku.com/apps/app-1/releases" in urls
        assert headers[1]["Range"] == INITIAL_RANGE


class TestSensitiveFieldRedaction:
    @parameterized.expand(
        [
            (
                "build_capability_urls_nulled",
                "builds",
                {
                    "id": "b-1",
                    "output_stream_url": "https://build-output.heroku.com/streams/secret",
                    "source_blob": {"url": "https://signed.example.com/tarball?sig=secret", "checksum": "SHA256:abc"},
                },
                {"id": "b-1", "output_stream_url": None, "source_blob": {"url": None, "checksum": "SHA256:abc"}},
            ),
            (
                "release_output_stream_nulled",
                "releases",
                {"id": "r-1", "output_stream_url": "https://release-output.heroku.com/streams/secret", "version": 3},
                {"id": "r-1", "output_stream_url": None, "version": 3},
            ),
            (
                "dyno_attach_url_nulled",
                "dynos",
                {"id": "d-1", "attach_url": "rendezvous://rendezvous.runtime.heroku.com:5000/secret", "state": "up"},
                {"id": "d-1", "attach_url": None, "state": "up"},
            ),
            (
                "row_without_sensitive_fields_untouched",
                "builds",
                {"id": "b-2", "status": "succeeded"},
                {"id": "b-2", "status": "succeeded"},
            ),
        ]
    )
    @mock.patch(SESSION_PATCH)
    def test_capability_urls_never_reach_the_warehouse(
        self, _name: str, endpoint: str, row: dict[str, Any], expected: dict[str, Any], MockSession: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        _wire(session, [_response(200, [{"id": "app-1"}]), _response(200, [row])])

        rows = _rows(_source(endpoint, _make_manager()))

        assert rows == [expected]


class TestValidateCredentials:
    @parameterized.expand([("valid", 200, True), ("unauthorized", 401, False)])
    @mock.patch(SESSION_PATCH)
    def test_maps_account_probe_status(
        self, _name: str, status_code: int, expected: bool, MockSession: mock.MagicMock
    ) -> None:
        MockSession.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("key") is expected

    @mock.patch(SESSION_PATCH)
    def test_network_error_is_invalid(self, MockSession: mock.MagicMock) -> None:
        MockSession.return_value.get.side_effect = requests.ConnectionError("boom")
        assert validate_credentials("key") is False


class TestSourceResponse:
    @parameterized.expand([(name,) for name in HEROKU_ENDPOINTS])
    @mock.patch(SESSION_PATCH)
    def test_source_response_matches_endpoint_settings(self, endpoint: str, MockSession: mock.MagicMock) -> None:
        response = _source(endpoint, _make_manager())
        config = HEROKU_ENDPOINTS[endpoint]

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
            # updated_at moves on every write, which would rewrite partitions each sync.
            assert config.partition_key != "updated_at"
        else:
            assert response.partition_mode is None

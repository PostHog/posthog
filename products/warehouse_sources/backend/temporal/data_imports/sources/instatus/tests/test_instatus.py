import json
from typing import Any

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.instatus.instatus import (
    InstatusResumeConfig,
    _child_path,
    _client_config,
    instatus_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.instatus.settings import INSTATUS_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the instatus module.
INSTATUS_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.instatus.instatus.make_tracked_session"
)


def _response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: InstatusResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[str], list[dict[str, Any]]]:
    """Wire a mock session, capturing each request's url and params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    url_snapshots: list[str] = []
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        url_snapshots.append(request.url)
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return url_snapshots, param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock):
    return instatus_source("key", endpoint, team_id=1, job_id="j", resumable_source_manager=manager)


class TestClientConfig:
    def test_uses_bearer_auth_and_json_content_type(self):
        config = _client_config("abc123")
        assert config["auth"] == {"type": "bearer", "token": "abc123"}
        # Instatus requires the JSON content type on every request, including GETs.
        assert config["headers"]["Content-Type"] == "application/json"
        # A credentialed request stays pinned to the validated host — a 3xx can't replay it elsewhere.
        assert config["allow_redirects"] is False


class TestPagesEndpoint:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_empty_including_short_pages(self, MockSession):
        session = MockSession.return_value
        # Pages of 2 then 1 rows are both short (< per_page) yet pagination must continue: a
        # short-but-non-empty page is not the last one. Only the empty array terminates.
        _, params = _wire(
            session,
            [_response([{"id": "p1"}, {"id": "p2"}]), _response([{"id": "p3"}]), _response([])],
        )

        rows = _rows(_source("pages", _make_manager()))

        assert [r["id"] for r in rows] == ["p1", "p2", "p3"]
        assert params[0]["per_page"] == 100
        assert params[0]["page"] == 1
        assert params[1]["page"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoints_next_page_after_each_non_empty_page(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response([{"id": "p1"}]), _response([{"id": "p2"}]), _response([])])
        manager = _make_manager()

        _rows(_source("pages", manager))

        saved = [c.args[0] for c in manager.save_state.call_args_list]
        # State saved once per non-empty yielded page, each pointing at the next page.
        assert [(s.page, s.parent_page_id, s.fanout_state) for s in saved] == [(2, None, None), (3, None, None)]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession):
        session = MockSession.return_value
        _, params = _wire(session, [_response([{"id": "p9"}]), _response([])])
        manager = _make_manager(InstatusResumeConfig(page=3, parent_page_id=None))

        _rows(_source("pages", manager))

        assert params[0]["page"] == 3

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_raises(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response({"error": {"message": "Could not authenticate"}}, status_code=401)])

        with pytest.raises(requests.HTTPError):
            _rows(_source("pages", _make_manager()))

    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retries_rate_limit_then_succeeds(self, MockSession, _mock_sleep):
        session = MockSession.return_value
        # A 429 is retried by the shared client; the retried attempt returns the page.
        _wire(session, [_response([], status_code=429), _response([{"id": "p1"}]), _response([])])

        rows = _rows(_source("pages", _make_manager()))

        assert [r["id"] for r in rows] == ["p1"]
        # First send 429, retried, then page 1, then empty terminator = 3 sends.
        assert session.send.call_count == 3


class TestFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fans_out_over_pages_and_injects_page_id(self, MockSession):
        session = MockSession.return_value
        urls, _ = _wire(
            session,
            [
                _response([{"id": "p1"}, {"id": "p2"}]),  # /v2/pages page 1
                _response([{"id": "c1"}]),  # /v1/p1/components page 1
                _response([]),  # /v1/p1/components page 2 (stop)
                _response([{"id": "c2"}]),  # /v1/p2/components page 1
                _response([]),  # /v1/p2/components page 2 (stop)
                _response([]),  # /v2/pages page 2 (stop)
            ],
        )

        rows = _rows(_source("components", _make_manager()))

        # page_id injected so the composite [page_id, id] key stays unique table-wide.
        assert rows == [{"id": "c1", "page_id": "p1"}, {"id": "c2", "page_id": "p2"}]
        assert "https://api.instatus.com/v1/p1/components" in urls
        assert "https://api.instatus.com/v1/p2/components" in urls

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_fan_out_at_saved_parent_and_page(self, MockSession):
        session = MockSession.return_value
        urls, params = _wire(
            session,
            [
                _response([{"id": "p1"}, {"id": "p2"}]),  # pages relisted on resume
                _response([{"id": "c2b"}]),  # resume p2 at page 2
                _response([]),  # p2 components page 3 (stop)
                _response([]),  # pages page 2 (stop)
            ],
        )
        # p1 already completed, p2 in progress at its next page (2) — p1 must not be re-requested.
        manager = _make_manager(
            InstatusResumeConfig(
                fanout_state={
                    "completed": [_child_path("components", "p1")],
                    "current": _child_path("components", "p2"),
                    "child_state": {"page": 2},
                }
            )
        )

        rows = _rows(_source("components", manager))

        assert rows == [{"id": "c2b", "page_id": "p2"}]
        assert not any("/v1/p1/components" in url for url in urls)
        component_requests = [
            (url, p) for url, p in zip(urls, params) if url == "https://api.instatus.com/v1/p2/components"
        ]
        assert component_requests[0][1]["page"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_parent_id_raises_loudly(self, MockSession):
        session = MockSession.return_value
        # A status page without an id can't drive the child fan-out — surface it loudly.
        _wire(session, [_response([{"name": "no-id"}]), _response([])])

        with pytest.raises(ValueError, match="id"):
            _rows(_source("components", _make_manager()))


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_ok",
        [(200, True), (401, False), (403, False), (500, False)],
    )
    @mock.patch(INSTATUS_SESSION_PATCH)
    def test_status_mapping(self, mock_session, status_code, expected_ok):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        ok, error = validate_credentials("key")
        assert ok is expected_ok
        if not ok:
            assert error

    @mock.patch(INSTATUS_SESSION_PATCH)
    def test_probes_pages_endpoint(self, mock_session):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("key")
        url = mock_session.return_value.get.call_args.args[0]
        assert url.startswith("https://api.instatus.com/v2/pages")

    @mock.patch(INSTATUS_SESSION_PATCH)
    def test_request_exception_is_failure(self, mock_session):
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        ok, error = validate_credentials("key")
        assert ok is False
        assert error


class TestInstatusSourceResponse:
    @pytest.mark.parametrize("endpoint", list(INSTATUS_ENDPOINTS.keys()))
    def test_source_response_shape(self, endpoint):
        config = INSTATUS_ENDPOINTS[endpoint]
        response = _source(endpoint, _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_key
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize(
        "endpoint, expected_keys",
        [
            ("pages", ["id"]),
            ("components", ["page_id", "id"]),
            ("subscribers", ["page_id", "id"]),
            ("incidents", ["page_id", "id"]),
        ],
    )
    def test_primary_keys_are_unique_table_wide(self, endpoint, expected_keys):
        # Fan-out children carry the parent page id in their key so rows from different pages
        # never collide on a bare resource id.
        assert INSTATUS_ENDPOINTS[endpoint].primary_key == expected_keys

    @pytest.mark.parametrize(
        "endpoint, expected_partition",
        [
            ("pages", "createdAt"),
            ("components", "createdAt"),
            ("templates", "createdAt"),
            ("incidents", "started"),
            ("maintenances", "start"),
            ("subscribers", None),
            ("metrics", None),
        ],
    )
    def test_partition_keys_are_stable_fields(self, endpoint, expected_partition):
        # Partition only on immutable creation-time fields, never updatedAt.
        assert INSTATUS_ENDPOINTS[endpoint].partition_key == expected_partition

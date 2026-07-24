import json
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.launchdarkly import (
    API_HOST,
    BASE_URL,
    LaunchDarklyResumeConfig,
    _resolve_url,
    launchdarkly_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.settings import (
    ENDPOINTS,
    LAUNCHDARKLY_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the launchdarkly module.
LD_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.launchdarkly.make_tracked_session"
)
SLEEP_PATCH = "tenacity.nap.time.sleep"


def _make_manager(resume_state: LaunchDarklyResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(items: list[dict[str, Any]], next_href: str | None = None, status_code: int = 200) -> Response:
    links: dict[str, Any] = {}
    if next_href:
        links["next"] = {"href": next_href}
    resp = Response()
    resp.status_code = status_code
    resp.url = f"{BASE_URL}/members"
    resp._content = json.dumps({"items": items, "_links": links}).encode()
    return resp


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session; capture each request's URL and params AT SEND TIME.

    The paginator mutates ``request.url``/``request.params`` in place across pages, so a copy is
    snapshotted when each request is prepared.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock):
    return launchdarkly_source("token", endpoint, team_id=1, job_id="j", resumable_source_manager=manager)


class TestUrlHelpers:
    @pytest.mark.parametrize(
        "href, expected",
        [
            ("/api/v2/projects?limit=20&offset=20", f"{API_HOST}/api/v2/projects?limit=20&offset=20"),
            ("https://app.launchdarkly.com/api/v2/members?offset=40", f"{API_HOST}/api/v2/members?offset=40"),
        ],
    )
    def test_resolve_url(self, href, expected):
        assert _resolve_url(href) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code", [200, 401, 403, 500])
    @mock.patch(LD_SESSION_PATCH)
    def test_returns_status_code(self, mock_session, status_code):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("api-token") == status_code

    @mock.patch(LD_SESSION_PATCH)
    def test_uses_no_bearer_prefix(self, mock_session):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("api-secret-token")
        headers = mock_session.return_value.get.call_args.kwargs["headers"]
        assert headers["Authorization"] == "api-secret-token"

    @mock.patch(LD_SESSION_PATCH)
    def test_returns_none_on_exception(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("api-token") is None


class TestGetRowsTopLevel:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_via_links_next(self, mock_session):
        session = mock_session.return_value
        snaps = _wire(
            session,
            [
                _response([{"_id": "1"}, {"_id": "2"}], "/api/v2/members?limit=20&offset=20"),
                _response([{"_id": "3"}], None),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("members", manager))

        assert [item["_id"] for item in rows] == ["1", "2", "3"]
        # No project key injected for top-level endpoints.
        assert all("_project_key" not in item for item in rows)
        # First page targets the base path; second follows the (resolved) _links.next href.
        assert snaps[0]["url"] == f"{BASE_URL}/members"
        assert snaps[0]["params"]["limit"] == 20
        assert snaps[1]["url"] == f"{API_HOST}/api/v2/members?limit=20&offset=20"
        # One checkpoint, saved after the first page (points at the next URL); the last page saves none.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == LaunchDarklyResumeConfig(
            next_url=f"{API_HOST}/api/v2/members?limit=20&offset=20"
        )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state(self, mock_session):
        session = mock_session.return_value
        snaps = _wire(session, [_response([{"_id": "9"}], None)])

        resume_url = f"{API_HOST}/api/v2/members?limit=20&offset=80"
        manager = _make_manager(LaunchDarklyResumeConfig(next_url=resume_url))
        _rows(_source("members", manager))

        assert snaps[0]["url"] == resume_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_response_yields_nothing(self, mock_session):
        session = mock_session.return_value
        _wire(session, [_response([], None)])

        manager = _make_manager()
        assert _rows(_source("members", manager)) == []
        manager.save_state.assert_not_called()


class TestGetRowsFanout:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_iterates_projects_and_injects_project_key(self, mock_session):
        session = mock_session.return_value
        snaps = _wire(
            session,
            [
                _response([{"key": "proj1"}, {"key": "proj2"}], None),
                _response([{"_id": "e1"}], None),
                _response([{"_id": "e2"}], None),
            ],
        )

        rows = _rows(_source("environments", _make_manager()))

        assert rows == [
            {"_id": "e1", "_project_key": "proj1"},
            {"_id": "e2", "_project_key": "proj2"},
        ]
        urls = [snap["url"] for snap in snaps]
        assert urls[0] == f"{BASE_URL}/projects"
        assert urls[1] == f"{BASE_URL}/projects/proj1/environments"
        assert urls[2] == f"{BASE_URL}/projects/proj2/environments"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_metrics_compose_path(self, mock_session):
        session = mock_session.return_value
        snaps = _wire(
            session,
            [
                _response([{"key": "proj1"}], None),
                _response([{"_id": "m1"}], None),
            ],
        )
        _rows(_source("metrics", _make_manager()))

        assert snaps[1]["url"] == f"{BASE_URL}/metrics/proj1"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_skips_completed_project(self, mock_session):
        session = mock_session.return_value
        # proj1 already fully synced last run; resume must start at proj2.
        snaps = _wire(
            session,
            [
                _response([{"key": "proj1"}, {"key": "proj2"}], None),
                _response([{"_id": "e2"}], None),
            ],
        )
        manager = _make_manager(
            LaunchDarklyResumeConfig(
                fanout_state={"completed": ["/projects/proj1/environments"], "current": None, "child_state": None}
            )
        )

        rows = _rows(_source("environments", manager))

        assert rows == [{"_id": "e2", "_project_key": "proj2"}]
        urls = [snap["url"] for snap in snaps]
        assert urls == [f"{BASE_URL}/projects", f"{BASE_URL}/projects/proj2/environments"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_midproject_uses_saved_url(self, mock_session):
        session = mock_session.return_value
        resume_url = f"{BASE_URL}/projects/proj1/environments?limit=20&offset=20"
        snaps = _wire(
            session,
            [
                _response([{"key": "proj1"}, {"key": "proj2"}], None),
                _response([{"_id": "e1b"}], None),
                _response([{"_id": "e2"}], None),
            ],
        )
        manager = _make_manager(
            LaunchDarklyResumeConfig(
                fanout_state={
                    "completed": [],
                    "current": "/projects/proj1/environments",
                    "child_state": {"next_url": resume_url},
                }
            )
        )

        _rows(_source("environments", manager))

        urls = [snap["url"] for snap in snaps]
        assert urls == [
            f"{BASE_URL}/projects",
            resume_url,
            f"{BASE_URL}/projects/proj2/environments",
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_projects_yields_nothing(self, mock_session):
        session = mock_session.return_value
        _wire(session, [_response([], None)])

        assert _rows(_source("flags", _make_manager())) == []


class TestRetryAndErrors:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_4xx_raises(self, mock_session):
        session = mock_session.return_value
        _wire(session, [_response([], None, status_code=403)])

        with pytest.raises(Exception, match="403 Client Error"):
            _rows(_source("members", _make_manager()))

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_429_is_retried_then_succeeds(self, mock_session, _mock_sleep):
        session = mock_session.return_value
        # A 429 is retryable at the client layer; the retry re-issues and succeeds.
        _wire(
            session,
            [
                _response([], None, status_code=429),
                _response([{"_id": "1"}], None),
            ],
        )

        rows = _rows(_source("members", _make_manager()))
        assert [item["_id"] for item in rows] == ["1"]


class TestLaunchDarklySourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_response_metadata_per_endpoint(self, mock_session, endpoint):
        mock_session.return_value.headers = {}
        config = LAUNCHDARKLY_ENDPOINTS[endpoint]
        response = _source(endpoint, _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_key
        # Partitioning is intentionally off (epoch-ms timestamps).
        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_flags_use_composite_primary_key(self):
        assert LAUNCHDARKLY_ENDPOINTS["flags"].primary_key == ["key", "_project_key"]

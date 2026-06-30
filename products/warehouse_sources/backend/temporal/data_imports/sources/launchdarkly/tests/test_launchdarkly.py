from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.launchdarkly import (
    API_HOST,
    BASE_URL,
    LaunchDarklyResumeConfig,
    _initial_url,
    _next_url_from,
    _resolve_url,
    get_rows,
    launchdarkly_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.settings import (
    ENDPOINTS,
    LAUNCHDARKLY_ENDPOINTS,
)


def _make_manager(resume_state: LaunchDarklyResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _page(items: list[dict[str, Any]], next_href: str | None = None) -> dict[str, Any]:
    links: dict[str, Any] = {}
    if next_href:
        links["next"] = {"href": next_href}
    return {"items": items, "_links": links}


def _resp(page: dict[str, Any], status_code: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = page
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 300
    return resp


class TestUrlHelpers:
    def test_initial_url_includes_limit(self):
        assert _initial_url("/projects", 20) == f"{BASE_URL}/projects?limit=20"

    @pytest.mark.parametrize(
        "href, expected",
        [
            ("/api/v2/projects?limit=20&offset=20", f"{API_HOST}/api/v2/projects?limit=20&offset=20"),
            ("https://app.launchdarkly.com/api/v2/members?offset=40", f"{API_HOST}/api/v2/members?offset=40"),
        ],
    )
    def test_resolve_url(self, href, expected):
        assert _resolve_url(href) == expected

    @pytest.mark.parametrize(
        "data, expected",
        [
            ({"_links": {"next": {"href": "/api/v2/members?offset=20"}}}, f"{API_HOST}/api/v2/members?offset=20"),
            ({"_links": {}}, None),
            ({}, None),
            ({"_links": {"next": {}}}, None),
        ],
    )
    def test_next_url_from(self, data, expected):
        assert _next_url_from(data) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code", [200, 401, 403, 500])
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.launchdarkly.make_tracked_session"
    )
    def test_returns_status_code(self, mock_session, status_code):
        response = mock.MagicMock(status_code=status_code)
        mock_session.return_value.get.return_value = response
        assert validate_credentials("api-token") == status_code

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.launchdarkly.make_tracked_session"
    )
    def test_uses_no_bearer_prefix(self, mock_session):
        response = mock.MagicMock(status_code=200)
        mock_session.return_value.get.return_value = response
        validate_credentials("api-secret-token")
        headers = mock_session.return_value.get.call_args.kwargs["headers"]
        assert headers["Authorization"] == "api-secret-token"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.launchdarkly.make_tracked_session"
    )
    def test_returns_none_on_exception(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("api-token") is None


class TestGetRowsTopLevel:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.launchdarkly.make_tracked_session"
    )
    def test_paginates_via_links_next(self, mock_session):
        pages = [
            _page([{"_id": "1"}, {"_id": "2"}], "/api/v2/members?limit=20&offset=20"),
            _page([{"_id": "3"}], None),
        ]
        mock_session.return_value.get.side_effect = [_resp(p) for p in pages]

        manager = _make_manager()
        batches = list(get_rows("token", "members", mock.MagicMock(), manager))

        assert [item["_id"] for batch in batches for item in batch] == ["1", "2", "3"]
        # No project key injected for top-level endpoints.
        assert all("_project_key" not in item for batch in batches for item in batch)
        # State saved after every page (final save records the empty next_url marker).
        saved_urls = [call.args[0].next_url for call in manager.save_state.call_args_list]
        assert saved_urls == [f"{API_HOST}/api/v2/members?limit=20&offset=20", ""]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.launchdarkly.make_tracked_session"
    )
    def test_resumes_from_saved_state(self, mock_session):
        mock_session.return_value.get.return_value = _resp(_page([{"_id": "9"}], None))

        resume_url = f"{API_HOST}/api/v2/members?limit=20&offset=80"
        manager = _make_manager(LaunchDarklyResumeConfig(next_url=resume_url))

        list(get_rows("token", "members", mock.MagicMock(), manager))

        assert mock_session.return_value.get.call_args_list[0].args[0] == resume_url

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.launchdarkly.make_tracked_session"
    )
    def test_empty_response_yields_nothing(self, mock_session):
        mock_session.return_value.get.return_value = _resp(_page([], None))

        manager = _make_manager()
        batches = list(get_rows("token", "members", mock.MagicMock(), manager))

        assert batches == []


class TestGetRowsFanout:
    def _fanout_side_effect(self) -> list[mock.MagicMock]:
        # 1) project list, 2) environments for proj1, 3) environments for proj2
        return [
            _resp(_page([{"key": "proj1"}, {"key": "proj2"}], None)),
            _resp(_page([{"_id": "e1"}], None)),
            _resp(_page([{"_id": "e2"}], None)),
        ]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.launchdarkly.make_tracked_session"
    )
    def test_iterates_projects_and_injects_project_key(self, mock_session):
        mock_session.return_value.get.side_effect = self._fanout_side_effect()

        manager = _make_manager()
        batches = list(get_rows("token", "environments", mock.MagicMock(), manager))

        rows = [item for batch in batches for item in batch]
        assert rows == [
            {"_id": "e1", "_project_key": "proj1"},
            {"_id": "e2", "_project_key": "proj2"},
        ]

        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert urls[0] == f"{BASE_URL}/projects?limit=20"
        assert urls[1] == f"{BASE_URL}/projects/proj1/environments?limit=20"
        assert urls[2] == f"{BASE_URL}/projects/proj2/environments?limit=20"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.launchdarkly.make_tracked_session"
    )
    def test_flags_compose_metrics_path(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _resp(_page([{"key": "proj1"}], None)),
            _resp(_page([{"_id": "m1"}], None)),
        ]
        list(get_rows("token", "metrics", mock.MagicMock(), _make_manager()))

        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert urls[1] == f"{BASE_URL}/metrics/proj1?limit=20"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.launchdarkly.make_tracked_session"
    )
    def test_resume_skips_completed_project(self, mock_session):
        # proj1 was finished last run (empty next_url marker); resume must start at proj2.
        mock_session.return_value.get.side_effect = [
            _resp(_page([{"key": "proj1"}, {"key": "proj2"}], None)),
            _resp(_page([{"_id": "e2"}], None)),
        ]
        manager = _make_manager(LaunchDarklyResumeConfig(next_url="", project_key="proj1"))

        batches = list(get_rows("token", "environments", mock.MagicMock(), manager))

        rows = [item for batch in batches for item in batch]
        assert rows == [{"_id": "e2", "_project_key": "proj2"}]
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        # projects list + proj2 environments only (proj1 skipped)
        assert urls == [f"{BASE_URL}/projects?limit=20", f"{BASE_URL}/projects/proj2/environments?limit=20"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.launchdarkly.make_tracked_session"
    )
    def test_resume_midproject_uses_saved_url(self, mock_session):
        resume_url = f"{BASE_URL}/projects/proj1/environments?limit=20&offset=20"
        mock_session.return_value.get.side_effect = [
            _resp(_page([{"key": "proj1"}, {"key": "proj2"}], None)),
            _resp(_page([{"_id": "e1b"}], None)),
            _resp(_page([{"_id": "e2"}], None)),
        ]
        manager = _make_manager(LaunchDarklyResumeConfig(next_url=resume_url, project_key="proj1"))

        list(get_rows("token", "environments", mock.MagicMock(), manager))

        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert urls == [
            f"{BASE_URL}/projects?limit=20",
            resume_url,
            f"{BASE_URL}/projects/proj2/environments?limit=20",
        ]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.launchdarkly.make_tracked_session"
    )
    def test_no_projects_yields_nothing(self, mock_session):
        mock_session.return_value.get.return_value = _resp(_page([], None))

        batches = list(get_rows("token", "flags", mock.MagicMock(), _make_manager()))
        assert batches == []


class TestRetryAndErrors:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.launchdarkly.make_tracked_session"
    )
    def test_4xx_raises(self, mock_session):
        resp = _resp(_page([], None), status_code=403)
        resp.raise_for_status.side_effect = Exception("403 Client Error")
        mock_session.return_value.get.return_value = resp

        with pytest.raises(Exception, match="403 Client Error"):
            list(get_rows("token", "members", mock.MagicMock(), _make_manager()))


class TestLaunchDarklySourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = LAUNCHDARKLY_ENDPOINTS[endpoint]
        response = launchdarkly_source("token", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_key
        # Partitioning is intentionally off (epoch-ms timestamps).
        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_flags_use_composite_primary_key(self):
        assert LAUNCHDARKLY_ENDPOINTS["flags"].primary_key == ["key", "_project_key"]

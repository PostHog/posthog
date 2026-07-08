from typing import Any, Optional

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.asana.asana import (
    ASANA_BASE_URL,
    AsanaResumeConfig,
    _build_initial_urls,
    _list_params,
    _with_query,
    asana_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.asana.settings import ASANA_ENDPOINTS, ENDPOINTS


def _make_manager(resume_state: Optional[AsanaResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _page(items: list[dict[str, Any]], next_uri: Optional[str]) -> dict[str, Any]:
    return {"data": items, "next_page": {"uri": next_uri, "offset": "tok"} if next_uri else None}


def _ok_response(payload: dict[str, Any]) -> mock.MagicMock:
    resp = mock.MagicMock(status_code=200, ok=True)
    resp.json.return_value = payload
    return resp


class TestWithQuery:
    def test_appends_with_question_mark_when_no_existing_query(self):
        assert _with_query("/workspaces", {"limit": 100}) == f"{ASANA_BASE_URL}/workspaces?limit=100"

    def test_appends_with_ampersand_when_query_present(self):
        url = _with_query("/projects?workspace=1", {"limit": 100})
        assert url == f"{ASANA_BASE_URL}/projects?workspace=1&limit=100"

    def test_drops_none_values(self):
        assert _with_query("/workspaces", {"limit": None}) == f"{ASANA_BASE_URL}/workspaces"

    def test_encodes_comma_separated_opt_fields(self):
        url = _with_query("/workspaces", {"opt_fields": "name,created_at"})
        assert "opt_fields=name%2Ccreated_at" in url


class TestListParams:
    def test_includes_limit_and_opt_fields(self):
        params = _list_params(ASANA_ENDPOINTS["projects"])
        assert params["limit"] == 100
        assert params["opt_fields"] == ",".join(ASANA_ENDPOINTS["projects"].opt_fields)
        assert "created_at" in params["opt_fields"]


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code, expected", [(200, True), (401, False), (403, False), (500, False)])
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.asana.asana.make_tracked_session")
    def test_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response
        assert validate_credentials("token") is expected

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.asana.asana.make_tracked_session")
    def test_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("token") is False


class TestBuildInitialUrls:
    def test_top_level_endpoint_yields_single_url(self):
        urls = _build_initial_urls(ASANA_ENDPOINTS["workspaces"], {}, mock.MagicMock(), mock.MagicMock())
        assert urls == [
            f"{ASANA_BASE_URL}/workspaces?limit=100&opt_fields=name%2Cemail_domains%2Cis_organization%2Cresource_type"
        ]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.asana.asana._list_workspaces")
    def test_workspace_fan_out_one_url_per_workspace(self, mock_list_workspaces):
        mock_list_workspaces.return_value = [{"gid": "1"}, {"gid": "2"}]
        urls = _build_initial_urls(ASANA_ENDPOINTS["projects"], {}, mock.MagicMock(), mock.MagicMock())
        assert len(urls) == 2
        assert all(url.startswith(f"{ASANA_BASE_URL}/projects?workspace=") for url in urls)
        assert "workspace=1" in urls[0]
        assert "workspace=2" in urls[1]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.asana.asana._list_workspaces")
    def test_organization_fan_out_skips_non_org_workspaces(self, mock_list_workspaces):
        mock_list_workspaces.return_value = [
            {"gid": "1", "is_organization": True},
            {"gid": "2", "is_organization": False},
        ]
        urls = _build_initial_urls(ASANA_ENDPOINTS["teams"], {}, mock.MagicMock(), mock.MagicMock())
        assert len(urls) == 1
        assert urls[0].startswith(f"{ASANA_BASE_URL}/organizations/1/teams")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.asana.asana._list_projects")
    def test_project_fan_out_one_url_per_project(self, mock_list_projects):
        mock_list_projects.return_value = iter([{"gid": "p1"}, {"gid": "p2"}])
        urls = _build_initial_urls(ASANA_ENDPOINTS["tasks"], {}, mock.MagicMock(), mock.MagicMock())
        assert [u.split("project=")[1].split("&")[0] for u in urls] == ["p1", "p2"]


class TestGetRows:
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.asana.asana.make_tracked_session")
    def test_paginates_via_next_page_uri(self, mock_session):
        pages = [
            _ok_response(_page([{"gid": "1"}, {"gid": "2"}], f"{ASANA_BASE_URL}/workspaces?offset=tok2")),
            _ok_response(_page([{"gid": "3"}], None)),
        ]
        mock_session.return_value.get.side_effect = pages

        manager = _make_manager()
        batches = list(get_rows("token", "workspaces", mock.MagicMock(), manager))

        assert [item["gid"] for batch in batches for item in batch] == ["1", "2", "3"]
        # Saved once: after the first page (which has a next uri); not after the terminal page.
        manager.save_state.assert_called_once()
        saved = manager.save_state.call_args.args[0]
        assert saved.current_url == f"{ASANA_BASE_URL}/workspaces?offset=tok2"
        assert saved.remaining_urls == []

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.asana.asana.make_tracked_session")
    def test_resumes_from_saved_state(self, mock_session):
        mock_session.return_value.get.return_value = _ok_response(_page([{"gid": "9"}], None))

        resume_url = f"{ASANA_BASE_URL}/workspaces?offset=resume"
        manager = _make_manager(AsanaResumeConfig(remaining_urls=[], current_url=resume_url))

        list(get_rows("token", "workspaces", mock.MagicMock(), manager))

        assert mock_session.return_value.get.call_args_list[0].args[0] == resume_url

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.asana.asana._build_initial_urls")
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.asana.asana.make_tracked_session")
    def test_drains_remaining_parent_urls(self, mock_session, mock_build_urls):
        # Two parents, each a single page with no next_page — the generator must advance to
        # the second parent URL once the first finishes.
        mock_build_urls.return_value = [
            f"{ASANA_BASE_URL}/tasks?project=p1",
            f"{ASANA_BASE_URL}/tasks?project=p2",
        ]
        mock_session.return_value.get.side_effect = [
            _ok_response(_page([{"gid": "a"}], None)),
            _ok_response(_page([{"gid": "b"}], None)),
        ]

        manager = _make_manager()
        batches = list(get_rows("token", "tasks", mock.MagicMock(), manager))

        assert [item["gid"] for batch in batches for item in batch] == ["a", "b"]
        assert mock_session.return_value.get.call_count == 2
        # After draining the first parent, state advances to the second parent URL.
        saved = manager.save_state.call_args.args[0]
        assert saved.current_url == f"{ASANA_BASE_URL}/tasks?project=p2"
        assert saved.remaining_urls == []

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.asana.asana._build_initial_urls")
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.asana.asana.make_tracked_session")
    def test_empty_single_endpoint_yields_nothing_and_saves_nothing(self, mock_session, mock_build_urls):
        mock_build_urls.return_value = [f"{ASANA_BASE_URL}/workspaces?limit=100"]
        mock_session.return_value.get.return_value = _ok_response(_page([], None))

        manager = _make_manager()
        batches = list(get_rows("token", "workspaces", mock.MagicMock(), manager))

        assert batches == []
        manager.save_state.assert_not_called()

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.asana.asana._build_initial_urls")
    def test_no_parents_yields_nothing(self, mock_build_urls):
        mock_build_urls.return_value = []
        manager = _make_manager()
        assert list(get_rows("token", "projects", mock.MagicMock(), manager)) == []
        manager.save_state.assert_not_called()


class TestAsanaSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = ASANA_ENDPOINTS[endpoint]
        response = asana_source("token", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == ["gid"]
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "week"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(ASANA_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key == "created_at"
            # The partition field must be opted into the response, else partitioning fails.
            assert config.partition_key in config.opt_fields

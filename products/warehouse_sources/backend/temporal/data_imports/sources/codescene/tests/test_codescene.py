from typing import Any, cast

import pytest
from unittest.mock import MagicMock, Mock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.codescene import codescene as codescene_module
from products.warehouse_sources.backend.temporal.data_imports.sources.codescene.codescene import (
    CodesceneResumeConfig,
    codescene_source,
    hostname_of,
    normalize_base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.codescene.settings import CODESCENE_ENDPOINTS


class _FakeDltResource:
    """Lightweight stand-in for a DltResource returned by rest_api_resources.

    ``process_parent_data_item`` injects parent fields as ``_<parent_resource>_<field>``
    (see ``make_parent_key_name``), so test data should include those prefixed keys to
    exercise the row mappers.
    """

    def __init__(self, name: str, rows: list[dict]) -> None:
        self.name = name
        self._rows = rows

    def add_map(self, mapper: Any) -> "_FakeDltResource":
        self._rows = [mapper(dict(row)) for row in self._rows]
        return self

    def __iter__(self) -> Any:
        return iter(self._rows)


def _make_fake_manager(can_resume: bool = False, state: CodesceneResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = state
    return manager


class TestNormalizeBaseUrl:
    def test_defaults_to_cloud(self) -> None:
        assert normalize_base_url(None) == "https://api.codescene.io/v2"
        assert normalize_base_url("") == "https://api.codescene.io/v2"

    @parameterized.expand(
        [
            ("bare_host", "codescene.example.com:3003", "https://codescene.example.com:3003/api/v2"),
            ("scheme_no_path", "http://codescene.example.com:3003", "http://codescene.example.com:3003/api/v2"),
            (
                "already_has_api_v2",
                "https://codescene.example.com:3003/api/v2",
                "https://codescene.example.com:3003/api/v2",
            ),
            (
                "trailing_slash",
                "https://codescene.example.com:3003/api/v2/",
                "https://codescene.example.com:3003/api/v2",
            ),
            ("cloud_v2_suffix", "https://api.codescene.io/v2/", "https://api.codescene.io/v2"),
        ]
    )
    def test_normalizes_variants(self, _name: str, given: str, expected: str) -> None:
        assert normalize_base_url(given) == expected

    def test_hostname_of(self) -> None:
        assert hostname_of("https://codescene.example.com:3003/api/v2") == "codescene.example.com"
        assert hostname_of(None) == "api.codescene.io"


class TestValidateCredentials:
    def _patch_session(self, response: Mock) -> Any:
        mock_session = MagicMock()
        mock_session.get.return_value = response
        return patch.object(codescene_module, "make_tracked_session", return_value=mock_session)

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid CodeScene API token"),
            ("forbidden", 403, False, "does not have the Admin, Architect, or RestApi role"),
            ("server_error", 500, False, "Could not connect to CodeScene"),
        ]
    )
    def test_status_mapping(
        self, _name: str, status_code: int, expect_valid: bool, message_fragment: str | None
    ) -> None:
        response = Mock(status_code=status_code)
        with self._patch_session(response):
            valid, message = validate_credentials("token", None, team_id=1)
        assert valid is expect_valid
        if message_fragment:
            assert message_fragment in (message or "")

    def test_request_exception_returns_failure(self) -> None:
        import requests

        mock_session = MagicMock()
        mock_session.get.side_effect = requests.exceptions.ConnectionError("boom")
        with patch.object(codescene_module, "make_tracked_session", return_value=mock_session):
            valid, message = validate_credentials("token", None, team_id=1)
        assert valid is False
        assert "boom" in (message or "")

    def test_blocks_unsafe_host(self) -> None:
        with (
            patch.object(codescene_module, "_is_host_safe", return_value=(False, "internal address")),
            self._patch_session(Mock(status_code=200)) as patched_session,
        ):
            valid, message = validate_credentials("token", "https://10.0.0.1", team_id=1)
        assert valid is False
        assert message == "internal address"
        patched_session.return_value.get.assert_not_called()

    @parameterized.expand(
        [
            # urlparse reads the host as example.com, but requests dials 169.254.169.254 — reject
            # the ambiguous authority before it reaches the host check or carries the token.
            ("percent_encoded_backslash", "http://169.254.169.254%5c@example.com"),
            ("raw_backslash", "http://169.254.169.254\\@example.com"),
            ("userinfo", "https://user:pass@example.com"),
            ("query_string", "https://codescene.example.com/api/v2?x=1"),
            ("bad_scheme", "ftp://codescene.example.com"),
        ]
    )
    def test_rejects_ambiguous_base_url_without_requesting(self, _name: str, base_url: str) -> None:
        # A structurally invalid URL must be rejected before any credential-bearing request.
        with self._patch_session(Mock(status_code=200)) as patched_session:
            valid, message = validate_credentials("token", base_url, team_id=1)
        assert valid is False
        assert message
        patched_session.return_value.get.assert_not_called()

    def test_cloud_requires_https(self) -> None:
        with (
            patch.object(codescene_module, "is_cloud", return_value=True),
            self._patch_session(Mock(status_code=200)) as patched_session,
        ):
            valid, message = validate_credentials("token", "http://codescene.example.com", team_id=1)
        assert valid is False
        assert message and "HTTPS" in message
        patched_session.return_value.get.assert_not_called()

    def test_self_hosted_allows_http(self) -> None:
        with (
            patch.object(codescene_module, "is_cloud", return_value=False),
            self._patch_session(Mock(status_code=200)) as patched_session,
        ):
            valid, _message = validate_credentials("token", "http://codescene.example.com", team_id=1)
        assert valid is True
        patched_session.return_value.get.assert_called_once()


class TestCodesceneSourceFlatEndpoint:
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.codescene.codescene.rest_api_resource")
    def test_projects_resource_config(self, mock_rest_api_resource: MagicMock) -> None:
        mock_rest_api_resource.return_value = _FakeDltResource("Projects", [{"id": "p1", "name": "demo"}])

        response = codescene_source(
            api_token="token",
            base_url=None,
            endpoint="Projects",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_make_fake_manager(),
        )

        assert response.name == "Projects"
        assert response.primary_keys == ["id"]
        config = mock_rest_api_resource.call_args.args[0]
        assert config["client"]["base_url"] == "https://api.codescene.io/v2"
        assert config["client"]["auth"] == {"type": "bearer", "token": "token"}
        resource = config["resources"][0]
        assert resource["endpoint"]["path"] == "/projects"
        assert resource["endpoint"]["params"] == {"page_size": 100}
        assert resource["endpoint"]["data_selector"] == "projects"
        assert resource["endpoint"]["data_selector_required"] is True

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.codescene.codescene.rest_api_resource")
    def test_resume_state_seeds_paginator(self, mock_rest_api_resource: MagicMock) -> None:
        mock_rest_api_resource.return_value = _FakeDltResource("Projects", [])
        manager = _make_fake_manager(can_resume=True, state=CodesceneResumeConfig(next_page=4))

        codescene_source(
            api_token="token",
            base_url=None,
            endpoint="Projects",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
        )

        assert mock_rest_api_resource.call_args.kwargs["initial_paginator_state"] == {"page": 4}

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.codescene.codescene.rest_api_resource")
    def test_resume_hook_saves_state_only_when_next_page_present(self, mock_rest_api_resource: MagicMock) -> None:
        mock_rest_api_resource.return_value = _FakeDltResource("Projects", [])
        manager = _make_fake_manager()

        codescene_source(
            api_token="token",
            base_url=None,
            endpoint="Projects",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
        )

        resume_hook = mock_rest_api_resource.call_args.kwargs["resume_hook"]
        resume_hook({"page": 7})
        manager.save_state.assert_called_once_with(CodesceneResumeConfig(next_page=7))

        manager.save_state.reset_mock()
        resume_hook(None)
        manager.save_state.assert_not_called()


class TestCodesceneSourceFanout:
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
    )
    def test_files_fanout_row_format(self, mock_rest_api_resources: MagicMock) -> None:
        mock_rest_api_resources.return_value = [
            _FakeDltResource("Projects", [{"id": "p1", "name": "demo"}]),
            _FakeDltResource(
                "Files",
                [{"name": "src/app.py", "code_health": 8.5, "_Projects_id": "p1"}],
            ),
        ]

        response = codescene_source(
            api_token="token",
            base_url=None,
            endpoint="Files",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_make_fake_manager(),
        )

        rows = list(cast(Any, response.items()))
        assert rows == [{"name": "src/app.py", "code_health": 8.5, "project_id": "p1"}]
        # A file path is only unique within its own project, so the parent project id is
        # part of the key.
        assert response.primary_keys == ["project_id", "name"]

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.codescene.codescene.build_dependent_resource"
    )
    def test_files_fanout_wiring(self, mock_build_dependent_resource: MagicMock) -> None:
        mock_build_dependent_resource.return_value = iter([])

        codescene_source(
            api_token="token",
            base_url=None,
            endpoint="Files",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_make_fake_manager(),
        )

        kwargs = mock_build_dependent_resource.call_args.kwargs
        assert kwargs["page_size_param"] == "page_size"
        assert kwargs["parent_endpoint_extra"]["data_selector"] == "projects"
        assert kwargs["child_endpoint_extra"]["data_selector"] == "files"
        assert kwargs["fanout"] is CODESCENE_ENDPOINTS["Files"].fanout

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.codescene.codescene.build_dependent_resource"
    )
    def test_components_fanout_wiring(self, mock_build_dependent_resource: MagicMock) -> None:
        mock_build_dependent_resource.return_value = iter([])

        codescene_source(
            api_token="token",
            base_url=None,
            endpoint="Components",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_make_fake_manager(),
        )

        kwargs = mock_build_dependent_resource.call_args.kwargs
        assert kwargs["child_endpoint_extra"]["data_selector"] == "components"


class TestCodesceneEndpointCatalog:
    @pytest.mark.parametrize("endpoint", list(CODESCENE_ENDPOINTS))
    def test_every_endpoint_has_primary_key(self, endpoint: str) -> None:
        primary_key = CODESCENE_ENDPOINTS[endpoint].primary_key
        assert primary_key

    def test_fanout_endpoints_key_on_parent_id(self) -> None:
        for endpoint in ("Files", "Components"):
            config = CODESCENE_ENDPOINTS[endpoint]
            assert isinstance(config.primary_key, list)
            assert "project_id" in config.primary_key

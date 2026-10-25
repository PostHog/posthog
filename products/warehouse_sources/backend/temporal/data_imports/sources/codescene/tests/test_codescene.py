from unittest.mock import patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.codescene import codescene as codescene_module
from products.warehouse_sources.backend.temporal.data_imports.sources.codescene.codescene import (
    CodesceneResumeConfig,
    normalize_base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.codescene.settings import CODESCENE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.codescene.source import CodesceneSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.codescene import (
    CodesceneSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(CodesceneSource(), CodesceneSourceConfig(api_token="token"))


class TestNormalizeBaseUrl:
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


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
        ]
    )
    def test_status_mapping(
        self, _name: str, status_code: int, expect_valid: bool, message_fragment: str | None
    ) -> None:
        response = ScriptedResponse(status=status_code)
        script = always(response) if status_code == 500 else [response]
        with scripted_network(script) as network:
            valid, message = validate_credentials("token", None, team_id=1)
        assert valid is expect_valid
        if message_fragment:
            assert message_fragment in (message or "")
        assert network.requests_log[0].path == "/v2/projects"
        assert network.requests_log[0].param("page") == "1"
        assert network.requests_log[0].param("page_size") == "1"
        assert network.requests_log[0].headers["authorization"] == "Bearer token"

    def test_request_exception_returns_failure(self) -> None:
        with scripted_network(always(requests.exceptions.ConnectionError("boom"))) as network:
            valid, message = validate_credentials("token", None, team_id=1)
        assert valid is False
        assert "boom" in (message or "")
        assert {request.path for request in network.requests_log} == {"/v2/projects"}

    def test_blocks_unsafe_host(self) -> None:
        with scripted_network([]) as network:
            with patch.object(codescene_module, "_is_host_safe", return_value=(False, "internal address")):
                valid, message = validate_credentials("token", "https://10.0.0.1", team_id=1)
        assert valid is False
        assert message == "internal address"
        assert network.requests_log == []

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
        with scripted_network([]) as network:
            valid, message = validate_credentials("token", base_url, team_id=1)
        assert valid is False
        assert message
        assert network.requests_log == []

    def test_cloud_requires_https(self) -> None:
        with scripted_network([]) as network:
            with patch.object(codescene_module, "is_cloud", return_value=True):
                valid, message = validate_credentials("token", "http://codescene.example.com", team_id=1)
        assert valid is False
        assert message and "HTTPS" in message
        assert network.requests_log == []


class TestCodesceneSourceFlatEndpoint:
    def test_resume_state_seeds_paginator(self) -> None:
        result = _driver().run(
            "Projects",
            [ScriptedResponse(json={"projects": [{"id": "project-4"}], "max_pages": 4})],
            resume_state=CodesceneResumeConfig(next_page=4),
        )

        assert result.raised is None
        assert result.params("page") == ["4"]
        assert result.rows == [{"id": "project-4"}]

    def test_resume_hook_saves_state_only_when_next_page_present(self) -> None:
        result = _driver().run(
            "Projects",
            [
                ScriptedResponse(json={"projects": [{"id": "project-1"}], "max_pages": 2}),
                ScriptedResponse(json={"projects": [{"id": "project-2"}], "max_pages": 2}),
            ],
        )

        assert result.raised is None
        assert result.params("page") == ["1", "2"]
        assert result.saved_states == [CodesceneResumeConfig(next_page=2)]
        assert result.rows == [{"id": "project-1"}, {"id": "project-2"}]


class TestCodesceneSourceFanout:
    @parameterized.expand(
        [
            ("files", "Files", "files", "page_size", PageNumberPaginator),
            ("components", "Components", "components", "page_size", PageNumberPaginator),
            # The analyses list pages on `page` alone, so no page-size param goes out.
            ("analyses", "Analyses", "analyses", None, PageNumberPaginator),
            ("issues", "Issues", "issues", "page_size", PageNumberPaginator),
            ("technical_debt", "TechnicalDebt", "result", "page_size", PageNumberPaginator),
            # Author statistics comes back as a bare array with no envelope and no pagination.
            ("author_statistics", "AuthorStatistics", None, None, SinglePagePaginator),
            ("branch_statistics", "BranchStatistics", None, None, SinglePagePaginator),
            ("commits", "Commits", "commits", "page_size", PageNumberPaginator),
            # Commit activity is wrapped in an envelope but has no pagination.
            ("commit_activity", "CommitActivity", "commit_activity_trend", None, SinglePagePaginator),
            ("delta_analyses", "DeltaAnalyses", "delta_analyses", None, PageNumberPaginator),
        ]
    )
    def test_fanout_wiring(
        self,
        _name: str,
        endpoint: str,
        data_selector: str | None,
        page_size_param: str | None,
        paginator_type: type,
    ) -> None:
        child_row = {"id": "child-1", "name": "file.py", "author": "Ada", "file_name": "file.py"}
        child_body = [child_row] if data_selector is None else {data_selector: [child_row], "max_pages": 1}
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(json={"projects": [{"id": "project-1"}], "max_pages": 1}),
                ScriptedResponse(json=child_body),
            ],
        )

        assert result.raised is None
        assert len(result.requests) == 2
        assert result.paths[0] == "/v2/projects"
        assert result.paths[1] == f"/v2{CODESCENE_ENDPOINTS[endpoint].path.format(project_id='project-1')}"
        assert result.requests[0].param("page_size") == ("100" if page_size_param else None)
        assert result.requests[1].param("page_size") == (
            str(CODESCENE_ENDPOINTS[endpoint].page_size) if page_size_param else None
        )
        assert result.requests[1].param("page") == ("1" if paginator_type is PageNumberPaginator else None)
        assert result.rows == [{**child_row, "project_id": "project-1"}]
        assert result.response is not None
        assert result.response.name == endpoint


class TestCodesceneEndpointCatalog:
    def test_fanout_endpoints_key_on_parent_id(self) -> None:
        # Every fan-out table aggregates rows from all projects, so a key that is only
        # unique within a project seeds duplicates the merge then multi-matches.
        for endpoint, config in CODESCENE_ENDPOINTS.items():
            if config.fanout is None:
                continue
            assert isinstance(config.primary_key, list), endpoint
            assert "project_id" in config.primary_key, endpoint

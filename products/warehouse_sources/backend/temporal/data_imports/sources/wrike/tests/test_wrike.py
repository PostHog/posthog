import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.wrike import WrikeSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.wrike.source import WrikeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.wrike.wrike import (
    WrikeResumeConfig,
    _build_url,
    is_host_valid,
    validate_credentials,
)


def _driver(host: str = "www.wrike.com") -> SourceDriver:
    return SourceDriver(WrikeSource(), WrikeSourceConfig(access_token="token", host=host))


class TestIsHostValid:
    @pytest.mark.parametrize(
        "host, expected",
        [
            ("www.wrike.com", True),
            ("app-us2.wrike.com", True),
            ("app-eu.wrike.com", True),
            ("https://www.wrike.com/", True),
            ("WWW.WRIKE.COM", True),
            ("www.wrike.com:443", True),
            ("evil.com", False),
            ("wrike.com.evil.com", False),
            ("notwrike.com", False),
            ("localhost", False),
            ("169.254.169.254", False),
            ("", False),
            # SSRF bypass attempts: a path/query/credentials must not smuggle a non-Wrike
            # netloc past the suffix check.
            ("evil.com?.wrike.com", False),
            ("evil.com/.wrike.com", False),
            ("internal.service/path.wrike.com", False),
            ("evil.com#.wrike.com", False),
            ("user:pass@evil.com", False),
            ("user@evil.com:443", False),
        ],
    )
    def test_is_host_valid(self, host: str, expected: bool) -> None:
        assert is_host_valid(host) is expected

    @pytest.mark.parametrize(
        "host",
        ["evil.com?.wrike.com", "internal.service/path.wrike.com", "user:pass@evil.com.attacker.net"],
    )
    def test_build_url_target_never_diverges_from_validation(self, host: str) -> None:
        # The connection target is built from the same normalized hostname is_host_valid checks,
        # so a host that fails validation can never resolve to a Wrike URL.
        assert is_host_valid(host) is False
        assert "wrike.com/api/v4" not in _build_url(host, "/tasks", {})


class TestBuildUrl:
    def test_no_params(self) -> None:
        assert _build_url("www.wrike.com", "/tasks", {}) == "https://www.wrike.com/api/v4/tasks"


class TestValidateCredentials:
    def test_rejects_non_wrike_host_without_request(self) -> None:
        with scripted_network([]) as network:
            is_valid, error = validate_credentials("token", "evil.com")
        assert is_valid is False
        assert error is not None and "Wrike domain" in error
        assert network.requests_log == []

    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_error",
        [
            (200, True, None),
            (401, False, "Invalid Wrike access token"),
            (403, False, "Wrike access token is missing the required permissions"),
            (500, False, "Wrike API error: status=500"),
        ],
    )
    def test_status_mapping(self, status_code: int, expected_valid: bool, expected_error: str | None) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))):
            is_valid, error = validate_credentials("token", "www.wrike.com")
        assert is_valid is expected_valid
        assert error == expected_error


class TestPagination:
    def test_non_paginated_endpoint_single_page(self) -> None:
        result = _driver().run(
            "contacts", [ScriptedResponse(json={"kind": "contacts", "data": [{"id": "a"}, {"id": "b"}]})]
        )

        assert result.rows == [{"id": "a"}, {"id": "b"}]
        assert len(result.requests) == 1
        assert result.saved_states == []

    def test_paginated_endpoint_follows_next_page_token(self) -> None:
        result = _driver().run(
            "tasks",
            [
                ScriptedResponse(json={"data": [{"id": 1}], "nextPageToken": "tok2"}),
                ScriptedResponse(json={"data": [{"id": 2}]}),
            ],
        )

        assert result.rows == [{"id": 1}, {"id": 2}]
        # First request carries pageSize; second carries the resume token.
        assert result.requests[0].param("pageSize") == "1000"
        assert result.requests[0].param("nextPageToken") is None
        assert result.requests[1].param("nextPageToken") == "tok2"
        # State saved once, after yielding the first page, before fetching the next.
        assert result.saved_states == [WrikeResumeConfig(next_page_token="tok2")]

    def test_resumes_from_saved_state(self) -> None:
        result = _driver().run(
            "tasks",
            [ScriptedResponse(json={"data": [{"id": 3}]})],
            resume_state=WrikeResumeConfig(next_page_token="resume_tok"),
        )

        assert result.rows == [{"id": 3}]
        assert result.requests[0].param("nextPageToken") == "resume_tok"

    def test_project_dependencies_fan_out_over_projects(self) -> None:
        result = _driver().run(
            "project_dependencies",
            [
                ScriptedResponse(json={"kind": "folders", "data": [{"id": "P1"}, {"id": "P2"}]}),
                ScriptedResponse(
                    json={
                        "kind": "dependencies",
                        "data": [{"id": "D1", "predecessorId": "P1", "successorId": "P2"}],
                    }
                ),
                ScriptedResponse(status=404, json={"errorDescription": "Folder not found"}),
            ],
        )

        assert dict(result.requests[0].query) == {"project": ("true",)}
        assert result.paths[1].endswith("/api/v4/folders/P1/dependencies")
        assert result.paths[2].endswith("/api/v4/folders/P2/dependencies")
        assert result.rows == [{"id": "D1", "predecessorId": "P1", "successorId": "P2", "projectId": "P1"}]

    def test_rejects_non_wrike_host_before_any_request(self) -> None:
        result = _driver(host="evil.com").run("tasks", [])

        assert isinstance(result.raised, ValueError)
        assert "non-Wrike host" in str(result.raised)
        assert result.requests == []

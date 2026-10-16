import pytest

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gologin import (
    GoLoginSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gologin.gologin import (
    GoLoginResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gologin.settings import REQUEST_TIMEOUT
from products.warehouse_sources.backend.temporal.data_imports.sources.gologin.source import GoLoginSource


class TestGoLoginTransport:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(GoLoginSource(), GoLoginSourceConfig(api_key="test-token"))

    @pytest.mark.parametrize("resume_page", [None, 4])
    @pytest.mark.parametrize("incremental", [False, True])
    def test_profiles_page_requests_and_checkpoints(self, resume_page: int | None, incremental: bool) -> None:
        rows = [{"id": f"profile-{index}", "createdAt": "2026-01-01T00:00:00Z"} for index in range(31)]
        result = self._driver().run(
            "profiles",
            [
                ScriptedResponse(json={"profiles": rows[:30], "allProfilesCount": 31}),
                ScriptedResponse(json={"profiles": rows[30:], "allProfilesCount": 31}),
                ScriptedResponse(json={"profiles": [], "allProfilesCount": 31}),
            ],
            resume_state=GoLoginResumeConfig(page=resume_page) if resume_page is not None else None,
            should_use_incremental_field=incremental,
            db_incremental_field_last_value="2026-01-02T00:00:00Z",
        )

        first_page = resume_page or 1
        assert result.raised is None
        assert result.items == [rows[:30], rows[30:]]
        assert result.rows == rows
        assert result.saved_states == [
            GoLoginResumeConfig(page=first_page + 1),
            GoLoginResumeConfig(page=first_page + 2),
        ]
        assert result.committed_states == result.saved_states
        assert len(result.requests) == 3
        for index, request in enumerate(result.requests):
            assert request.method == "GET"
            assert request.origin == "https://api.gologin.com"
            assert request.path == "/browser/v2"
            assert request.query == {
                "page": (str(first_page + index),),
                "sorterField": ("createdAt",),
                "sorterOrder": ("ascend",),
            }
            assert request.headers["authorization"] == "Bearer test-token"
            assert request.read_timeout == REQUEST_TIMEOUT[1]

    @pytest.mark.parametrize("status", [401, 403])
    def test_pipeline_errors_match_user_messages(self, status: int) -> None:
        result = self._driver().run("profiles", [ScriptedResponse(status=status, json={"statusCode": status})])

        assert isinstance(result.raised, HTTPError)
        errors = GoLoginSource().get_non_retryable_errors()
        assert any(key in str(result.raised) and message for key, message in errors.items())
        assert result.paths == ["/browser/v2"]

    def test_pipeline_refuses_redirect(self) -> None:
        result = self._driver().run(
            "profiles",
            [ScriptedResponse(status=302, headers={"Location": "https://example.com/browser/v2"})],
        )

        assert isinstance(result.raised, ValueError)
        assert result.paths == ["/browser/v2"]

    @pytest.mark.parametrize("status", [200, 401, 403, 404])
    def test_validation_uses_one_request(self, status: int) -> None:
        with scripted_network(
            [ScriptedResponse(status=status, json={"id": "user-1"} if status == 200 else {"statusCode": status})]
        ) as network:
            if status == 404:
                with pytest.raises(HTTPError):
                    validate_credentials("test-token")
            else:
                valid, error = validate_credentials("test-token")
                assert valid is (status == 200)
                assert (error is None) is (status == 200)
                if error is not None:
                    assert "API key" in error

        assert len(network.requests_log) == 1
        request = network.requests_log[0]
        assert request.method == "GET"
        assert request.url == "https://api.gologin.com/user"
        assert request.headers["authorization"] == "Bearer test-token"
        assert request.read_timeout == REQUEST_TIMEOUT[1]

    def test_validation_refuses_redirect(self) -> None:
        with scripted_network(
            [ScriptedResponse(status=302, headers={"Location": "https://example.com/user"})]
        ) as network:
            with pytest.raises(ValueError):
                validate_credentials("test-token")

        assert len(network.requests_log) == 1
        assert network.requests_log[0].path == "/user"

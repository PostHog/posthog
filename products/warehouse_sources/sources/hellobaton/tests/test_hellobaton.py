import pytest

from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hellobaton import (
    HellobatonSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hellobaton.hellobaton import (
    HellobatonResumeConfig,
    normalize_company,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hellobaton.source import HellobatonSource


def _page(items: list[dict[str, int]], *, next_url: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"results": items, "next": next_url})


def _driver(api_key: str = "key") -> SourceDriver:
    return SourceDriver(HellobatonSource(), HellobatonSourceConfig(company="acme", api_key=api_key))


class TestNormalizeCompany:
    @pytest.mark.parametrize(
        "value",
        ["acme/../evil", "acme.evil.com", "acme@evil.com", "", "ac me", "acme-"],
    )
    def test_invalid_companies_raise(self, value: str) -> None:
        # The api_key must never be retargeted off <company>.hellobaton.com.
        with pytest.raises(ValueError):
            normalize_company(value)


class TestPagination:
    def test_page_size_sent_on_every_page(self) -> None:
        result = _driver().run(
            "projects",
            [
                _page([{"id": 1}], next_url="https://acme.hellobaton.com/api/projects/?page=2"),
                _page([{"id": 2}]),
            ],
        )

        # Baton caps page size at 100; request the max on every page.
        assert result.raised is None
        assert result.params("page_size") == ["100", "100"]

    def test_stops_on_empty_results(self) -> None:
        result = _driver().run("companies", [_page([])])

        assert result.raised is None
        assert result.rows == []
        assert result.paths == ["/api/companies/"]

    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run("tasks", [_page([{"id": 2}])], resume_state=HellobatonResumeConfig(next_page=2))

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [2]
        assert result.params("page") == ["2"]
        assert result.paths == ["/api/tasks/"]


class TestErrorHandling:
    def test_client_error_raises_and_scrubs_api_key(self) -> None:
        # The api_key rides in the query string; a 4xx must fail loud (non-retryable) while never
        # leaking the key into the raised error the user sees, and still expose the status text
        # get_non_retryable_errors() matches on.
        result = _driver(api_key="supersecret").run("projects", [ScriptedResponse(status=401)])

        assert isinstance(result.raised, HTTPError)
        assert result.params("api_key") == ["supersecret"]
        message = str(result.raised)
        assert "supersecret" not in message
        assert "401 Client Error: Unauthorized" in message


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_ok",
        [
            (200, True),
        ],
    )
    def test_maps_probe_status(self, status_code: int, expected_ok: bool) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            ok, status = validate_credentials("acme", "key")

        assert ok is expected_ok
        assert status == status_code
        assert len(network.requests_log) == 1
        assert network.requests_log[0].path == "/api/projects/"
        assert network.requests_log[0].param("page_size") == "1"
        assert network.requests_log[0].param("api_key") == "key"

    def test_malformed_company_raises_before_probe(self) -> None:
        # _base_url validates the company, so a bad instance fails before any network call.
        with pytest.raises(ValueError):
            validate_credentials("acme/../evil", "key")

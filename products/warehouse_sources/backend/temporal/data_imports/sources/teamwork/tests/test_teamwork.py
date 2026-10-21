from datetime import UTC, date, datetime
from typing import Any

import pytest

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.teamwork import (
    TeamworkSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.teamwork.settings import TEAMWORK_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.teamwork.source import TeamworkSource
from products.warehouse_sources.backend.temporal.data_imports.sources.teamwork.teamwork import (
    _format_updated_after,
    normalize_host,
    validate_credentials,
)


def _page(data_key: str, items: list[dict[str, Any]], *, has_more: bool, status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json={data_key: items, "meta": {"page": {"hasMore": has_more}}})


def _redirect(status: int = 301) -> ScriptedResponse:
    return ScriptedResponse(status=status, headers={"Location": "https://attacker.example.com/"})


def _run(responses: Any, *, endpoint: str = "tasks", **kwargs: Any) -> DriveResult:
    driver = SourceDriver(TeamworkSource(), TeamworkSourceConfig(site="mycompany.teamwork.com", api_key="key"))
    return driver.run(endpoint, responses, **kwargs)


class TestNormalizeHost:
    @parameterized.expand(
        [
            ("bare_subdomain", "mycompany", "mycompany.teamwork.com"),
            ("full_host", "mycompany.teamwork.com", "mycompany.teamwork.com"),
            ("https_url", "https://mycompany.teamwork.com/", "mycompany.teamwork.com"),
            ("http_url_with_path", "http://mycompany.teamwork.com/projects", "mycompany.teamwork.com"),
            ("regional_host", "mycompany.eu.teamwork.com", "mycompany.eu.teamwork.com"),
            ("trims_whitespace_and_case", "  MyCompany  ", "mycompany.teamwork.com"),
            ("trailing_dot", "mycompany.teamwork.com.", "mycompany.teamwork.com"),
        ]
    )
    def test_normalize_host(self, _name: str, raw: str, expected: str) -> None:
        assert normalize_host(raw) == expected


class TestFormatUpdatedAfter:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format_updated_after(self, _name: str, value: object, expected: str) -> None:
        assert _format_updated_after(value) == expected


class TestPagination:
    def test_follows_pagination_until_has_more_false(self) -> None:
        responses = [
            _page("tasks", [{"id": 1}], has_more=True),
            _page("tasks", [{"id": 2}], has_more=True),
            _page("tasks", [{"id": 3}], has_more=False),
        ]
        result = _run(responses)
        assert result.rows == [{"id": 1}, {"id": 2}, {"id": 3}]
        assert result.params("page") == ["1", "2", "3"]
        # hasMore=false on the last (non-empty) page stops without an extra empty-page request.
        assert len(result.requests) == 3

    def test_stops_on_empty_page(self) -> None:
        # hasMore lies and says there's more, but an empty page must terminate the loop.
        result = _run([_page("tasks", [], has_more=True)])
        assert result.rows == []
        assert len(result.requests) == 1

    def test_incremental_builds_updated_after_from_last_value(self) -> None:
        result = _run(
            [_page("tasks", [{"id": 1}], has_more=False)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert result.requests[0].param("updatedAfter") == "2026-03-04T02:58:14Z"
        assert result.requests[0].param("orderBy") == "updatedat"

    def test_full_refresh_endpoint_never_sends_updated_after(self) -> None:
        result = _run(
            [_page("projects", [{"id": 1}], has_more=False)],
            endpoint="projects",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert result.requests[0].param("updatedAfter") is None


class TestRedirectRejection:
    @parameterized.expand([("moved", 301), ("found", 302), ("temporary", 307), ("permanent", 308)])
    def test_redirect_is_rejected(self, _name: str, status: int) -> None:
        # A 3xx means the host tried to bounce us elsewhere — refuse rather than forward credentials.
        result = _run([_redirect(status)])
        assert isinstance(result.raised, ValueError)
        assert "redirect" in str(result.raised)


class TestValidateCredentials:
    def test_uses_no_redirect_session(self) -> None:
        # The Basic auth header must never follow a redirect off the validated host.
        with scripted_network(always(ScriptedResponse(status=200))) as network:
            validate_credentials("mycompany.teamwork.com", "key")
        assert network.session_options[0]["allow_redirects"] is False


class TestEndpointCatalog:
    def test_every_endpoint_has_id_primary_key(self) -> None:
        for config in TEAMWORK_ENDPOINTS.values():
            assert config.primary_keys == ["id"]

    def test_partition_keys_are_creation_fields_not_update_fields(self) -> None:
        # An update-timestamp partition key would rewrite partitions every sync.
        for config in TEAMWORK_ENDPOINTS.values():
            if config.partition_key is not None:
                assert "updated" not in config.partition_key.lower()
                assert "edited" not in config.partition_key.lower()

    def test_incremental_endpoints_sort_by_an_update_field(self) -> None:
        # If we filter by updatedAfter we must also sort by the update field, or sort_mode="asc" lies.
        for config in TEAMWORK_ENDPOINTS.values():
            if config.incremental_field is not None:
                assert config.order_by is not None
                assert "updated" in config.order_by.lower()

    @parameterized.expand(
        [
            ("projects", "projects", "/projects.json"),
            ("tasks", "tasks", "/tasks.json"),
            ("tasklists", "tasklists", "/tasklists.json"),
            ("milestones", "milestones", "/milestones.json"),
            ("timelogs", "timelogs", "/time.json"),
            ("people", "people", "/people.json"),
            ("companies", "companies", "/companies.json"),
            ("tags", "tags", "/tags.json"),
            ("comments", "comments", "/comments.json"),
        ]
    )
    def test_endpoint_paths_and_keys(self, name: str, data_key: str, path: str) -> None:
        config = TEAMWORK_ENDPOINTS[name]
        assert config.data_key == data_key
        assert config.path == path


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

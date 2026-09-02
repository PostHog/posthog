from typing import Any

from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.automox.automox import (
    MULTIPLE_ORGS_ERROR,
    ORG_NOT_FOUND_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.automox.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.automox.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.automox.source import AutomoxSource


def _config(api_key: str = "key", organization_id: str | None = None) -> Any:
    config = MagicMock()
    config.api_key = api_key
    config.organization_id = organization_id
    return config


class TestSourceConfig:
    def test_fields(self) -> None:
        fields = {f.name: f for f in AutomoxSource().get_source_config.fields if isinstance(f, SourceFieldInputConfig)}
        assert set(fields) == {"api_key", "organization_id"}
        assert fields["api_key"].required is True
        assert fields["api_key"].secret is True
        # The organization id is a non-secret, optional connection parameter.
        assert fields["organization_id"].required is False
        assert fields["organization_id"].secret is False

    def test_connection_host_fields_force_secret_reentry_on_org_change(self) -> None:
        # Changing organization_id retargets the stored API key, so it must count as a host field.
        assert AutomoxSource().connection_host_fields == ["organization_id"]


class TestGetSchemas:
    def test_only_server_side_filtered_endpoints_are_incremental(self) -> None:
        schemas = {s.name: s for s in AutomoxSource().get_schemas(_config(), team_id=1)}
        assert set(schemas) == set(ENDPOINTS)
        # Only events (startDate) and policy_runs (start_time) have a server-side time filter.
        assert {name for name, s in schemas.items() if s.supports_incremental} == {"events", "policy_runs"}
        assert [f["field"] for f in schemas["events"].incremental_fields] == ["create_time"]
        assert [f["field"] for f in schemas["policy_runs"].incremental_fields] == ["run_time"]
        # Fan-out style composite keys where uniqueness beyond the parent is undocumented.
        assert schemas["packages"].detected_primary_keys == ["id", "server_id"]
        assert schemas["policy_runs"].detected_primary_keys == ["policy_uuid", "execution_token"]

    def test_names_filter(self) -> None:
        schemas = AutomoxSource().get_schemas(_config(), team_id=1, names=["devices", "policies"])
        assert {s.name for s in schemas} == {"devices", "policies"}

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog (no I/O) — public docs render the table list.
        assert AutomoxSource.lists_tables_without_credentials is True
        tables = {t["name"]: t for t in AutomoxSource().get_documented_tables()}
        assert set(tables) == set(ENDPOINTS)
        assert tables["devices"]["sync_methods"] == ["Full refresh"]
        assert "Incremental" in tables["policy_runs"]["sync_methods"]


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://console.automox.com/api/servers?page=0&limit=500",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://console.automox.com/api/policies?page=0",
            ),
            # Raised by resolve_organization — the message prefixes must stay matchable.
            ("org_not_found", f"{ORG_NOT_FOUND_ERROR}: no organization with ID 999 is accessible with this API key"),
            (
                "multiple_orgs",
                f"{MULTIPLE_ORGS_ERROR}: set the organization ID on the source to pick which one to sync",
            ),
        ]
    )
    def test_permanent_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = AutomoxSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='console.automox.com', port=443): Read timed out."),
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://console.automox.com/api/servers",
            ),
            (
                "rate_limited",
                "429 Client Error: Too Many Requests for url: https://console.automox.com/api/servers",
            ),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = AutomoxSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)


class TestCanonicalDescriptions:
    def test_canonical_descriptions_keys_are_known_endpoints(self) -> None:
        # Every documented table must map to a real endpoint, or its descriptions never apply.
        assert set(CANONICAL_DESCRIPTIONS) == set(ENDPOINTS)

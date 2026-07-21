from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.automox.automox import (
    MULTIPLE_ORGS_ERROR,
    ORG_NOT_FOUND_ERROR,
    AutomoxResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.automox.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.automox.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.automox.source import AutomoxSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config(api_key: str = "key", organization_id: str | None = None) -> Any:
    config = MagicMock()
    config.api_key = api_key
    config.organization_id = organization_id
    return config


class TestSourceConfig:
    def test_source_type(self) -> None:
        assert AutomoxSource().source_type == ExternalDataSourceType.AUTOMOX

    def test_config_is_visible_and_alpha(self) -> None:
        config = AutomoxSource().get_source_config
        # A finished source must not be hidden from users.
        assert getattr(config, "unreleasedSource", None) in (None, False)
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/automox"

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


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", (True, None)),
            ("invalid", (False, "Automox authentication failed.")),
        ]
    )
    def test_plumbs_transport_result(self, _name: str, result: tuple[bool, str | None]) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.automox.source.validate_automox_credentials",
            return_value=result,
        ) as mocked:
            assert AutomoxSource().validate_credentials(_config(organization_id="7"), team_id=1) == result
        mocked.assert_called_once_with("key", "7")


class TestResumableWiring:
    def test_get_resumable_source_manager_binds_data_class(self) -> None:
        inputs = MagicMock()
        inputs.logger = MagicMock()
        manager = AutomoxSource().get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is AutomoxResumeConfig

    @parameterized.expand(
        [
            ("incremental", True, "2026-01-01"),
            # A stale watermark must not leak into a full-refresh run.
            ("full_refresh", False, None),
        ]
    )
    def test_source_for_pipeline_plumbs_arguments(
        self, _name: str, should_use_incremental_field: bool, expected_last_value: Any
    ) -> None:
        inputs = MagicMock()
        inputs.schema_name = "policy_runs"
        inputs.logger = MagicMock()
        inputs.should_use_incremental_field = should_use_incremental_field
        inputs.db_incremental_field_last_value = "2026-01-01"
        manager = MagicMock()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.automox.source.automox_source"
        ) as mocked:
            AutomoxSource().source_for_pipeline(_config(organization_id="3"), manager, inputs)
        mocked.assert_called_once_with(
            api_key="key",
            organization_id="3",
            endpoint="policy_runs",
            logger=inputs.logger,
            resumable_source_manager=manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=expected_last_value,
        )


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

    def test_source_exposes_canonical_descriptions(self) -> None:
        assert AutomoxSource().get_canonical_descriptions() is CANONICAL_DESCRIPTIONS

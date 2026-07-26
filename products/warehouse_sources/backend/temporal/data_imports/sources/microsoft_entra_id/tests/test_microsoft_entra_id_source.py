from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.microsoftentraid import (
    MicrosoftEntraIdSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_entra_id import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_entra_id.microsoft_entra_id import (
    MicrosoftEntraIdResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_entra_id.settings import (
    ENDPOINTS,
    ENTRA_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_entra_id.source import (
    MicrosoftEntraIdSource,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

INCREMENTAL_ENDPOINTS = {"DirectoryAudits", "SignIns"}


class TestMicrosoftEntraIdSourceClass:
    def setup_method(self) -> None:
        self.source = MicrosoftEntraIdSource()
        self.config = MicrosoftEntraIdSourceConfig(
            tenant_id="contoso.onmicrosoft.com", client_id="client-id", client_secret="secret"
        )
        self.team_id = 1

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.MICROSOFTENTRAID

    def test_source_config_collects_app_registration_credentials(self) -> None:
        config = self.source.get_source_config
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/microsoft-entra-id"
        fields = config.fields or []
        assert [field.name for field in fields] == ["tenant_id", "client_id", "client_secret"]
        # Only the secret is masked; the two identifiers are not confidential.
        assert [getattr(field, "secret", None) for field in fields] == [False, False, True]
        assert fields[2].type == "password"

    def test_tenant_change_forces_secret_re_entry(self) -> None:
        # The client secret is posted to the tenant-scoped token endpoint, so retargeting the
        # tenant must not silently reuse the stored secret.
        assert self.source.connection_host_fields == ["tenant_id"]

    def test_api_version_pins_what_the_code_calls(self) -> None:
        assert self.source.default_version in self.source.supported_versions
        assert self.source.default_version == "v1.0"
        assert (self.source.api_docs_url or "").startswith("https://")

    @parameterized.expand([("401 Client Error",), ("403 Client Error",), ("[oauth2_token_config_error]",)])
    def test_non_retryable_errors(self, expected_key_fragment: str) -> None:
        keys = self.source.get_non_retryable_errors()
        assert any(expected_key_fragment in key for key in keys)

    def test_get_schemas_lists_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_only_audit_log_endpoints_are_incremental(self) -> None:
        # Graph exposes a real server-side `$filter ge` only on the auditLogs resources; the
        # directory-object endpoints must stay full refresh.
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        for name, schema in schemas.items():
            assert schema.supports_incremental is (name in INCREMENTAL_ENDPOINTS), name
        assert [f["field"] for f in schemas["DirectoryAudits"].incremental_fields] == ["activityDateTime"]
        assert [f["field"] for f in schemas["SignIns"].incremental_fields] == ["createdDateTime"]

    def test_sign_in_logs_start_disabled(self) -> None:
        # Sign-in logs need a Microsoft Entra ID P1/P2 license, so a one-shot setup must not
        # enable a table that would immediately fail on a free-tier tenant.
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["SignIns"].should_sync_default is False
        assert schemas["Users"].should_sync_default is True

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Users", "Groups"])
        assert {schema.name for schema in schemas} == {"Users", "Groups"}

    def test_documented_tables_render_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True
        tables = {table["name"]: table for table in self.source.get_documented_tables()}
        assert set(tables) == set(ENDPOINTS)
        assert tables["Users"]["description"]

    @parameterized.expand([("valid", (True, None)), ("invalid", (False, "Invalid credentials"))])
    def test_validate_credentials_delegates(self, _name: str, expected: tuple[bool, str | None]) -> None:
        with mock.patch.object(source_module, "validate_entra_credentials", return_value=expected) as mocked:
            assert self.source.validate_credentials(self.config, self.team_id, schema_name="Users") == expected

        kwargs = mocked.call_args.kwargs
        assert kwargs["tenant_id"] == "contoso.onmicrosoft.com"
        assert kwargs["client_secret"] == "secret"
        assert kwargs["schema_name"] == "Users"
        # An unpinned source validates against the version it will actually sync with.
        assert kwargs["api_version"] == "v1.0"

    def test_get_endpoint_permissions_delegates(self) -> None:
        expected = {"Users": None, "SignIns": "Grant the `AuditLog.Read.All` permission."}
        with mock.patch.object(source_module, "check_endpoint_permissions", return_value=expected) as mocked:
            assert self.source.get_endpoint_permissions(self.config, self.team_id, ["Users", "SignIns"]) == expected

        assert mocked.call_args.kwargs["endpoints"] == ["Users", "SignIns"]

    def test_get_resumable_source_manager_bound_to_data_class(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.Mock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is MicrosoftEntraIdResumeConfig

    def _plumb(self, schema_name: str, should_use_incremental_field: bool) -> dict[str, Any]:
        inputs = mock.Mock()
        inputs.schema_name = schema_name
        inputs.team_id = 7
        inputs.job_id = "job"
        inputs.api_version = None
        inputs.should_use_incremental_field = should_use_incremental_field
        inputs.db_incremental_field_last_value = "2024-03-01T00:00:00Z"
        inputs.incremental_field = "activityDateTime"

        with mock.patch.object(source_module, "microsoft_entra_id_source") as mocked:
            self.source.source_for_pipeline(self.config, mock.Mock(), inputs)
        return dict(mocked.call_args.kwargs)

    def test_source_for_pipeline_plumbs_incremental_args(self) -> None:
        kwargs = self._plumb("DirectoryAudits", should_use_incremental_field=True)
        assert kwargs["endpoint"] == "DirectoryAudits"
        assert kwargs["tenant_id"] == "contoso.onmicrosoft.com"
        assert kwargs["api_version"] == "v1.0"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-03-01T00:00:00Z"
        assert kwargs["incremental_field"] == "activityDateTime"

    def test_source_for_pipeline_drops_watermark_on_full_refresh(self) -> None:
        assert self._plumb("Users", should_use_incremental_field=False)["db_incremental_field_last_value"] is None


class TestEndpointCatalog:
    @parameterized.expand(sorted(ENDPOINTS))
    def test_every_endpoint_declares_a_required_permission(self, name: str) -> None:
        # The permission string is shown verbatim to users, so a blank one leaves them guessing.
        assert ENTRA_ENDPOINTS[name].required_permission

    def test_fanout_children_carry_the_parent_id_in_their_primary_key(self) -> None:
        # A member id is unique per directory object but a membership row is only unique per
        # (group, member) — a bare `id` key would collapse rows across groups.
        for name, config in ENTRA_ENDPOINTS.items():
            if config.parent is None:
                continue
            assert config.parent_id_column is not None, name
            assert config.parent_id_column in config.primary_keys, name

    def test_only_endpoints_with_a_server_filter_advertise_incremental_fields(self) -> None:
        for name, config in ENTRA_ENDPOINTS.items():
            assert bool(config.incremental_fields) is bool(config.incremental_filter_field), name

    def test_partition_keys_are_creation_time_columns(self) -> None:
        # A partition key that changes rewrites partitions on every sync.
        allowed = {"createdDateTime", "activityDateTime"}
        for name, config in ENTRA_ENDPOINTS.items():
            if config.partition_key is not None:
                assert config.partition_key in allowed, name


class TestCanonicalDescriptions:
    def test_keys_are_all_real_endpoints(self) -> None:
        descriptions: dict[str, Any] = MicrosoftEntraIdSource().get_canonical_descriptions()
        assert set(descriptions).issubset(set(ENDPOINTS))
        assert "Users" in descriptions


if __name__ == "__main__":
    pytest.main([__file__])

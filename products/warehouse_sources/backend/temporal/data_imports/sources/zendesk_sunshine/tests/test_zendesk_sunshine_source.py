import datetime

import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zendesksunshine import (
    ZendeskSunshineSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sunshine.settings import (
    ENDPOINTS_BY_VERSION,
    ZENDESK_SUNSHINE_V1,
    ZENDESK_SUNSHINE_V2,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sunshine.source import (
    ZendeskSunshineSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sunshine.zendesk_sunshine import (
    ZendeskSunshineResumeConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestZendeskSunshineSource:
    def setup_method(self) -> None:
        self.source = ZendeskSunshineSource()
        self.team_id = 123
        self.config = ZendeskSunshineSourceConfig(
            subdomain="nibbles", api_key="zendesk-token", email_address="agent@example.com"
        )

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.ZENDESKSUNSHINE

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "ZendeskSunshine"
        assert config.label == "Zendesk Sunshine"
        assert config.category == DataWarehouseSourceCategory.CRM
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/zendesk_sunshine.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/zendesk-sunshine"
        # A finished source ships visible; the scaffold's unreleasedSource flag must stay gone.
        assert not config.unreleasedSource

    def test_source_config_fields(self) -> None:
        config = self.source.get_source_config
        fields = {f.name: f for f in config.fields if isinstance(f, SourceFieldInputConfig)}
        assert set(fields) == {"subdomain", "api_key", "email_address"}
        assert fields["api_key"].type == SourceFieldInputConfigType.PASSWORD
        assert fields["api_key"].secret is True
        assert fields["subdomain"].secret is False
        assert fields["email_address"].type == SourceFieldInputConfigType.EMAIL
        assert all(f.required for f in fields.values())

    @parameterized.expand([("v1", ZENDESK_SUNSHINE_V1), ("v2", ZENDESK_SUNSHINE_V2)])
    def test_get_schemas_returns_version_table_set(self, _name: str, api_version: str) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, api_version=api_version)
        assert {s.name for s in schemas} == set(ENDPOINTS_BY_VERSION[api_version])

    def test_get_schemas_defaults_to_v2_table_set(self) -> None:
        # No pin resolves to default_version (v2); discovery of a NULL-pinned source must not fall
        # back to the legacy v1 catalog.
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS_BY_VERSION[ZENDESK_SUNSHINE_V2])

    def test_get_schemas_v1_object_records_are_merge_incremental(self) -> None:
        schemas = {
            s.name: s for s in self.source.get_schemas(self.config, self.team_id, api_version=ZENDESK_SUNSHINE_V1)
        }

        # v1 object records sync incrementally via the `objects/query` `_updated_at` range; its
        # inclusive lower bound re-fetches boundary rows, so only merge (dedupes on `id`) is offered.
        assert schemas["object_records"].supports_incremental is True
        assert schemas["object_records"].supports_append is False
        assert [f["field"] for f in schemas["object_records"].incremental_fields] == ["updated_at"]

        for name in ("object_types", "object_type_policies", "relationship_types", "relationship_records", "limits"):
            assert schemas[name].supports_incremental is False, name
            assert schemas[name].incremental_fields == [], name

    def test_get_schemas_v2_records_are_full_refresh(self) -> None:
        # The v2 records list endpoint has no server-side updated_at filter, so no v2 table is
        # incremental.
        schemas = self.source.get_schemas(self.config, self.team_id, api_version=ZENDESK_SUNSHINE_V2)
        for schema in schemas:
            assert schema.supports_incremental is False, schema.name
            assert schema.incremental_fields == [], schema.name

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(
            self.config, self.team_id, names=["object_records"], api_version=ZENDESK_SUNSHINE_V1
        )
        assert [s.name for s in schemas] == ["object_records"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_get_schemas_rejects_unsupported_version(self) -> None:
        with pytest.raises(ValueError, match="Unsupported Zendesk Sunshine API version"):
            self.source.get_schemas(self.config, self.team_id, api_version="v9")

    def test_versions_declare_deprecated_v1_with_sunset(self) -> None:
        assert self.source.supported_versions == (ZENDESK_SUNSHINE_V1, ZENDESK_SUNSHINE_V2)
        assert self.source.default_version == ZENDESK_SUNSHINE_V2
        deprecation = self.source.get_version_deprecation(ZENDESK_SUNSHINE_V1)
        assert deprecation is not None
        assert deprecation.sunset_at == datetime.date(2026, 6, 30)
        # The default must never be deprecated — new sources are stamped with it.
        assert self.source.get_version_deprecation(ZENDESK_SUNSHINE_V2) is None

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://nibbles.zendesk.com/api/sunshine/objects/types",
            "403 Client Error: Forbidden for url: https://nibbles.zendesk.com/api/sunshine/objects/records",
            "404 Client Error: Not Found for url: https://nibbles.zendesk.com/api/sunshine/objects/types",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    def test_non_retryable_errors_ignore_transient_failures(self) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        transient = "HTTP 500 for https://nibbles.zendesk.com/api/sunshine/objects/types"
        assert not any(key in transient for key in non_retryable)

    @pytest.mark.parametrize("bad_subdomain", ["bad domain", "sub.domain!", ""])
    def test_validate_credentials_rejects_invalid_subdomain_without_http(self, bad_subdomain: str) -> None:
        config = ZendeskSunshineSourceConfig(
            subdomain=bad_subdomain, api_key="zendesk-token", email_address="agent@example.com"
        )
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sunshine.source.validate_zendesk_sunshine_credentials"
        ) as mock_validate:
            is_valid, message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert message == "Zendesk subdomain is incorrect"
        mock_validate.assert_not_called()

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sunshine.source.validate_zendesk_sunshine_credentials"
    )
    def test_validate_credentials_plumbs_arguments(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)

        result = self.source.validate_credentials(self.config, self.team_id)

        assert result == (True, None)
        # No pin → resolves to default_version (v2), so a new source validates against v2.
        mock_validate.assert_called_once_with("nibbles", "zendesk-token", "agent@example.com", ZENDESK_SUNSHINE_V2)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sunshine.source.validate_zendesk_sunshine_credentials"
    )
    def test_validate_credentials_plumbs_pinned_version(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)

        self.source.validate_credentials(self.config, self.team_id, api_version=ZENDESK_SUNSHINE_V1)

        mock_validate.assert_called_once_with("nibbles", "zendesk-token", "agent@example.com", ZENDESK_SUNSHINE_V1)

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is ZendeskSunshineResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sunshine.source.zendesk_sunshine_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "object_records"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.api_version = ZENDESK_SUNSHINE_V1
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["subdomain"] == "nibbles"
        assert kwargs["api_key"] == "zendesk-token"
        assert kwargs["email_address"] == "agent@example.com"
        assert kwargs["endpoint"] == "object_records"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"
        # The resolved source pin reaches the request layer.
        assert kwargs["api_version"] == ZENDESK_SUNSHINE_V1

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sunshine.source.zendesk_sunshine_source"
    )
    def test_source_for_pipeline_omits_watermark_when_not_incremental(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "object_records"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_cover_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        # Descriptions are keyed by schema name and version-blind, so they must cover both catalogs.
        expected = set(ENDPOINTS_BY_VERSION[ZENDESK_SUNSHINE_V1]) | set(ENDPOINTS_BY_VERSION[ZENDESK_SUNSHINE_V2])
        assert set(descriptions.keys()) == expected

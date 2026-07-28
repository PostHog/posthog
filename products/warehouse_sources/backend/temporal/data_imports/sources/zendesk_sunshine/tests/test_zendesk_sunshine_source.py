import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zendesksunshine import (
    ZendeskSunshineSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sunshine.settings import ENDPOINTS
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

    def test_get_schemas_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_incremental_semantics(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        # Only object records have a server-side timestamp filter (the `objects/query`
        # endpoint's `_updated_at` range); everything else is full refresh.
        assert schemas["object_records"].supports_incremental is True
        # The inclusive `_updated_at.start` window re-fetches boundary rows each sync, so only
        # merge (which dedupes on `id`) is offered — append would duplicate those rows.
        assert schemas["object_records"].supports_append is False
        assert [f["field"] for f in schemas["object_records"].incremental_fields] == ["updated_at"]

        for name in ("object_types", "object_type_policies", "relationship_types", "relationship_records", "limits"):
            assert schemas[name].supports_incremental is False, name
            assert schemas[name].incremental_fields == [], name

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["object_records"])
        assert [s.name for s in schemas] == ["object_records"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

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
        mock_validate.assert_called_once_with("nibbles", "zendesk-token", "agent@example.com")

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
        assert set(descriptions.keys()) == set(ENDPOINTS)

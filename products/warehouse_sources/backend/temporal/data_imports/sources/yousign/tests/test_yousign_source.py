import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.yousign import (
    YouSignSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.yousign.settings import ENDPOINTS, WEBHOOK_EVENTS
from products.warehouse_sources.backend.temporal.data_imports.sources.yousign.source import YouSignSource
from products.warehouse_sources.backend.temporal.data_imports.sources.yousign.yousign import YousignResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestYousignSource:
    def setup_method(self) -> None:
        self.source = YouSignSource()
        self.team_id = 123
        self.config = YouSignSourceConfig(api_key="key", environment="production")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.YOUSIGN

    def test_source_is_released_not_hidden(self) -> None:
        # A finished source must be visible: `unreleasedSource` hides it from every user.
        config = self.source.get_source_config
        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "YouSign"
        assert config.label == "Yousign"
        assert config.category == DataWarehouseSourceCategory.SALES
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/yousign"
        assert config.iconPath == "/static/services/yousign.png"

    def test_api_key_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_environment_options_match_yousign_hosts(self) -> None:
        config = self.source.get_source_config
        environment = next(f for f in config.fields if isinstance(f, SourceFieldSelectConfig))
        assert environment.name == "environment"
        assert {o.value for o in environment.options} == {"production", "sandbox"}
        assert environment.defaultValue == "production"

    def test_get_schemas_incremental_flags(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert set(schemas) == set(ENDPOINTS)

        # Only the signature requests list has server-side timestamp filters; rows arrive
        # newest-first, so it must be merge-only (never append).
        signature_requests = schemas.pop("signature_requests")
        assert signature_requests.supports_incremental is True
        assert signature_requests.supports_append is False
        assert signature_requests.supports_webhooks is True
        assert {f["field"] for f in signature_requests.incremental_fields} == {
            "created_at",
            "activated_at",
            "completed_at",
        }

        for schema in schemas.values():
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.supports_webhooks is False

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["contacts"])
        assert [s.name for s in schemas] == ["contacts"]

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O — powers the public docs table list.
        assert self.source.lists_tables_without_credentials is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.yousign.app/v3/signature_requests",
            "403 Client Error: Forbidden for url: https://api-sandbox.yousign.app/v3/users",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    def test_non_retryable_errors_ignore_transient(self) -> None:
        transient = "500 Server Error for url: https://api.yousign.app/v3/signature_requests"
        assert not any(key in transient for key in self.source.get_non_retryable_errors())

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.yousign.source.validate_yousign_credentials"
    )
    def test_validate_credentials_plumbs_config(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)
        assert self.source.validate_credentials(self.config, self.team_id, schema_name="users") == (True, None)
        mock_validate.assert_called_once_with("key", "production", "users")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is YousignResumeConfig

    def test_webhook_resource_map_matches_event_name_prefixes(self) -> None:
        # The hog template routes on the event name prefix (`signature_request.done` ->
        # `signature_request`), so the map values must be that prefix.
        assert self.source.webhook_resource_map == {"signature_requests": "signature_request"}
        assert all(event.split(".")[0] == "signature_request" for event in WEBHOOK_EVENTS)

    def test_webhook_template_shape(self) -> None:
        template = self.source.webhook_template
        assert template is not None
        assert template.type == "warehouse_source_webhook"
        assert template.id == "template-warehouse-source-yousign"
        input_keys = {schema_input["key"] for schema_input in template.inputs_schema or []}
        assert {"signing_secret", "schema_mapping", "source_id"} <= input_keys

    def test_desired_webhook_events_cover_all_mapped_events(self) -> None:
        assert self.source.get_desired_webhook_events(self.config, ["signature_requests"]) == WEBHOOK_EVENTS

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.yousign.source.create_yousign_webhook"
    )
    def test_create_webhook_plumbs_config(self, mock_create: mock.MagicMock) -> None:
        self.source.create_webhook(self.config, "https://ph/webhook", self.team_id)
        args = mock_create.call_args.args
        assert args[:3] == ("key", "production", "https://ph/webhook")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.yousign.source.yousign_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_yousign_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "signature_requests"
        inputs.team_id = self.team_id
        inputs.should_use_incremental_field = True
        inputs.incremental_field = "completed_at"
        inputs.db_incremental_field_last_value = "2025-03-02"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_yousign_source.call_args.kwargs
        assert kwargs["api_key"] == "key"
        assert kwargs["environment"] == "production"
        assert kwargs["endpoint"] == "signature_requests"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["webhook_source_manager"] is not None
        assert kwargs["incremental_field"] == "completed_at"
        assert kwargs["db_incremental_field_last_value"] == "2025-03-02"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.yousign.source.yousign_source")
    def test_source_for_pipeline_drops_watermark_for_full_refresh(self, mock_yousign_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "signature_requests"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2025-03-02"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_yousign_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not-a-schema"
        with pytest.raises(ValueError, match="Unknown Yousign schema"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

    def test_canonical_descriptions_cover_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions) == set(ENDPOINTS)
        for entry in descriptions.values():
            assert entry["description"]
            assert entry["docs_url"].startswith("https://")

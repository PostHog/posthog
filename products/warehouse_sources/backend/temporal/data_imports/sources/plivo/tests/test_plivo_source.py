import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.plivo import PlivoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.plivo.plivo import PlivoResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.plivo.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.plivo.source import PlivoSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestPlivoSource:
    def setup_method(self):
        self.source = PlivoSource()
        self.team_id = 123
        self.config = PlivoSourceConfig(auth_id="MA123", auth_token="token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.PLIVO

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Plivo"
        assert config.label == "Plivo"
        assert config.category == DataWarehouseSourceCategory.COMMUNICATION
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source must be visible — regressing to the scaffold's hidden state would
        # remove the connector from every user's wizard.
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/plivo.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/plivo"

    def test_source_config_fields(self):
        config = self.source.get_source_config
        assert [f.name for f in config.fields] == ["auth_id", "auth_token"]

        auth_token = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "auth_token")
        assert auth_token.type == SourceFieldInputConfigType.PASSWORD
        assert auth_token.secret is True
        assert auth_token.required is True

    def test_get_schemas_incremental_support(self):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for name in ("messages", "calls", "recordings"):
            assert schemas[name].supports_incremental is True, name
            assert schemas[name].incremental_fields == INCREMENTAL_FIELDS[name]
        # The application list has no server-side time filter — full refresh only.
        assert schemas["applications"].supports_incremental is False
        assert schemas["applications"].supports_append is False

    def test_get_schemas_filtered_by_names(self):
        assert [s.name for s in self.source.get_schemas(self.config, self.team_id, names=["calls"])] == ["calls"]
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_lists_tables_without_credentials(self):
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert [t["name"] for t in documented] == list(ENDPOINTS)

    @pytest.mark.parametrize(
        "observed_error, is_non_retryable",
        [
            ("401 Client Error: Unauthorized for url: https://api.plivo.com/v1/Account/MA123/Message/", True),
            ("403 Client Error: Forbidden for url: https://api.plivo.com/v1/Account/MA123/Call/", True),
            ("500 Server Error: Internal Server Error for url: https://api.plivo.com/v1/Account/MA123/Call/", False),
            ("429 Client Error: Too Many Requests for url: https://api.plivo.com/v1/Account/MA123/Message/", False),
            ("401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers", False),
        ],
    )
    def test_non_retryable_errors(self, observed_error, is_non_retryable):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors) is is_non_retryable

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Plivo Auth ID or Auth Token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.plivo.source.validate_plivo_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("MA123", "token")

    def test_get_resumable_source_manager_binds_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is PlivoResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.plivo.source.plivo_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_plivo_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "messages"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-07-01 00:00:00"
        inputs.incremental_field = "message_time"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_plivo_source.call_args.kwargs
        assert kwargs["auth_id"] == "MA123"
        assert kwargs["auth_token"] == "token"
        assert kwargs["endpoint"] == "messages"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-07-01 00:00:00"
        assert kwargs["incremental_field"] == "message_time"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.plivo.source.plivo_source")
    def test_source_for_pipeline_drops_cursor_on_full_refresh(self, mock_plivo_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "messages"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-07-01 00:00:00"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        # A stale cursor must not narrow a full refresh to a partial window.
        assert mock_plivo_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_keyed_by_endpoint(self):
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions) == set(ENDPOINTS)

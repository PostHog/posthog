from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.drip.drip import DripResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.drip.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.drip.source import DripSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DripSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestDripSource:
    def setup_method(self):
        self.source = DripSource()
        self.team_id = 123
        self.config = DripSourceConfig(api_token="test_token", account_id="9999999")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.DRIP

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Drip"
        assert config.label == "Drip"
        assert config.iconPath == "/static/services/drip.png"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource

        field_names = [f.name for f in config.fields]
        assert field_names == ["api_token", "account_id"]

        api_token_field = config.fields[0]
        assert isinstance(api_token_field, SourceFieldInputConfig)
        assert api_token_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_token_field.required is True
        assert api_token_field.secret is True

        account_id_field = config.fields[1]
        assert isinstance(account_id_field, SourceFieldInputConfig)
        assert account_id_field.type == SourceFieldInputConfigType.TEXT
        assert account_id_field.required is True
        assert account_id_field.secret is False

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {s.name for s in schemas} == set(ENDPOINTS)
        # Drip exposes no reliable server-side update cursor, so everything is full refresh.
        assert all(not s.supports_incremental for s in schemas)
        assert all(not s.supports_append for s in schemas)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["subscribers"])

        assert len(schemas) == 1
        assert schemas[0].name == "subscribers"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["nonexistent"])

        assert schemas == []

    @parameterized.expand(
        [
            ("success", (True, None), True, None),
            ("failure", (False, "Invalid Drip API token"), False, "Invalid Drip API token"),
        ]
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.drip.source.validate_drip_credentials"
    )
    def test_validate_credentials(self, _name, mock_return, expected_valid, expected_message, mock_validate):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_token, self.config.account_id)

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.getdrip.com/v2/9999/subscribers"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.getdrip.com/v2/9999/campaigns"),
        ]
    )
    def test_non_retryable_errors_match_drip(self, _name, observed_error):
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("stripe", "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers"),
            ("klaviyo", "403 Client Error: Forbidden for url: https://a.klaviyo.com/api/profiles"),
        ]
    )
    def test_non_retryable_errors_do_not_match_other_vendors(self, _name, observed_error):
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in observed_error for key in non_retryable)

    def test_get_resumable_source_manager(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is DripResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.drip.source.drip_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_drip_source):
        manager = mock.MagicMock()
        inputs = mock.MagicMock()
        inputs.schema_name = "subscribers"

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_drip_source.assert_called_once_with(
            api_token="test_token",
            account_id="9999999",
            endpoint="subscribers",
            logger=inputs.logger,
            resumable_source_manager=manager,
        )

    @parameterized.expand(ENDPOINTS)
    def test_every_endpoint_is_a_schema(self, endpoint):
        schemas = self.source.get_schemas(self.config, self.team_id, names=[endpoint])
        assert len(schemas) == 1
        assert schemas[0].name == endpoint

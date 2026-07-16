from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import NewRelicSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.new_relic.new_relic import NewRelicResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.new_relic.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.new_relic.source import NewRelicSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.new_relic.source"


class TestNewRelicSource:
    def setup_method(self):
        self.source = NewRelicSource()
        self.team_id = 123
        self.config = NewRelicSourceConfig(api_key="NRAK-x", account_id=1234567, region="US")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.NEWRELIC

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "NewRelic"
        assert config.label == "New Relic"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/new-relic"

        field_names = [f.name for f in config.fields]
        assert field_names == ["api_key", "account_id", "region"]

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        key_field = next(f for f in config.fields if f.name == "api_key")
        assert isinstance(key_field, SourceFieldInputConfig)
        assert key_field.type == SourceFieldInputConfigType.PASSWORD
        assert key_field.secret is True
        assert key_field.required is True

    def test_region_field_defaults_to_us_and_offers_eu(self):
        config = self.source.get_source_config
        region_field = next(f for f in config.fields if f.name == "region")
        assert isinstance(region_field, SourceFieldSelectConfig)
        assert region_field.defaultValue == "US"
        assert [option.value for option in region_field.options] == ["US", "EU"]

    @parameterized.expand(
        [
            ("us_unauthorized", "401 Client Error: Unauthorized for url: https://api.newrelic.com/graphql"),
            ("eu_unauthorized", "401 Client Error: Unauthorized for url: https://api.eu.newrelic.com/graphql"),
            ("us_forbidden", "403 Client Error: Forbidden for url: https://api.newrelic.com/graphql"),
            ("eu_forbidden", "403 Client Error: Forbidden for url: https://api.eu.newrelic.com/graphql"),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            ("other_vendor", "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers"),
            ("server_error", "500 Server Error for url: https://api.newrelic.com/graphql"),
        ]
    )
    def test_non_retryable_errors_do_not_match_unrelated(self, _name, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_covers_every_endpoint(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    @parameterized.expand(
        [
            ("transactions", True),
            ("transaction_errors", True),
            ("page_views", True),
            ("logs", True),
            ("spans", True),
            ("entities", False),
            ("alert_policies", False),
            ("alert_conditions", False),
        ]
    )
    def test_event_tables_are_append_only_and_entity_tables_full_refresh(self, endpoint, supports_append):
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        assert schema.supports_append is supports_append
        assert schema.supports_incremental is False
        assert bool(schema.incremental_fields) is supports_append

    @parameterized.expand([("logs",), ("spans",)])
    def test_high_volume_tables_are_off_by_default(self, endpoint):
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        assert schema.should_sync_default is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["entities"])
        assert [schema.name for schema in schemas] == ["entities"]

    def test_get_schemas_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_canonical_descriptions_cover_every_endpoint(self):
        assert set(self.source.get_canonical_descriptions().keys()) == set(ENDPOINTS)

    def test_documented_tables_render_without_credentials(self):
        tables = self.source.get_documented_tables()
        assert {table["name"] for table in tables} == set(ENDPOINTS)

    @parameterized.expand(
        [
            ("valid", (True, None)),
            ("invalid", (False, "Invalid New Relic API key")),
        ]
    )
    @patch(f"{SOURCE_MODULE}.validate_new_relic_credentials")
    def test_validate_credentials_plumbs_config(self, _name, result, mock_validate):
        mock_validate.return_value = result

        assert self.source.validate_credentials(self.config, self.team_id) == result
        mock_validate.assert_called_once_with(self.config.api_key, self.config.account_id, self.config.region)

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is NewRelicResumeConfig

    @patch(f"{SOURCE_MODULE}.new_relic_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source):
        inputs = MagicMock()
        inputs.schema_name = "transactions"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "watermark"
        manager = MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once_with(
            api_key=self.config.api_key,
            account_id=self.config.account_id,
            region=self.config.region,
            endpoint="transactions",
            logger=inputs.logger,
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value="watermark",
        )

    @patch(f"{SOURCE_MODULE}.new_relic_source")
    def test_source_for_pipeline_drops_watermark_on_full_refresh(self, mock_source):
        inputs = MagicMock()
        inputs.schema_name = "transactions"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "stale-watermark"

        self.source.source_for_pipeline(self.config, MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

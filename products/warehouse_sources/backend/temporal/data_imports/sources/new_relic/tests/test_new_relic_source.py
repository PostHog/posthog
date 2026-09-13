from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.newrelic import (
    NewRelicSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.new_relic.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.new_relic.source import NewRelicSource

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.new_relic.source"


class TestNewRelicSource:
    def setup_method(self):
        self.source = NewRelicSource()
        self.team_id = 123
        self.config = NewRelicSourceConfig(api_key="NRAK-x", account_id=1234567, region="US")

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

    def test_documented_tables_render_without_credentials(self):
        tables = self.source.get_documented_tables()
        assert {table["name"] for table in tables} == set(ENDPOINTS)

    def test_connection_host_fields_require_secret_reentry_on_retarget(self):
        assert self.source.connection_host_fields == ["account_id", "region"]

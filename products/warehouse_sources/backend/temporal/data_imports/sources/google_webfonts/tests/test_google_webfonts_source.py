import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googlewebfonts import (
    GoogleWebfontsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_webfonts.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.google_webfonts.source import GoogleWebfontsSource

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.google_webfonts.source"


class TestGoogleWebfontsSource:
    def setup_method(self):
        self.source = GoogleWebfontsSource()
        self.team_id = 123
        self.config = GoogleWebfontsSourceConfig(api_key="AIza-key")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "400 Client Error: Bad Request for url: https://www.googleapis.com/webfonts/v1/webfonts?sort=alpha",
            "403 Client Error: Forbidden for url: https://www.googleapis.com/webfonts/v1/webfonts?sort=alpha",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            # A 400 from an unrelated API must not trip the Google Webfonts credential handler.
            "400 Client Error: Bad Request for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://www.googleapis.com/webfonts/v1/webfonts",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_are_full_refresh_only(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["webfonts"])
        assert len(schemas) == 1
        assert schemas[0].name == "webfonts"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_without_credentials(self):
        # Static catalog opt-in powers the posthog.com "Supported tables" section.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        webfonts = next(t for t in tables if t["name"] == "webfonts")
        assert webfonts["sync_methods"] == ["Full refresh"]
        assert webfonts["description"]

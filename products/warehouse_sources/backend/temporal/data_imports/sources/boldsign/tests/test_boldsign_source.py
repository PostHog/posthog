import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.boldsign.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.boldsign.source import BoldSignSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.boldsign import (
    BoldSignSourceConfig,
)


class TestBoldSignSource:
    def setup_method(self):
        self.source = BoldSignSource()
        self.team_id = 123
        self.config = BoldSignSourceConfig(api_key="key", region="us")

    def test_lists_tables_without_credentials(self):
        # Static endpoint catalog (no I/O) so the public docs can render Supported tables.
        assert self.source.lists_tables_without_credentials is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.boldsign.com/v1/document/list?Page=1",
            "401 Client Error: Unauthorized for url: https://api-eu.boldsign.com/v1/template/list?Page=1",
            "403 Client Error: Forbidden for url: https://api.boldsign.com/v1/users/list",
            "403 Client Error: Forbidden for url: https://api-eu.boldsign.com/v1/teams/list",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://api.boldsign.com/v1/document/list",
            "500 Server Error: Internal Server Error for url: https://api.boldsign.com/v1/document/list",
            "HTTPSConnectionPool(host='api.boldsign.com', port=443): Read timed out.",
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_lists_every_endpoint(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_get_schemas_are_full_refresh_only(self):
        # BoldSign has no reliable updated-since cursor, so nothing supports incremental/append.
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)

    def test_get_schemas_expose_primary_keys(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["documents"].detected_primary_keys == ["documentId"]
        assert schemas["teams"].detected_primary_keys == ["teamId"]
        assert schemas["contacts"].detected_primary_keys == ["id"]

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["documents"])
        assert len(schemas) == 1
        assert schemas[0].name == "documents"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_for_public_docs(self):
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        documents = next(t for t in tables if t["name"] == "documents")
        assert documents["sync_methods"] == ["Full refresh"]
        assert documents["primary_keys"] == ["documentId"]
        assert documents["description"]

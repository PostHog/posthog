import pytest

import pyarrow as pa

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.workos import WorkOSSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.workos.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.workos.source import WorkOSSource
from products.warehouse_sources.backend.temporal.data_imports.sources.workos.workos import _webhook_table_transformer


class TestWorkOSSource:
    def setup_method(self):
        self.source = WorkOSSource()
        self.team_id = 123
        self.config = WorkOSSourceConfig(api_key="sk_test_123")

    @pytest.mark.parametrize(
        "expected_key",
        [
            "401 Client Error: Unauthorized for url: https://api.workos.com",
            "403 Client Error: Forbidden for url: https://api.workos.com",
            "422 Client Error: Unprocessable Entity for url: https://api.workos.com",
        ],
    )
    def test_non_retryable_errors_includes_workos_key(self, expected_key):
        errors = self.source.get_non_retryable_errors()
        assert expected_key in errors

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.workos.com/organizations?limit=100",
            "422 Client Error: Unprocessable Entity for url: https://api.workos.com/directory_users?limit=100&order=desc",
        ],
    )
    def test_non_retryable_errors_matches_observed_error_message(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "401 Client Error: Unauthorized for url: https://api.clerk.com/v1/users",
        ],
    )
    def test_non_retryable_errors_does_not_match_other_vendors(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        schema_names = {schema.name for schema in schemas}
        assert schema_names == set(ENDPOINTS)
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)

    def test_get_schemas_filtered_by_names(self):
        first_endpoint = next(iter(ENDPOINTS))
        schemas = self.source.get_schemas(self.config, self.team_id, names=[first_endpoint])

        assert len(schemas) == 1
        assert schemas[0].name == first_endpoint

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["nonexistent"])
        assert schemas == []

    def test_webhook_transformer_extracts_rows_and_marks_deletes(self):
        table = pa.Table.from_pylist(
            [
                {
                    "event": "user.updated",
                    "created_at": "2026-01-01T00:00:00Z",
                    "data": '{"id":"user_1","email":"old@example.com"}',
                },
                {
                    "event": "user.deleted",
                    "created_at": "2026-01-02T00:00:00Z",
                    "data": '{"id":"user_1","email":"old@example.com"}',
                },
            ]
        )

        assert _webhook_table_transformer(table).to_pylist() == [
            {
                "id": "user_1",
                "email": "old@example.com",
                "workos_deleted": True,
                "workos_deleted_at": "2026-01-02T00:00:00Z",
            }
        ]

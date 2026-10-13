from typing import Any

from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.singlestore import (
    SinglestoreSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.singlestore import (
    source as singlestore_source_module,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.singlestore.source import SinglestoreSource


def _source_inputs(schema_name: str, **overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": schema_name,
        "schema_id": "schema-id",
        "source_id": "source-id",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-id",
        "logger": MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestSinglestoreSource:
    def setup_method(self) -> None:
        self.source = SinglestoreSource()
        self.config = SinglestoreSourceConfig(api_key="key")

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas iterates a static catalog with no I/O, so the public docs render the table list.
        assert self.source.lists_tables_without_credentials is True

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.singlestore.com/v1/organizations/current",
            ),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.singlestore.com/v1/workspaces"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("rate_limit", "429 Client Error: Too Many Requests for url: https://api.singlestore.com/v1/workspaces"),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.singlestore.com/v1/regions"),
            ("read_timeout", "HTTPSConnectionPool(host='api.singlestore.com', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        captured: dict[str, Any] = {}

        def fake_singlestore_source(**kwargs: Any) -> MagicMock:
            captured.update(kwargs)
            return MagicMock(name="source_response")

        inputs = _source_inputs(
            "billing_usage", should_use_incremental_field=True, db_incremental_field_last_value="2026-01-01"
        )
        with mock.patch.object(singlestore_source_module, "singlestore_source", fake_singlestore_source):
            self.source.source_for_pipeline(self.config, inputs)

        assert captured["api_key"] == "key"
        assert captured["endpoint"] == "billing_usage"
        assert captured["should_use_incremental_field"] is True
        assert captured["db_incremental_field_last_value"] == "2026-01-01"

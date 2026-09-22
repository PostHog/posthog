from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.cortex.source import CortexSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cortex import CortexSourceConfig


class TestCortexSource:
    def setup_method(self) -> None:
        self.source = CortexSource()
        self.team_id = 123
        self.config = CortexSourceConfig(api_key="cx_key")

    def test_source_is_released_not_hidden(self) -> None:
        # A finished source must be visible: `unreleasedSource` hides it from every user.
        assert not self.source.get_source_config.unreleasedSource

    def test_only_custom_events_syncs_incrementally(self) -> None:
        # `startTime` on the custom event stream is the only server-side time filter Cortex
        # documents; every other list endpoint has to be re-read in full.
        incremental = {
            schema.name for schema in self.source.get_schemas(self.config, self.team_id) if schema.supports_incremental
        }
        assert incremental == {"custom_events"}

    def test_full_refresh_schemas_advertise_no_cursor(self) -> None:
        for schema in self.source.get_schemas(self.config, self.team_id):
            if schema.name == "custom_events":
                continue
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O — powers the public docs table list.
        assert self.source.lists_tables_without_credentials is True

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.getcortexapp.com/api/v1/catalog"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.getcortexapp.com/api/v1/catalog"),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    def test_non_retryable_errors_ignore_transient(self) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(
            key in "503 Server Error for url: https://api.getcortexapp.com/api/v1/catalog" for key in non_retryable
        )

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lightdash import (
    LightdashSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lightdash.source import LightdashSource


class TestLightdashSource:
    def setup_method(self) -> None:
        self.source = LightdashSource()
        self.team_id = 123
        self.config = LightdashSourceConfig(instance_url="https://app.lightdash.cloud", api_token="tok")

    def test_source_is_released_not_hidden(self) -> None:
        # A finished source must be visible: `unreleasedSource` hides it from every user.
        assert not self.source.get_source_config.unreleasedSource

    def test_get_schemas_are_all_full_refresh(self) -> None:
        # Lightdash exposes no server-side updated-since filter, so no stream is incremental.
        for schema in self.source.get_schemas(self.config, self.team_id):
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O — powers the public docs table list.
        assert self.source.lists_tables_without_credentials is True

    def test_connection_host_fields_cover_token_destination(self) -> None:
        # Dropping this would let an editor retarget the stored token at a host they control
        # without re-entering it (the update serializer keys off this list).
        assert self.source.connection_host_fields == ["instance_url"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://x.lightdash.cloud/api/v1/user",
            "403 Client Error: Forbidden for url: https://x.lightdash.cloud/api/v1/user",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    def test_non_retryable_errors_ignore_transient(self) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(
            key in "503 Server Error for url: https://x.lightdash.cloud/api/v1/user" for key in non_retryable
        )

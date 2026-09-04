import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.shortcut import (
    ShortcutSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shortcut.source import ShortcutSource


class TestShortcutSource:
    def setup_method(self):
        self.source = ShortcutSource()
        self.team_id = 123
        self.config = ShortcutSourceConfig(api_token="test-token")

    def test_only_stories_supports_incremental(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["stories"].supports_incremental is True
        assert schemas["stories"].supports_append is True
        # Story incremental fields are updated_at (default) and created_at.
        assert {f["field"] for f in schemas["stories"].incremental_fields} == {"updated_at", "created_at"}

        for name, schema in schemas.items():
            if name == "stories":
                continue
            assert schema.supports_incremental is False, name
            assert schema.supports_append is False, name
            assert schema.incremental_fields == []

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.app.shortcut.com/api/v3/members",
            "403 Client Error: Forbidden for url: https://api.app.shortcut.com/api/v3/stories/search",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

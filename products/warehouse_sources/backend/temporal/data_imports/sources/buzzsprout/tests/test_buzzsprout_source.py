import pytest

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.buzzsprout.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.buzzsprout.source import BuzzsproutSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.buzzsprout import (
    BuzzsproutSourceConfig,
)


class TestBuzzsproutSource:
    def setup_method(self):
        self.source = BuzzsproutSource()
        self.team_id = 123
        self.config = BuzzsproutSourceConfig(api_token="test-token", podcast_id="123456")

    def test_get_source_config_fields(self):
        fields = self.source.get_source_config.fields

        by_name = {field.name: field for field in fields if isinstance(field, SourceFieldInputConfig)}
        assert set(by_name) == {"api_token", "podcast_id"}

        token_field = by_name["api_token"]
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.required is True
        assert token_field.secret is True

        podcast_field = by_name["podcast_id"]
        assert podcast_field.type == SourceFieldInputConfigType.TEXT
        assert podcast_field.required is True
        # The podcast ID is not a secret — it scopes the URL but grants no access on its own.
        assert podcast_field.secret is False

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_get_schemas_full_refresh_only(self, endpoint):
        # Buzzsprout has no server-side timestamp filter, so every endpoint is full refresh only.
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas[endpoint].supports_incremental is False
        assert schemas[endpoint].supports_append is False

    def test_non_retryable_errors_include_auth_failures(self):
        errors = self.source.get_non_retryable_errors()

        assert any("401 Client Error: Unauthorized" in key for key in errors)
        assert any("403 Client Error: Forbidden" in key for key in errors)
        # The match must be anchored to the Buzzsprout host so unrelated 401s don't trip it.
        assert all("https://www.buzzsprout.com" in key for key in errors)

    def test_lists_tables_without_credentials(self):
        # The static endpoint catalog has no I/O, so the public docs table list opts in.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)

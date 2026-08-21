from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.guardian import (
    GuardianSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.guardian.source import GuardianSource


class TestGuardianSource:
    def setup_method(self):
        self.source = GuardianSource()
        self.config = GuardianSourceConfig(api_key="test-key")

    def test_only_content_supports_incremental(self):
        # /search is the sole endpoint with a server-side from-date cursor; the reference
        # catalogs (tags/sections/editions) have no timestamp filter, so they're full refresh.
        schemas = {s.name: s for s in self.source.get_schemas(self.config, team_id=1)}
        assert schemas["content"].supports_incremental is True
        assert schemas["content"].incremental_fields[0]["field"] == "webPublicationDate"
        for name in ("tags", "sections", "editions"):
            assert schemas[name].supports_incremental is False
            assert schemas[name].incremental_fields == []

    def test_validate_credentials_success(self):
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.guardian.source.validate_guardian_credentials",
            return_value=True,
        ):
            assert self.source.validate_credentials(self.config, team_id=1) == (True, None)

    def test_validate_credentials_failure(self):
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.guardian.source.validate_guardian_credentials",
            return_value=False,
        ):
            ok, error = self.source.validate_credentials(self.config, team_id=1)
            assert ok is False
            assert error == "Invalid Guardian API key"

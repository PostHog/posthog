import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.loops import LoopsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.loops.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.loops.source import LoopsSource


class TestLoopsSource:
    def setup_method(self) -> None:
        self.source = LoopsSource()
        self.team_id = 123
        self.config = LoopsSourceConfig(api_key="test-key")

    @pytest.mark.parametrize(
        "raised_message",
        [
            # requests raises `<status> Client Error: <reason> for url: <url>`; the sync matcher
            # is a substring check, so the keys must classify these as non-retryable.
            "401 Client Error: Unauthorized for url: https://app.loops.so/api/v1/campaigns?perPage=50",
            "403 Client Error: Forbidden for url: https://app.loops.so/api/v1/lists",
        ],
    )
    def test_auth_errors_are_non_retryable(self, raised_message: str) -> None:
        keys = self.source.get_non_retryable_errors().keys()
        assert any(key in raised_message for key in keys)

    def test_get_schemas_all_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {s.name for s in schemas} == set(ENDPOINTS)
        # Loops list endpoints have no server-side timestamp filters, so advertising
        # incremental sync would silently degrade to a broken full scan.
        assert all(not s.supports_incremental for s in schemas)
        assert all(not s.supports_append for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_canonical_descriptions_cover_only_known_endpoints(self) -> None:
        # A description keyed by a name `get_schemas` never returns is dead metadata
        # (typo'd endpoint or a rename that missed this file).
        assert set(self.source.get_canonical_descriptions().keys()) <= set(ENDPOINTS)

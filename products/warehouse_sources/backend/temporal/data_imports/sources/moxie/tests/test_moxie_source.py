import pytest

from posthog.schema import ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.moxie import MoxieSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.moxie.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.moxie.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.moxie.source import MoxieSource


class TestMoxieSource:
    def setup_method(self) -> None:
        self.source = MoxieSource()
        self.team_id = 123
        self.config = MoxieSourceConfig(base_url="https://pod00.withmoxie.dev/api/public", api_key="test_key")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Moxie"
        assert config.label == "Moxie"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source is visible to users — the scaffold's unreleasedSource flag must be gone.
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/moxie.png"

    def test_connection_host_fields(self) -> None:
        # base_url carries the API key's destination, so editing it must re-require the secret.
        assert self.source.connection_host_fields == ["base_url"]

    def test_documented_tables_render_for_public_docs(self) -> None:
        # lists_tables_without_credentials=True + static get_schemas means the doc's Supported tables
        # section is populated without a live connection.
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)

    def test_canonical_descriptions_keyed_by_endpoint_names(self) -> None:
        # A renamed endpoint would silently orphan its curated descriptions.
        assert set(CANONICAL_DESCRIPTIONS.keys()) == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://pod00.withmoxie.dev/api/public/action/clients/list",
            "403 Client Error: Forbidden for url: https://pod00.withmoxie.dev/api/public/action/clients/list",
            "Moxie workspace base URL is not allowed",
            "Moxie workspace base URL must use HTTPS",
        ],
    )
    def test_non_retryable_errors_match_auth_and_host_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

from posthog.schema import ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tvmaze import TVMazeSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tvmaze.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tvmaze.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.tvmaze.source import TVMazeSource


class TestTVMazeSource:
    def setup_method(self) -> None:
        self.source = TVMazeSource()
        self.team_id = 123
        self.config = TVMazeSourceConfig()

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "TVMaze"
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/tvmaze.png"
        # Doc slug and docsUrl must agree (see /documenting-warehouse-sources).
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/tvmaze"
        # Open public API — the connect form has no credential fields.
        assert config.fields == []

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog: public docs render the table list from get_schemas.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_all_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {s.name for s in schemas} == set(ENDPOINTS)
        # TVmaze has no server-side timestamp filter, so no endpoint may
        # advertise incremental or append sync.
        assert all(not s.supports_incremental for s in schemas)
        assert all(not s.supports_append for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        # A drifted key silently falls back to LLM enrichment, so keep the
        # curated catalog aligned with the endpoint names.
        assert set(self.source.get_canonical_descriptions()) == set(ENDPOINTS)
        assert self.source.get_canonical_descriptions() is CANONICAL_DESCRIPTIONS

    def test_get_non_retryable_errors_covers_auth_rejections(self) -> None:
        # A 401/403 from the public API is an IP-level block that a retry can't
        # fix, so it must be classified non-retryable rather than looping forever.
        errors = self.source.get_non_retryable_errors()
        assert set(errors) == {"401 Client Error", "403 Client Error"}
        assert all(message for message in errors.values())

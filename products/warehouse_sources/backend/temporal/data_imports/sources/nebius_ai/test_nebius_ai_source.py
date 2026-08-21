from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.nebius_ai.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.nebius_ai.source import NebiusAISource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestNebiusAISchemas:
    def test_exposes_expected_endpoints(self) -> None:
        schemas = NebiusAISource().get_schemas(MagicMock(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        assert {s.name for s in schemas} == {"models", "files", "batches", "fine_tuning_jobs"}

    def test_every_endpoint_is_full_refresh_only(self) -> None:
        # No endpoint has a server-side timestamp filter, so incremental/append must stay off to
        # avoid advertising a mode that would cost the same as a full refresh every run.
        for schema in NebiusAISource().get_schemas(MagicMock(), team_id=1):
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_names_filter_narrows_the_list(self) -> None:
        schemas = NebiusAISource().get_schemas(MagicMock(), team_id=1, names=["files"])
        assert [s.name for s in schemas] == ["files"]


class TestNebiusAIRegistration:
    def test_source_is_registered(self) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry

        source = SourceRegistry.get_source(ExternalDataSourceType.NEBIUSAI)
        assert isinstance(source, NebiusAISource)

from products.warehouse_sources.backend.temporal.data_imports.sources import load_all_sources, source_module_path
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry


def test_load_all_sources_imports_every_source_module():
    # A stale import in any single source module breaks the whole registry load — every
    # source self-registers on import, so one bad path takes down imports for all sources.
    load_all_sources()

    # `SourceRegistry.get_source` imports one module per type, derived from the directory
    # name. A source registered from a differently named directory would silently fall back
    # to the full load on every request.
    for source_type, source in SourceRegistry.get_all_sources().items():
        assert type(source).__module__ == source_module_path(source_type)

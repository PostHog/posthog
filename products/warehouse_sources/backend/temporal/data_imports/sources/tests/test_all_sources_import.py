from products.warehouse_sources.backend.temporal.data_imports.sources import load_all_sources


def test_load_all_sources_imports_every_source_module():
    # A stale import in any single source module breaks the whole registry load — every
    # source self-registers on import, so one bad path takes down imports for all sources.
    load_all_sources()

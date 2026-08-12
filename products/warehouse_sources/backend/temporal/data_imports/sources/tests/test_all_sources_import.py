from products.warehouse_sources.backend.temporal.data_imports.sources import (
    _module_paths_by_source_type,
    load_all_sources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry


def test_load_all_sources_imports_every_source_module():
    # A stale import in any single source module breaks the whole registry load — every
    # source self-registers on import, so one bad path takes down imports for all sources.
    load_all_sources()


def test_source_module_mapping_matches_where_each_registered_source_lives():
    # `get_source` imports the mapped module and expects the type to be registered
    # afterwards, so a mapping entry that resolves to any other module makes that type
    # unloadable on the targeted path. Comparing against the registered class's defining
    # module checks the mapping against where each source actually lives.
    mapping = _module_paths_by_source_type()

    mismatches = {
        source_type: (mapping.get(source_type), type(source).__module__)
        for source_type, source in SourceRegistry.get_all_sources().items()
        if mapping.get(source_type) != type(source).__module__
    }
    assert mismatches == {}

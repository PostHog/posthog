import ast
from pathlib import Path

from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources import _source_module_paths, load_all_sources
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

_SOURCES = "products.warehouse_sources.backend.temporal.data_imports.sources"


def test_broken_source_module_does_not_block_the_rest_of_the_catalog():
    with (
        patch(f"{_SOURCES}._bulk_load", side_effect=ModuleNotFoundError("No module named 'gone'")),
        patch(
            f"{_SOURCES}._source_module_paths",
            return_value=[f"{_SOURCES}.gone.source", f"{_SOURCES}.pypi.source"],
        ),
        patch(f"{_SOURCES}.capture_exception") as capture_exception,
    ):
        load_all_sources()

    # Reads `_sources` rather than `get_all_sources()` so the assertion can't be satisfied by
    # the real full load that `_ensure_loaded` would kick off.
    assert ExternalDataSourceType.PYPI in SourceRegistry._sources
    capture_exception.assert_called_once()


def test_per_source_fallback_covers_every_source_the_bulk_import_loads():
    bulk_import_list = ast.parse((Path(__file__).parent.parent / "_load_all.py").read_text())

    assert set(_source_module_paths()) == {
        f"{_SOURCES}.{node.module}"
        for node in ast.walk(bulk_import_list)
        if isinstance(node, ast.ImportFrom) and node.module
    }

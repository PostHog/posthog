import ast
from pathlib import Path
from typing import cast

import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources import (
    _source_module_paths,
    load_all_sources,
    source_module_path,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import AnySource
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


class _FakePypiSource:
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PYPI


def _register_fake_pypi_source(*_args) -> None:
    SourceRegistry.register(cast(type[AnySource], _FakePypiSource))


@pytest.fixture
def empty_registry():
    saved_sources, saved_loaded = dict(SourceRegistry._sources), SourceRegistry._loaded
    SourceRegistry._sources.clear()
    SourceRegistry._loaded = False
    try:
        yield
    finally:
        SourceRegistry._sources.clear()
        SourceRegistry._sources.update(saved_sources)
        SourceRegistry._loaded = saved_loaded


def test_get_source_imports_only_the_requested_source(empty_registry):
    with (
        patch(f"{_SOURCES}.load_source", side_effect=_register_fake_pypi_source) as load_source,
        patch(f"{_SOURCES}.load_all_sources", side_effect=AssertionError("the full catalog load must not run")),
    ):
        source = SourceRegistry.get_source(ExternalDataSourceType.PYPI)

    assert isinstance(source, _FakePypiSource)
    load_source.assert_called_once_with(ExternalDataSourceType.PYPI)
    assert SourceRegistry._loaded is False


def test_get_source_falls_back_to_the_full_load_when_the_single_import_registers_nothing(empty_registry):
    with (
        patch(f"{_SOURCES}.load_source"),
        patch(f"{_SOURCES}.load_all_sources", side_effect=_register_fake_pypi_source),
    ):
        source = SourceRegistry.get_source(ExternalDataSourceType.PYPI)

    assert isinstance(source, _FakePypiSource)
    assert SourceRegistry._loaded is True


def test_get_source_resolves_a_raw_string_value_through_the_lazy_path(empty_registry):
    # Reproduces the cold-worker `oauth_accounts` call: a raw query-param string reaches
    # `get_source`, whose lazy load reads `source_type.name`. `_load_source` is stubbed so the
    # real `source_module_path` runs without importing a vendor module.
    with (
        patch(f"{_SOURCES}._load_source", side_effect=_register_fake_pypi_source),
        patch(f"{_SOURCES}.load_all_sources", side_effect=AssertionError("the full catalog load must not run")),
    ):
        source = SourceRegistry.get_source(cast(ExternalDataSourceType, ExternalDataSourceType.PYPI.value))

    assert isinstance(source, _FakePypiSource)


def test_get_source_raises_valueerror_for_an_unknown_string_value(empty_registry):
    # The endpoint turns ValueError into a 400. An unknown string must not read `.name` off a str.
    with patch(f"{_SOURCES}.load_all_sources", side_effect=AssertionError("the full catalog load must not run")):
        with pytest.raises(ValueError):
            SourceRegistry.get_source(cast(ExternalDataSourceType, "NotARealSource"))


def test_source_module_path_resolves_every_source_type_without_importing_it():
    module_paths = set(_source_module_paths())

    assert {source_module_path(source_type) for source_type in ExternalDataSourceType} <= module_paths

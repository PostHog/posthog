import ast
from pathlib import Path

import pytest
from unittest.mock import patch

from django.test import override_settings

from products.warehouse_sources.backend.temporal.data_imports.sources import (
    _should_capture_import_failure,
    _source_module_paths,
    load_all_sources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

_SOURCES = "products.warehouse_sources.backend.temporal.data_imports.sources"


@pytest.mark.parametrize("cloud_deployment,expect_capture", [("US", True), (None, False)])
def test_missing_dependency_import_is_reported_only_when_deployed(cloud_deployment, expect_capture):
    # An unprovisioned interpreter fails to import every source missing its SDK. Reporting each
    # one files a fresh error-tracking issue per source, so the fallback stays silent unless a
    # deployed environment (deps guaranteed synced) makes the failure real signal.
    with (
        patch(f"{_SOURCES}._bulk_load", side_effect=ModuleNotFoundError("No module named 'gone'")),
        patch(
            f"{_SOURCES}._source_module_paths",
            return_value=[f"{_SOURCES}.gone.source", f"{_SOURCES}.pypi.source"],
        ),
        patch(f"{_SOURCES}.capture_exception") as capture_exception,
        override_settings(CLOUD_DEPLOYMENT=cloud_deployment, DEBUG=False),
    ):
        load_all_sources()

    # Reads `_sources` rather than `get_all_sources()` so the assertion can't be satisfied by
    # the real full load that `_ensure_loaded` would kick off.
    assert ExternalDataSourceType.PYPI in SourceRegistry._sources
    assert capture_exception.call_count == (1 if expect_capture else 0)


def test_real_source_breakage_is_always_reported():
    # A non-import error is a broken source module, not a missing dependency, so it carries
    # product signal in every environment.
    with override_settings(CLOUD_DEPLOYMENT=None, DEBUG=False):
        assert _should_capture_import_failure(ValueError("bad module-level code")) is True


def test_per_source_fallback_covers_every_source_the_bulk_import_loads():
    bulk_import_list = ast.parse((Path(__file__).parent.parent / "_load_all.py").read_text())

    assert set(_source_module_paths()) == {
        f"{_SOURCES}.{node.module}"
        for node in ast.walk(bulk_import_list)
        if isinstance(node, ast.ImportFrom) and node.module
    }

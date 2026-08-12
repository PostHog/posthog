import ast
import sys
import subprocess
from pathlib import Path

from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources import (
    _module_paths_by_source_type,
    _source_module_paths,
    load_all_sources,
)
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


def test_every_source_type_maps_to_exactly_one_source_module():
    mapping = _module_paths_by_source_type()

    assert set(mapping) == set(ExternalDataSourceType)
    assert sorted(mapping.values()) == _source_module_paths()


# Runs in a clean interpreter: pytest has long since imported source modules into this
# process, so only a cold subprocess can observe which modules a targeted lookup pulls in.
_TARGETED_LOAD_SCRIPT = f"""
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
import django
django.setup()

import sys
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

SOURCES = "{_SOURCES}"
for module in (SOURCES + "._load_all", SOURCES + ".postgres.source", SOURCES + ".stripe.source"):
    assert module not in sys.modules, module + " already imported at django.setup(); no cold state to observe"

postgres = SourceRegistry.get_source(ExternalDataSourceType.POSTGRES)
assert type(postgres).__name__ == "PostgresSource", type(postgres).__name__
assert type(postgres).__module__ == SOURCES + ".postgres.source", type(postgres).__module__
assert SOURCES + ".postgres.source" in sys.modules
assert SOURCES + "._load_all" not in sys.modules, "get_source ran the full-catalog loader"
assert SOURCES + ".stripe.source" not in sys.modules, "get_source imported an unrelated source"

stripe = SourceRegistry.get_source(ExternalDataSourceType.STRIPE)
assert type(stripe).__name__ == "StripeSource", type(stripe).__name__
assert SOURCES + ".stripe.source" in sys.modules
assert SOURCES + "._load_all" not in sys.modules, "the second lookup ran the full-catalog loader"

assert SourceRegistry.is_registered(ExternalDataSourceType.MYSQL)
assert SOURCES + ".mysql.source" in sys.modules, "is_registered did not load the requested source"
assert SOURCES + "._load_all" not in sys.modules, "is_registered ran the full-catalog loader"

with patch(SOURCES + ".load_source") as load_source:
    assert SourceRegistry.get_source(ExternalDataSourceType.POSTGRES) is postgres
    load_source.assert_not_called()

with patch(SOURCES + ".load_all_sources") as load_all_sources:
    SourceRegistry.get_all_sources()
    load_all_sources.assert_called_once()
"""


def test_get_source_imports_only_the_requested_source_module():
    result = subprocess.run(
        [sys.executable, "-c", _TARGETED_LOAD_SCRIPT],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, f"targeted-load subprocess failed:\n{result.stderr[-4000:]}"

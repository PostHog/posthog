import functools
import importlib
import importlib.util
from pathlib import Path

from django.conf import settings

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.run_mode import derive_run_mode

from products.warehouse_sources.backend.types import ExternalDataSourceType

from .common.registry import SourceRegistry

__all__ = ["SourceRegistry", "load_all_sources", "load_source", "source_module_path"]

logger = structlog.get_logger(__name__)

# Vendor directories live in two packages: this one holds the vendors that other code imports,
# and the top-level `sources` package holds all other vendors. Each vendor is one directory
# with a `source.py`, so the loader finds both by the directory layout.
TOP_LEVEL_SOURCES_PACKAGE = "sources"


def load_all_sources() -> None:
    """Import every source module so each registers itself with ``SourceRegistry``.

    Deferred out of module scope so importing a leaf (e.g. ``sources.stripe.constants``)
    doesn't drag every vendor SDK at app startup. Importing a source module runs its
    ``@SourceRegistry.register`` decorator. Idempotent — re-imports are cheap dict lookups
    in ``sys.modules``.

    Best-effort: each module imports on its own, so a source module that can't be imported
    is reported and skipped, leaving the rest of the catalog usable.
    """
    for module_path in _source_module_paths():
        _load_source(module_path)


def source_module_path(source_type: ExternalDataSourceType) -> str | None:
    """The source module that registers ``source_type``, or None when no directory matches.

    A source directory is the enum member's name in lowercase with underscores added
    (``BINGADS`` -> ``bing_ads``), so the lookup strips underscores from the directory names.
    A test asserts every registered source resolves this way. A string key with no enum
    member is its own name (``"DemoAcme"`` -> ``demo_acme``).
    """
    name = source_type.name if isinstance(source_type, ExternalDataSourceType) else source_type
    return _source_modules_by_squashed_name().get(name.lower())


def load_source(source_type: ExternalDataSourceType) -> None:
    """Import only the module that registers ``source_type``.

    Request paths ask the registry for a handful of source types, and importing every
    source module costs seconds per process, so they import just the modules they need.
    """
    module_path = source_module_path(source_type)
    if module_path is not None:
        _load_source(module_path)


@functools.cache
def _source_modules_by_squashed_name() -> dict[str, str]:
    return {path.rsplit(".", 2)[1].replace("_", ""): path for path in _source_module_paths()}


def _top_level_sources_dir() -> Path | None:
    """The directory of the top-level `sources` package, or None when it is not importable."""
    spec = importlib.util.find_spec(TOP_LEVEL_SOURCES_PACKAGE)
    if spec is None or not spec.submodule_search_locations:
        return None
    return Path(spec.submodule_search_locations[0])


def _source_module_paths() -> list[str]:
    """Every source module, derived from the directory layout of both packages.

    Sorted by vendor directory name, so the registry fills in alphabetical order whichever
    package holds a vendor.
    """
    module_paths = [f"{__name__}.{source.parent.name}.source" for source in Path(__path__[0]).glob("*/source.py")]
    top_level_dir = _top_level_sources_dir()
    if top_level_dir is not None:
        module_paths += [
            f"{TOP_LEVEL_SOURCES_PACKAGE}.{source.parent.name}.source" for source in top_level_dir.glob("*/source.py")
        ]
    return sorted(module_paths, key=lambda path: path.rsplit(".", 2)[1])


def _load_source(module_path: str) -> None:
    try:
        importlib.import_module(module_path)
    except Exception as e:
        logger.exception("load_all_sources: source module failed to import", module=module_path)
        if _should_capture_import_failure(e):
            capture_exception(e)


def _should_capture_import_failure(error: Exception) -> bool:
    """Whether an import failure is a broken source or an incomplete checkout.

    A missing module means the tree is incomplete: an interpreter without the source SDKs,
    or a source directory added before its generated config was written. A deploy has every
    SDK locked and every generated config committed, so only there does a missing module
    mean a source dropped out of the catalog. Any other error is module-level breakage,
    which counts wherever it happens.
    """
    if isinstance(error, ImportError):  # ModuleNotFoundError is a subclass
        return derive_run_mode(settings.CLOUD_DEPLOYMENT, settings.DEBUG).is_deployed_cloud
    return True

import importlib
from functools import cache
from pathlib import Path
from typing import Any

import structlog

from posthog.exceptions_capture import capture_exception

from products.warehouse_sources.backend.types import ExternalDataSourceType

from .common.registry import SourceRegistry

__all__ = ["SourceRegistry", "load_all_sources", "load_source"]

logger = structlog.get_logger(__name__)

# Source types whose module directory `_normalize` cannot derive from the enum value. When a
# new source's enum value and directory name stop normalizing to the same key, map the type
# to its directory here; `test_every_source_type_maps_to_exactly_one_source_module` fails
# until every type resolves.
_SOURCE_MODULE_OVERRIDES: dict[ExternalDataSourceType, str] = {}


def load_all_sources() -> None:
    """Import every source module so each registers itself with ``SourceRegistry``.

    Deferred out of module scope so importing a leaf (e.g. ``sources.stripe.constants``)
    doesn't drag every vendor SDK at app startup. Importing ``_load_all`` runs each
    source module's ``@SourceRegistry.register`` decorator. Idempotent — re-imports are
    cheap dict lookups in ``sys.modules``.

    Best-effort: a source module that can't be imported is reported and skipped, leaving the
    rest of the catalog usable.
    """
    try:
        _bulk_load()
    except Exception:
        # `_load_all` is one flat import list, so a single unimportable source module aborts it
        # and leaves every later source unregistered — failing every sync and the whole sources
        # UI rather than just the offending source. Import the rest individually so one broken
        # vendor module costs only its own source.
        logger.exception("load_all_sources: bulk import failed, falling back to per-source import")
        for module_path in _source_module_paths():
            _load_source(module_path)


def load_source(source_type: ExternalDataSourceType) -> None:
    """Import just the module that registers ``source_type`` with ``SourceRegistry``.

    Same failure isolation as ``load_all_sources``: a module that can't be imported is
    reported and skipped, so the caller observes the type as unregistered. A type with no
    mapped module is skipped silently, matching how a bulk load leaves an unknown type
    unregistered.
    """
    module_path = _module_paths_by_source_type().get(source_type)
    if module_path is not None:
        _load_source(module_path)


def _bulk_load() -> None:
    from . import _load_all  # noqa: F401, PLC0415


def _source_module_dirs() -> list[str]:
    package_dir = Path(__path__[0])
    return sorted(source.parent.name for source in package_dir.glob("*/source.py"))


def _source_module_paths() -> list[str]:
    """Every source module `_load_all` imports, derived from the directory layout.

    A test asserts this stays in step with `_load_all`'s import list.
    """
    return [f"{__name__}.{module_dir}.source" for module_dir in _source_module_dirs()]


def _normalize(name: str) -> str:
    # Enum values are CamelCase and source directories are snake_case, with word boundaries
    # that don't line up mechanically ("TikTokAds" -> "tiktok_ads", "DoIt" -> "doit"). Case
    # and underscores are the only differences, so stripping both pairs each enum value with
    # its directory.
    return name.lower().replace("_", "")


@cache
def _module_paths_by_source_type() -> dict[ExternalDataSourceType, str]:
    """The module that registers each source type, derived from the directory layout.

    Tests assert the result is a bijection between ``ExternalDataSourceType`` and the on-disk
    catalog, and that each mapped module is where the registered source class really lives.
    """
    dirs_by_key = {_normalize(module_dir): module_dir for module_dir in _source_module_dirs()}
    mapping: dict[ExternalDataSourceType, str] = {}
    for source_type in ExternalDataSourceType:
        module_dir = _SOURCE_MODULE_OVERRIDES.get(source_type) or dirs_by_key.get(_normalize(source_type.value))
        if module_dir is not None:
            mapping[source_type] = f"{__name__}.{module_dir}.source"
    return mapping


def _load_source(module_path: str) -> None:
    try:
        importlib.import_module(module_path)
    except Exception as e:
        logger.exception("load_all_sources: source module failed to import", module=module_path)
        capture_exception(e)


def __getattr__(name: str) -> Any:
    # Back-compat: source classes used to be re-exported here. Resolve them lazily so
    # `from ...sources import StripeSource` keeps working without eager-loading every SDK.
    # Guard private/dunder names (including `_load_all` itself) to avoid recursing through
    # the very import we use to populate the namespace. Every re-exported class is a
    # `*Source`, so anything else is an attribute probe (pytest looking for `pytest_plugins`,
    # a `hasattr` check) that must not drag in 1200-odd vendor modules to answer.
    if name.startswith("_") or not name.endswith("Source"):
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    from . import _load_all  # noqa: PLC0415

    try:
        return getattr(_load_all, name)
    except AttributeError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None

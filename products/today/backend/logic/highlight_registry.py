import pkgutil
import importlib
from collections.abc import Iterator
from functools import cache
from types import ModuleType

from posthog.products import load_product_modules

from ..facade.contracts import HighlightSource
from . import highlight_sources

SOURCES_MODULE = "facade.today_highlights"
SOURCES_ATTRIBUTE = "HIGHLIGHT_SOURCES"


class HighlightRegistryError(Exception):
    pass


def _legacy_modules() -> Iterator[ModuleType]:
    for name in sorted(module.name for module in pkgutil.iter_modules(highlight_sources.__path__)):
        yield importlib.import_module(f"{highlight_sources.__name__}.{name}")


def _declared(module: ModuleType) -> object:
    if module.__name__.startswith(f"{highlight_sources.__name__}."):
        source = getattr(module, "SOURCE", None)
        return None if source is None else (source,)
    return getattr(module, SOURCES_ATTRIBUTE, None)


@cache
def load_sources() -> tuple[HighlightSource, ...]:
    """Every source that a product declares in `backend/facade/today_highlights.py`, sorted by name.

    A product depends on Today's facade to declare a source, so Today needs no import of that product.
    Sources still in the legacy `highlight_sources/` package declare a module-level `SOURCE` and load too.
    A broken declaration raises instead of dropping the source without a trace.
    """
    sources: dict[str, HighlightSource] = {}
    owners: dict[str, str] = {}
    for module in [*load_product_modules(SOURCES_MODULE), *_legacy_modules()]:
        declared = _declared(module)
        if not isinstance(declared, tuple | list):
            raise HighlightRegistryError(f"{module.__name__}.{SOURCES_ATTRIBUTE} must be a tuple of HighlightSource")
        for source in declared:
            if not isinstance(source, HighlightSource) or not source.name or not callable(source.find):
                raise HighlightRegistryError(
                    f"{module.__name__} declares {source!r}, which is not a usable HighlightSource"
                )
            if source.name in sources:
                raise HighlightRegistryError(
                    f"{module.__name__} and {owners[source.name]} both declare the source name {source.name!r}"
                )
            sources[source.name] = source
            owners[source.name] = module.__name__
    return tuple(sources[name] for name in sorted(sources))

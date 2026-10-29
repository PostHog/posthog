from collections.abc import Mapping
from functools import cache

from posthog.dataclasses import frozen
from posthog.products import load_product_modules

from ..facade.contracts import HighlightSource

SOURCES_MODULE = "facade.today_highlights"
SOURCES_ATTRIBUTE = "HIGHLIGHT_SOURCES"


class HighlightRegistryError(Exception):
    pass


@frozen
class HighlightRegistry:
    sources: tuple[HighlightSource, ...]
    products: Mapping[str, str]


def _product(module_name: str) -> str:
    # Product apps are named `products.<product>.backend`.
    return module_name.split(".")[1]


@cache
def load_registry() -> HighlightRegistry:
    """Every source that a product declares in `backend/facade/today_highlights.py`, sorted by name.

    Today imports no product by name, so the dependency points from the product to Today's facade.
    A broken declaration raises instead of dropping the source without a trace.
    """
    sources: dict[str, HighlightSource] = {}
    owners: dict[str, str] = {}
    for module in load_product_modules(SOURCES_MODULE):
        declared = getattr(module, SOURCES_ATTRIBUTE, None)
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
    return HighlightRegistry(
        sources=tuple(sources[name] for name in sorted(sources)),
        products={name: _product(module_name) for name, module_name in owners.items()},
    )


def load_sources() -> tuple[HighlightSource, ...]:
    return load_registry().sources


def source_product(name: str) -> str | None:
    """None for a name that no product declares, such as a source removed after a result was stored."""
    return load_registry().products.get(name)

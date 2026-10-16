from functools import cache

from posthog.products import load_product_modules

from ..facade.contracts import HighlightSource

SOURCES_MODULE = "facade.today_highlights"
SOURCES_ATTRIBUTE = "HIGHLIGHT_SOURCES"


class HighlightRegistryError(Exception):
    pass


@cache
def load_sources() -> tuple[HighlightSource, ...]:
    """Every source that a product declares in `backend/facade/today_highlights.py`, sorted by name.

    Today imports no product by name, so the dependency points from the product to Today's facade.
    A broken declaration raises instead of dropping the source without a trace.
    """
    sources: dict[str, HighlightSource] = {}
    for module in load_product_modules(SOURCES_MODULE):
        declared = getattr(module, SOURCES_ATTRIBUTE, None)
        if declared is None:
            raise HighlightRegistryError(f"{module.__name__} has no {SOURCES_ATTRIBUTE}")
        for source in declared:
            if not isinstance(source, HighlightSource):
                raise HighlightRegistryError(f"{module.__name__} declares {source!r}, which is not a HighlightSource")
            if source.name in sources:
                raise HighlightRegistryError(f"{module.__name__} declares the source name {source.name!r} again")
            sources[source.name] = source
    return tuple(sources[name] for name in sorted(sources))

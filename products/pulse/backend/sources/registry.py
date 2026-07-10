from products.pulse.backend.sources.anchored_insights import AnchoredInsightsSource
from products.pulse.backend.sources.base import BriefSource

# Mutable registry so new sources can be registered (tests, future products) without editing
# the gather path. `get_sources` returns a copy so callers can't mutate the registry in place.
_sources: list[BriefSource] = [AnchoredInsightsSource()]


def get_sources() -> list[BriefSource]:
    return list(_sources)


def register_source(source: BriefSource) -> None:
    _sources.append(source)

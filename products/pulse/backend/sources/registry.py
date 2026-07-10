from products.pulse.backend.sources.anchored_dashboards import AnchoredDashboardsSource
from products.pulse.backend.sources.anchored_insights import AnchoredInsightsSource
from products.pulse.backend.sources.base import BriefSource
from products.pulse.backend.sources.strategy import MovementScoringStrategy

# Both anchored sources share one scoring strategy: retrieval (which insights) differs, scoring
# is identical. Mutable registry so new sources can be registered (tests, future products)
# without editing the gather path. `get_sources` returns a copy so callers can't mutate in place.
_strategy = MovementScoringStrategy()
_sources: list[BriefSource] = [AnchoredInsightsSource(_strategy), AnchoredDashboardsSource(_strategy)]


def get_sources() -> list[BriefSource]:
    return list(_sources)


def register_source(source: BriefSource) -> None:
    _sources.append(source)

from products.pulse.backend.sources.anchored_insights import AnchoredInsightsSource
from products.pulse.backend.sources.annotations import AnnotationsSource
from products.pulse.backend.sources.base import BriefSource
from products.pulse.backend.sources.resource_health import ResourceHealthSource
from products.pulse.backend.sources.signal_reports import SignalReportsSource


def get_sources() -> list[BriefSource]:
    return [AnchoredInsightsSource(), AnnotationsSource(), ResourceHealthSource(), SignalReportsSource()]

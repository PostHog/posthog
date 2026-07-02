from products.pulse.backend.sources.anchored_insights import AnchoredInsightsSource
from products.pulse.backend.sources.annotations import AnnotationsSource
from products.pulse.backend.sources.base import BriefSource


def get_sources() -> list[BriefSource]:
    return [AnchoredInsightsSource(), AnnotationsSource()]

from products.pulse.backend.sources.anchored_insights import AnchoredInsightsSource
from products.pulse.backend.sources.annotations import AnnotationsSource
from products.pulse.backend.sources.registry import get_sources
from products.pulse.backend.sources.resource_health import ResourceHealthSource


def test_registry_returns_every_source() -> None:
    assert {type(source) for source in get_sources()} == {
        AnchoredInsightsSource,
        AnnotationsSource,
        ResourceHealthSource,
    }

import pytest

from products.pulse.backend.models import Opportunity
from products.signals.backend.models import SignalSourceConfig


@pytest.mark.parametrize("kind", Opportunity.Kind.values)
def test_every_opportunity_kind_has_a_registered_signal_source_type(kind: str) -> None:
    # Emit maps kind -> source_type via f"opportunity_{kind}"; an unregistered source_type makes
    # emit_signal reject the payload (logged skip), so a new Kind must register its SourceType.
    assert f"opportunity_{kind}" in SignalSourceConfig.SourceType.values

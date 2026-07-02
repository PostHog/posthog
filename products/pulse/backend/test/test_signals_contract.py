import pytest

from products.pulse.backend.models import Opportunity
from products.signals.backend.facade.api import SIGNAL_VARIANT_LOOKUP
from products.signals.backend.models import SignalSourceConfig


@pytest.mark.parametrize("kind", Opportunity.Kind.values)
def test_every_opportunity_kind_has_a_registered_signal_source_type(kind: str) -> None:
    # Emit maps kind -> source_type via f"opportunity_{kind}"; registration is two-sided: the
    # SourceType choice (per-team opt-in config) and the generated SignalInput schema variant
    # emit_signal validates against — a Kind missing from either is silently rejected at emit.
    assert f"opportunity_{kind}" in SignalSourceConfig.SourceType.values
    assert ("pulse", f"opportunity_{kind}") in SIGNAL_VARIANT_LOOKUP

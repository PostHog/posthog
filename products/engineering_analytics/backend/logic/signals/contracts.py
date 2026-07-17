"""Internal contract between the CI detectors and the emitter; the cross-boundary emit contract
is the ``SignalInput`` variant in ``products/signals/backend/contracts.py``."""

from dataclasses import dataclass, field

from products.signals.backend.contracts import SignalRemediation
from products.signals.backend.enums import SignalSourceProduct, SignalSourceType

# Taken straight from the signals taxonomy so the pair can't drift from emit-time validation.
SOURCE_PRODUCT = SignalSourceProduct.ENGINEERING_ANALYTICS.value
SOURCE_TYPE_FLAKY_CHECK = SignalSourceType.CI_FLAKY_CHECK.value
SOURCE_TYPE_BROKEN_DEFAULT_BRANCH = SignalSourceType.CI_BROKEN_DEFAULT_BRANCH.value
SOURCE_TYPE_DURATION_REGRESSION = SignalSourceType.CI_DURATION_REGRESSION.value


@dataclass(frozen=True)
class CISignalFinding:
    """One detected CI condition, ready to emit. ``source_id`` is the dedupe key: the coordinator
    skips findings already recorded in ``SignalEmissionRecord``."""

    source_type: str
    source_id: str
    description: str
    weight: float
    remediation: SignalRemediation
    extra: dict = field(default_factory=dict)

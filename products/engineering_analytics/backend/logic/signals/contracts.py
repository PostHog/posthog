"""Internal contract between the CI detectors and the emitter; the cross-boundary emit contract
is the ``SignalInput`` variant in ``products/signals/backend/contracts.py``."""

from dataclasses import dataclass, field

from products.signals.backend.contracts import SignalRemediation

# Mirrors the products/signals taxonomy; a typo here fails emit-time variant validation.
SOURCE_PRODUCT = "engineering_analytics"
SOURCE_TYPE_FLAKY_CHECK = "ci_flaky_check"
SOURCE_TYPE_BROKEN_DEFAULT_BRANCH = "ci_broken_default_branch"
SOURCE_TYPE_DURATION_REGRESSION = "ci_duration_regression"


@dataclass(frozen=True)
class CISignalFinding:
    """One detected CI condition, ready to emit. ``source_id`` names one immutable observation
    and doubles as the emit idempotency key."""

    source_type: str
    source_id: str
    description: str
    weight: float
    remediation: SignalRemediation
    extra: dict = field(default_factory=dict)

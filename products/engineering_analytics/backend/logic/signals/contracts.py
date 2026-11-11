from dataclasses import dataclass, field

from products.signals.backend.facade.taxonomy import SignalRemediation, SignalSourceProduct, SignalSourceType

# Read from the signals taxonomy, because emit-time validation checks against the same values.
SOURCE_PRODUCT = SignalSourceProduct.ENGINEERING_ANALYTICS.value
SOURCE_TYPE_FLAKY_CHECK = SignalSourceType.CI_FLAKY_CHECK.value
SOURCE_TYPE_BROKEN_DEFAULT_BRANCH = SignalSourceType.CI_BROKEN_DEFAULT_BRANCH.value
SOURCE_TYPE_DURATION_REGRESSION = SignalSourceType.CI_DURATION_REGRESSION.value


@dataclass(frozen=True)
class CISignalFinding:
    """``source_id`` is the dedupe key: the coordinator skips a finding whose
    ``(source_type, source_id)`` the emission ledger already holds."""

    source_type: str
    source_id: str
    description: str
    weight: float
    remediation: SignalRemediation
    extra: dict = field(default_factory=dict)

"""Internal contract between the CI detectors and the emitter.

A ``CISignalFinding`` is what a detector returns and the coordinator activity emits — everything
``emit_signal`` needs, including the ``SignalRemediation`` it forwards verbatim. These are
product-internal; the typed cross-boundary emit contract is the ``SignalInput`` variant in
``products/signals/backend/contracts.py``.
"""

from dataclasses import dataclass, field

from products.signals.backend.contracts import SignalRemediation

# The signal source taxonomy, mirrored from products/signals SignalSourceProduct/SignalSourceType.
# Kept as constants so a typo can't silently emit a signal that fails the emit-time variant
# validation.
SOURCE_PRODUCT = "engineering_analytics"
SOURCE_TYPE_FLAKY_CHECK = "ci_flaky_check"
SOURCE_TYPE_BROKEN_MASTER = "ci_broken_master"
SOURCE_TYPE_DURATION_REGRESSION = "ci_duration_regression"


@dataclass(frozen=True)
class CISignalFinding:
    """One detected CI condition, ready to emit.

    ``source_id`` is stable per (repo, workflow, condition) so re-emitting the same condition
    regroups onto the same report instead of spamming a new one. ``weight`` (0–1) is the signal's
    importance; ``remediation`` carries the human + agent fix guidance and the suggested priority.
    """

    source_type: str
    source_id: str
    description: str
    weight: float
    remediation: SignalRemediation
    extra: dict = field(default_factory=dict)

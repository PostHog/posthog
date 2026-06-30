"""Internal contract between the CI detectors and the emitter.

A ``CISignalFinding`` is what a detector returns and the activity emits — everything
``emit_signal`` needs, plus the remediation strings it wraps into a ``SignalRemediation``.
Remediation rides as plain strings (not a schema object) so detectors stay pure and easy to test
without constructing pydantic models. These are product-internal; the typed cross-boundary emit
contract is the ``SignalInput`` variant in ``schema-signals.ts`` (regenerated into ``posthog.schema``).
"""

from dataclasses import dataclass, field

# The signal source taxonomy, mirrored from products/signals SourceProduct/SourceType (and
# schema-signals.ts). Kept as constants so a typo can't silently emit a signal that fails the
# emit-time variant validation.
SOURCE_PRODUCT = "engineering_analytics"
SOURCE_TYPE_FLAKY_CHECK = "ci_flaky_check"
SOURCE_TYPE_BROKEN_MASTER = "ci_broken_master"
SOURCE_TYPE_DURATION_REGRESSION = "ci_duration_regression"


@dataclass(frozen=True)
class CISignalFinding:
    """One detected CI condition, ready to emit.

    ``source_id`` is stable per (repo, workflow, condition) so re-emitting the same condition
    regroups onto the same report instead of spamming a new one. ``weight`` (0–1) is the signal's
    importance; ``priority`` (P0–P4) is the suggested report priority the remediation carries.
    """

    source_type: str
    source_id: str
    description: str
    weight: float
    extra: dict = field(default_factory=dict)
    remediation_human: str = ""
    remediation_agent: str = ""
    priority: str = "P2"

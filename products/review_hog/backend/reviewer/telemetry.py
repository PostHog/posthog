"""The model and effort labels every ReviewHog analytics event carries."""

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.reviewer.constants import (
    RESOLUTION_MODEL,
    RESOLUTION_REASONING_EFFORT,
    VALIDATION_MODEL,
    VALIDATION_REASONING_EFFORT,
    resolve_review_arm,
)


def review_routing_properties(report: ReviewReport) -> dict[str, str | bool | None]:
    """The tier, the reviewer arm, and the fixed validator and resolver pins of a report's reviews.

    Every review event (started, completed, failed, finding outcome) spreads this in, so a dashboard
    can split any of them by what actually ran. The reviewer arm is resolved, not raw: pre-arm rows
    carry NULLs but their reviews run on the default pins, and the event must say what ran. The tier
    and priority are raw: they are the decision as recorded, and NULL means the row predates tiers.
    The values are the row's as of the call: a per-turn event reads them at that point of the turn,
    and the finding-outcome event reads the report's arm when the outcome is classified, not the
    arm of the turn that produced the finding. The validator and resolver are module pins, not per
    report; they are included so one event names every model a turn spent on.
    """
    persisted = (
        report.review_runtime_adapter,
        report.review_model,
        report.review_reasoning_effort,
        report.review_initial_permission_mode,
    )
    arm = resolve_review_arm(*persisted)
    resolved = (arm.runtime_adapter.value, arm.model, arm.reasoning_effort.value, arm.initial_permission_mode)
    return {
        "review_tier": report.review_tier,
        "signal_priority": report.review_signal_priority,
        "signal_report_id": str(report.signal_report_id) if report.signal_report_id else None,
        "review_runtime_adapter": arm.runtime_adapter.value,
        "review_model": arm.model,
        "review_reasoning_effort": arm.reasoning_effort.value,
        # True when a persisted assignment failed resolution and the turn ran the fallback pins
        # instead of its tier's arm; per-tier dashboards must exclude these contaminated turns.
        # The whole bundle is compared because a failed assignment can share the default arm's model
        # string while differing on adapter or effort. Pre-arm rows (all NULL) stay False.
        "review_arm_fallback": any(persisted) and resolved != persisted,
        "validator_model": VALIDATION_MODEL,
        "validator_reasoning_effort": VALIDATION_REASONING_EFFORT.value if VALIDATION_REASONING_EFFORT else None,
        "resolution_model": RESOLUTION_MODEL,
        "resolution_reasoning_effort": RESOLUTION_REASONING_EFFORT.value if RESOLUTION_REASONING_EFFORT else None,
    }

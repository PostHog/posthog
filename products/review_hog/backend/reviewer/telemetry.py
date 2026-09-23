"""The model and effort labels every ReviewHog analytics event carries."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ValidationError

from products.review_hog.backend.reviewer.constants import (
    RESOLUTION_MODEL,
    RESOLUTION_REASONING_EFFORT,
    REVIEW_MODE_FLASH,
    REVIEW_MODE_FULL,
    ReviewArm,
    resolve_review_arm,
    review_arm_for_mode,
    validation_arm_for_mode,
)
from products.tasks.backend.facade.run_config import ReasoningEffort

if TYPE_CHECKING:
    from products.review_hog.backend.models import ReviewReport
    from products.review_hog.backend.reviewer.artefact_content import ReviewIssueFinding


class _FindingModelContext(BaseModel):
    review_mode: Literal["full", "flash"]
    review_arm: ReviewArm
    validation_arm: ReviewArm


def review_event_uuid(event_name: str, *, report_id: str, run_index: int, review_mode: str) -> str:
    """Preserve legacy Full event IDs while separating retry histories by review mode."""
    identity = f"{event_name}:{report_id}:{run_index}"
    if review_mode != REVIEW_MODE_FULL:
        identity = f"{identity}:{review_mode}"
    return str(uuid5(NAMESPACE_URL, identity))


def review_routing_properties(
    report: ReviewReport,
    *,
    review_mode: str | None = None,
    flash_reasoning_effort: str = ReasoningEffort.MEDIUM.value,
) -> dict[str, str | bool | None]:
    """The tier, the reviewer arm, and the validator and resolver pins of a report's reviews.

    Every review event (started, completed, failed, finding outcome) spreads this in, so a dashboard
    can split any of them by what actually ran. The reviewer arm is resolved, not raw: pre-arm rows
    carry NULLs but their reviews run on the default pins, and the event must say what ran. The tier
    and priority are raw: they are the decision as recorded, and NULL means the row predates tiers.
    The values are the row's as of the call: a per-turn event reads them at that point of the turn,
    and Full finding outcomes read the report's arm when the outcome is classified. `review_mode`
    is the turn's, and the per-turn events pass it so a flash turn names the flash arm in both seats.
    Flash finding outcomes override these pins with their saved configuration in
    `finding_routing_properties`. The resolver is a module pin, not per report; it is included so
    one event names every model a turn spent on.
    """
    persisted = (
        report.review_runtime_adapter,
        report.review_model,
        report.review_reasoning_effort,
        report.review_initial_permission_mode,
    )
    stored_arm = resolve_review_arm(*persisted)
    resolved = (
        stored_arm.runtime_adapter.value,
        stored_arm.model,
        stored_arm.reasoning_effort.value,
        stored_arm.initial_permission_mode,
    )
    mode = review_mode if review_mode is not None else REVIEW_MODE_FULL
    arm = review_arm_for_mode(mode, stored_arm, flash_reasoning_effort=flash_reasoning_effort)
    validator = validation_arm_for_mode(mode, flash_reasoning_effort=flash_reasoning_effort)
    return {
        "review_mode": review_mode,
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
        "review_arm_fallback": mode != REVIEW_MODE_FLASH and any(persisted) and resolved != persisted,
        "validator_model": validator.model,
        "validator_reasoning_effort": validator.reasoning_effort.value,
        "resolution_model": RESOLUTION_MODEL,
        "resolution_reasoning_effort": RESOLUTION_REASONING_EFFORT.value if RESOLUTION_REASONING_EFFORT else None,
    }


def finding_routing_properties(report: ReviewReport, finding: ReviewIssueFinding) -> dict[str, str | bool | None]:
    """Flash does not change the report's arm, so its outcomes need the finding's saved model pins.

    Full outcomes keep the report-level arm semantics. Findings without a readable context retain
    the legacy labels and an unknown mode; an absent snapshot cannot establish that Flash ran.
    """
    context = None
    if finding.validation_context is not None:
        try:
            context = _FindingModelContext.model_validate_json(finding.validation_context)
        except ValidationError:
            pass
    properties = review_routing_properties(report, review_mode=context.review_mode if context else None)
    if context is not None and context.review_mode == REVIEW_MODE_FLASH:
        properties.update(
            review_runtime_adapter=context.review_arm.runtime_adapter.value,
            review_model=context.review_arm.model,
            review_reasoning_effort=context.review_arm.reasoning_effort.value,
            validator_model=context.validation_arm.model,
            validator_reasoning_effort=context.validation_arm.reasoning_effort.value,
        )
    return properties

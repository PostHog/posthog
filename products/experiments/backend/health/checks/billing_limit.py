"""
A running experiment in an organization that reached its billing limit for product analytics. Pure functions, no I/O.

Capture drops the project's product analytics events while the limit holds, the flag calls included, so an experiment
that counts them counts nobody new. The limit stores no start time, so the finding names only the limit in force now.
"""

from datetime import UTC

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
    ExperimentHealthValueKey,
)
from products.experiments.backend.health.context import ExposureEvents, HealthContext
from products.experiments.backend.health.skips import (
    NOT_AFTER_END,
    RUNS_AFTER_LAUNCH,
    CheckOutcome,
    CheckValues,
    not_applicable,
    not_checked,
)
from products.experiments.backend.health.split_changes import format_change_time

# Kept in sync with the scoped limiters of capture: `is_exception_event`, `is_survey_event` and `is_llm_event` in
# rust/capture/src/quota_limiters.rs, registered in rust/capture/src/setup.rs. Capture keeps these events under limits of
# their own, so the product analytics limit doesn't drop them. Update both.
_EXCEPTION_EVENT = "$exception"
# Capture limits a survey event with `$product_tour_id` as a product analytics event. The exposure criteria can't tell
# the two apart, so a product tour's survey event reads as having its own limit.
_SURVEY_EVENTS = frozenset({"survey sent", "survey shown", "survey dismissed"})
_LLM_EVENT_PREFIX = "$ai_"


def _exposure_event_with_own_limit(events: ExposureEvents | None) -> str | None:
    # An action's steps aren't read, so an action counts as product analytics events.
    event = events.custom_event if events is not None else None
    if event is None:
        return None
    if event == _EXCEPTION_EVENT or event in _SURVEY_EVENTS or event.startswith(_LLM_EVENT_PREFIX):
        return event
    return None


def billing_limit_drops_exposures(ctx: HealthContext) -> bool:
    """Whether the billing limit check reports a limit that also drops the events the experiment counts as exposures."""
    return isinstance(billing_limit(ctx), ExperimentHealthFinding) and (
        _exposure_event_with_own_limit(ctx.exposure_events) is None
    )


def billing_limit_values(ctx: HealthContext) -> CheckValues:
    limit = ctx.events_billing_limit
    if limit is None:
        return {}
    if limit.ends_at is None:
        return {ExperimentHealthValueKey.BILLING_LIMIT_REACHED: False}
    return {
        ExperimentHealthValueKey.BILLING_LIMIT_REACHED: True,
        ExperimentHealthValueKey.BILLING_LIMIT_ENDS_AT: limit.ends_at.astimezone(UTC).isoformat(),
    }


def billing_limit(ctx: HealthContext) -> CheckOutcome:
    exposures = ctx.exposures
    if exposures is None or not ctx.is_launched:
        return not_applicable(RUNS_AFTER_LAUNCH)
    # A limit in force now says nothing about the run before the end.
    if ctx.has_ended:
        return not_applicable(NOT_AFTER_END)
    limit = ctx.events_billing_limit
    if limit is None:
        return not_checked("Couldn't check because the billing limit couldn't be read")
    if limit.ends_at is None:
        return None
    unit = exposures.unit
    ends_at = format_change_time(limit.ends_at, ctx.team_timezone)
    own_limit_event = _exposure_event_with_own_limit(ctx.exposure_events)
    if own_limit_event is None:
        effect = f"Until then, the experiment counts no new {unit}s, and metrics on these events get no new data."
    else:
        effect = (
            f'The exposure event "{own_limit_event}" has a limit of its own, so this limit doesn\'t stop the experiment '
            f"from counting exposed {unit}s, but metrics on product analytics events get no new data until then."
        )
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.BILLING_LIMIT,
        subcode=None,
        severity=ExperimentHealthFindingSeverity.WARNING,
        title="Events are dropped: the product analytics limit is reached",
        detail=(
            "Your organization reached its billing limit or free tier limit for product analytics, so PostHog drops "
            f"the product analytics events this project sends until {ends_at}. {effect} To count events sooner, raise "
            "the limit or subscribe on the billing page. PostHog doesn't keep the events it drops, so they can't be "
            "counted later."
        ),
        evidence={"billing_limit_ends_at": limit.ends_at.astimezone(UTC).isoformat()},
        actions=(),
        diagnostic_ref=None,
    )

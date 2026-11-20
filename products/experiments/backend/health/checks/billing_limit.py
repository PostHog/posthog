"""
A running experiment in an organization that reached a billing limit the experiment depends on. Pure functions, no I/O.

Capture drops the project's product analytics events while the events limit holds, the flag calls included, so an
experiment that counts them counts nobody new. The flags service returns no flags while the feature flags limit holds,
so a client without stored flags gets no variant. The limits store no start time, so a finding names only a limit in
force now.
"""

from collections.abc import Callable
from datetime import UTC, datetime

from posthog.dataclasses import frozen

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
    ExperimentHealthValueKey,
)
from products.experiments.backend.health.context import BillingLimits, ExposureEvents, HealthContext
from products.experiments.backend.health.skips import (
    NOT_AFTER_END,
    RUNS_AFTER_LAUNCH,
    CheckOutcome,
    CheckSkip,
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

_LimitEnd = Callable[[BillingLimits], datetime | None]


def _events_ends_at(limits: BillingLimits) -> datetime | None:
    return limits.events_ends_at


def _feature_flags_ends_at(limits: BillingLimits) -> datetime | None:
    return limits.feature_flags_ends_at


@frozen
class _LimitInForce:
    ends_at: datetime
    unit: str


def _limit_in_force(ctx: HealthContext, limit_end: _LimitEnd) -> _LimitInForce | CheckSkip | None:
    exposures = ctx.exposures
    if exposures is None or not ctx.is_launched:
        return not_applicable(RUNS_AFTER_LAUNCH)
    # A limit in force now says nothing about the run before the end.
    if ctx.has_ended:
        return not_applicable(NOT_AFTER_END)
    limits = ctx.billing_limits
    if limits is None:
        return not_checked("Couldn't check because the billing limits couldn't be read")
    ends_at = limit_end(limits)
    return None if ends_at is None else _LimitInForce(ends_at=ends_at, unit=exposures.unit)


def _limit_values(
    ctx: HealthContext,
    limit_end: _LimitEnd,
    reached_key: ExperimentHealthValueKey,
    ends_at_key: ExperimentHealthValueKey,
) -> CheckValues:
    limits = ctx.billing_limits
    if limits is None:
        return {}
    ends_at = limit_end(limits)
    if ends_at is None:
        return {reached_key: False}
    return {reached_key: True, ends_at_key: ends_at.astimezone(UTC).isoformat()}


def _limit_finding(
    limit: _LimitInForce,
    *,
    code: ExperimentHealthFindingCode,
    ends_at_key: ExperimentHealthValueKey,
    title: str,
    detail: str,
) -> ExperimentHealthFinding:
    return ExperimentHealthFinding(
        code=code,
        subcode=None,
        severity=ExperimentHealthFindingSeverity.WARNING,
        title=title,
        detail=detail,
        evidence={ends_at_key.value: limit.ends_at.astimezone(UTC).isoformat()},
        actions=(),
        diagnostic_ref=None,
    )


def _exposure_event_with_own_limit(events: ExposureEvents | None) -> str | None:
    # An action's steps aren't read, so an action counts as product analytics events.
    event = events.custom_event if events is not None else None
    if event is None:
        return None
    if event == _EXCEPTION_EVENT or event in _SURVEY_EVENTS or event.startswith(_LLM_EVENT_PREFIX):
        return event
    return None


def events_billing_limit_drops_exposures(ctx: HealthContext) -> bool:
    """Whether the events billing limit check reports a limit that also drops the events counted as exposures."""
    return isinstance(events_billing_limit(ctx), ExperimentHealthFinding) and (
        _exposure_event_with_own_limit(ctx.exposure_events) is None
    )


def feature_flags_billing_limit_holds(ctx: HealthContext) -> bool:
    return isinstance(feature_flags_billing_limit(ctx), ExperimentHealthFinding)


def events_billing_limit_values(ctx: HealthContext) -> CheckValues:
    return _limit_values(
        ctx,
        _events_ends_at,
        ExperimentHealthValueKey.EVENTS_BILLING_LIMIT_REACHED,
        ExperimentHealthValueKey.EVENTS_BILLING_LIMIT_ENDS_AT,
    )


def feature_flags_billing_limit_values(ctx: HealthContext) -> CheckValues:
    return _limit_values(
        ctx,
        _feature_flags_ends_at,
        ExperimentHealthValueKey.FEATURE_FLAGS_BILLING_LIMIT_REACHED,
        ExperimentHealthValueKey.FEATURE_FLAGS_BILLING_LIMIT_ENDS_AT,
    )


def events_billing_limit(ctx: HealthContext) -> CheckOutcome:
    limit = _limit_in_force(ctx, _events_ends_at)
    if not isinstance(limit, _LimitInForce):
        return limit
    unit, until = limit.unit, format_change_time(limit.ends_at, ctx.team_timezone)
    own_limit_event = _exposure_event_with_own_limit(ctx.exposure_events)
    if own_limit_event is None:
        effect = f"Until then, the experiment counts no new {unit}s, and metrics on these events get no new data."
    else:
        effect = (
            f'The exposure event "{own_limit_event}" has a limit of its own, so this limit doesn\'t stop the experiment '
            f"from counting exposed {unit}s, but metrics on product analytics events get no new data until then."
        )
    return _limit_finding(
        limit,
        code=ExperimentHealthFindingCode.EVENTS_BILLING_LIMIT,
        ends_at_key=ExperimentHealthValueKey.EVENTS_BILLING_LIMIT_ENDS_AT,
        title="Events are dropped: the product analytics limit is reached",
        detail=(
            "Your organization reached its billing limit or free tier limit for product analytics, so PostHog drops "
            f"the product analytics events this project sends until {until}. {effect} To count events sooner, raise "
            "the limit or subscribe on the billing page. PostHog doesn't keep the events it drops, so they can't be "
            "counted later."
        ),
    )


def feature_flags_billing_limit(ctx: HealthContext) -> CheckOutcome:
    limit = _limit_in_force(ctx, _feature_flags_ends_at)
    if not isinstance(limit, _LimitInForce):
        return limit
    unit, until = limit.unit, format_change_time(limit.ends_at, ctx.team_timezone)
    return _limit_finding(
        limit,
        code=ExperimentHealthFindingCode.FEATURE_FLAGS_BILLING_LIMIT,
        ends_at_key=ExperimentHealthValueKey.FEATURE_FLAGS_BILLING_LIMIT_ENDS_AT,
        title="Flags aren't served: the feature flags limit is reached",
        detail=(
            "Your organization reached its billing limit or free tier limit for feature flags, so PostHog returns no "
            f"flags to this project's flag requests until {until}. Until then, only clients that stored their flags "
            f"earlier, such as browsers, keep their variant, so the experiment counts new {unit}s only from those "
            f"clients. Other {unit}s can get no variant and see what the code shows without the flag. That includes "
            f"{unit}s the experiment already counted, which mixes the results. To serve flags sooner, raise the limit "
            "or subscribe on the billing page."
        ),
    )

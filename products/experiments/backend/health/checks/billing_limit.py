"""
A running experiment in an organization that reached its billing limit for product analytics. Pure functions, no I/O.

Capture drops the project's product analytics events while the limit holds, the exposures and the flag calls included,
so the experiment counts nobody new. The limit stores no start time, so the finding names only the limit in force now.
"""

from datetime import UTC

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
    ExperimentHealthValueKey,
)
from products.experiments.backend.health.context import HealthContext
from products.experiments.backend.health.skips import (
    NOT_AFTER_END,
    RUNS_AFTER_LAUNCH,
    CheckOutcome,
    CheckValues,
    not_applicable,
    not_checked,
)
from products.experiments.backend.health.split_changes import format_change_time


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
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.BILLING_LIMIT,
        subcode=None,
        severity=ExperimentHealthFindingSeverity.WARNING,
        title="Events are dropped: the product analytics limit is reached",
        detail=(
            "Your organization reached its billing limit or free tier limit for product analytics, so PostHog drops "
            f"the product analytics events this project sends until {ends_at}. "
            f"Until then, the experiment counts no new {unit}s, and metrics on these events get no new data. Every "
            "variant loses events alike, so the results aren't biased. To count events sooner, raise the limit or "
            "subscribe on the billing page. PostHog doesn't keep the events it drops, so they can't be counted later."
        ),
        evidence={"limit_ends_at": limit.ends_at.astimezone(UTC).isoformat()},
        actions=(),
        diagnostic_ref=None,
    )

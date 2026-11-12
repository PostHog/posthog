"""
An experiment that runs past the daily calculation. Pure functions, no I/O.

The finding says what stopped and not that the results are old, because a page load can still refresh them.
"""

from datetime import UTC

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
    ExperimentHealthValueKey,
)
from products.experiments.backend.facade.daily_calculation import DAILY_CALCULATION_DAYS
from products.experiments.backend.health.context import HealthContext
from products.experiments.backend.health.skips import (
    NOT_AFTER_END,
    NOT_ON_ARCHIVED,
    RUNS_AFTER_LAUNCH,
    CheckOutcome,
    CheckValues,
    not_applicable,
)


def stale_experiment_values(ctx: HealthContext) -> CheckValues:
    if ctx.archived or ctx.has_ended or not ctx.is_launched or ctx.hours_since_start is None:
        return {}
    ends_at = ctx.daily_calculation_ends_at
    return {
        ExperimentHealthValueKey.SINCE_START_HOURS: round(ctx.hours_since_start, 1),
        ExperimentHealthValueKey.DAILY_CALCULATION_ENDS_AT: None
        if ends_at is None
        else ends_at.astimezone(UTC).isoformat(),
    }


def stale_experiment(ctx: HealthContext) -> CheckOutcome:
    if ctx.archived:
        return not_applicable(NOT_ON_ARCHIVED)
    if ctx.has_ended:
        return not_applicable(NOT_AFTER_END)
    if not ctx.is_launched:
        return not_applicable(RUNS_AFTER_LAUNCH)
    if not ctx.past_daily_calculation or ctx.hours_since_start is None:
        return None
    days_running = int(ctx.hours_since_start // 24)
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.STALE_EXPERIMENT,
        subcode=None,
        severity=ExperimentHealthFindingSeverity.INFO,
        title=f"This experiment has been running for {days_running} days",
        detail=" ".join(
            (
                f"PostHog's daily calculation covers only the first {DAILY_CALCULATION_DAYS} days after the start "
                "date.",
                "After that, the chart of results over time stops updating, and PostHog sends no significance "
                "notifications.",
                "If you have your answer, end the experiment. Users and events after the end date don't count in the "
                "results.",
                *(
                    (
                        "If you're measuring long-term effects, freeze exposure instead: no new users enter, and the "
                        "events of the users already in it keep counting.",
                    )
                    if ctx.can_freeze_exposure
                    else ()
                ),
            )
        ),
        evidence={"days_running": days_running},
        actions=(
            ExperimentHealthFindingActionKind.END_EXPERIMENT,
            *((ExperimentHealthFindingActionKind.FREEZE_EXPOSURE,) if ctx.can_freeze_exposure else ()),
        ),
        diagnostic_ref=None,
    )

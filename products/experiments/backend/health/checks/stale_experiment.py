"""
An experiment that runs past the daily calculation. Pure functions, no I/O.

A reader's page load still refreshes the results, so the finding doesn't say that they are old. It says what stopped.
"""

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.context import HealthContext
from products.experiments.backend.health.delays import DAILY_CALCULATION_DAYS
from products.experiments.backend.health.skips import (
    NOT_AFTER_END,
    NOT_ON_ARCHIVED,
    RUNS_AFTER_LAUNCH,
    CheckOutcome,
    not_applicable,
)


def is_stale(ctx: HealthContext) -> bool:
    return (
        ctx.is_launched
        and not ctx.has_ended
        and not ctx.archived
        and ctx.hours_since_launch is not None
        and ctx.hours_since_launch > DAILY_CALCULATION_DAYS * 24
    )


def stale_experiment(ctx: HealthContext) -> CheckOutcome:
    if ctx.archived:
        return not_applicable(NOT_ON_ARCHIVED)
    if ctx.has_ended:
        return not_applicable(NOT_AFTER_END)
    if not ctx.is_launched:
        return not_applicable(RUNS_AFTER_LAUNCH)
    if not is_stale(ctx) or ctx.hours_since_launch is None:
        return None
    days_running = int(ctx.hours_since_launch // 24)
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.STALE_EXPERIMENT,
        subcode=None,
        severity=ExperimentHealthFindingSeverity.INFO,
        title=f"This experiment has been running for {days_running} days",
        detail=" ".join(
            (
                f"PostHog calculates an experiment's results every day for its first {DAILY_CALCULATION_DAYS} days.",
                "After that, the chart of results over time and significance notifications stop updating.",
                "The results still update when someone opens this page.",
                "If you have your answer, end the experiment, and the results count users up to the end date.",
                *(
                    (
                        "If you're measuring long-term effects, freeze exposure instead: no new users enter, and the "
                        "metrics of the users already in it keep updating.",
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

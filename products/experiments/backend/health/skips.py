from typing import Literal

from posthog.dataclasses import frozen

from products.experiments.backend.facade.contracts import ExperimentHealthCheckStatus, ExperimentHealthFinding
from products.experiments.backend.health.context import FlagState, HealthContext


@frozen
class CheckSkip:
    status: Literal[ExperimentHealthCheckStatus.NOT_APPLICABLE, ExperimentHealthCheckStatus.NOT_CHECKED]
    reason: str


# What a check returns: a finding, why the check doesn't look, or None when it looks and finds no problem.
CheckOutcome = ExperimentHealthFinding | CheckSkip | None

RUNS_AFTER_LAUNCH = "Runs after launch"
RUNS_BEFORE_LAUNCH = "Runs only before launch"
NOT_AFTER_END = "Doesn't run after the experiment ends"
NOT_ON_ARCHIVED = "Doesn't run on archived experiments"
NO_FLAG = "The experiment has no feature flag"
FLAG_DELETED = "The feature flag is deleted"
NEEDS_VARIANTS = "Runs once the feature flag has variants"


def not_applicable(reason: str) -> CheckSkip:
    return CheckSkip(status=ExperimentHealthCheckStatus.NOT_APPLICABLE, reason=reason)


def not_checked(reason: str) -> CheckSkip:
    return CheckSkip(status=ExperimentHealthCheckStatus.NOT_CHECKED, reason=reason)


def no_calculated_metric(ctx: HealthContext) -> CheckSkip:
    """Why a check of the metrics that the experiment calculates doesn't look when it calculates none."""
    # The calculation leaves out a metric in the legacy format, which the no-metric check counts.
    if ctx.primary_metric_count + ctx.secondary_metric_count:
        return not_applicable("Runs once the experiment has a metric in the current format")
    return not_applicable("Runs once the experiment has a metric")


def flag_to_check(ctx: HealthContext, *, before_launch: bool) -> FlagState | CheckSkip:
    """The flag that a check of the flag's setup reads, or why the check doesn't look. After the end the flag often
    holds the shipped decision, not the setup of the run, so these checks stop there."""
    flag = ctx.flag
    if ctx.archived:
        return not_applicable(NOT_ON_ARCHIVED)
    if flag is None:
        return not_applicable(NO_FLAG)
    if flag.deleted:
        return not_applicable(FLAG_DELETED)
    if ctx.has_ended:
        return not_applicable(NOT_AFTER_END)
    if not before_launch and not ctx.is_launched:
        return not_applicable(RUNS_AFTER_LAUNCH)
    return flag

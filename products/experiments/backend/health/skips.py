from typing import Literal

from posthog.dataclasses import frozen

from products.experiments.backend.facade.contracts import ExperimentHealthCheckStatus
from products.experiments.backend.health.context import HealthContext


@frozen
class CheckSkip:
    status: Literal[ExperimentHealthCheckStatus.NOT_APPLICABLE, ExperimentHealthCheckStatus.NOT_CHECKED]
    reason: str


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


def flag_setup_skip(ctx: HealthContext, *, before_launch: bool) -> CheckSkip | None:
    """The skip of a check of the flag's setup. After the end the flag often holds the shipped decision, not the
    setup of the run, so these checks stop there."""
    if ctx.archived:
        return not_applicable(NOT_ON_ARCHIVED)
    if ctx.flag is None:
        return not_applicable(NO_FLAG)
    if ctx.flag.deleted:
        return not_applicable(FLAG_DELETED)
    if ctx.has_ended:
        return not_applicable(NOT_AFTER_END)
    if not before_launch and not ctx.is_launched:
        return not_applicable(RUNS_AFTER_LAUNCH)
    return None

from collections.abc import Mapping
from typing import Literal

from posthog.dataclasses import frozen

from products.experiments.backend.facade.contracts import (
    ExperimentHealthCheckStatus,
    ExperimentHealthFinding,
    ExperimentHealthValue,
    ExperimentHealthValueKey,
)
from products.experiments.backend.health.context import FlagState, HealthContext
from products.experiments.backend.hogql_queries import MULTIPLE_VARIANT_KEY


@frozen
class CheckSkip:
    status: Literal[ExperimentHealthCheckStatus.NOT_APPLICABLE, ExperimentHealthCheckStatus.NOT_CHECKED]
    reason: str


# What a check returns: a finding, why the check doesn't look, or None for a pass.
CheckOutcome = ExperimentHealthFinding | CheckSkip | None
# What a check read on the experiment, for every status.
CheckValues = Mapping[ExperimentHealthValueKey, ExperimentHealthValue]
# What a check read per variant, metric or flag change, one mapping each.
CheckRows = tuple[CheckValues, ...]

RUNS_AFTER_LAUNCH = "Runs after launch"
RUNS_BEFORE_LAUNCH = "Runs only before launch"
NOT_AFTER_END = "Doesn't run after the experiment ends"
NOT_ON_ARCHIVED = "Doesn't run on archived experiments"
NO_FLAG = "The experiment has no feature flag"
FLAG_DELETED = "The feature flag is deleted"
NEEDS_VARIANTS = "Runs once the feature flag has variants"
NEEDS_SPLIT_VARIANTS = "Needs two or more variants in the split"
SPLIT_NOW_ONE_VARIANT = "The split now serves one variant, so the split of the run isn't tested"
REPORTED_BY_FLAG_STATE = "A variant has 100% of the split, which the flag state check reports"
SPLIT_ASSIGNS_NOBODY = "The split assigns nobody, because every release condition sets a variant override"
SPLIT_CHANGED_AFTER_END = "The variant split changed after the experiment ended, so it can't be compared with the run"
NEEDS_EXPOSURES = "Runs once enough users are exposed"
NEEDS_PRIMARY_METRIC = "Runs once the experiment has a primary metric"
NOT_ON_FLAG_RULE = "Not supported yet for experiments on a feature flag rule"


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


def fewer_than_two_in_split(total_exposures: Mapping[str, int]) -> CheckSkip:
    """Why a check that compares the variants of the split doesn't look when the split serves fewer than two. When the
    run exposed two or more, a variant got the whole split after launch, so the run's split goes untested. The exposure
    query lists every variant of the flag, so a variant counts as exposed only with a count above zero."""
    exposed = [key for key, count in total_exposures.items() if key != MULTIPLE_VARIANT_KEY and count > 0]
    return not_applicable(SPLIT_NOW_ONE_VARIANT if len(exposed) > 1 else NEEDS_SPLIT_VARIANTS)


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

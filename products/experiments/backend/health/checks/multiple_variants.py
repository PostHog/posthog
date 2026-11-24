from datetime import UTC

from posthog.schema import MultipleVariantHandling

from products.experiments.backend.facade.contracts import (
    ExperimentHealthCheckKey,
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.checks.bias_risk import bias_risk_multiple_excluded, multiple_variant_values
from products.experiments.backend.health.checks.change_wording import suggested_start_at
from products.experiments.backend.health.context import HealthContext
from products.experiments.backend.health.skips import (
    RUNS_AFTER_LAUNCH,
    CheckOutcome,
    CheckValues,
    not_applicable,
    not_checked,
)
from products.experiments.backend.health.split_changes import format_change_time
from products.experiments.backend.health.variant_moves import MultipleVariantCause, multiple_variant_cause
from products.experiments.backend.hogql_queries import MULTIPLE_VARIANT_KEY

# Some users get more than one ID in any experiment, for example one per device, so a low share is expected.
# The share grows as users return and log in, so a lower line fires on a large part of all experiments. The cases
# that users report sit above this line.
MULTIPLE_VARIANTS_SHARE_THRESHOLD = 5.0  # on the 0-100 scale (5.0 = 5%)
# The floor counts users or groups, not exposures: each of them is a fact, so the finding can fire on a new
# experiment. The floor stops one or two testers who switch between variants from firing it.
MULTIPLE_VARIANTS_MINIMUM_COUNT = 5


def reads_flag_changes(ctx: HealthContext) -> bool:
    """Whether this check or the bias check reports a finding that a flag change can explain. The exposure query then
    loads the flag's changes, because their load reads the flag's activity log."""
    return any(
        isinstance(check(ctx), ExperimentHealthFinding)
        for check in (multiple_variants_share, bias_risk_multiple_excluded)
    )


def multiple_variants_values(ctx: HealthContext) -> CheckValues:
    return multiple_variant_values(ctx.exposures) if ctx.exposures else {}


def multiple_variants_share(ctx: HealthContext) -> CheckOutcome:
    exposures = ctx.exposures
    if exposures is None:
        return not_applicable(RUNS_AFTER_LAUNCH)
    # Under "First seen" the exposure query gives each user their first variant, so it counts none of these users.
    if exposures.multiple_variant_handling != MultipleVariantHandling.EXCLUDE:
        return not_checked("Couldn't check because the First seen handling doesn't count these users")
    multiple = exposures.total_exposures.get(MULTIPLE_VARIANT_KEY, 0)
    total = exposures.total
    if multiple < MULTIPLE_VARIANTS_MINIMUM_COUNT:
        return None
    percentage = multiple / total * 100
    if percentage <= MULTIPLE_VARIANTS_SHARE_THRESHOLD:
        return None
    cause = multiple_variant_cause(ctx, threshold=MULTIPLE_VARIANTS_SHARE_THRESHOLD)
    unit = exposures.unit
    left_out = (
        f"{percentage:.1f}% of {unit}s ({multiple}) were exposed to multiple variants, so the results leave them out. "
        "The exposures table lists them as $multiple."
    )
    group_switch = (
        "when a person switches to another group and your code reads the flag before the flags reload: the event then "
        "carries the new group with the variant of the old group."
    )
    several_ids = (
        "one person has more than one ID: an anonymous ID before login and another after, an ID for each device, a new "
        "ID after reset(), or a different ID on your server than in the browser"
    )
    identify = (
        "Identify users before your code evaluates the flag, call reset() only at logout, and send the same ID from "
        "your server."
    )
    # The flag gives every member of a group the same variant, so the causes of a person's several IDs do not apply.
    if exposures.counts_groups and cause is not None:
        paragraphs = [
            left_out,
            _changed(cause, unit),
            f"It also happens {group_switch} After a group switch, read the flag only once the flags reload.",
        ]
    elif exposures.counts_groups:
        paragraphs = [
            left_out,
            "The flag gives every member of a group the same variant, so this usually means that the flag changed "
            "after launch, for example with a new variant split or a change from matching users to matching groups. "
            f"It also happens {group_switch}",
            "Check the flag's history, and after a group switch, read the flag only once the flags reload.",
        ]
    else:
        biased = (
            f"{left_out} If a variant changes how often users log in, each variant loses a different group of users, "
            "and the results can be biased."
        )
        paragraphs = (
            [
                biased,
                _changed(cause, unit),
                f"If the share grows again among users exposed later, {several_ids}. {identify}",
            ]
            if cause is not None
            else [
                biased,
                f"This usually means that {several_ids}. It also happens when a bootstrapped flag value differs "
                "from the value PostHog evaluates, or when the flag changes after launch, for example with a new "
                "variant split.",
                identify,
            ]
        )
    start_at = suggested_start_at(cause.move.changed_at) if cause is not None else None
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.MULTIPLE_VARIANTS_SHARE,
        subcode=None,
        severity=ExperimentHealthFindingSeverity.WARNING,
        title=f"{percentage:.1f}% of {unit}s were exposed to more than one variant, so the results leave them out",
        detail="\n\n".join(paragraphs),
        evidence={
            "multiple_variant_percentage": percentage,
            "multiple_variant_count": multiple,
            **(
                {
                    "flag_changed_at": cause.move.changed_at.astimezone(UTC).isoformat(),
                    "multiple_variant_count_before_change": cause.multiple_before,
                    "multiple_variant_percentage_after_change": cause.share_after,
                    # pinned: the start date that MOVE_START_DATE sets, in UTC.
                    "suggested_start_date": start_at.astimezone(UTC).isoformat(),
                }
                if cause is not None and start_at is not None
                else {}
            ),
        },
        # Nothing in PostHog fixes several IDs per person. Moving the start date past a flag change that explains the
        # share leaves out the users that the change moved.
        actions=(ExperimentHealthFindingActionKind.MOVE_START_DATE,) if cause is not None else (),
        diagnostic_ref="A3",
        caused_by=cause.move.check if cause is not None else None,
    )


_CHANGED = {
    ExperimentHealthCheckKey.SPLIT_CHANGED_MID_RUN: "the variant split changed",
    ExperimentHealthCheckKey.RELEASE_CONDITIONS_CHANGED_MID_RUN: "the release conditions changed",
    ExperimentHealthCheckKey.BUCKETING_CHANGED_MID_RUN: "the flag's variant assignment changed",
}


def _changed(cause: MultipleVariantCause, unit: str) -> str:
    move = cause.move
    at = format_change_time(move.changed_at, move.team_timezone)
    start = format_change_time(suggested_start_at(move.changed_at), move.team_timezone)
    return (
        f"At least {cause.multiple_before:,} of them were first exposed before {_CHANGED[move.check]} on {at}, and "
        f"that change can give {unit}s who were already exposed another variant. Among the {unit}s first exposed "
        f"after the day of the change, {cause.share_after:.1f}% were exposed to multiple variants. Move the start "
        f"date to {start} so the results count only exposures after the change."
    )

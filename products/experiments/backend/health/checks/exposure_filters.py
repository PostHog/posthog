"""
Cohort filters of the exposure criteria that count other users than they read like. Pure functions, no I/O.

The exposure query reads a cohort's members when it runs, so a dynamic cohort counts the users who are in it at the
calculation, not at their exposure.
"""

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.checks.events_received import quoted
from products.experiments.backend.health.context import ExposureCohort, ExposureEvents, HealthContext
from products.experiments.backend.health.skips import NOT_ON_ARCHIVED, CheckOutcome, not_applicable, not_checked

# pinned: the subcodes are sent as `finding_subcode` on the health finding events, so insights group on them.
COHORT_FORCES_VARIANT = "cohort_forces_variant"
COHORT_IN_RELEASE_CONDITIONS = "cohort_in_release_conditions"


def exposure_filters(ctx: HealthContext) -> CheckOutcome:
    if ctx.archived:
        return not_applicable(NOT_ON_ARCHIVED)
    events = ctx.exposure_events
    if events is None:
        return not_checked("Couldn't check because the exposure criteria can't be read")
    if not events.cohort_ids:
        return not_applicable("The exposure criteria have no cohort filter")
    dynamic = [cohort for cohort in ctx.exposure_cohorts if not cohort.is_static]
    if dynamic:
        return _filter_on_dynamic_cohort(ctx, events, dynamic)
    if len(ctx.exposure_cohorts) < len(events.cohort_ids):
        return not_checked("Couldn't check because a cohort in the exposure criteria is deleted or missing")
    return None


def _filter_on_dynamic_cohort(
    ctx: HealthContext, events: ExposureEvents, cohorts: list[ExposureCohort]
) -> ExperimentHealthFinding:
    conditions = ctx.flag.reachable_conditions if ctx.flag else ()
    # The criteria and a release condition read the same users only when both keep the cohort's members.
    in_flag = [
        cohort
        for cohort in cohorts
        if cohort.id in events.member_cohort_ids and any(cohort.id in c.member_cohort_ids for c in conditions)
    ]
    pinning = [
        c for c in conditions if c.pinned_variant and any(cohort.id in c.member_cohort_ids for cohort in in_flag)
    ]
    forced = [cohort for cohort in in_flag if any(cohort.id in c.member_cohort_ids for c in pinning)]
    many = len(cohorts) > 1
    lead = (
        f"The exposure criteria filter on the dynamic {'cohorts' if many else 'cohort'} {_names(cohorts)}. The results "
        f"read {'their' if many else 'its'} members at the time of the calculation, not at the time of each user's "
        "exposure."
    )
    subcode: str | None
    if forced:
        subcode = COHORT_FORCES_VARIANT
        pinned = (
            "Release conditions of the feature flag on {names} give one variant to all the users they match"
            if len(pinning) > 1
            else "A release condition of the feature flag on {names} gives one variant to all the users it matches"
        ).format(names=_names(forced))
        effect = (
            f"{pinned}, and the flag checks who is in {_them(forced)} on each call. Users who joined or left since the "
            "calculation are counted differently from how the flag assigned them, which can make the split of users "
            f"across variants uneven. {_static_in_both_places(ctx)}"
        )
    elif in_flag:
        subcode = COHORT_IN_RELEASE_CONDITIONS
        effect = (
            f"The feature flag's release conditions use {_names(in_flag)} too, and the flag checks who is in "
            f"{_them(in_flag)} on each call, so users the flag served since the calculation can be missing from the "
            f"results. If the release conditions already limit the experiment to these users, remove {_names(in_flag)} "
            f"from the exposure criteria. {_static_in_both_places(ctx, otherwise=True)}"
        )
    else:
        subcode = None
        effect = (
            "Users who join or leave after their exposure move in or out of the results, so if the variant changes who "
            "joins, the results are biased. Use a static cohort instead, which keeps the same members."
        )
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.EXPOSURE_FILTER_ON_DYNAMIC_COHORT,
        subcode=subcode,
        severity=ExperimentHealthFindingSeverity.WARNING,
        title="The exposure criteria filter on a dynamic cohort",
        detail=f"{lead} {effect}",
        evidence={"cohort_ids": ", ".join(str(cohort.id) for cohort in cohorts)},
        actions=(ExperimentHealthFindingActionKind.EDIT_EXPOSURE_CRITERIA,),
        diagnostic_ref=None,
    )


def _static_in_both_places(ctx: HealthContext, *, otherwise: bool = False) -> str:
    use = "Otherwise, use" if otherwise else "Use"
    if not ctx.is_launched:
        return f"{use} a static cohort in both places, so the flag and the results agree on who is in it."
    if ctx.has_ended:
        return f"{'Otherwise, in' if otherwise else 'In'} your next experiment, use a static cohort in both places."
    return f"{use} a static cohort in both places, then reset the experiment, because the change moves users."


def _names(cohorts: list[ExposureCohort]) -> str:
    return quoted([cohort.name for cohort in cohorts])


def _them(cohorts: list[ExposureCohort]) -> str:
    return "them" if len(cohorts) > 1 else "it"

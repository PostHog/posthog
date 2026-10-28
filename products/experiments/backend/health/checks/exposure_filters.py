"""
Exposure criteria filters that count other users than they read like. Pure functions, no I/O.

The exposure query applies each filter to the events that it reads, and reads a cohort's members when it runs. So a
dynamic cohort counts the users who are in it at the calculation, not at their exposure, and a filter that leaves out
events with a property value keeps a user who sent another exposure event.
"""

from posthog.hogql.property import operator_is_negative

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.checks.events_received import quoted
from products.experiments.backend.health.context import ExposureCohort, ExposurePropertyFilter, HealthContext
from products.experiments.backend.health.skips import NOT_ON_ARCHIVED, CheckOutcome, not_applicable, not_checked

# pinned: the subcodes are sent as `finding_variant` on the health finding events, so insights group on them.
COHORT_FORCES_VARIANT = "cohort_forces_variant"
COHORT_IN_RELEASE_CONDITIONS = "cohort_in_release_conditions"


def exposure_filters(ctx: HealthContext) -> CheckOutcome:
    if ctx.archived:
        return not_applicable(NOT_ON_ARCHIVED)
    events = ctx.exposure_events
    if events is None:
        return not_checked("Couldn't check because the exposure criteria can't be read")
    exclusions = [f for f in events.property_filters if _excludes_events(f)]
    if not events.cohort_ids and not exclusions:
        return not_applicable("The exposure criteria have no cohort filter and no negated event property filter")
    dynamic = [cohort for cohort in ctx.exposure_cohorts if not cohort.is_static]
    if dynamic:
        return _filter_on_dynamic_cohort(ctx, dynamic)
    if exclusions:
        return _filter_excludes_events(ctx, exclusions)
    if len(ctx.exposure_cohorts) < len(events.cohort_ids):
        return not_checked("Couldn't check because a cohort in the exposure criteria is deleted or missing")
    return None


def _excludes_events(property_filter: ExposurePropertyFilter) -> bool:
    # A person property has one value per user at a time, so a filter on it reads as leaving out the user.
    return (
        property_filter.type == "event"
        and property_filter.key != "$feature_flag"
        and operator_is_negative(property_filter.operator)
    )


def _filter_on_dynamic_cohort(ctx: HealthContext, cohorts: list[ExposureCohort]) -> ExperimentHealthFinding:
    conditions = ctx.flag.reachable_conditions if ctx.flag else ()
    in_flag = [cohort for cohort in cohorts if any(cohort.id in c.cohort_ids for c in conditions)]
    forced = [cohort for cohort in in_flag if any(cohort.id in c.cohort_ids and c.pinned_variant for c in conditions)]
    many = len(cohorts) > 1
    lead = (
        f"The exposure criteria filter on the dynamic {'cohorts' if many else 'cohort'} {_names(cohorts)}. The results "
        f"read {'their' if many else 'its'} members at the time of the calculation, not at the time of each user's "
        "exposure."
    )
    subcode: str | None
    if forced:
        subcode = COHORT_FORCES_VARIANT
        effect = (
            f"The feature flag's release conditions give one variant to everyone in {_names(forced)}, and the flag "
            f"checks who is in {_them(forced)} on each call. Users who joined or left since the calculation are "
            "counted differently from how the flag assigned them, which can make the split of users across variants "
            f"uneven. {_static_in_both_places(ctx)}"
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
        advice = (
            "Use a static cohort instead, or limit the experiment to these users in the feature flag's release "
            "conditions."
            if not ctx.is_launched
            else "Use a static cohort instead, which keeps the same members."
        )
        effect = (
            "Users who join or leave after their exposure move in or out of the results, so if the variant changes who "
            f"joins, the results are biased. {advice}"
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


def _filter_excludes_events(ctx: HealthContext, filters: list[ExposurePropertyFilter]) -> ExperimentHealthFinding:
    keys = list(dict.fromkeys(f.key for f in filters))
    subject = (
        f"The filter on the event property {quoted(keys)} in the exposure criteria leaves"
        if len(keys) == 1
        else f"The filters on the event properties {quoted(keys)} in the exposure criteria leave"
    )
    advice = (
        " To keep users out of the experiment, leave them out in the feature flag's release conditions."
        if not ctx.is_launched
        else ""
    )
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.EXPOSURE_FILTER_EXCLUDES_EVENTS,
        subcode=None,
        severity=ExperimentHealthFindingSeverity.INFO,
        title="An exposure filter leaves out events, not users",
        detail=(
            f"{subject} out single events, not the users who sent them. A user with a left-out event is still counted "
            f"when another of their events passes.{advice}"
        ),
        evidence={"properties": ", ".join(keys)},
        actions=(ExperimentHealthFindingActionKind.EDIT_EXPOSURE_CRITERIA,),
        diagnostic_ref=None,
    )

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
COHORT_IN_RELEASE_CONDITIONS = "cohort_in_release_conditions"


def exposure_filters(ctx: HealthContext) -> CheckOutcome:
    if ctx.archived:
        return not_applicable(NOT_ON_ARCHIVED)
    events = ctx.exposure_events
    if events is None:
        return not_checked("Couldn't check because the exposure criteria can't be read")
    exclusions = [f for f in events.property_filters if _excludes_events(f)]
    if not events.cohort_ids and not exclusions:
        return not_applicable("The exposure criteria have no cohort filter, and no filter that leaves out events")
    dynamic = [cohort for cohort in ctx.exposure_cohorts if not cohort.is_static]
    if dynamic:
        return _filter_on_dynamic_cohort(ctx, dynamic)
    if exclusions:
        return _filter_excludes_events(exclusions)
    return None


def _excludes_events(property_filter: ExposurePropertyFilter) -> bool:
    # A filter on a person property leaves out every event of a user who has the value at the event, which reads as
    # leaving out the user.
    return (
        property_filter.type == "event"
        and property_filter.key != "$feature_flag"
        and operator_is_negative(property_filter.operator)
    )


def _filter_on_dynamic_cohort(ctx: HealthContext, cohorts: list[ExposureCohort]) -> ExperimentHealthFinding:
    names = quoted([cohort.name for cohort in cohorts])
    subject = f"the dynamic cohort {names}" if len(cohorts) == 1 else f"the dynamic cohorts {names}"
    in_flag = ctx.flag is not None and any(cohort.id in ctx.flag.cohort_ids for cohort in cohorts)
    flag_note = (
        " The feature flag's release conditions use this cohort too. The flag checks who is in it on each call, while "
        "the results use its members from its last update, so the variants can get uneven numbers of users."
        if in_flag
        else ""
    )
    advice = (
        "Use a static cohort in both places instead, which keeps the same members."
        if in_flag
        else "Use a static cohort instead, which keeps the same members, or set who takes part in the feature "
        "flag's release conditions."
    )
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.EXPOSURE_FILTER_ON_DYNAMIC_COHORT,
        subcode=COHORT_IN_RELEASE_CONDITIONS if in_flag else None,
        severity=ExperimentHealthFindingSeverity.WARNING,
        title="The exposure criteria filter on a dynamic cohort",
        detail=(
            f"The exposure criteria filter on {subject}. The results read the cohort's members at the time of the "
            "calculation, not at the time of each user's exposure. Users who join or leave the cohort after their "
            "exposure move in or out of the results, so if the variant changes who joins, the results are biased."
            f"{flag_note} {advice}"
        ),
        evidence={"cohort_ids": ", ".join(str(cohort.id) for cohort in cohorts)},
        actions=(ExperimentHealthFindingActionKind.EDIT_EXPOSURE_CRITERIA,),
        diagnostic_ref=None,
    )


def _filter_excludes_events(filters: list[ExposurePropertyFilter]) -> ExperimentHealthFinding:
    keys = list(dict.fromkeys(f.key for f in filters))
    subject = (
        f"The filter on the event property {quoted(keys)} in the exposure criteria leaves"
        if len(keys) == 1
        else f"The filters on the event properties {quoted(keys)} in the exposure criteria leave"
    )
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.EXPOSURE_FILTER_EXCLUDES_EVENTS,
        subcode=None,
        # Info: the filter can mean to leave out only these events, such as the flag calls on one page.
        severity=ExperimentHealthFindingSeverity.INFO,
        title="An exposure filter leaves out events, not users",
        detail=(
            f"{subject} out single exposure events, not the users who sent them. A user with a left-out event is "
            "still counted when another of their exposure events passes. To keep users out of the experiment, leave "
            "them out in the feature flag's release conditions."
        ),
        evidence={"properties": ", ".join(keys)},
        actions=(ExperimentHealthFindingActionKind.EDIT_EXPOSURE_CRITERIA,),
        diagnostic_ref=None,
    )

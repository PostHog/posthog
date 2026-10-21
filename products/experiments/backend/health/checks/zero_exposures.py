from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.checks.new_flag_no_traffic import LAST_CALLED_AT_LAG
from products.experiments.backend.health.context import HealthContext
from products.experiments.backend.health.skips import RUNS_AFTER_LAUNCH, CheckSkip, not_applicable

# A new experiment often has no exposure in its first hours, so the finding waits as long as the experiments scout does.
ZERO_EXPOSURES_GRACE_HOURS = 24

# pinned: the subcodes are sent as `finding_variant` on the health finding events, so insights group on them.
FLAG_NOT_CALLED = "flag_not_called"
CALLS_NOT_COUNTED = "calls_not_counted"
CUSTOM_EXPOSURE_NOT_MATCHED = "custom_exposure_not_matched"


def zero_exposures_skip(ctx: HealthContext) -> CheckSkip | None:
    exposures = ctx.exposures
    if exposures is None or exposures.hours_since_launch is None or not ctx.is_launched:
        return not_applicable(RUNS_AFTER_LAUNCH)
    if exposures.hours_since_launch < ZERO_EXPOSURES_GRACE_HOURS:
        return not_applicable(f"Runs {ZERO_EXPOSURES_GRACE_HOURS} hours after launch")
    return None


def zero_exposures(ctx: HealthContext) -> ExperimentHealthFinding | None:
    exposures = ctx.exposures
    if exposures is None or exposures.hours_since_launch is None or not ctx.is_launched:
        return None
    if exposures.hours_since_launch < ZERO_EXPOSURES_GRACE_HOURS or sum(exposures.total_exposures.values()) > 0:
        return None
    evidence = {"hours_since_launch": int(exposures.hours_since_launch)}
    events = ctx.exposure_events
    if events is None or ctx.flag is None or ctx.flag.deleted:
        return _cause_unknown(evidence)
    if events.required_flag_key is None:
        # A custom event or an action carries the variant in a property that client SDKs add to every event, so the
        # flag's calls say nothing about these exposures.
        if events.custom_event is not None:
            counted = f'they send the event "{events.custom_event}"'
        else:
            counted = "they send an event that matches the exposure action"
        return _finding(
            subcode=CUSTOM_EXPOSURE_NOT_MATCHED,
            title="No users exposed: no events match the exposure criteria",
            detail=(
                f"Users are counted as exposed when {counted} with one of the experiment's variants in the property "
                f'"{events.variant_property}". No event has matched since launch, so nobody is counted. Check that '
                "your code sends the event with the variant, and that the exposure criteria, such as the test "
                "account filter, don't leave out your users."
            ),
            evidence=evidence,
            actions=(ExperimentHealthFindingActionKind.EDIT_EXPOSURE_CRITERIA,),
        )
    flag_key = events.required_flag_key
    if ctx.flag_called_since_launch is False:
        return _finding(
            subcode=FLAG_NOT_CALLED,
            title="No users exposed: the feature flag has no recorded calls",
            detail=(
                f'PostHog hasn\'t recorded a call of the feature flag "{flag_key}" since the experiment launched, so '
                "nobody is counted as exposed. Users are counted when your code reads the flag's value with a "
                "single-flag call, such as getFeatureFlag in JavaScript or get_feature_flag in Python. Reading all "
                "flags at once or only a payload records no call, and neither does a call with send_event set to "
                f"false. New calls can take up to {LAST_CALLED_AT_LAG} to show up here."
            ),
            evidence=evidence,
            actions=(),
        )
    if ctx.flag_called_since_launch is True:
        return _finding(
            subcode=CALLS_NOT_COUNTED,
            title="No users exposed, although the feature flag is called",
            detail=(
                f'PostHog has recorded calls of the feature flag "{flag_key}" since the experiment launched, but '
                "none of them counts as an exposure. A call counts when the flag returns one of the experiment's "
                "variants and the user passes the exposure criteria. Check that the flag's release conditions include "
                "your users, and that the exposure criteria, such as the test account filter, don't leave them out."
            ),
            evidence=evidence,
            actions=(
                ExperimentHealthFindingActionKind.OPEN_FEATURE_FLAG,
                ExperimentHealthFindingActionKind.EDIT_EXPOSURE_CRITERIA,
            ),
        )
    return _cause_unknown(evidence)


def _cause_unknown(evidence: dict[str, int]) -> ExperimentHealthFinding:
    return _finding(
        subcode=None,
        title="No users exposed",
        detail=(
            "No users have been exposed to this experiment, so it shows no results. "
            "Users are counted when the exposure event is sent for them. Check that your code evaluates "
            "the linked feature flag and that the exposure criteria match the events you send."
        ),
        evidence=evidence,
        actions=(ExperimentHealthFindingActionKind.EDIT_EXPOSURE_CRITERIA,),
    )


def _finding(
    *,
    subcode: str | None,
    title: str,
    detail: str,
    evidence: dict[str, int],
    actions: tuple[ExperimentHealthFindingActionKind, ...],
) -> ExperimentHealthFinding:
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.ZERO_EXPOSURES,
        subcode=subcode,
        severity=ExperimentHealthFindingSeverity.WARNING,
        title=title,
        detail=detail,
        evidence=evidence,
        actions=actions,
        diagnostic_ref=None,
    )

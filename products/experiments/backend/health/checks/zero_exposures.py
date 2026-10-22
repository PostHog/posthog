from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.context import HealthContext
from products.experiments.backend.health.delays import LAST_CALLED_AT_LAG, ZERO_EXPOSURES_GRACE_HOURS
from products.experiments.backend.health.skips import RUNS_AFTER_LAUNCH, CheckSkip, not_applicable

# pinned: the subcodes are sent as `finding_variant` on the health finding events, so insights group on them.
EXPERIMENT_PAUSED = "experiment_paused"
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
    # The cause reads the flag besides the cached exposure answer. The page recomputes that answer on each load while it
    # holds fewer than 50 exposures, so the cause is as fresh as the zero.
    flag = ctx.flag
    # Deleting a flag changes its key, so its calls stop moving `last_called_at`, and a custom event's variant property
    # names a key the flag no longer has. The flag-state check reports the deletion.
    if flag is None or flag.deleted:
        return _cause_unknown(evidence)
    if ctx.is_paused:
        return _finding(
            subcode=EXPERIMENT_PAUSED,
            title="No users exposed: the experiment is paused",
            detail=(
                "The experiment is paused, so its feature flag serves no variants and nobody is counted as exposed. "
                "Resume the experiment to expose users."
            ),
            evidence=evidence,
            actions=(),
        )
    events = ctx.exposure_events
    if events is None:
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
                f'"{events.variant_property}". No event has matched during the experiment, so nobody is counted. '
                "Check that your code sends the event with the variant, and that the exposure criteria, such as the "
                "test account filter, don't leave out your users."
            ),
            evidence=evidence,
            actions=(ExperimentHealthFindingActionKind.EDIT_EXPOSURE_CRITERIA,),
        )
    flag_key = events.required_flag_key
    if ctx.flag_called_during_run is False:
        return _finding(
            subcode=FLAG_NOT_CALLED,
            title="No users exposed: the feature flag has no recorded calls",
            detail=(
                f'PostHog hasn\'t recorded a call of the feature flag "{flag_key}" during the experiment, so nobody is '
                "counted as exposed. Users are counted when your code reads this flag's value, for example with "
                "getFeatureFlag in the browser or with get_flag on the result of evaluate_flags in Python. Reading "
                "only a payload or a list of all flags records no call, and neither does a call with send_event set "
                f"to false. New calls can take up to {LAST_CALLED_AT_LAG} to show up here."
            ),
            evidence=evidence,
            actions=(),
        )
    if ctx.flag_called_during_run is True:
        return _finding(
            subcode=CALLS_NOT_COUNTED,
            title="No users exposed, although the feature flag is called",
            detail=(
                f'PostHog has recorded calls of the feature flag "{flag_key}" during the experiment, but none of them '
                "counts as an exposure. A call counts when the flag returns one of the experiment's variants and the "
                "user passes the exposure criteria. Check that the flag's release conditions include your users, and "
                "that the exposure criteria, such as the test account filter, don't leave them out."
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

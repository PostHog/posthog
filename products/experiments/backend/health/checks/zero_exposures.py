from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.checks.exposure_criteria import exposure_criteria_cannot_match
from products.experiments.backend.health.context import HealthContext
from products.experiments.backend.health.delays import LAST_CALLED_AT_LAG, ZERO_EXPOSURES_GRACE_HOURS
from products.experiments.backend.health.skips import RUNS_AFTER_LAUNCH, CheckOutcome, not_applicable

# pinned: the finding's subcodes. The page sends them as `finding_subcode` on the health finding events.
EXPERIMENT_PAUSED = "experiment_paused"
FLAG_NOT_CALLED = "flag_not_called"
CALLS_NOT_COUNTED = "calls_not_counted"
CUSTOM_EXPOSURE_NOT_MATCHED = "custom_exposure_not_matched"
# pinned: the finding's `reason`.
TEST_ACCOUNT_FILTER = "test_account_filter"


def reads_exposed_without_test_account_filter(ctx: HealthContext) -> bool:
    """Whether `zero_exposures` reports flag calls that count as no exposure, which the test account filter can
    explain. The exposure query counts the exposures without the filter only then, because the count scans the
    exposure events."""
    outcome = zero_exposures(ctx)
    return isinstance(outcome, ExperimentHealthFinding) and outcome.subcode == CALLS_NOT_COUNTED


def zero_exposures(ctx: HealthContext) -> CheckOutcome:
    exposures = ctx.exposures
    if exposures is None or exposures.hours_since_launch is None or not ctx.is_launched:
        return not_applicable(RUNS_AFTER_LAUNCH)
    if exposures.hours_since_launch < ZERO_EXPOSURES_GRACE_HOURS:
        return not_applicable(f"Runs {ZERO_EXPOSURES_GRACE_HOURS} hours after launch")
    if sum(exposures.total_exposures.values()) > 0:
        return None
    # Criteria that no event can match leave nobody exposed, and the exposure criteria check names that cause. This
    # check calls it rather than repeating its rules, so exactly one of the two reports the experiment.
    if isinstance(exposure_criteria_cannot_match(ctx), ExperimentHealthFinding):
        return not_applicable("The exposure criteria check reports why no users are exposed")
    evidence: dict[str, int | str] = {"hours_since_launch": int(exposures.hours_since_launch)}
    # A group experiment counts groups, by the rule the exposure query uses.
    unit = "group" if exposures.counts_groups else "user"
    # The cause reads the flag besides the cached exposure answer. The page recomputes that answer on each load while it
    # holds fewer than 50 exposures, so the cause is as fresh as the zero.
    flag = ctx.flag
    # Deleting a flag changes its key, so its calls stop moving `last_called_at`. The flag-state check reports the
    # deletion.
    if flag is None or flag.deleted:
        return _cause_unknown(evidence, unit, ended=ctx.has_ended)
    if ctx.is_paused:
        # Info, because the flag-state check already reports the pause, and a pause needs no fix.
        return _finding(
            subcode=EXPERIMENT_PAUSED,
            severity=ExperimentHealthFindingSeverity.INFO,
            title=f"No {unit}s exposed: the experiment is paused",
            detail=(
                "The experiment is paused, so its feature flag serves no variants and nobody is counted as exposed. "
                f"Resume the experiment to expose {unit}s."
            ),
            evidence=evidence,
            actions=(),
        )
    events = ctx.exposure_events
    if events is None:
        return _cause_unknown(evidence, unit, ended=ctx.has_ended)
    if events.required_flag_key is None:
        # A custom event or an action carries the variant in a property that client SDKs add to every event, so the
        # flag's calls say nothing about these exposures.
        sender = "a member sends" if unit == "group" else "they send"
        if events.custom_event is not None:
            counted = f'{sender} the event "{events.custom_event}"'
        else:
            counted = f"{sender} an event that matches the exposure action"
        rule = (
            f"{unit.capitalize()}s are counted as exposed when {counted} with one of the experiment's variants in "
            f'the property "{events.variant_property}".'
        )
        if ctx.has_ended:
            title = f"No {unit}s exposed: no events matched the exposure criteria"
            detail = (
                f"No {unit}s were exposed while the experiment ran, because no event matched the exposure criteria. "
                f"{rule} If your code sent the event, check that the exposure criteria, such as the test account "
                f"filter, don't leave out your {unit}s."
            )
        else:
            title = f"No {unit}s exposed: no events match the exposure criteria"
            detail = (
                f"{rule} No event has matched during the experiment, so nobody is counted. Check that your code sends "
                "the event with the variant, and that the exposure criteria, such as the test account filter, don't "
                f"leave out your {unit}s."
            )
        # A warning also after the end, because the exposure query reruns over the events up to the end, so a fix to
        # the exposure criteria brings back the results.
        return _finding(
            subcode=CUSTOM_EXPOSURE_NOT_MATCHED,
            severity=ExperimentHealthFindingSeverity.WARNING,
            title=title,
            detail=detail,
            evidence=evidence,
            actions=(ExperimentHealthFindingActionKind.EDIT_EXPOSURE_CRITERIA,),
        )
    flag_key = events.required_flag_key
    if ctx.flag_called_during_run is False:
        no_call_recorded = (
            "Reading only a payload or a list of all flags records no call, and neither does a call with send_event "
            "set to false."
        )
        if ctx.has_ended:
            title = f"No {unit}s exposed: the feature flag had no recorded calls"
            detail = (
                f"No {unit}s were exposed while the experiment ran, because PostHog didn't record a call of the feature "
                f'flag "{flag_key}" in that time. {unit.capitalize()}s are counted when your code reads this flag\'s '
                f"value. {no_call_recorded}"
            )
        else:
            title = f"No {unit}s exposed: the feature flag has no recorded calls"
            detail = (
                f'PostHog hasn\'t recorded a call of the feature flag "{flag_key}" during the experiment, so nobody is '
                f"counted as exposed. {unit.capitalize()}s are counted when your code reads this flag's value, for "
                "example with getFeatureFlag in the browser or with get_flag on the result of evaluate_flags in Python. "
                f"{no_call_recorded} New calls can take up to {LAST_CALLED_AT_LAG} to show up here."
            )
        # Info after the end, because no change to the code can expose more users then, so the finding only explains
        # the empty results.
        return _finding(
            subcode=FLAG_NOT_CALLED,
            severity=ExperimentHealthFindingSeverity.INFO if ctx.has_ended else ExperimentHealthFindingSeverity.WARNING,
            title=title,
            detail=detail,
            evidence=evidence,
            actions=(),
        )
    if ctx.flag_called_during_run is True:
        exposed_without_filter = exposures.exposed_without_test_account_filter
        if exposed_without_filter is not None:
            evidence["exposed_without_test_account_filter"] = exposed_without_filter
        if exposed_without_filter:
            return _test_accounts_filtered_out(
                exposed_without_filter, flag_key, unit, ended=ctx.has_ended, evidence=evidence
            )
        activation = (
            f' With the activation "{events.activation}" set, a {unit} also needs a matching event after the flag call.'
            if events.activation
            else ""
        )
        if ctx.has_ended:
            group_rule = " A call counts only when it carries the group." if unit == "group" else ""
            title = f"No {unit}s exposed, although the feature flag was called"
            detail = (
                f"No {unit}s were exposed while the experiment ran, although PostHog recorded calls of the feature "
                f'flag "{flag_key}" in that time. A call counts when the flag returns one of the experiment\'s '
                f"variants and the {unit} passes the exposure criteria.{group_rule}{activation} Check that the "
                f"exposure criteria, such as the test account filter, don't leave out your {unit}s."
            )
        else:
            # Calls made before the group is set carry no group key, and the exposure query drops them.
            group_rule = (
                " A call counts only when it carries the group, so set the group before your code reads the flag."
                if unit == "group"
                else ""
            )
            title = f"No {unit}s exposed, although the feature flag is called"
            detail = (
                f'PostHog has recorded calls of the feature flag "{flag_key}" during the experiment, but none of them '
                "counts as an exposure. A call counts when the flag returns one of the experiment's variants and the "
                f"{unit} passes the exposure criteria.{group_rule}{activation} Check that the flag's release "
                f"conditions include your {unit}s, and that the exposure criteria, such as the test account filter, "
                "don't leave them out."
            )
        return _finding(
            subcode=CALLS_NOT_COUNTED,
            severity=ExperimentHealthFindingSeverity.WARNING,
            title=title,
            detail=detail,
            evidence=evidence,
            actions=(
                ExperimentHealthFindingActionKind.OPEN_FEATURE_FLAG,
                ExperimentHealthFindingActionKind.EDIT_EXPOSURE_CRITERIA,
            ),
        )
    return _cause_unknown(evidence, unit, ended=ctx.has_ended)


def _test_accounts_filtered_out(
    exposed: int, flag_key: str, unit: str, *, ended: bool, evidence: dict[str, int | str]
) -> ExperimentHealthFinding:
    exposed_units = f"the only {unit}" if exposed == 1 else f"all {exposed:,} {unit}s"
    served = f'{exposed_units} that got a variant of the feature flag "{flag_key}"'
    fix = 'Turn off "Filter out internal and test users" in the exposure criteria'
    if ended:
        title = f"No {unit}s exposed: the test account filter removed all of them"
        detail = (
            f"No {unit}s were exposed while the experiment ran, because the exposure criteria filter out test "
            f"accounts, and the project's test account filters matched {served}. {fix} to count them."
        )
    else:
        title = f"No {unit}s exposed: the test account filter removes all of them"
        detail = (
            f"The exposure criteria filter out test accounts, and the project's test account filters match {served} "
            f"during the experiment, so nobody is counted as exposed. {fix}, or change the project's test account "
            f"filters so that they don't match your {unit}s."
        )
    return _finding(
        subcode=CALLS_NOT_COUNTED,
        reason=TEST_ACCOUNT_FILTER,
        severity=ExperimentHealthFindingSeverity.WARNING,
        title=title,
        detail=detail,
        evidence=evidence,
        actions=(ExperimentHealthFindingActionKind.EDIT_EXPOSURE_CRITERIA,),
    )


def _cause_unknown(evidence: dict[str, int | str], unit: str, *, ended: bool) -> ExperimentHealthFinding:
    if ended:
        detail = (
            f"No {unit}s were exposed while the experiment ran, so it shows no results. "
            f"{unit.capitalize()}s are counted when the exposure event is sent for them. If your code sent it, "
            "check that the exposure criteria match the events it sent."
        )
    else:
        detail = (
            f"No {unit}s have been exposed to this experiment, so it shows no results. "
            f"{unit.capitalize()}s are counted when the exposure event is sent for them. Check that your code "
            "evaluates the linked feature flag and that the exposure criteria match the events you send."
        )
    # Info after the end, because with the cause unknown the finding names no fix that is sure to bring back results.
    return _finding(
        subcode=None,
        severity=ExperimentHealthFindingSeverity.INFO if ended else ExperimentHealthFindingSeverity.WARNING,
        title=f"No {unit}s exposed",
        detail=detail,
        evidence=evidence,
        actions=(ExperimentHealthFindingActionKind.EDIT_EXPOSURE_CRITERIA,),
    )


def _finding(
    *,
    subcode: str | None,
    reason: str | None = None,
    severity: ExperimentHealthFindingSeverity,
    title: str,
    detail: str,
    evidence: dict[str, int | str],
    actions: tuple[ExperimentHealthFindingActionKind, ...],
) -> ExperimentHealthFinding:
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.ZERO_EXPOSURES,
        subcode=subcode,
        reason=reason,
        severity=severity,
        title=title,
        detail=detail,
        evidence=evidence,
        actions=actions,
        diagnostic_ref=None,
    )

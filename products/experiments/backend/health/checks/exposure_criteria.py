"""
Exposure criteria that no event can match, read from the criteria alone. Pure functions, no I/O.

The zero exposures check reports an experiment that counted nobody. This check names the cause when the criteria show
it: a custom exposure event that the project never received, or a filter on the flag call events that requires
another flag than the one the exposure query requires.
"""

from posthog.schema import PropertyOperator

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.checks.events_received import not_received_severity, quoted
from products.experiments.backend.health.context import FlagKeyFilter, HealthContext
from products.experiments.backend.health.skips import (
    NO_FLAG,
    NOT_AFTER_END,
    NOT_ON_ARCHIVED,
    CheckSkip,
    not_applicable,
    not_checked,
)

# pinned: the subcodes are sent as `finding_variant` on the health finding events, so insights group on them.
EXPOSURE_EVENT_NOT_INGESTED = "exposure_event_not_ingested"
FILTER_ON_ANOTHER_FLAG = "filter_on_another_flag"


def exposure_criteria_skip(ctx: HealthContext) -> CheckSkip | None:
    if ctx.archived:
        return not_applicable(NOT_ON_ARCHIVED)
    events = ctx.exposure_events
    if events is None:
        return not_checked("Couldn't check because the exposure criteria can't be read")
    if events.custom_event is not None:
        if ctx.has_ended:
            return not_applicable(NOT_AFTER_END)
        if events.custom_event not in ctx.events_received:
            return not_checked("Couldn't check because PostHog keeps no record of this event name")
        return None
    if events.required_flag_key is None:
        if ctx.flag is None:
            return not_applicable(NO_FLAG)
        return not_applicable("Doesn't check exposure criteria that use an action")
    return None


def exposure_criteria_cannot_match(ctx: HealthContext) -> ExperimentHealthFinding | None:
    events = ctx.exposure_events
    if ctx.archived or events is None:
        return None
    flag_key = events.required_flag_key
    if flag_key is not None:
        other = next((f for f in events.flag_key_filters if _requires_another_flag(f, flag_key)), None)
        if other is not None:
            return _filter_on_another_flag(flag_key, other)
    event = events.custom_event
    if event is not None and not ctx.has_ended and ctx.events_received.get(event) is False:
        return _exposure_event_not_ingested(ctx, event)
    return None


def _requires_another_flag(flag_filter: FlagKeyFilter, flag_key: str) -> bool:
    # `exact` compares the property with each value as a case-sensitive string. A filter without values matches every
    # event, and the query converts a number to a string, so only string values prove that the filter excludes the key.
    return (
        flag_filter.operator == PropertyOperator.EXACT
        and len(flag_filter.values) > 0
        and all(isinstance(value, str) for value in flag_filter.values)
        and flag_key not in flag_filter.values
    )


def _filter_on_another_flag(flag_key: str, flag_filter: FlagKeyFilter) -> ExperimentHealthFinding:
    values = [str(value) for value in flag_filter.values]
    required = f'the flag "{values[0]}"' if len(values) == 1 else f"one of the flags {quoted(values, 'or')}"
    return _finding(
        subcode=FILTER_ON_ANOTHER_FLAG,
        severity=ExperimentHealthFindingSeverity.WARNING,
        title="The exposure criteria can't match any event",
        detail=(
            f'The experiment counts the calls of its feature flag "{flag_key}" as exposures, but a filter in the '
            f"exposure criteria requires {required}. No call matches both, so nobody is counted as exposed. "
            f'Remove the filter, or change it to "{flag_key}".'
        ),
        evidence={"flag_key": flag_key, "filter_flag_keys": ", ".join(values)},
    )


def _exposure_event_not_ingested(ctx: HealthContext, event: str) -> ExperimentHealthFinding:
    advice = (
        "Launch the experiment after your code starts sending it."
        if not ctx.is_launched
        else "Check that your code sends the event with exactly this name, or change the exposure criteria."
    )
    return _finding(
        subcode=EXPOSURE_EVENT_NOT_INGESTED,
        severity=not_received_severity(ctx, affects_results=True),
        title="This project hasn't received the exposure event",
        detail=(
            f'The experiment counts users as exposed when they send the event "{event}", which this project hasn\'t '
            f"received yet. Until it arrives, nobody is counted as exposed. {advice}"
        ),
        evidence={"event": event},
    )


def _finding(
    *, subcode: str, severity: ExperimentHealthFindingSeverity, title: str, detail: str, evidence: dict[str, str]
) -> ExperimentHealthFinding:
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.EXPOSURE_CRITERIA_CANNOT_MATCH,
        subcode=subcode,
        severity=severity,
        title=title,
        detail=detail,
        evidence=evidence,
        actions=(ExperimentHealthFindingActionKind.EDIT_EXPOSURE_CRITERIA,),
        diagnostic_ref=None,
    )

"""
Exposure criteria that no event can match, read from the criteria alone. Pure functions, no I/O.

The zero exposures check reports an experiment that counted nobody. This check names the cause when the criteria show
it: a custom exposure event that the project never received, a filter on the flag call events that requires another
flag than the one the exposure query requires, or a filter that requires a property the project never received.
"""

from posthog.schema import PropertyOperator

from products.experiments.backend.facade.contracts import (
    ExperimentHealthCheckStatus,
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.checks.events_received import joined, not_received_severity, quoted
from products.experiments.backend.health.context import (
    ExposureEvents,
    ExposurePropertyFilter,
    FlagKeyFilter,
    HealthContext,
)
from products.experiments.backend.health.skips import (
    NO_FLAG,
    NOT_AFTER_END,
    NOT_ON_ARCHIVED,
    CheckOutcome,
    CheckSkip,
    not_applicable,
    not_checked,
)

# pinned: the subcodes are sent as `finding_variant` on the health finding events, so insights group on them.
EXPOSURE_EVENT_NOT_INGESTED = "exposure_event_not_ingested"
FILTER_ON_ANOTHER_FLAG = "filter_on_another_flag"
FILTER_ON_PROPERTY_NOT_INGESTED = "filter_on_property_not_ingested"

# A filter with one of these operators matches no event that lacks the property: the query reads a missing property as
# null, and `property_to_expr` compares null as false for them. The other operators match such an event.
_REQUIRES_THE_PROPERTY = frozenset(
    {
        PropertyOperator.EXACT,
        PropertyOperator.ICONTAINS,
        PropertyOperator.ICONTAINS_MULTI,
        PropertyOperator.STARTS_WITH,
        PropertyOperator.ENDS_WITH,
        PropertyOperator.REGEX,
        PropertyOperator.GT,
        PropertyOperator.GTE,
        PropertyOperator.LT,
        PropertyOperator.LTE,
        PropertyOperator.MIN,
        PropertyOperator.MAX,
        PropertyOperator.IS_SET,
        PropertyOperator.IS_DATE_EXACT,
        PropertyOperator.IS_DATE_BEFORE,
        PropertyOperator.IS_DATE_AFTER,
        PropertyOperator.BETWEEN,
        PropertyOperator.IN_,
        PropertyOperator.IS_CLEANED_PATH_EXACT,
        PropertyOperator.SEMVER_EQ,
        PropertyOperator.SEMVER_NEQ,
        PropertyOperator.SEMVER_GT,
        PropertyOperator.SEMVER_GTE,
        PropertyOperator.SEMVER_LT,
        PropertyOperator.SEMVER_LTE,
        PropertyOperator.SEMVER_TILDE,
        PropertyOperator.SEMVER_CARET,
        PropertyOperator.SEMVER_WILDCARD,
    }
)


def exposure_criteria_cannot_match(ctx: HealthContext) -> CheckOutcome:
    if ctx.archived:
        return not_applicable(NOT_ON_ARCHIVED)
    events = ctx.exposure_events
    if events is None:
        return not_checked("Couldn't check because the exposure criteria can't be read")
    event_outcome = _exposure_event_cannot_match(ctx, events)
    if isinstance(event_outcome, ExperimentHealthFinding):
        return event_outcome
    property_outcome = _property_filter_cannot_match(ctx, events)
    if isinstance(property_outcome, ExperimentHealthFinding):
        return property_outcome
    # A part that couldn't read its input leaves a problem possible, and a part that looked makes the check look.
    for outcome in (event_outcome, property_outcome):
        if isinstance(outcome, CheckSkip) and outcome.status == ExperimentHealthCheckStatus.NOT_CHECKED:
            return outcome
    return None if event_outcome is None or property_outcome is None else event_outcome


def _exposure_event_cannot_match(ctx: HealthContext, events: ExposureEvents) -> CheckOutcome:
    event = events.custom_event
    if event is not None:
        if ctx.has_ended:
            return not_applicable(NOT_AFTER_END)
        received = ctx.events_received.get(event)
        if received is None:
            return not_checked("Couldn't check because PostHog keeps no record of this event name")
        return None if received else _exposure_event_not_ingested(ctx, event)
    flag_key = events.required_flag_key
    if flag_key is None:
        return not_applicable(NO_FLAG if ctx.flag is None else "Doesn't check exposure criteria that use an action")
    other = next((f for f in events.flag_key_filters if _requires_another_flag(f, flag_key)), None)
    return None if other is None else _filter_on_another_flag(flag_key, other)


def _property_filter_cannot_match(ctx: HealthContext, events: ExposureEvents) -> CheckOutcome:
    filters = [f for f in events.property_filters if f.key != "$feature_flag" and _requires_the_property(f)]
    if not filters:
        return not_applicable("The exposure criteria have no filter that requires a property")
    received = ctx.exposure_properties_received
    missing = [f for f in filters if received.get((f.type, f.key)) is False]
    if missing:
        return _filter_on_property_not_ingested(ctx, missing)
    if any((f.type, f.key) not in received for f in filters):
        return not_checked("Couldn't check because PostHog keeps no record of a property that a filter names")
    return None


def _requires_the_property(property_filter: ExposurePropertyFilter) -> bool:
    values = property_filter.values
    if property_filter.operator == PropertyOperator.IS_SET:
        # The test ignores a value, but an empty list of values matches every event.
        return values is None or len(values) > 0
    # Without a value, `exact` tests that the property is missing, and an empty list of values matches every event.
    return property_filter.operator in _REQUIRES_THE_PROPERTY and bool(values)


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


def _filter_on_property_not_ingested(
    ctx: HealthContext, filters: list[ExposurePropertyFilter]
) -> ExperimentHealthFinding:
    properties = list(dict.fromkeys(f'the {f.type} property "{f.key}"' for f in filters))
    one = len(properties) == 1
    advice = (
        f"Check the {'name' if one else 'names'} for a typo, or launch the experiment after your code starts sending "
        f"{'it' if one else 'them'}."
        if not ctx.is_launched
        else f"Check that the {'name matches' if one else 'names match'} what your code sends, or remove the "
        f"{'filter' if one else 'filters'}."
    )
    return _finding(
        subcode=FILTER_ON_PROPERTY_NOT_INGESTED,
        severity=not_received_severity(ctx, affects_results=True),
        title="An exposure filter needs a property this project hasn't received",
        detail=(
            f"{'A filter' if one else 'Filters'} in the exposure criteria {'needs' if one else 'need'} "
            f"{joined(properties)}, which this project hasn't received yet. Until "
            f"{'it arrives' if one else 'they arrive'}, no event passes the {'filter' if one else 'filters'}, so "
            f"nobody is counted as exposed. {advice}"
        ),
        evidence={"properties": ", ".join(dict.fromkeys(f.key for f in filters))},
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

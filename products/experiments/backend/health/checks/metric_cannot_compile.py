"""
Metrics whose query doesn't compile, so that every calculation of the metric fails. Pure functions, no I/O.

Nothing checks this at save: a metric fails only when its query runs, and before launch no query runs. The compiler's
messages are written for HogQL, so the finding puts the known ones in words. A message that names a field, a function,
a cohort, a regular expression or a table gets those words only when the metric's definition holds that name, because
a query can also fail on a name that PostHog generates.
"""

import re
from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Any

from posthog.dataclasses import frozen

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
    ExperimentHealthMetricCompileErrorKind,
)
from products.experiments.backend.health.context import HealthContext, MetricCompileFailure
from products.experiments.backend.health.skips import (
    NOT_ON_ARCHIVED,
    CheckOutcome,
    no_calculated_metric,
    not_applicable,
    not_checked,
)


class MetricCompileError(StrEnum):
    # pinned: the finding's subcode and `evidence.metric_N_error`.
    COMPOUND_AGGREGATION = "compound_aggregation"
    AGGREGATION_ARGUMENTS = "aggregation_arguments"
    UNKNOWN_FUNCTION = "unknown_function"
    UNKNOWN_FIELD = "unknown_field"
    SYNTAX_ERROR = "syntax_error"
    DELETED_COHORT = "deleted_cohort"
    INVALID_REGEX = "invalid_regex"
    INCOMPLETE_BEHAVIORAL_FILTER = "incomplete_behavioral_filter"
    UNSUPPORTED_ELEMENT_OPERATOR = "unsupported_element_operator"
    MISSING_WAREHOUSE_TABLE = "missing_warehouse_table"
    INVALID_DEFINITION = "invalid_definition"
    # A message that the query builder writes for the user, shown as it is.
    REJECTED = "rejected"
    OTHER = "other"


@frozen
class _Wording:
    error: MetricCompileError
    # What is wrong and what fixes it, after the sentence that names the metric.
    explanation: str


_COMPOUND_AGGREGATION = "must be a single aggregation"
_MAX_EVIDENCE_MESSAGE_LENGTH = 300
_ELEMENT_LABELS = {"selector": "CSS selector", "tag_name": "tag name", "href": "link target", "text": "text"}


def metric_cannot_compile(ctx: HealthContext) -> CheckOutcome:
    if ctx.archived:
        return not_applicable(NOT_ON_ARCHIVED)
    compiles = ctx.metric_compiles
    if compiles is None:
        return not_checked("Couldn't check because the metric queries couldn't be built")
    if compiles.metric_count == 0:
        return no_calculated_metric(ctx)
    if compiles.exposure_query_fails:
        return not_checked("Couldn't check because the exposure criteria can't be built into a query")
    if not compiles.failures:
        if compiles.no_access_count:
            reads = "reads" if compiles.no_access_count == 1 else "read"
            return not_checked(
                f"Couldn't check {_metrics(compiles.no_access_count)} that {reads} data you don't have access to"
            )
        if compiles.unknown_count:
            return not_checked(f"Couldn't check {_metrics(compiles.unknown_count)}")
        return None
    failures = sorted(compiles.failures, key=lambda failure: failure.role != "primary")
    worded = [(failure, _word(failure)) for failure in failures]
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.METRIC_CANNOT_COMPILE,
        subcode=worded[0][1].error.value,
        # The metric fails every calculation, so the warning holds before launch too. It holds after the end, because
        # the calculation after the fix reads the events up to the end and brings back the results.
        severity=ExperimentHealthFindingSeverity.WARNING
        if any(failure.role == "primary" for failure in failures)
        else ExperimentHealthFindingSeverity.INFO,
        title="PostHog can't calculate a metric"
        if len(failures) == 1
        else f"PostHog can't calculate {_metrics(len(failures))}",
        detail=" ".join(
            f'PostHog can\'t calculate the {failure.role} metric "{failure.name}". {wording.explanation}'
            for failure, wording in worded
        ),
        evidence=_evidence(worded),
        # No action opens a given metric.
        actions=(),
        diagnostic_ref=None,
    )


def _metrics(count: int) -> str:
    return "1 metric" if count == 1 else f"{count} metrics"


def _evidence(worded: list[tuple[MetricCompileFailure, _Wording]]) -> dict[str, str | None]:
    evidence: dict[str, str | None] = {}
    for number, (failure, wording) in enumerate(worded, start=1):
        message = failure.message
        evidence[f"metric_{number}"] = failure.name
        evidence[f"metric_{number}_role"] = failure.role
        evidence[f"metric_{number}_error"] = wording.error.value
        evidence[f"metric_{number}_message"] = message[:_MAX_EVIDENCE_MESSAGE_LENGTH] if message else None
    return evidence


def _word(failure: MetricCompileFailure) -> _Wording:
    return word_compile_error(failure.kind, failure.message, failure.definition)


def word_compile_error(
    kind: ExperimentHealthMetricCompileErrorKind, message: str | None, definition: Mapping[str, Any]
) -> _Wording:
    """The words for an error that building the query of a metric with `definition` raised."""
    match kind:
        case ExperimentHealthMetricCompileErrorKind.DEFINITION if message is not None:
            return _Wording(
                error=MetricCompileError.INVALID_DEFINITION,
                explanation=f"Its saved settings aren't valid: {_sentence(message)} Create the metric again, or edit it "
                "to fix the setting.",
            )
        case ExperimentHealthMetricCompileErrorKind.REJECTED if (
            message is not None and _COMPOUND_AGGREGATION in message
        ):
            return _Wording(
                error=MetricCompileError.COMPOUND_AGGREGATION,
                explanation="Its SQL expression combines several aggregations, such as sum(a) / count(). The expression "
                "can hold one aggregation, such as sum(properties.revenue). To divide one sum by another, use a ratio "
                "metric.",
            )
        case ExperimentHealthMetricCompileErrorKind.REJECTED if message is not None:
            return _Wording(error=MetricCompileError.REJECTED, explanation=_sentence(message))
        case ExperimentHealthMetricCompileErrorKind.SYNTAX if message is not None:
            return _Wording(
                error=MetricCompileError.SYNTAX_ERROR,
                explanation=f"An SQL expression of the metric has a syntax error: {_sentence(message)} Correct the "
                "expression.",
            )
        case ExperimentHealthMetricCompileErrorKind.QUERY if message is not None:
            for pattern, subject, word in _QUERY_RULES:
                found = pattern.search(message)
                if found and (subject is None or _mentions(definition, found.group(subject))):
                    return word(found, message)
    return _Wording(
        error=MetricCompileError.OTHER,
        explanation=(f"Building its query fails: {_sentence(message)}" if message else "Building its query fails.")
        + " Check the metric's settings, or contact support if they look right.",
    )


def _sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith((".", "?", "!")) else f"{text}."


def _mentions(definition: Mapping[str, Any], subject: str) -> bool:
    """Whether a value of the definition holds `subject`, such as a field name inside an SQL expression."""

    def values(node: object) -> list[str]:
        if isinstance(node, Mapping):
            return [text for value in node.values() for text in values(value)]
        if isinstance(node, list):
            return [text for value in node for text in values(value)]
        return [] if node is None else [str(node)]

    return any(subject in value for value in values(definition))


def _aggregation_arguments(match: re.Match[str], _message: str) -> _Wording:
    name = match.group("name")
    # An aggregation with a condition, such as uniqIf, comes from the plain one with the suffix If.
    plain = name[:-2] if len(name) > 2 and name.endswith("If") else None
    fix = (
        f" Use {plain}, and set the condition as a filter of the metric."
        if plain
        else " Use an aggregation that takes one argument, such as sum or max."
    )
    return _Wording(
        error=MetricCompileError.AGGREGATION_ARGUMENTS,
        explanation=f"Its SQL expression uses {name}, and PostHog passes only the first argument of the aggregation "
        f"to it, so {name} gets too few arguments.{fix}",
    )


def _unknown_function(match: re.Match[str], _message: str) -> _Wording:
    suggestion = match.group("suggestion")
    return _Wording(
        error=MetricCompileError.UNKNOWN_FUNCTION,
        explanation=f"Its SQL expression calls {match.group('name')}, which PostHog doesn't support."
        + (f" Did you mean {suggestion}?" if suggestion else " Check the name of the function."),
    )


_SUGGESTIONS = re.compile(r"Did you mean: (?P<first>[^,?]+)")
_PROPERTY_HINT = re.compile(r"is a custom property, read it as (?P<path>.+?)\.(?:\s|$)")


def _unknown_field(match: re.Match[str], message: str) -> _Wording:
    name = match.group("name")
    suggestion = _SUGGESTIONS.search(message)
    hint = _PROPERTY_HINT.search(message)
    if suggestion:
        fix = f" Did you mean {suggestion.group('first')}?"
    elif hint:
        fix = f" If {name} is an event property, write {hint.group('path')}."
    else:
        fix = " Check the name of the field."
    return _Wording(
        error=MetricCompileError.UNKNOWN_FIELD,
        explanation=f'It reads "{name}", which isn\'t a field that PostHog knows.{fix}',
    )


def _deleted_cohort(match: re.Match[str], _message: str) -> _Wording:
    return _Wording(
        error=MetricCompileError.DELETED_COHORT,
        explanation=f"A filter of the metric uses a cohort that doesn't exist anymore (ID {match.group('id')}). "
        "Remove the filter, or choose another cohort.",
    )


def _invalid_regex(match: re.Match[str], _message: str) -> _Wording:
    return _Wording(
        error=MetricCompileError.INVALID_REGEX,
        explanation=f'A filter of the metric uses the regular expression "{match.group("regex")}", which PostHog '
        "can't run. PostHog supports the RE2 syntax, which has no lookaheads, such as (?!...), and no backreferences. "
        "Rewrite the expression.",
    )


def _incomplete_behavioral_filter(_match: re.Match[str], _message: str) -> _Wording:
    return _Wording(
        error=MetricCompileError.INCOMPLETE_BEHAVIORAL_FILTER,
        explanation="A behavioral filter of the metric is incomplete. Set all of its fields, such as the time "
        "range, or remove the filter.",
    )


def _unsupported_element_operator(match: re.Match[str], _message: str) -> _Wording:
    key = match.group("key")
    return _Wording(
        error=MetricCompileError.UNSUPPORTED_ELEMENT_OPERATOR,
        explanation=f"A filter of the metric on the element's {_ELEMENT_LABELS.get(key, key)} uses an operator "
        'that this filter doesn\'t support. Use "equals" or "doesn\'t equal".',
    )


def _missing_warehouse_table(match: re.Match[str], message: str) -> _Wording:
    suggestion = _SUGGESTIONS.search(message)
    return _Wording(
        error=MetricCompileError.MISSING_WAREHOUSE_TABLE,
        explanation=f'It reads the data warehouse table "{match.group("table")}", which this project doesn\'t '
        "have." + (f" Did you mean {suggestion.group('first')}?" if suggestion else " Choose another table."),
    )


# Each rule is a pattern of the compiler's message, the group that the definition must hold (None when the message
# names nothing), and the words. The first rule that matches applies.
_QUERY_RULES: tuple[tuple[re.Pattern[str], str | None, Callable[[re.Match[str], str], _Wording]], ...] = (
    (re.compile(r"Aggregation '(?P<name>\w+)' expects"), "name", _aggregation_arguments),
    (
        re.compile(
            r"Unsupported function call '(?P<name>[^'(]+)\(\.\.\.\)'"
            r"(?:\. Perhaps you meant '(?P<suggestion>[^'(]+)\(\.\.\.\)'\?)?"
        ),
        "name",
        _unknown_function,
    ),
    (re.compile(r"(?:Unable to resolve field|Field not found): `?(?P<name>[^\s`.]+)"), "name", _unknown_field),
    (re.compile(r"Cohort (?P<id>\d+) does not exist"), "id", _deleted_cohort),
    (re.compile(r"Could not find cohort with ID (?P<id>\d+)"), "id", _deleted_cohort),
    (re.compile(r"Invalid regular expression: '(?P<regex>.*)'"), "regex", _invalid_regex),
    (re.compile(r"Invalid behavioral property filter"), None, _incomplete_behavioral_filter),
    (re.compile(r"property_to_expr for element (?P<key>\w+) only supports"), None, _unsupported_element_operator),
    (re.compile(r"Unknown table `(?P<table>[^`]+)`"), "table", _missing_warehouse_table),
)

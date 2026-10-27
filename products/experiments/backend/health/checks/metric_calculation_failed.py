"""
Metrics whose latest calculation failed, so the results page shows an error in place of their results. Pure
functions, no I/O.

The page shows the stored error text, which is often the raw text of an exception. The finding says in words what
kind of failure it was and what to do next. It repeats a message only when PostHog wrote it for users: the message of
a validation error, or a HogQL message that the metric queries check also words. The text of other exceptions is
written for engineers.
"""

import re
from dataclasses import replace
from enum import StrEnum

from posthog.dataclasses import frozen

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
    ExperimentHealthMetricCompileErrorKind,
)
from products.experiments.backend.health.checks.metric_cannot_compile import MetricCompileError, word_compile_error
from products.experiments.backend.health.context import HealthContext, MetricCalculationFailure
from products.experiments.backend.health.skips import (
    NOT_ON_ARCHIVED,
    RUNS_AFTER_LAUNCH,
    CheckOutcome,
    not_applicable,
    not_checked,
)
from products.experiments.backend.hogql_queries.error_handling import ERROR_TYPE_MESSAGES
from products.experiments.backend.recalculation import RECALCULATION_WINDOW_TOO_LONG_MESSAGE
from products.experiments.backend.temporal.models import RECALCULATION_WINDOW_TOO_LONG_ERROR_TYPE
from products.experiments.stats.shared.statistics import StatisticError


class MetricCalculationFailureKind(StrEnum):
    # pinned: the finding's subcode and `evidence.metric_N_failure`.
    BUSY = "busy"
    QUERY_LIMIT = "query_limit"
    SETTINGS = "settings"
    NOT_ENOUGH_DATA = "not_enough_data"
    EXPERIMENT_TOO_OLD = "experiment_too_old"
    UNEXPECTED_ERROR = "unexpected_error"


# The kinds that a change of the metric or the experiment fixes. The others go away with time or a retry.
_NEEDS_A_FIX = frozenset(
    {
        MetricCalculationFailureKind.QUERY_LIMIT,
        MetricCalculationFailureKind.SETTINGS,
        MetricCalculationFailureKind.EXPERIMENT_TOO_OLD,
    }
)
_MAX_EVIDENCE_MESSAGE_LENGTH = 300
_LIMIT_NEEDS = {
    "read_limit": "needed to read more data",
    "memory_limit": "needed more memory",
    "time_limit": "took longer",
}

# A failure stored before calculations stored the class of the error has only its message, and some classes are too
# wide, so these rules read the message. They follow the messages of `ClickHouseAtCapacity`, of the ClickHouse
# limits, of the calculation's own time limit and of the friendly texts in `ERROR_TYPE_MESSAGES`.
_BUSY_MESSAGE = re.compile(r"too busy|Too many queries|maximum concurrency", re.IGNORECASE)
_READ_LIMIT = re.compile(r"Limit for rows or bytes to read exceeded")
_MEMORY_LIMIT = re.compile(r"ran out of memory|using too much memory|memory limit", re.IGNORECASE)
_TIME_LIMIT = re.compile(r"max execution time|ran out of time", re.IGNORECASE)
# A DRF validation error is stored as the `repr` of its detail list.
_VALIDATION_ERROR = re.compile(
    r"^\[ErrorDetail\(string=(?P<quote>['\"])(?P<text>.*?)(?P=quote), code='(?P<code>[^']*)'\)", re.DOTALL
)
# pydantic's text for a stored definition that its schema rejects. The rest of the text quotes the stored values.
_SCHEMA_ERROR = re.compile(r"^\d+ validation errors? for (?P<model>\w+)")
_TYPE_MISMATCH = re.compile(r"There is no supertype for types|Cannot convert string .* to type")
_NO_DATA = re.compile(r"No control variant found|No exposures for the '.*' variant yet")
_NOT_ENOUGH_DATA_TEXTS = frozenset({ERROR_TYPE_MESSAGES[StatisticError], ERROR_TYPE_MESSAGES[ZeroDivisionError]})


@frozen
class _Wording:
    kind: MetricCalculationFailureKind
    # The class of the error inside the kind, such as the limit or the family of a setting. None when the kind is all.
    error: str | None
    # What went wrong and what to do, after the sentence that names the metric.
    explanation: str
    # The message, when PostHog wrote it for users.
    message: str | None = None


_UNEXPECTED = _Wording(
    kind=MetricCalculationFailureKind.UNEXPECTED_ERROR,
    error=None,
    explanation="Its query failed with an unexpected error. Try again, and contact support if it keeps failing.",
)
_BUSY = _Wording(
    kind=MetricCalculationFailureKind.BUSY,
    error=None,
    explanation="PostHog was too busy to run its query. Try again in a few minutes.",
)
# The words of the kinds above when the page has no button to try again: after the end the page shows no "Refresh
# results" button, and only an error stored as retriable gets a "Try again" button.
_WITHOUT_RETRY_AFTER_END = {
    MetricCalculationFailureKind.BUSY: "PostHog was too busy to run its query. Contact support to calculate it again.",
    MetricCalculationFailureKind.UNEXPECTED_ERROR: "Its query failed with an unexpected error. Contact support for "
    "help.",
}
_NOT_ENOUGH_DATA = _Wording(
    kind=MetricCalculationFailureKind.NOT_ENOUGH_DATA,
    error=None,
    explanation="There wasn't enough data to calculate it. Results show once each variant has more exposures and "
    "events.",
)
# After the end the experiment collects no more exposures, so the words can't promise results.
_NOT_ENOUGH_DATA_AFTER_END = "There wasn't enough data to calculate it before the experiment ended."


def metric_calculation_failed(ctx: HealthContext) -> CheckOutcome:
    if ctx.archived:
        return not_applicable(NOT_ON_ARCHIVED)
    if not ctx.is_launched:
        return not_applicable(RUNS_AFTER_LAUNCH)
    calculation = ctx.latest_calculation
    if calculation is None:
        return not_checked("Couldn't check because the latest calculation couldn't be read")
    if calculation.finished_at is None:
        return not_applicable("Runs once a calculation of the metrics has finished")
    if not calculation.failures:
        return None
    # A metric whose query doesn't compile fails every calculation, and the metric queries check words that better.
    not_compiling = {failure.metric_id for failure in ctx.metric_compiles.failures} if ctx.metric_compiles else set()
    worded = [
        (failure, _word(failure, ended=ctx.has_ended))
        for failure in calculation.failures
        if failure.metric_id not in not_compiling
    ]
    if not worded:
        return not_applicable("The metric queries check reports the metric that failed")
    worded.sort(key=lambda item: (item[0].role != "primary", item[1].kind not in _NEEDS_A_FIX))
    count = len(worded)
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.METRIC_CALCULATION_FAILED,
        subcode=worded[0][1].kind.value,
        # A retry or more data fixes the other kinds. A kind that needs a fix stays a warning after the end, because
        # the calculation after the fix reads the events up to the end and brings back the results.
        severity=ExperimentHealthFindingSeverity.WARNING
        if any(failure.role == "primary" and wording.kind in _NEEDS_A_FIX for failure, wording in worded)
        else ExperimentHealthFindingSeverity.INFO,
        title=f"Latest calculation failed for {count} {'metric' if count == 1 else 'metrics'}",
        detail=" ".join(
            f'The latest calculation of the {failure.role} metric "{failure.name}" failed. {wording.explanation}'
            for failure, wording in worded
        ),
        evidence={"calculated_at": calculation.finished_at.isoformat(), **_evidence(worded)},
        # No action opens a given metric.
        actions=(),
        diagnostic_ref=None,
    )


def _evidence(worded: list[tuple[MetricCalculationFailure, _Wording]]) -> dict[str, str | None]:
    evidence: dict[str, str | None] = {}
    for number, (failure, wording) in enumerate(worded, start=1):
        evidence[f"metric_{number}"] = failure.name
        evidence[f"metric_{number}_role"] = failure.role
        evidence[f"metric_{number}_failure"] = wording.kind.value
        evidence[f"metric_{number}_error"] = wording.error
        evidence[f"metric_{number}_message"] = (
            wording.message[:_MAX_EVIDENCE_MESSAGE_LENGTH] if wording.message else None
        )
    return evidence


def _word(failure: MetricCalculationFailure, *, ended: bool) -> _Wording:
    wording = _word_error(failure)
    if not ended:
        return wording
    if wording.kind == MetricCalculationFailureKind.NOT_ENOUGH_DATA:
        return replace(wording, explanation=_NOT_ENOUGH_DATA_AFTER_END)
    if wording.kind in _WITHOUT_RETRY_AFTER_END and not failure.retriable:
        return replace(wording, explanation=_WITHOUT_RETRY_AFTER_END[wording.kind])
    return wording


def _word_error(failure: MetricCalculationFailure) -> _Wording:
    error_type = failure.error_type
    message = failure.message
    if error_type == "rate_limited" or _BUSY_MESSAGE.search(message):
        return _BUSY
    limit = _limit(error_type, message)
    if limit is not None:
        return _Wording(
            kind=MetricCalculationFailureKind.QUERY_LIMIT,
            error=limit,
            explanation=f"Its query {_LIMIT_NEEDS[limit]} than PostHog allows for one calculation. A query reads "
            "more data the longer an experiment runs and the more traffic it gets. Simplify the metric, for example "
            "with fewer funnel steps, or contact support for help.",
        )
    if error_type == "insufficient_data" or (error_type is None and _NO_DATA.search(message)):
        return _NOT_ENOUGH_DATA
    if error_type == RECALCULATION_WINDOW_TOO_LONG_ERROR_TYPE:
        return _Wording(
            kind=MetricCalculationFailureKind.EXPERIMENT_TOO_OLD,
            error=None,
            explanation=RECALCULATION_WINDOW_TOO_LONG_MESSAGE,
        )
    # The other steps fail before the query runs, for example on a metric that the calculation doesn't know yet.
    if failure.step not in (None, "calculation"):
        return _UNEXPECTED
    return _settings(failure) or _UNEXPECTED


def _limit(error_type: str | None, message: str) -> str | None:
    """The limit of `_LIMIT_NEEDS` that the query reached, or None."""
    # A read limit can arrive as a validation error, so the message decides before the class does.
    if error_type == "byte_limit" or _READ_LIMIT.search(message):
        return "read_limit"
    if error_type == "out_of_memory" or _MEMORY_LIMIT.search(message):
        return "memory_limit"
    if error_type == "timeout" or _TIME_LIMIT.search(message):
        return "time_limit"
    return None


def _settings(failure: MetricCalculationFailure) -> _Wording | None:
    """The words for a failure that a setting of the metric or the experiment caused, or None when the failure isn't
    known to be one."""
    message = failure.message
    validation = _VALIDATION_ERROR.match(message)
    if validation is not None:
        return _validation_error(failure, validation.group("text"), validation.group("code"))
    schema = _SCHEMA_ERROR.match(message)
    if schema is not None:
        if schema.group("model") == "ExperimentExposureCriteria":
            return _setting(
                "invalid_exposure_criteria",
                "The experiment's exposure criteria aren't valid, so no metric can be calculated. Edit the exposure "
                "criteria and save them again.",
            )
        return _setting(
            MetricCompileError.INVALID_DEFINITION.value,
            "Its saved settings aren't valid. Create the metric again, or edit it to fix the setting.",
        )
    if _TYPE_MISMATCH.search(message):
        return _setting(
            "type_mismatch",
            "A filter or an expression of the metric compares values of different types, such as text with a "
            "number. Check the types of the properties that the metric filters on.",
        )
    wording = word_compile_error(ExperimentHealthMetricCompileErrorKind.QUERY, message, failure.definition)
    if wording.error != MetricCompileError.OTHER:
        return _setting(wording.error.value, wording.explanation, message)
    if failure.error_type == "validation_error":
        return _setting(
            MetricCompileError.OTHER.value,
            "A setting of the metric makes its query fail. Check the metric's settings, or contact support if they "
            "look right.",
        )
    return None


def _validation_error(failure: MetricCalculationFailure, text: str, code: str) -> _Wording:
    if code == "no_data":
        return _Wording(kind=MetricCalculationFailureKind.NOT_ENOUGH_DATA, error=None, explanation=text, message=text)
    if text in _NOT_ENOUGH_DATA_TEXTS:
        return _NOT_ENOUGH_DATA
    # The query runner gives these texts to errors of PostHog, not of the metric.
    if text in ERROR_TYPE_MESSAGES.values():
        return _UNEXPECTED
    wording = word_compile_error(ExperimentHealthMetricCompileErrorKind.REJECTED, text, failure.definition)
    return _setting(wording.error.value, wording.explanation, text)


def _setting(error: str, explanation: str, message: str | None = None) -> _Wording:
    return _Wording(kind=MetricCalculationFailureKind.SETTINGS, error=error, explanation=explanation, message=message)

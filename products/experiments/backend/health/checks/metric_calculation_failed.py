"""
Metrics whose latest calculation failed, so the results page shows an error in place of their results. Pure
functions, no I/O.

The page shows the stored error text, which is often the raw text of an exception. The finding says in words what
kind of failure it was and what to do next. It repeats a message only when PostHog's query builder wrote it for
users, as the message of a validation error. It doesn't repeat HogQL's text, which the calculation writes without the
reader's warehouse access, or the text of other exceptions, which is written for engineers.
"""

import re
from dataclasses import replace
from enum import StrEnum

from posthog.dataclasses import frozen
from posthog.exceptions import ClickHouseClusterMemoryLimitExceeded

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
    ExperimentHealthMetricCompileErrorKind,
)
from products.experiments.backend.facade.enums import ExposuresPath
from products.experiments.backend.health.checks.events_received import joined
from products.experiments.backend.health.checks.metric_cannot_compile import MetricCompileError, word_compile_error
from products.experiments.backend.health.context import (
    ExposureFilterSource,
    ExposureFilterWithoutColumn,
    HealthContext,
    LatestCalculation,
    MetricCalculationFailure,
)
from products.experiments.backend.health.skips import (
    NOT_ON_ARCHIVED,
    RUNS_AFTER_LAUNCH,
    CheckOutcome,
    no_calculated_metric,
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


class QueryLimitCause(StrEnum):
    # pinned: the finding's `reason` when its subcode is `query_limit`.
    EXPOSURE_CRITERIA = "exposure_criteria"
    METRIC = "metric"


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
_FILTER_OWNERS = {
    ExposureFilterSource.EXPOSURE_CRITERIA: "the exposure criteria's",
    ExposureFilterSource.EXPOSURE_ACTION: "the exposure action's",
    ExposureFilterSource.TEST_ACCOUNTS: "the test account",
}
_QUERY_SIZE_LIMIT = "query_size"

# A failure stored before calculations stored the class of the error has only its message, and some classes are too
# wide, so these rules read the message. They follow the messages of `ClickHouseAtCapacity`, of the ClickHouse
# limits, of the calculation's own time limit and of the friendly texts in `ERROR_TYPE_MESSAGES`.
# A socket timeout is stored as a timeout, but PostHog words it as a temporary problem of the database, so it counts as
# busy.
_BUSY_MESSAGE = re.compile(
    r"too busy|Too many queries|maximum concurrency|temporary problem|while (?:reading from|writing to) socket",
    re.IGNORECASE,
)
# Stored as out of memory, because the class subclasses the memory limit of one query, but the cluster was full and the
# query can be fine, so it counts as busy. The rule reads the class's own text, so a change of the wording can't turn
# the failure into a query limit.
_CLUSTER_MEMORY_FULL = str(ClickHouseClusterMemoryLimitExceeded.default_detail)
_QUERY_SIZE = re.compile(r"query size exceeded", re.IGNORECASE)
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
# Django's text when the query names a cohort that was deleted. It names no cohort, so the wording can't say where.
_DELETED_COHORT = re.compile(r"Cohort matching query does not exist")
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
    # Whether a setting of the experiment causes the failure, which then fails every metric, so the finding says the
    # explanation once and names no metric in it.
    every_metric: bool = False
    # What caused the failure, when the words name it.
    reason: str | None = None
    # The filters that the words name.
    exposure_filters: tuple[ExposureFilterWithoutColumn, ...] = ()


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
_EXPOSURE_QUERY = _Wording(
    kind=MetricCalculationFailureKind.SETTINGS,
    error="exposure_query",
    explanation="The experiment's exposure criteria or the project's test account filters can't be built into a "
    "query, so no metric can be calculated. Check them, or contact support if they look right.",
    every_metric=True,
)


def metric_calculation_failed(ctx: HealthContext) -> CheckOutcome:
    if ctx.archived:
        return not_applicable(NOT_ON_ARCHIVED)
    if not ctx.is_launched:
        return not_applicable(RUNS_AFTER_LAUNCH)
    calculation = ctx.latest_calculation
    if calculation is None:
        return not_checked("Couldn't check because the latest calculation couldn't be read")
    if calculation.metric_count == 0:
        return no_calculated_metric(ctx)
    if calculation.finished_at is None:
        return not_applicable("Runs once a calculation of the metrics has finished")
    if not calculation.failures:
        return None
    compiles = ctx.metric_compiles
    # A metric whose query doesn't compile fails every calculation, and `metric_cannot_compile` words that better.
    not_compiling = {failure.metric_id for failure in compiles.failures} if compiles else set()
    exposure_query_fails = compiles is not None and compiles.exposure_query_fails
    worded = [
        (failure, _word(failure, ended=ctx.has_ended, exposure_query_fails=exposure_query_fails))
        for failure in calculation.failures
        if failure.metric_id not in not_compiling
    ]
    if not worded:
        return not_applicable('Reported under "Invalid metric definitions"')
    worded = _with_query_limit_cause(worded, calculation, ctx.exposure_filters_without_column)
    worded.sort(key=lambda item: (item[0].role != "primary", item[1].kind not in _NEEDS_A_FIX))
    count = len(worded)
    exposure_filters = worded[0][1].exposure_filters
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.METRIC_CALCULATION_FAILED,
        subcode=worded[0][1].kind.value,
        reason=worded[0][1].reason,
        # A retry or more data fixes the other kinds. A kind that needs a fix stays a warning after the end, because
        # the calculation after the fix reads the events up to the end and brings back the results.
        severity=ExperimentHealthFindingSeverity.WARNING
        if any(failure.role == "primary" and wording.kind in _NEEDS_A_FIX for failure, wording in worded)
        else ExperimentHealthFindingSeverity.INFO,
        title=f"Latest calculation failed for {count} {'metric' if count == 1 else 'metrics'}",
        detail=" ".join(dict.fromkeys(_sentence(failure, wording) for failure, wording in worded)),
        evidence={
            "calculated_at": calculation.finished_at.isoformat(),
            **_evidence(worded),
            **({"properties": ", ".join(dict.fromkeys(f.key for f in exposure_filters))} if exposure_filters else {}),
        },
        # No action opens a given metric.
        actions=(ExperimentHealthFindingActionKind.EDIT_EXPOSURE_CRITERIA,) if exposure_filters else (),
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


def _sentence(failure: MetricCalculationFailure, wording: _Wording) -> str:
    if wording.every_metric:
        return wording.explanation
    return f'The latest calculation of the {failure.role} metric "{failure.name}" failed. {wording.explanation}'


def _word(failure: MetricCalculationFailure, *, ended: bool, exposure_query_fails: bool) -> _Wording:
    wording = _word_error(failure, exposure_query_fails=exposure_query_fails)
    if not ended:
        return wording
    if wording.kind == MetricCalculationFailureKind.NOT_ENOUGH_DATA:
        return replace(wording, explanation=_NOT_ENOUGH_DATA_AFTER_END)
    if wording.kind in _WITHOUT_RETRY_AFTER_END and not failure.retriable:
        return replace(wording, explanation=_WITHOUT_RETRY_AFTER_END[wording.kind])
    return wording


def _word_error(failure: MetricCalculationFailure, *, exposure_query_fails: bool) -> _Wording:
    error_type = failure.error_type
    message = failure.message
    if error_type == "rate_limited" or _CLUSTER_MEMORY_FULL in message or _BUSY_MESSAGE.search(message):
        return _BUSY
    limit = _limit(error_type, message)
    if limit is not None:
        return _Wording(
            kind=MetricCalculationFailureKind.QUERY_LIMIT,
            error=limit,
            explanation=_limit_explanation(limit, failure),
        )
    if error_type == "insufficient_data" or (error_type is None and _NO_DATA.search(message)):
        return _NOT_ENOUGH_DATA
    if error_type == RECALCULATION_WINDOW_TOO_LONG_ERROR_TYPE:
        return _Wording(
            kind=MetricCalculationFailureKind.EXPERIMENT_TOO_OLD,
            error=None,
            explanation=RECALCULATION_WINDOW_TOO_LONG_MESSAGE,
            every_metric=True,
        )
    # The other steps fail before the query runs, for example on a metric that the calculation doesn't know yet.
    if failure.step not in (None, "calculation"):
        return _UNEXPECTED
    # The exposure query is part of every metric's query, so a metric's query fails where the exposure query fails.
    if exposure_query_fails:
        return _EXPOSURE_QUERY
    return _settings(failure) or _UNEXPECTED


def _limit(error_type: str | None, message: str) -> str | None:
    """The limit of `_LIMIT_NEEDS`, or the limit of the query's length, that the query reached, or None."""
    if _QUERY_SIZE.search(message):
        return _QUERY_SIZE_LIMIT
    # A read limit can arrive as a validation error, so the message decides before the class does.
    if error_type == "byte_limit" or _READ_LIMIT.search(message):
        return "read_limit"
    if error_type == "out_of_memory" or _MEMORY_LIMIT.search(message):
        return "memory_limit"
    if error_type == "timeout" or _TIME_LIMIT.search(message):
        return "time_limit"
    return None


def _limit_explanation(limit: str, failure: MetricCalculationFailure) -> str:
    if limit == _QUERY_SIZE_LIMIT:
        return (
            "Its query is longer than PostHog allows. A filter with a long list of values can cause this. Shorten "
            "the filters of the metric or of the exposure criteria, or contact support for help."
        )
    return (
        f"Its query {_LIMIT_NEEDS[limit]} than PostHog allows for one calculation. A query reads more data the longer "
        f"an experiment runs and the more traffic it gets. Simplify the metric, for example with {_simpler(failure)}, "
        "or contact support for help."
    )


def _simpler(failure: MetricCalculationFailure) -> str:
    return (
        "fewer funnel steps or narrower filters"
        if failure.definition.get("metric_type") == "funnel"
        else "narrower filters"
    )


def _with_query_limit_cause(
    worded: list[tuple[MetricCalculationFailure, _Wording]],
    calculation: LatestCalculation,
    filters: tuple[ExposureFilterWithoutColumn, ...] | None,
) -> list[tuple[MetricCalculationFailure, _Wording]]:
    """The words of each failure that reached the read, memory or time limit of a query, with the cause that the rest
    of the calculation shows.

    Every metric's query reads the exposures. So when another metric of the calculation completed the same read, that
    read fits the limits, and the failing metric's own part of its query reached them. When every metric reached a
    limit and a query that read the events applies a filter that reads all the properties, that filter is the likely
    cause, unless a query read precomputed exposures. A metric that ran out of the workflow's time stores no read, so
    the other failures show the read.
    """
    limited = {
        failure.metric_id: wording.error
        for failure, wording in worded
        if wording.kind == MetricCalculationFailureKind.QUERY_LIMIT
        and wording.error is not None
        and wording.error in _LIMIT_NEEDS
    }
    if calculation.completed_count:
        return [
            (failure, _metric_cause(failure, limited[failure.metric_id], calculation.completed_count))
            if failure.metric_id in limited and failure.exposures_path in calculation.completed_exposures_paths
            else (failure, wording)
            for failure, wording in worded
        ]
    if (
        limited
        and len(limited) == calculation.metric_count
        and filters
        and {failure.exposures_path for failure, _ in worded} - {None} == {ExposuresPath.DIRECT_SCAN}
    ):
        # With one metric the words name it, as for a failure of the metric.
        every_metric = calculation.metric_count > 1
        explanation = _exposure_explanation(set(limited.values()), filters, every_metric=every_metric)
        return [
            (
                failure,
                _Wording(
                    kind=MetricCalculationFailureKind.QUERY_LIMIT,
                    error=limited[failure.metric_id],
                    explanation=explanation,
                    every_metric=every_metric,
                    reason=QueryLimitCause.EXPOSURE_CRITERIA.value,
                    exposure_filters=filters,
                ),
            )
            for failure, _ in worded
        ]
    return worded


def _metric_cause(failure: MetricCalculationFailure, limit: str, completed_count: int) -> _Wording:
    others = "another metric" if completed_count == 1 else "other metrics"
    return _Wording(
        kind=MetricCalculationFailureKind.QUERY_LIMIT,
        error=limit,
        explanation=f"Its query {_LIMIT_NEEDS[limit]} than PostHog allows for one calculation, while {others} of the "
        f"experiment returned results. Simplify this metric, for example with {_simpler(failure)}, or contact support "
        "for help.",
        reason=QueryLimitCause.METRIC.value,
    )


def _exposure_explanation(
    limits: set[str], filters: tuple[ExposureFilterWithoutColumn, ...], *, every_metric: bool
) -> str:
    needs = _LIMIT_NEEDS[next(iter(limits))] if len(limits) == 1 else "needed more resources"
    named = joined(
        [
            _named(owner, owned)
            for source, owner in _FILTER_OWNERS.items()
            if (owned := [f for f in filters if f.source == source])
        ]
    )
    read = joined(list(dict.fromkeys(f.type for f in filters)))
    one = len(filters) == 1
    the_filters = "the filter" if one else "these filters"
    query, each_query = ("Every metric's query", "each query") if every_metric else ("Its query", "the query")
    fix = (
        f"Change {the_filters}, or turn off the test account filter in the exposure criteria"
        if any(f.source == ExposureFilterSource.TEST_ACCOUNTS for f in filters)
        else f"Remove or change {the_filters}"
    )
    return (
        f"{query} {needs} than PostHog allows for one calculation. The likely cause is {named}, which "
        f"{'makes' if one else 'make'} {each_query} read all {read} properties. {fix}, or contact support for help."
    )


def _named(owner: str, filters: list[ExposureFilterWithoutColumn]) -> str:
    properties = joined([f'the {f.type} property "{f.key}"' for f in filters])
    return f"{owner} {'filter' if len(filters) == 1 else 'filters'} on {properties}"


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
            return _Wording(
                kind=MetricCalculationFailureKind.SETTINGS,
                error="invalid_exposure_criteria",
                explanation="The experiment's exposure criteria aren't valid, so no metric can be calculated. Edit "
                "the exposure criteria and save them again.",
                every_metric=True,
            )
        return _setting(
            MetricCompileError.INVALID_DEFINITION.value,
            "Its saved settings aren't valid. Create the metric again, or edit it to fix the setting.",
        )
    if _DELETED_COHORT.search(message):
        return _setting(
            MetricCompileError.DELETED_COHORT.value,
            "A filter uses a cohort that doesn't exist anymore. Check the cohorts in the metric's filters, the "
            "exposure criteria and the project's test account filters.",
        )
    if _TYPE_MISMATCH.search(message):
        return _setting(
            "type_mismatch",
            "A filter or an expression of the metric compares values of different types, such as text with a "
            "number. Check the types of the properties that the metric filters on.",
        )
    if not failure.can_quote_evaluation_rules:
        wording = word_compile_error(ExperimentHealthMetricCompileErrorKind.QUERY, message, failure.definition)
        if wording.error != MetricCompileError.OTHER:
            # Unlike `metric_cannot_compile`, which compiles as the reader, the evidence leaves out HogQL's text.
            return _setting(wording.error.value, wording.explanation)
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

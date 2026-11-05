"""
Compiles the query of each metric that the experiment calculates, without running it, so that a metric that every
calculation fails on shows before launch. The compile is the query runner's own, so it fails where a calculation
fails before ClickHouse receives the query. A failure inside ClickHouse, such as a type that the data holds, doesn't
show here.

The compile runs as the reader, with the reader's warehouse access. The compiler's messages, such as its "Did you mean"
suggestions, can name any table or column that the compile can see, so a reader only sees names they may query. A
metric that reads a table or a view that the reader may not query is not checked for them.

Only an answer without a compiler message is cached, per reader and per input of the compile. A failure's message can
name the tables that the reader may query, and a denial is a decision on the reader's access, so both compile again on
every read and follow the reader's current access. The cache key doesn't hold the cohorts, actions and warehouse tables
that a metric names, or the reader's access, so a metric that compiled can show as passing until its answer expires,
also after one of them is deleted or the reader loses access.
"""

import re
import json
import hashlib
from collections.abc import Mapping
from datetime import timedelta
from enum import StrEnum
from typing import Any

from django.core.cache import cache

import pydantic
from rest_framework.exceptions import ValidationError

from posthog.schema import ExperimentQuery

from posthog.hogql.database.database import Database
from posthog.hogql.errors import (
    ExposedHogQLError,
    NotImplementedError as HogQLNotImplementedError,
    SyntaxError as HogQLSyntaxError,
    TableAccessDeniedError,
)

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models.user import User

from products.ai_observability.backend.facade.api import mentions_evaluation_pass_markers
from products.experiments.backend.facade.contracts import ExperimentHealthMetricCompileErrorKind
from products.experiments.backend.health.context import MetricCompileFailure, MetricCompiles
from products.experiments.backend.hogql_queries.error_handling import get_user_friendly_message
from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.metric_calculation.config import (
    MetricCalculationConfig,
    build_calculation_configs,
    calculation_metric_name,
    team_experiments_configs,
)
from products.experiments.backend.metric_resolution import build_metric
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig

# Part of the cache key. Raise it when the cached answer changes shape.
_ANSWER_SHAPE = 1
_MAX_MESSAGE_LENGTH = 1000


class _Outcome(StrEnum):
    COMPILES = "compiles"
    # The compile raised an error that names no problem of the metric, such as a defect of PostHog.
    UNKNOWN = "unknown"
    # The metric reads a warehouse table or view that the reader may not query.
    NO_ACCESS = "no_access"
    EXPOSURE_QUERY_FAILS = "exposure_query_fails"


@frozen
class _Failure:
    kind: ExperimentHealthMetricCompileErrorKind
    message: str


# A failure and NO_ACCESS depend on the reader's current access, as the module docstring explains, so they aren't cached.
_CACHE_SECONDS = {
    _Outcome.COMPILES: int(timedelta(days=1).total_seconds()),
    # The cause can go away without an edit of the metric, for example when a deleted cohort is restored.
    _Outcome.UNKNOWN: int(timedelta(hours=1).total_seconds()),
    _Outcome.EXPOSURE_QUERY_FAILS: int(timedelta(hours=1).total_seconds()),
}
# The errors that the configuration of the experiment causes. HogQL raises its NotImplementedError for a filter that
# combines settings it doesn't support, such as an element selector with "contains".
_CONFIGURATION_ERRORS = (ValidationError, ExposedHogQLError, HogQLNotImplementedError, pydantic.ValidationError)


def load_metric_compiles(experiment: Experiment, *, user: User | None) -> MetricCompiles | None:
    """The compile of each metric that the experiment calculates, as `user`, or None when it fails. Never raises: the
    check then reports that it couldn't check. Without a user, a metric that reads the warehouse is not checked."""
    try:
        return _load_metric_compiles(experiment, user)
    except Exception as error:
        capture_exception(error)
        return None


def _load_metric_compiles(experiment: Experiment, user: User | None) -> MetricCompiles:
    team_config = team_experiments_configs([experiment.team_id])[experiment.team_id]
    # Metrics that share a uuid share its first definition, so one compile covers them.
    configs: dict[str, MetricCalculationConfig] = {}
    for calculation_config in build_calculation_configs(experiment, team_config=team_config):
        configs.setdefault(calculation_config.metric_id, calculation_config)
    compiler = _MetricCompiler(experiment, team_config=team_config, user=user)
    failures: list[MetricCompileFailure] = []
    unknown_count = 0
    no_access_count = 0
    exposure_query_fails = False
    for calculation_config in configs.values():
        match _answer(compiler, calculation_config):
            case _Outcome.UNKNOWN:
                unknown_count += 1
            case _Outcome.NO_ACCESS:
                no_access_count += 1
            case _Outcome.EXPOSURE_QUERY_FAILS:
                exposure_query_fails = True
            case _Failure(kind=kind, message=message):
                failures.append(
                    MetricCompileFailure(
                        metric_id=calculation_config.metric_id,
                        name=calculation_metric_name(experiment, calculation_config),
                        role=calculation_config.role,
                        kind=kind,
                        message=None if _can_hold_evaluation_rules(kind, calculation_config) else message,
                        definition=calculation_config.definition,
                    )
                )
    return MetricCompiles(
        metric_count=len(configs),
        failures=() if exposure_query_fails else tuple(failures),
        unknown_count=unknown_count,
        no_access_count=no_access_count,
        exposure_query_fails=exposure_query_fails,
    )


def can_hold_evaluation_rules(definition: Mapping[str, Any]) -> bool:
    """Whether a HogQL message about the query of a metric with `definition` can quote the team's evaluation rules."""
    # The compile replaces each marker with the team's evaluation rules, so a HogQL message can quote them.
    return mentions_evaluation_pass_markers(json.dumps(definition, default=str))


def _can_hold_evaluation_rules(
    kind: ExperimentHealthMetricCompileErrorKind, calculation_config: MetricCalculationConfig
) -> bool:
    # The query builder's own messages don't quote the evaluation rules.
    return kind != ExperimentHealthMetricCompileErrorKind.REJECTED and can_hold_evaluation_rules(
        calculation_config.definition
    )


def _answer(compiler: "_MetricCompiler", calculation_config: MetricCalculationConfig) -> _Outcome | _Failure:
    cache_key = _cache_key(compiler.experiment.team_id, compiler.user, calculation_config)
    cached = cache.get(cache_key)
    if isinstance(cached, str) and cached in _CACHE_SECONDS:
        return _Outcome(cached)
    answer: _Outcome | _Failure
    try:
        answer = compiler.compile(calculation_config.definition)
    except Exception as error:
        capture_exception(error)
        answer = _Outcome.UNKNOWN
    if isinstance(answer, _Outcome) and answer in _CACHE_SECONDS:
        cache.set(cache_key, answer.value, _CACHE_SECONDS[answer])
    return answer


class _MetricCompiler:
    """Compiles the metrics of one experiment as one reader, against one HogQL database, which is the costly part of
    a compile."""

    def __init__(self, experiment: Experiment, *, team_config: TeamExperimentsConfig, user: User | None) -> None:
        self.experiment = experiment
        self.user = user
        self._team_config = team_config
        self._database: Database | None = None

    def compile(self, definition: dict[str, Any]) -> _Outcome | _Failure:
        try:
            metric = build_metric(definition)
        except pydantic.ValidationError as error:
            return _failure(ExperimentHealthMetricCompileErrorKind.DEFINITION, _definition_message(error))
        runner = ExperimentQueryRunner(
            query=ExperimentQuery(experiment_id=self.experiment.id, metric=metric),
            team=self.experiment.team,
            user=self.user,
            user_facing=False,
            error_event_context=None,
            experiment=self.experiment,
            team_experiments_config=self._team_config,
        )
        if self._database is None:
            # A compile only validates the query, as editor assist does, so it can read the team's catalog from HogQL's
            # short-lived cache. HogQL applies the reader's current access on every read.
            self._database = runner.create_database(runner.query_modifiers(), use_cached_sources=True)
        try:
            runner.compile_query(self._database)
        except TableAccessDeniedError:
            return _Outcome.NO_ACCESS
        except _CONFIGURATION_ERRORS as error:
            # The exposure criteria and the project's test account filters are part of every metric's query, so a
            # failure in them fails every metric and isn't a problem of the metric.
            if not self._exposure_query_compiles(runner):
                return _Outcome.EXPOSURE_QUERY_FAILS
            return _failure(_error_kind(error), _error_message(error))
        return _Outcome.COMPILES

    def _exposure_query_compiles(self, runner: ExperimentQueryRunner) -> bool:
        assert self._database is not None
        try:
            runner.compile_exposure_query(self._database)
        except _CONFIGURATION_ERRORS:
            return False
        return True


def _failure(kind: ExperimentHealthMetricCompileErrorKind, message: str) -> _Failure:
    return _Failure(kind=kind, message=message[:_MAX_MESSAGE_LENGTH])


def _error_kind(error: Exception) -> ExperimentHealthMetricCompileErrorKind:
    if isinstance(error, ValidationError):
        return ExperimentHealthMetricCompileErrorKind.REJECTED
    if isinstance(error, HogQLSyntaxError):
        return ExperimentHealthMetricCompileErrorKind.SYNTAX
    if isinstance(error, pydantic.ValidationError):
        return ExperimentHealthMetricCompileErrorKind.DEFINITION
    return ExperimentHealthMetricCompileErrorKind.QUERY


# The fields of the scope that a field doesn't resolve in, which name the columns that the query builder generates.
# The list ends at the hints that follow it, or at the end of the message, because a column name can hold a dot.
_AVAILABLE_FIELDS = re.compile(r"\. Available fields: .*?\.(?= If |$)", re.DOTALL)


def without_available_fields(message: str) -> str:
    return _AVAILABLE_FIELDS.sub(".", message)


def _error_message(error: Exception) -> str:
    if isinstance(error, ValidationError):
        return get_user_friendly_message(error) or str(error)
    if isinstance(error, pydantic.ValidationError):
        return _definition_message(error)
    return without_available_fields(str(error))


def _definition_message(error: pydantic.ValidationError) -> str:
    # The location and the reason only. The full text echoes the stored values and runs to many lines.
    details = error.errors()
    # A part with brackets names the member of a union that pydantic tried, such as `str-enum[BaseMathType]`.
    locations = list(
        dict.fromkeys(".".join(str(part) for part in detail["loc"] if "[" not in str(part)) for detail in details)
    )
    if len(details) == 1:
        return f"{locations[0]}: {details[0]['msg']}"
    return f"PostHog doesn't accept the value of {', '.join(locations[:3])}"


def _cache_key(team_id: int, user: User | None, calculation_config: MetricCalculationConfig) -> str:
    settings = calculation_config.settings
    # Every input of the compile except the dates, which change only constants of the query, so a draft's answer
    # still holds after launch.
    inputs = json.dumps(
        [
            _ANSWER_SHAPE,
            calculation_config.metric,
            settings.feature_flag_key,
            settings.aggregation_group_type_index,
            settings.variants,
            settings.stored_exposure_criteria,
            settings.test_account_filters,
            settings.only_count_matured_users,
            settings.cuped.enabled,
            settings.cuped.lookback_days,
            settings.timezone,
        ],
        sort_keys=True,
        default=str,
    )
    digest = hashlib.sha256(inputs.encode()).hexdigest()
    # The reader decides which warehouse tables the compile sees, so each reader has an answer of their own.
    return f"experiment_metric_compile:{team_id}:{user.pk if user else 'none'}:{digest}"

"""
Loads the split changes of a running experiment's flag since launch, and asks ClickHouse whether anyone was
exposed before each change. A change before the first exposure moved nobody, so it does not count.

The answer for a past window does not change, so it is cached per window. A slow answer is then paid once per
change, not on every load of the experiment page. A failed query is cached as unknown too, so a scan that is
too large for a request runs at most once a day.
"""

import json
import hashlib
from collections.abc import Sequence
from datetime import datetime, timedelta
from time import monotonic

from django.core.cache import cache
from django.utils import timezone

from posthog.schema import ActionsNode

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.exceptions import (
    ClickHouseEstimatedQueryExecutionTimeTooLong,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQueryTimeOut,
)
from posthog.exceptions_capture import capture_exception
from posthog.models.activity_logging.activity_log import ActivityLog

from products.actions.backend.models.action import Action
from products.experiments.backend.health.context import SplitChange, SplitHistory
from products.experiments.backend.health.split_changes import (
    same_assignment,
    split_change_from_activity,
    split_variant_keys,
)
from products.experiments.backend.hogql_queries.exposure_query_logic import (
    build_exposure_event_conditions,
    get_exposure_event_and_property,
    normalize_to_exposure_criteria,
    resolve_default_exposure_event,
)
from products.experiments.backend.models.experiment import Experiment

MAX_EXPOSURE_QUERIES = 20
EXPOSURE_QUERY_TIMEOUT_SECONDS = 10
# No query starts after this, so one request takes at most this plus one query's timeout.
REQUEST_BUDGET_SECONDS = 10
_ANSWER_CACHE_SECONDS = int(timedelta(days=30).total_seconds())
# A scan too large for a request stays too large, so it waits a day. Another error can be brief, and an
# unknown answer shows the finding, so it waits an hour.
_TOO_EXPENSIVE_CACHE_SECONDS = int(timedelta(days=1).total_seconds())
_FAILED_CACHE_SECONDS = int(timedelta(hours=1).total_seconds())
_UNKNOWN = "unknown"
# Events can arrive after the window ends, so a "nobody" answer for a recent window can still change.
_SETTLED_AFTER = timedelta(hours=1)
# The scan is too large for a request. These are expected, so they are not reported.
_TOO_EXPENSIVE_ERRORS = (
    ClickHouseQueryTimeOut,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseEstimatedQueryExecutionTimeTooLong,
)


def load_split_history(experiment: Experiment) -> SplitHistory | None:
    """
    The split history of a running, not archived experiment whose flag exists and is not deleted, or None.
    Never raises: the health endpoint serves the other findings when this fails.
    """
    try:
        return _load_split_history(experiment)
    except Exception as error:
        capture_exception(error)
        return None


def query_any_exposure(
    experiment: Experiment,
    *,
    window_start: datetime,
    window_end: datetime,
    variant_keys: Sequence[str],
    default_exposure_event: str,
) -> bool:
    """Whether anyone was exposed to one of the variant keys in `[window_start, window_end)`."""
    team = experiment.team
    flag_key = experiment.get_feature_flag_key()
    _, variant_property = get_exposure_event_and_property(
        flag_key, experiment.exposure_criteria, default_exposure_event=default_exposure_event
    )
    # No test-account filter, as in the exposure freeze: the question is whether the flag served anyone.
    query = parse_select(
        """
        SELECT 1 FROM events
        WHERE timestamp >= {window_start} AND timestamp < {window_end} AND {exposure} AND {variant} IN {variant_keys}
        LIMIT 1
        """,
        placeholders={
            "window_start": ast.Constant(value=window_start),
            "window_end": ast.Constant(value=window_end),
            "exposure": ast.And(
                exprs=build_exposure_event_conditions(
                    experiment.exposure_criteria, team, flag_key, default_exposure_event=default_exposure_event
                )
            ),
            "variant": ast.Field(chain=["properties", variant_property]),
            "variant_keys": ast.Constant(value=list(variant_keys)),
        },
    )
    with tags_context(
        product=Product.EXPERIMENTS, feature=Feature.HEALTH_CHECK, team_id=team.pk, org_id=team.organization_id
    ):
        response = execute_hogql_query(
            query, team=team, settings=HogQLGlobalSettings(max_execution_time=EXPOSURE_QUERY_TIMEOUT_SECONDS)
        )
    return bool(response.results)


class _ExposureGate:
    """
    Answers the exposure questions of one request from the cache, or with at most MAX_EXPOSURE_QUERIES queries
    that start within REQUEST_BUDGET_SECONDS.
    """

    def __init__(self, experiment: Experiment, launched_at: datetime) -> None:
        self._experiment = experiment
        self._launched_at = launched_at
        self._default_exposure_event = resolve_default_exposure_event(experiment.team, launched_at)
        self._exposure_action_version = _exposure_action_version(experiment)
        self._started_at = monotonic()
        self._query_count = 0
        self._stopped = False

    def exposed(self, *, window_start: datetime, window_end: datetime, variant_keys: Sequence[str]) -> bool | None:
        """None when unknown: the query failed in this request or in the last day, or the request is out of budget."""
        if not variant_keys:
            return False
        cache_key = self._cache_key(window_start, window_end, variant_keys)
        cached = cache.get(cache_key)
        if isinstance(cached, bool):
            return cached
        if cached == _UNKNOWN:
            return None
        if self._stopped:
            return None
        if self._query_count >= MAX_EXPOSURE_QUERIES or monotonic() - self._started_at >= REQUEST_BUDGET_SECONDS:
            # Every answer is cached on its own, so the next request continues the walk where this one stopped.
            self._stopped = True
            return None
        self._query_count += 1
        try:
            answer = query_any_exposure(
                self._experiment,
                window_start=window_start,
                window_end=window_end,
                variant_keys=variant_keys,
                default_exposure_event=self._default_exposure_event,
            )
        except Exception as error:
            # The page calls the endpoint on every load, so a scan that fails must not run again on every load.
            too_expensive = isinstance(error, _TOO_EXPENSIVE_ERRORS)
            if not too_expensive:
                capture_exception(error)
            cache.set(cache_key, _UNKNOWN, _TOO_EXPENSIVE_CACHE_SECONDS if too_expensive else _FAILED_CACHE_SECONDS)
            self._stopped = True
            return None
        if answer or timezone.now() - window_end > _SETTLED_AFTER:
            cache.set(cache_key, answer, _ANSWER_CACHE_SECONDS)
        return answer

    def _cache_key(self, window_start: datetime, window_end: datetime, variant_keys: Sequence[str]) -> str:
        experiment = self._experiment
        # Every input of the query. The resolved exposure event is one, because the exposure event rollout
        # can move an experiment to another event. An exposure action is one by its last edit, because the
        # criteria hold only its id.
        inputs = json.dumps(
            [
                self._launched_at.isoformat(),
                window_start.isoformat(),
                window_end.isoformat(),
                experiment.get_feature_flag_key(),
                sorted(variant_keys),
                experiment.exposure_criteria,
                self._default_exposure_event,
                self._exposure_action_version,
            ],
            sort_keys=True,
            default=str,
        )
        digest = hashlib.sha256(inputs.encode()).hexdigest()
        return f"experiment_split_exposure:{experiment.team_id}:{experiment.id}:{digest}"


def _exposure_action_version(experiment: Experiment) -> str | None:
    criteria = normalize_to_exposure_criteria(experiment.exposure_criteria)
    config = criteria.exposure_config if criteria else None
    if not isinstance(config, ActionsNode):
        return None
    updated_at = (
        Action.objects.filter(team_id=experiment.team_id, id=int(config.id))
        .values_list("updated_at", flat=True)
        .first()
    )
    return updated_at.isoformat() if updated_at else None


def _load_split_history(experiment: Experiment) -> SplitHistory | None:
    launched_at = experiment.start_date
    # django-stubs types the id as int, but an unsaved instance can carry None.
    feature_flag_id: int | None = experiment.feature_flag_id
    if launched_at is None or experiment.end_date is not None or experiment.archived or feature_flag_id is None:
        return None
    if experiment.feature_flag.deleted:
        return None

    changes = _split_changes_since(team_id=experiment.team_id, feature_flag_id=feature_flag_id, since=launched_at)
    gate = _ExposureGate(experiment, launched_at)
    window_start = launched_at
    for index, change in enumerate(changes):
        exposed_before = gate.exposed(
            window_start=window_start,
            window_end=change.changed_at,
            variant_keys=split_variant_keys(change.before),
        )
        if exposed_before is not False:
            counted = tuple(changes[index:])
            return SplitHistory(
                launched_at=launched_at,
                team_timezone=experiment.team.timezone,
                counted_changes=counted,
                exposed_before_first=exposed_before,
                exposed_between=_exposed_between(gate, counted),
            )
        window_start = change.changed_at

    return SplitHistory(
        launched_at=launched_at,
        team_timezone=experiment.team.timezone,
        counted_changes=(),
        exposed_before_first=False,
        exposed_between=None,
    )


def _exposed_between(gate: _ExposureGate, counted: Sequence[SplitChange]) -> bool | None:
    first = counted[0]
    last = counted[-1]
    if not same_assignment(first.before, last.after):
        return None
    # The splits in force between the first and the last change.
    variant_keys = sorted({key for change in counted[:-1] for key in split_variant_keys(change.after)})
    return gate.exposed(window_start=first.changed_at, window_end=last.changed_at, variant_keys=variant_keys)


def _split_changes_since(*, team_id: int, feature_flag_id: int, since: datetime) -> list[SplitChange]:
    rows = (
        ActivityLog.objects.filter(
            team_id=team_id,
            scope="FeatureFlag",
            item_id=str(feature_flag_id),
            created_at__gt=since,
            detail__contains={"changes": [{"field": "filters"}]},
        )
        .order_by("created_at")
        .values_list("created_at", "detail")
    )
    changes = [split_change_from_activity(detail, changed_at) for changed_at, detail in rows]
    return [change for change in changes if change is not None]

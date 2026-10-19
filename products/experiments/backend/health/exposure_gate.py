"""
Loads the split changes of a running experiment's flag since launch, and asks ClickHouse whether anyone was
exposed before each change. A change before the first exposure moved nobody, so it does not count.

The answer for a past window does not change, so it is cached per window and shared by every reader. A slow
answer is then paid once per change, not on every load of the experiment page. A failed query is cached as
unknown too, so a scan that is too large for a request runs at most once a day.

Only exposure criteria that name an event are asked about. The answer for a property filter or an action can
depend on what each reader may read, and can change as the filter matches other events over time, so no cached
answer for them is safe to share. The split changes of those experiments are reported as not checked.
"""

import json
import hashlib
from collections.abc import Sequence
from datetime import datetime, timedelta
from time import monotonic

from django.core.cache import cache
from django.db.models import F, Func, JSONField, Value
from django.db.models.fields.json import KT
from django.utils import timezone

import pydantic

from posthog.schema import ActionsNode

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.errors import CH_TRANSIENT_ERRORS
from posthog.exceptions import (
    ClickHouseEstimatedQueryExecutionTimeTooLong,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQueryTimeOut,
)
from posthog.exceptions_capture import capture_exception
from posthog.models.activity_logging.activity_log import ActivityLog

from products.experiments.backend.facade.contracts import ExperimentHealthReaderAccess
from products.experiments.backend.health.context import (
    SplitChange,
    SplitHistory,
    SplitHistoryNotChecked,
    SplitHistoryNotCheckedReason,
)
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
UNKNOWN = "unknown"
_BEFORE_VARIANTS_PATH = '$.changes[*] ? (@.field == "filters").before.multivariate.variants'
_AFTER_VARIANTS_PATH = '$.changes[*] ? (@.field == "filters").after.multivariate.variants'
# Events can arrive after the window ends, so a "nobody" answer for a recent window can still change.
_SETTLED_AFTER = timedelta(hours=1)
# A recent "nobody" is kept briefly, so page loads in that hour do not each run the scan again.
_RECENT_NOBODY_CACHE_SECONDS = int(timedelta(minutes=5).total_seconds())
# The scan is too large for a request. These are expected, so they are not reported.
_TOO_EXPENSIVE_ERRORS = (
    ClickHouseQueryTimeOut,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseEstimatedQueryExecutionTimeTooLong,
)


def load_split_history(
    experiment: Experiment, *, reader_access: ExperimentHealthReaderAccess
) -> SplitHistory | SplitHistoryNotChecked | None:
    """
    The split history of a running, not archived experiment whose flag exists and is not deleted, or None.
    Never raises: the health endpoint serves the other findings when this fails.
    """
    try:
        return _load_split_history(experiment, reader_access)
    except Exception as error:
        capture_exception(error)
        return None


def cache_failed_scan(cache_key: str, error: Exception) -> None:
    """Caches the answer of a failed scan as UNKNOWN, and reports an error that is not expected."""
    # The page calls the endpoint on every load, so a scan that fails must not run again on every load.
    # Cluster memory pressure subclasses the per-query memory error, but it says nothing about this scan.
    transient = isinstance(error, CH_TRANSIENT_ERRORS)
    too_expensive = not transient and isinstance(error, _TOO_EXPENSIVE_ERRORS)
    if not transient and not too_expensive:
        capture_exception(error)
    cache.set(cache_key, UNKNOWN, _TOO_EXPENSIVE_CACHE_SECONDS if too_expensive else _FAILED_CACHE_SECONDS)


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
        # No user, as in the exposure freeze, because every reader gets the cached answer.
        response = execute_hogql_query(
            query,
            team=team,
            # A profile that breaks on timeout returns no rows, which would read as "nobody exposed".
            settings=HogQLGlobalSettings(
                max_execution_time=EXPOSURE_QUERY_TIMEOUT_SECONDS, timeout_overflow_mode="throw"
            ),
        )
    return bool(response.results)


@frozen
class _Window:
    start: datetime
    end: datetime
    variant_keys: tuple[str, ...]


class _ExposureGate:
    """
    Answers the exposure questions of one request from the cache, or with at most MAX_EXPOSURE_QUERIES queries
    that start within REQUEST_BUDGET_SECONDS.
    """

    def __init__(self, experiment: Experiment, launched_at: datetime, *, prefetch: Sequence[_Window]) -> None:
        self._experiment = experiment
        self._launched_at = launched_at
        self._default_exposure_event = resolve_default_exposure_event(experiment.team, launched_at)
        # One cache read for all windows of the walk, so a flag with many changes costs one round trip.
        self._prefetched_keys = {self._cache_key(window) for window in prefetch if window.variant_keys}
        self._prefetched = cache.get_many(list(self._prefetched_keys))
        self._started_at = monotonic()
        self._query_count = 0
        self._stopped = False

    def exposed(self, window: _Window) -> bool | None:
        """None when unknown: the query failed in this request or within its cache time, or the request is out of budget."""
        if not window.variant_keys:
            return False
        cache_key = self._cache_key(window)
        cached = self._prefetched.get(cache_key) if cache_key in self._prefetched_keys else cache.get(cache_key)
        if isinstance(cached, bool):
            return cached
        if cached == UNKNOWN:
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
                window_start=window.start,
                window_end=window.end,
                variant_keys=window.variant_keys,
                default_exposure_event=self._default_exposure_event,
            )
        except Exception as error:
            cache_failed_scan(cache_key, error)
            self._stopped = True
            return None
        settled = answer or timezone.now() - window.end > _SETTLED_AFTER
        cache.set(cache_key, answer, _ANSWER_CACHE_SECONDS if settled else _RECENT_NOBODY_CACHE_SECONDS)
        return answer

    def _cache_key(self, window: _Window) -> str:
        experiment = self._experiment
        # Every input of the query. The resolved exposure event is one, because the exposure event rollout
        # can move an experiment to another event.
        inputs = json.dumps(
            [
                self._launched_at.isoformat(),
                window.start.isoformat(),
                window.end.isoformat(),
                experiment.get_feature_flag_key(),
                sorted(window.variant_keys),
                experiment.exposure_criteria,
                self._default_exposure_event,
            ],
            sort_keys=True,
            default=str,
        )
        digest = hashlib.sha256(inputs.encode()).hexdigest()
        return f"experiment_split_exposure:{experiment.team_id}:{experiment.id}:{digest}"


def _load_split_history(
    experiment: Experiment, reader_access: ExperimentHealthReaderAccess
) -> SplitHistory | SplitHistoryNotChecked | None:
    launched_at = experiment.start_date
    # django-stubs types the id as int, but an unsaved instance can carry None.
    feature_flag_id: int | None = experiment.feature_flag_id
    if launched_at is None or experiment.end_date is not None or experiment.archived or feature_flag_id is None:
        return None
    if experiment.feature_flag.deleted:
        return None
    team_timezone = experiment.team.timezone
    if not reader_access.can_read_flag_history:
        return SplitHistoryNotChecked(
            reason=SplitHistoryNotCheckedReason.NO_HISTORY_ACCESS,
            launched_at=launched_at,
            team_timezone=team_timezone,
            changes=(),
        )

    changes = tuple(
        _split_changes_since(team_id=experiment.team_id, feature_flag_id=feature_flag_id, since=launched_at)
    )
    if not changes:
        return SplitHistory(
            launched_at=launched_at,
            team_timezone=team_timezone,
            changes=(),
            counted_changes=(),
            exposed_before_first=False,
            exposed_between=None,
        )
    reason = _not_checked_reason(experiment, reader_access)
    if reason is not None:
        return SplitHistoryNotChecked(
            reason=reason, launched_at=launched_at, team_timezone=team_timezone, changes=changes
        )

    starts = (launched_at, *(change.changed_at for change in changes[:-1]))
    walk = [
        _Window(start=start, end=change.changed_at, variant_keys=split_variant_keys(change.before))
        for start, change in zip(starts, changes)
    ]
    gate = _ExposureGate(experiment, launched_at, prefetch=walk)
    counted: tuple[SplitChange, ...] = ()
    exposed_before_first: bool | None = False
    exposed_between: bool | None = None
    for index, window in enumerate(walk):
        exposed_before = gate.exposed(window)
        if exposed_before is not False:
            counted = changes[index:]
            exposed_before_first = exposed_before
            exposed_between = _exposed_between(gate, counted)
            break

    return SplitHistory(
        launched_at=launched_at,
        team_timezone=team_timezone,
        changes=changes,
        counted_changes=counted,
        exposed_before_first=exposed_before_first,
        exposed_between=exposed_between,
    )


def _not_checked_reason(
    experiment: Experiment, reader_access: ExperimentHealthReaderAccess
) -> SplitHistoryNotCheckedReason | None:
    # The criteria come first, because adding the query:read scope would not let the check run for them.
    try:
        criteria = normalize_to_exposure_criteria(experiment.exposure_criteria)
    except pydantic.ValidationError:
        return SplitHistoryNotCheckedReason.EXPOSURE_CRITERIA
    config = criteria.exposure_config if criteria else None
    if isinstance(config, ActionsNode):
        return SplitHistoryNotCheckedReason.EXPOSURE_ACTION
    if config is not None and config.properties:
        return SplitHistoryNotCheckedReason.EXPOSURE_FILTERS
    if not reader_access.can_query_events:
        return SplitHistoryNotCheckedReason.NO_QUERY_ACCESS
    return None


def _exposed_between(gate: _ExposureGate, counted: Sequence[SplitChange]) -> bool | None:
    first = counted[0]
    last = counted[-1]
    if not same_assignment(first.before, last.after):
        return None
    in_between = [change.after for change in counted[:-1]]
    # A flag without variants serves `true`, so people can be exposed with no variant key to look for.
    if any(not split_variant_keys(split) for split in in_between):
        return None
    variant_keys = tuple(sorted({key for split in in_between for key in split_variant_keys(split)}))
    return gate.exposed(_Window(start=first.changed_at, end=last.changed_at, variant_keys=variant_keys))


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
        # Only the variants decide the split, and the whole `detail` of a flag edit can be large.
        .annotate(
            job_type=KT("detail__trigger__job_type"),
            before_variants=_variants_of_filters_change(_BEFORE_VARIANTS_PATH),
            after_variants=_variants_of_filters_change(_AFTER_VARIANTS_PATH),
        )
        .values_list("created_at", "job_type", "before_variants", "after_variants")
    )
    changes = [
        split_change_from_activity(
            changed_at=changed_at, job_type=job_type, before_variants=before_variants, after_variants=after_variants
        )
        for changed_at, job_type, before_variants, after_variants in rows
    ]
    return [change for change in changes if change is not None]


def _variants_of_filters_change(path: str) -> Func:
    return Func(F("detail"), Value(path), function="jsonb_path_query_first", output_field=JSONField())

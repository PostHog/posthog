"""
Loads the changes of a running experiment's flag since launch that can move exposed people: the split and the
settings that decide the variant draw. Then asks ClickHouse whether anyone was exposed before each change. A change before the first exposure moved nobody, so it does not count.

The answer for a past window does not change, so it is cached per window and shared by every reader. A slow
answer is then paid once per change, not on every load of the experiment page. A failed query is cached as
unknown too, so a scan that is too large for a request runs at most once a day.

Only exposure criteria that name an event are asked about. The answer for a property filter or an action can
depend on what each reader may read, and can change as the filter matches other events over time, so no cached
answer for them is safe to share. The changes of those experiments are reported as not checked.
"""

import json
import hashlib
from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from time import monotonic

from django.core.cache import cache
from django.db.models import F, Func, JSONField, Q, Value
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
from products.experiments.backend.health.bucketing_changes import (
    BucketingChangeShape,
    bucketing_changes_from_activity,
    bucketing_net_effect,
    changes_that_apply,
    conditions_follow_flag_aggregation,
)
from products.experiments.backend.health.context import (
    BucketingChange,
    BucketingSetting,
    FlagHistory,
    FlagHistoryNotChecked,
    FlagHistoryNotCheckedReason,
    Split,
    SplitChange,
    parse_variants,
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
# The activity log fields of a flag save that can move exposed people.
_FILTERS = "filters"
_SETTING_FIELDS = {
    BucketingSetting.KEY: "key",
    BucketingSetting.BUCKETING_IDENTIFIER: "bucketing_identifier",
    BucketingSetting.EXPERIENCE_CONTINUITY: "ensure_experience_continuity",
}
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


def load_flag_history(
    experiment: Experiment, *, reader_access: ExperimentHealthReaderAccess
) -> FlagHistory | FlagHistoryNotChecked | None:
    """
    The flag history of a running, not archived experiment whose flag exists and is not deleted, or None.
    Never raises: the health endpoint serves the other findings when this fails.
    """
    try:
        return _load_flag_history(experiment, reader_access)
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
    flag_key: str,
    window_start: datetime,
    window_end: datetime,
    variant_keys: Sequence[str],
    default_exposure_event: str,
) -> bool:
    """Whether anyone was exposed to one of the variant keys of the flag key in `[window_start, window_end)`."""
    team = experiment.team
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
    # The flag's key and variants while the window lasted. Exposures carry the key they were served under.
    flag_key: str
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
                flag_key=window.flag_key,
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
                window.flag_key,
                sorted(window.variant_keys),
                experiment.exposure_criteria,
                self._default_exposure_event,
            ],
            sort_keys=True,
            default=str,
        )
        digest = hashlib.sha256(inputs.encode()).hexdigest()
        return f"experiment_split_exposure:{experiment.team_id}:{experiment.id}:{digest}"


class _ConditionAggregationMismatch(Exception):
    """A release condition aggregates by person while the flag-level aggregation names a group type."""


def _load_flag_history(
    experiment: Experiment, reader_access: ExperimentHealthReaderAccess
) -> FlagHistory | FlagHistoryNotChecked | None:
    launched_at = experiment.start_date
    # django-stubs types the id as int, but an unsaved instance can carry None.
    feature_flag_id: int | None = experiment.feature_flag_id
    if launched_at is None or experiment.end_date is not None or experiment.archived or feature_flag_id is None:
        return None
    if experiment.feature_flag.deleted:
        return None
    team_timezone = experiment.team.timezone
    if not reader_access.can_read_flag_history:
        return FlagHistoryNotChecked(
            reason=FlagHistoryNotCheckedReason.NO_HISTORY_ACCESS,
            launched_at=launched_at,
            team_timezone=team_timezone,
            split_changes=(),
            bucketing_changes=(),
        )

    changes = _flag_changes_since(team_id=experiment.team_id, feature_flag_id=feature_flag_id, since=launched_at)
    flag = experiment.feature_flag
    trust_flag_aggregation = conditions_follow_flag_aggregation(flag.aggregation_group_type_index, flag.conditions)
    relies_on_flag_aggregation = any(
        change.setting in (BucketingSetting.BUCKETING_IDENTIFIER, BucketingSetting.EXPERIENCE_CONTINUITY)
        for change in changes.bucketing
    )
    if relies_on_flag_aggregation and not trust_flag_aggregation:
        # The check then counts every identifier change, so it can report one that moved nobody.
        capture_exception(
            _ConditionAggregationMismatch(), {"team_id": experiment.team_id, "feature_flag_id": feature_flag_id}
        )
    # A change the flag service does not read moved nobody, so it neither counts nor needs an exposure window.
    changes = replace(
        changes,
        bucketing=changes_that_apply(
            changes.bucketing,
            feature_flag_id=feature_flag_id,
            aggregation=flag.aggregation_group_type_index,
            bucketing_identifier=flag.bucketing_identifier,
            trust_flag_aggregation=trust_flag_aggregation,
        ),
    )
    history = FlagHistory(
        launched_at=launched_at,
        team_timezone=team_timezone,
        split_changes=changes.split,
        bucketing_changes=changes.bucketing,
        counted_since=None,
        exposed_before_first=False,
        split_exposed_between=None,
        bucketing_exposed_between=None,
    )
    if not changes.times:
        return history
    reason = _not_checked_reason(experiment, reader_access)
    if reason is not None:
        return FlagHistoryNotChecked(
            reason=reason,
            launched_at=launched_at,
            team_timezone=team_timezone,
            split_changes=changes.split,
            bucketing_changes=changes.bucketing,
        )

    timeline = _Timeline(
        changes,
        current_key=experiment.get_feature_flag_key(),
        current_split=parse_variants(experiment.feature_flag.variants),
    )
    starts = (launched_at, *changes.times[:-1])
    walk = [timeline.window(start=start, end=end) for start, end in zip(starts, changes.times)]
    gate = _ExposureGate(experiment, launched_at, prefetch=walk)
    for window in walk:
        exposed_before = gate.exposed(window)
        if exposed_before is not False:
            history = replace(history, counted_since=window.end, exposed_before_first=exposed_before)
            break
    if history.counted_since is None:
        return history

    split = history.counted_split_changes
    bucketing = bucketing_net_effect(history.counted_bucketing_changes)
    return replace(
        history,
        split_exposed_between=(
            _exposed_between(gate, timeline, start=split[0].changed_at, end=split[-1].changed_at)
            if split and same_assignment(split[0].before, split[-1].after)
            else None
        ),
        bucketing_exposed_between=(
            _exposed_between(gate, timeline, start=bucketing.first.changed_at, end=bucketing.last.changed_at)
            if bucketing and bucketing.shape == BucketingChangeShape.REVERTED
            else None
        ),
    )


def _not_checked_reason(
    experiment: Experiment, reader_access: ExperimentHealthReaderAccess
) -> FlagHistoryNotCheckedReason | None:
    # The criteria come first, because adding the query:read scope would not let the check run for them.
    try:
        criteria = normalize_to_exposure_criteria(experiment.exposure_criteria)
    except pydantic.ValidationError:
        return FlagHistoryNotCheckedReason.EXPOSURE_CRITERIA
    config = criteria.exposure_config if criteria else None
    if isinstance(config, ActionsNode):
        return FlagHistoryNotCheckedReason.EXPOSURE_ACTION
    if config is not None and config.properties:
        return FlagHistoryNotCheckedReason.EXPOSURE_FILTERS
    if not reader_access.can_query_events:
        return FlagHistoryNotCheckedReason.NO_QUERY_ACCESS
    return None


@frozen
class _FlagChanges:
    split: tuple[SplitChange, ...]
    bucketing: tuple[BucketingChange, ...]

    @property
    def times(self) -> tuple[datetime, ...]:
        # One save can change several things, so it is one point in time.
        return tuple(
            sorted({change.changed_at for change in self.split} | {change.changed_at for change in self.bucketing})
        )


class _Timeline:
    """The flag's key and split at any time since launch, from its changes and its current state."""

    def __init__(self, changes: _FlagChanges, *, current_key: str, current_split: Split) -> None:
        self._changes = changes
        self._key_changes = [change for change in changes.bucketing if change.setting == BucketingSetting.KEY]
        # The changes come in time order, so a binary search finds the first change at or after a time.
        self._key_times = [change.changed_at for change in self._key_changes]
        self._split_times = [change.changed_at for change in changes.split]
        self._current_key = current_key
        self._current_split = current_split

    def window(self, *, start: datetime, end: datetime) -> _Window:
        """The window up to a change, with the key and the split that the flag served before that change."""
        return _Window(
            start=start,
            end=end,
            flag_key=self.key_before(end),
            variant_keys=split_variant_keys(self.split_before(end)),
        )

    def key_before(self, at: datetime) -> str:
        index = bisect_left(self._key_times, at)
        key = self._key_changes[index].before if index < len(self._key_changes) else self._current_key
        return key if isinstance(key, str) else self._current_key

    def split_before(self, at: datetime) -> Split:
        index = bisect_left(self._split_times, at)
        return self._changes.split[index].before if index < len(self._changes.split) else self._current_split

    def points_within(self, *, start: datetime, end: datetime) -> list[datetime]:
        return [at for at in self._changes.times if start < at <= end]


def _exposed_between(gate: _ExposureGate, timeline: _Timeline, *, start: datetime, end: datetime) -> bool | None:
    """Whether anyone was exposed in `[start, end)`, under any key and split that the flag served then."""
    variant_keys_by_flag_key: dict[str, set[str]] = {}
    for at in timeline.points_within(start=start, end=end):
        split = timeline.split_before(at)
        # A flag without variants serves `true`, so people can be exposed with no variant key to look for.
        if not split_variant_keys(split):
            return None
        variant_keys_by_flag_key.setdefault(timeline.key_before(at), set()).update(split_variant_keys(split))
    answers = []
    for flag_key, variant_keys in variant_keys_by_flag_key.items():
        answer = gate.exposed(
            _Window(start=start, end=end, flag_key=flag_key, variant_keys=tuple(sorted(variant_keys)))
        )
        if answer:
            return True
        answers.append(answer)
    return None if None in answers else False


_PROJECTED = (
    "before_variants",
    "after_variants",
    "before_aggregation",
    "after_aggregation",
    *(f"{side}_{setting}" for side in ("before", "after") for setting in _SETTING_FIELDS),
)


def _flag_changes_since(*, team_id: int, feature_flag_id: int, since: datetime) -> _FlagChanges:
    rows = (
        ActivityLog.objects.filter(
            _changes_any_field(_FILTERS, *_SETTING_FIELDS.values()),
            team_id=team_id,
            scope="FeatureFlag",
            item_id=str(feature_flag_id),
            created_at__gt=since,
        )
        .order_by("created_at")
        # Only these values decide who gets which variant, and the whole `detail` of a flag edit can be large.
        .annotate(
            job_type=KT("detail__trigger__job_type"),
            before_variants=_changed(_FILTERS, "before.multivariate.variants"),
            after_variants=_changed(_FILTERS, "after.multivariate.variants"),
            before_aggregation=_changed(_FILTERS, "before.aggregation_group_type_index"),
            after_aggregation=_changed(_FILTERS, "after.aggregation_group_type_index"),
            **{f"before_{setting}": _changed(field, "before") for setting, field in _SETTING_FIELDS.items()},
            **{f"after_{setting}": _changed(field, "after") for setting, field in _SETTING_FIELDS.items()},
        )
        .values("created_at", "job_type", *_PROJECTED)
    )
    split: list[SplitChange] = []
    bucketing: list[BucketingChange] = []
    for row in rows:
        changed_at = row["created_at"]
        split_change = split_change_from_activity(
            changed_at=changed_at,
            job_type=row["job_type"],
            before_variants=row["before_variants"],
            after_variants=row["after_variants"],
        )
        if split_change is not None:
            split.append(split_change)
        bucketing.extend(
            bucketing_changes_from_activity(
                changed_at=changed_at,
                feature_flag_id=feature_flag_id,
                before=_settings(row, "before"),
                after=_settings(row, "after"),
            )
        )
    return _FlagChanges(split=tuple(split), bucketing=tuple(bucketing))


def _settings(row: dict[str, object], side: str) -> dict[BucketingSetting, object]:
    return {
        BucketingSetting.AGGREGATION: row[f"{side}_aggregation"],
        **{setting: row[f"{side}_{setting}"] for setting in _SETTING_FIELDS},
    }


def _changes_any_field(*fields: str) -> Q:
    query = Q()
    for field in fields:
        query |= Q(detail__contains={"changes": [{"field": field}]})
    return query


def _changed(field: str, path: str) -> Func:
    return Func(
        F("detail"),
        Value(f'$.changes[*] ? (@.field == "{field}").{path}'),
        function="jsonb_path_query_first",
        output_field=JSONField(),
    )

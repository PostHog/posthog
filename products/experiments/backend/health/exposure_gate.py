"""
Loads the changes of a running experiment's flag since launch that can move exposed people: the split, the
settings that decide the variant draw, and the release conditions. Then asks ClickHouse whether anyone was exposed
before each change. A change before the first exposure moved nobody, so it does not count. For each kind of change
that counts, it also counts the persons or groups exposed before the last change of that kind, up to a few.

The answer for a past window does not change, so it is cached per window and shared by every reader. A slow
answer is then paid once per change, not on every load of the experiment page. A failed query is cached as
unknown too, so a scan that is too large for a request runs at most once a day.

Only exposure criteria that name an event are asked about. The answer for a property filter or an action can
depend on what each reader may read, and can change as the filter matches other events over time, so no cached
answer for them is safe to share. The changes of those experiments are reported as not checked.

The answers run without the reader and are shared, so a reader denied any event property gets none. Every change
then counts for that reader, as if every answer were unknown.
"""

import json
import hashlib
from bisect import bisect_left
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from time import monotonic
from typing import Any

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

from products.experiments.backend.facade.contracts import ExperimentHealthFlagChangeKind, ExperimentHealthReaderAccess
from products.experiments.backend.health.bucketing_changes import BucketingChangeShape, bucketing_net_effect
from products.experiments.backend.health.condition_changes import (
    ConditionsChangeShape,
    conditions_change_from_activity,
    conditions_net_effect,
)
from products.experiments.backend.health.context import (
    MAX_FLAG_SAVES,
    MAX_RELEASE_CONDITIONS,
    MIN_EXPOSED_UNITS_TO_WARN,
    ChangeWindow,
    FlagChange,
    FlagHistory,
    FlagHistoryNotChecked,
    FlagHistoryNotCheckedReason,
    changes_of_kind,
)
from products.experiments.backend.health.split_changes import split_change_from_activity
from products.experiments.backend.hogql_queries.exposure_query_logic import (
    aggregates_by_group,
    build_exposure_event_conditions,
    get_entity_key,
    get_exposure_event_and_property,
    normalize_to_exposure_criteria,
    resolve_default_exposure_event,
)
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.facade.edits import (
    BucketingChange,
    BucketingSetting,
    ConditionsChange,
    Split,
    SplitChange,
    bucketing_changes_from_activity,
    changes_that_apply,
    conditions_follow_flag_aggregation,
    parse_release_conditions,
    parse_variants,
    same_assignment,
    split_variant_keys,
)

MAX_EXPOSURE_QUERIES = 20
# Each override window costs a cache read, and a query when the answer is not cached. A window past this stays
# unknown, so its override stays reported.
MAX_OVERRIDE_WINDOWS = 20
EXPOSURE_QUERY_TIMEOUT_SECONDS = 10
# No query starts after this, so one request takes at most this plus one query's timeout.
REQUEST_BUDGET_SECONDS = 10
_ANSWER_CACHE_SECONDS = int(timedelta(days=30).total_seconds())
# A scan too large for a request stays too large, so it waits a day. Another error can be brief, and an
# unknown answer shows the finding, so it waits an hour.
_TOO_EXPENSIVE_CACHE_SECONDS = int(timedelta(days=1).total_seconds())
_FAILED_CACHE_SECONDS = int(timedelta(hours=1).total_seconds())
UNKNOWN = "unknown"
# The two questions have their own key prefixes, so a cached bool of "anyone exposed" is never read as a count.
_EXPOSED_KEY_PREFIX = "experiment_split_exposure"
_EXPOSED_UNITS_KEY_PREFIX = "experiment_exposed_units"
_KINDS: dict[ExperimentHealthFlagChangeKind, type[FlagChange]] = {
    ExperimentHealthFlagChangeKind.SPLIT: SplitChange,
    ExperimentHealthFlagChangeKind.BUCKETING: BucketingChange,
    ExperimentHealthFlagChangeKind.RELEASE_CONDITIONS: ConditionsChange,
}
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
    return bool(_execute(experiment, query))


def query_exposed_units(
    experiment: Experiment,
    *,
    window_start: datetime,
    window_end: datetime,
    served: Sequence[tuple[str, Sequence[str]]],
    group_type_index: int | None,
    default_exposure_event: str,
) -> int:
    """
    The persons or groups exposed in `[window_start, window_end)`, up to MIN_EXPOSED_UNITS_TO_WARN. `served` pairs each
    flag key with the variant keys the flag served under it, and an exposure counts when it matches one of the pairs.
    """
    team = experiment.team
    # `person_id` joins an aggregation of the team's person overrides, which runs in full whatever the LIMIT. The raw
    # id on the event needs no join. A person merged after an exposure can then count twice, which only keeps a warning.
    unit = get_entity_key(group_type_index) if aggregates_by_group(group_type_index) else "event_person_id"
    conditions: list[ast.Expr] = []
    for flag_key, variant_keys in served:
        _, variant_property = get_exposure_event_and_property(
            flag_key, experiment.exposure_criteria, default_exposure_event=default_exposure_event
        )
        conditions.append(
            ast.And(
                exprs=[
                    *build_exposure_event_conditions(
                        experiment.exposure_criteria, team, flag_key, default_exposure_event=default_exposure_event
                    ),
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.In,
                        left=ast.Field(chain=["properties", variant_property]),
                        right=ast.Constant(value=list(variant_keys)),
                    ),
                ]
            )
        )
    # The exposure query leaves out group exposures without a group key, so they don't count here either.
    has_unit = (
        ast.Call(name="notEmpty", args=[ast.Field(chain=[unit])])
        if aggregates_by_group(group_type_index)
        else ast.Constant(value=True)
    )
    # No test-account filter, as in `query_any_exposure`. DISTINCT with LIMIT stops the scan at the cap.
    query = parse_select(
        """
        SELECT count() FROM (
            SELECT DISTINCT {unit} FROM events
            WHERE timestamp >= {window_start} AND timestamp < {window_end} AND {served} AND {has_unit}
            LIMIT {cap}
        )
        """,
        placeholders={
            "unit": ast.Field(chain=[unit]),
            "window_start": ast.Constant(value=window_start),
            "window_end": ast.Constant(value=window_end),
            "served": ast.Or(exprs=conditions),
            "has_unit": has_unit,
            "cap": ast.Constant(value=MIN_EXPOSED_UNITS_TO_WARN),
        },
    )
    results = _execute(experiment, query)
    return int(results[0][0]) if results else 0


def _execute(experiment: Experiment, query: ast.SelectQuery | ast.SelectSetQuery) -> list[Any]:
    team = experiment.team
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
    return response.results or []


@frozen
class _Window:
    start: datetime
    end: datetime
    # The flag's key and variants while the window lasted. Exposures carry the key they were served under.
    flag_key: str
    variant_keys: tuple[str, ...]


@frozen
class _UnitsWindow:
    start: datetime
    end: datetime
    # Each flag key the flag had in the window, with the variant keys it served under that key.
    served: tuple[tuple[str, tuple[str, ...]], ...]


class _ExposureGate:
    """
    Answers the exposure questions of one request from the cache, or with at most MAX_EXPOSURE_QUERIES queries
    that start within REQUEST_BUDGET_SECONDS.
    """

    def __init__(
        self,
        experiment: Experiment,
        launched_at: datetime,
        *,
        group_type_index: int | None,
        denied_event_properties: frozenset[str],
        prefetch: Sequence[_Window | _UnitsWindow],
    ) -> None:
        self._experiment = experiment
        self._launched_at = launched_at
        self._group_type_index = group_type_index
        self._denied_event_properties = denied_event_properties
        self._default_exposure_event = resolve_default_exposure_event(experiment.team, launched_at)
        # One cache read for all windows of the walk and the counts, so a flag with many changes costs one round trip.
        self._prefetched_keys = (
            set()
            if denied_event_properties
            else {
                self._units_cache_key(window) if isinstance(window, _UnitsWindow) else self._cache_key(window)
                for window in prefetch
                if isinstance(window, _UnitsWindow) or window.variant_keys
            }
        )
        self._prefetched = cache.get_many(list(self._prefetched_keys)) if self._prefetched_keys else {}
        self._started_at = monotonic()
        self._query_count = 0
        self._stopped = False

    def exposed(self, window: _Window) -> bool | None:
        """None when unknown: the query failed in this request or within its cache time, the request is out of budget,
        or the reader is denied an event property."""
        if not window.variant_keys:
            return False
        return self._answer(
            self._cache_key(window),
            bool,
            lambda: query_any_exposure(
                self._experiment,
                flag_key=window.flag_key,
                window_start=window.start,
                window_end=window.end,
                variant_keys=window.variant_keys,
                default_exposure_event=self._default_exposure_event,
            ),
            window_end=window.end,
            final=lambda answer: answer,
        )

    def exposed_units(self, window: _UnitsWindow | None) -> int | None:
        """The persons or groups exposed in the window, up to MIN_EXPOSED_UNITS_TO_WARN. None when unknown, as for
        `exposed`, or without a window, because the flag served no variants for a while."""
        if window is None:
            return None
        return self._answer(
            self._units_cache_key(window),
            int,
            lambda: query_exposed_units(
                self._experiment,
                window_start=window.start,
                window_end=window.end,
                served=window.served,
                group_type_index=self._group_type_index,
                default_exposure_event=self._default_exposure_event,
            ),
            window_end=window.end,
            # Late events can only add units, so a count at the cap can't change.
            final=lambda count: count >= MIN_EXPOSED_UNITS_TO_WARN,
        )

    def _answer[A: (bool, int)](
        self,
        cache_key: str,
        answer_type: type[A],
        ask: Callable[[], A],
        *,
        window_end: datetime,
        final: Callable[[A], bool],
    ) -> A | None:
        # Every answer reads the flag, variant and group properties of the exposures. Any denied event property, not
        # a list of the read ones, so no list can miss one. The findings then keep their warnings.
        if self._denied_event_properties:
            return None
        cached = self._prefetched.get(cache_key) if cache_key in self._prefetched_keys else cache.get(cache_key)
        if isinstance(cached, answer_type):
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
            answer = ask()
        except Exception as error:
            cache_failed_scan(cache_key, error)
            self._stopped = True
            return None
        settled = final(answer) or timezone.now() - window_end > _SETTLED_AFTER
        cache.set(cache_key, answer, _ANSWER_CACHE_SECONDS if settled else _RECENT_NOBODY_CACHE_SECONDS)
        # Two kinds can ask the same window, and a prefetched miss would otherwise send the second to ClickHouse.
        self._prefetched[cache_key] = answer
        return answer

    def _cache_key(self, window: _Window) -> str:
        return self._key(
            _EXPOSED_KEY_PREFIX,
            window.start.isoformat(),
            window.end.isoformat(),
            window.flag_key,
            sorted(window.variant_keys),
        )

    def _units_cache_key(self, window: _UnitsWindow) -> str:
        # The cap is an input, so a count cached under another cap is never read as one under this cap.
        return self._key(
            _EXPOSED_UNITS_KEY_PREFIX,
            window.start.isoformat(),
            window.end.isoformat(),
            [[flag_key, sorted(variant_keys)] for flag_key, variant_keys in window.served],
            self._group_type_index,
            MIN_EXPOSED_UNITS_TO_WARN,
        )

    def _key(self, prefix: str, *window_inputs: object) -> str:
        experiment = self._experiment
        # Every input of the query. The resolved exposure event is one, because the exposure event rollout
        # can move an experiment to another event.
        inputs = json.dumps(
            [self._launched_at.isoformat(), *window_inputs, experiment.exposure_criteria, self._default_exposure_event],
            sort_keys=True,
            default=str,
        )
        digest = hashlib.sha256(inputs.encode()).hexdigest()
        return f"{prefix}:{experiment.team_id}:{experiment.id}:{digest}"


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
            changes=(),
        )

    rows = _flag_rows_since(team_id=experiment.team_id, feature_flag_id=feature_flag_id, since=launched_at)
    too_large = _too_large(rows)
    if too_large is not None:
        return FlagHistoryNotChecked(reason=too_large, launched_at=launched_at, team_timezone=team_timezone, changes=())
    read = _flag_changes(rows, feature_flag_id=feature_flag_id)
    flag = experiment.feature_flag
    trust_flag_aggregation = conditions_follow_flag_aggregation(flag.aggregation_group_type_index, flag.conditions)
    bucketing = changes_of_kind(read, BucketingChange)
    relies_on_flag_aggregation = any(
        change.setting in (BucketingSetting.BUCKETING_IDENTIFIER, BucketingSetting.EXPERIENCE_CONTINUITY)
        for change in bucketing
    )
    if relies_on_flag_aggregation and not trust_flag_aggregation:
        # The check then counts every identifier change, so it can report one that moved nobody.
        capture_exception(
            _ConditionAggregationMismatch(), {"team_id": experiment.team_id, "feature_flag_id": feature_flag_id}
        )
    # A change the flag service does not read moved nobody, so it neither counts nor needs an exposure window.
    applied = changes_that_apply(
        bucketing,
        feature_flag_id=feature_flag_id,
        aggregation=flag.aggregation_group_type_index,
        bucketing_identifier=flag.bucketing_identifier,
        trust_flag_aggregation=trust_flag_aggregation,
    )
    # An applied bucketing change can move to a later save, so the changes are sorted again. The sort is stable,
    # so the changes of one kind keep their order.
    merged: list[FlagChange] = [change for change in read if not isinstance(change, BucketingChange)]
    merged.extend(applied)
    changes = tuple(sorted(merged, key=lambda change: change.changed_at))
    history = FlagHistory(
        launched_at=launched_at,
        team_timezone=team_timezone,
        changes=changes,
        counted_since=None,
        exposed_before_first=False,
        exposed_between={},
        release_conditions=parse_release_conditions(
            flag.conditions,
            flag_aggregation=flag.aggregation_group_type_index,
            variant_keys=split_variant_keys(parse_variants(flag.variants)),
        ),
        exposed_during_overrides={},
        counts_groups=aggregates_by_group(flag.aggregation_group_type_index),
        exposed_units_before_last={},
    )
    times = _change_times(changes)
    if not times:
        return history
    reason = _not_checked_reason(experiment, reader_access)
    if reason is not None:
        return FlagHistoryNotChecked(
            reason=reason, launched_at=launched_at, team_timezone=team_timezone, changes=changes
        )

    timeline = _Timeline(
        changes,
        current_key=experiment.get_feature_flag_key(),
        current_split=parse_variants(experiment.feature_flag.variants),
    )
    starts = (launched_at, *times[:-1])
    walk = [timeline.window(start=start, end=end) for start, end in zip(starts, times)]
    # The last change of a kind is its last counted change whenever the kind has one, so these windows are known
    # before the walk and share its cache read.
    units_windows = {
        kind: timeline.units_window(start=launched_at, end=of_kind[-1].changed_at)
        for kind, change_type in _KINDS.items()
        if (of_kind := changes_of_kind(changes, change_type))
    }
    gate = _ExposureGate(
        experiment,
        launched_at,
        group_type_index=flag.aggregation_group_type_index,
        denied_event_properties=reader_access.denied_event_properties,
        prefetch=[*walk, *(window for window in units_windows.values() if window is not None)],
    )
    for window in walk:
        exposed_before = gate.exposed(window)
        if exposed_before is not False:
            history = replace(history, counted_since=window.end, exposed_before_first=exposed_before)
            break
    if history.counted_since is None:
        return history
    # Asked before the set-back and override questions, because a count can lower the finding of every kind.
    exposed_units_before_last = {
        kind: gate.exposed_units(units_windows[kind])
        for kind, change_type in _KINDS.items()
        if history.counted(change_type)
    }
    return replace(
        history,
        exposed_units_before_last=exposed_units_before_last,
        exposed_between=_exposed_between_set_backs(gate, timeline, history),
        exposed_during_overrides=_exposed_during_overrides(gate, timeline, history),
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


def _change_times(changes: tuple[FlagChange, ...]) -> tuple[datetime, ...]:
    # One save can change several things, so it is one point in time.
    return tuple(sorted({change.changed_at for change in changes}))


class _Timeline:
    """The flag's key and split at any time since launch, from its changes and its current state."""

    def __init__(self, changes: tuple[FlagChange, ...], *, current_key: str, current_split: Split) -> None:
        self._times = _change_times(changes)
        self._split_changes = changes_of_kind(changes, SplitChange)
        self._key_changes = [
            change for change in changes_of_kind(changes, BucketingChange) if change.setting == BucketingSetting.KEY
        ]
        # The changes come in time order, so a binary search finds the first change at or after a time.
        self._key_times = [change.changed_at for change in self._key_changes]
        self._split_times = [change.changed_at for change in self._split_changes]
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
        return self._split_changes[index].before if index < len(self._split_changes) else self._current_split

    def units_window(self, *, start: datetime, end: datetime) -> _UnitsWindow | None:
        """The window up to a change, with every key and split that the flag served in it. None when the flag served
        no variants for a while."""
        served = self.served_between(start=start, end=end)
        return None if served is None else _UnitsWindow(start=start, end=end, served=served)

    def served_between(self, *, start: datetime, end: datetime) -> tuple[tuple[str, tuple[str, ...]], ...] | None:
        """The variant keys that the flag served in `[start, end)`, by flag key. None when it served a flag without
        variants for a while."""
        variant_keys_by_flag_key: dict[str, set[str]] = {}
        for at in self.points_within(start=start, end=end):
            split = self.split_before(at)
            # A flag without variants serves `true`, so people can be exposed with no variant key to look for.
            if not split_variant_keys(split):
                return None
            variant_keys_by_flag_key.setdefault(self.key_before(at), set()).update(split_variant_keys(split))
        return tuple(
            (flag_key, tuple(sorted(variant_keys))) for flag_key, variant_keys in variant_keys_by_flag_key.items()
        )

    def points_within(self, *, start: datetime, end: datetime) -> list[datetime]:
        return [at for at in self._times if start < at <= end]


def _exposed_between(gate: _ExposureGate, timeline: _Timeline, *, start: datetime, end: datetime) -> bool | None:
    """Whether anyone was exposed in `[start, end)`, under any key and split that the flag served then."""
    served = timeline.served_between(start=start, end=end)
    if served is None:
        return None
    answers = []
    for flag_key, variant_keys in served:
        answer = gate.exposed(_Window(start=start, end=end, flag_key=flag_key, variant_keys=variant_keys))
        if answer:
            return True
        answers.append(answer)
    return None if None in answers else False


def _exposed_between_set_backs(
    gate: _ExposureGate, timeline: _Timeline, history: FlagHistory
) -> dict[ExperimentHealthFlagChangeKind, bool | None]:
    """Asks, per kind, whether anyone was exposed between the first and the last counted change, when the last sets
    back what the first changed."""
    exposed_between: dict[ExperimentHealthFlagChangeKind, bool | None] = {}
    split = history.counted(SplitChange)
    if split and same_assignment(split[0].before, split[-1].after):
        exposed_between[ExperimentHealthFlagChangeKind.SPLIT] = _exposed_between(
            gate, timeline, start=split[0].changed_at, end=split[-1].changed_at
        )
    bucketing = bucketing_net_effect(history.counted(BucketingChange))
    if bucketing and bucketing.shape == BucketingChangeShape.REVERTED:
        exposed_between[ExperimentHealthFlagChangeKind.BUCKETING] = _exposed_between(
            gate, timeline, start=bucketing.first.changed_at, end=bucketing.last.changed_at
        )
    conditions = conditions_net_effect(history.counted(ConditionsChange), current=history.release_conditions)
    if conditions and conditions.shape == ConditionsChangeShape.REVERTED:
        exposed_between[ExperimentHealthFlagChangeKind.RELEASE_CONDITIONS] = _exposed_between(
            gate, timeline, start=conditions.first.changed_at, end=conditions.last.changed_at
        )
    return exposed_between


def _exposed_during_overrides(
    gate: _ExposureGate, timeline: _Timeline, history: FlagHistory
) -> dict[ChangeWindow, bool | None]:
    """Asks, per override that was set and removed again or removed and set back, whether anyone was exposed in
    between. The set-back question above covers only the span of every change of a kind."""
    effect = conditions_net_effect(history.counted(ConditionsChange), current=history.release_conditions)
    windows = [] if effect is None else [override.temporary_window for override in effect.overrides.removed]
    asked = [window for window in dict.fromkeys(windows) if window is not None][:MAX_OVERRIDE_WINDOWS]
    return {window: _exposed_between(gate, timeline, start=window.start, end=window.end) for window in asked}


_PROJECTED = (
    "before_variants",
    "after_variants",
    "before_groups",
    "after_groups",
    "before_aggregation",
    "after_aggregation",
    *(f"{side}_{setting}" for side in ("before", "after") for setting in _SETTING_FIELDS),
)


def _flag_rows_since(*, team_id: int, feature_flag_id: int, since: datetime) -> list[dict[str, Any]]:
    return list(
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
            before_groups=_changed(_FILTERS, "before.groups"),
            after_groups=_changed(_FILTERS, "after.groups"),
            before_aggregation=_changed(_FILTERS, "before.aggregation_group_type_index"),
            after_aggregation=_changed(_FILTERS, "after.aggregation_group_type_index"),
            **{f"before_{setting}": _changed(field, "before") for setting, field in _SETTING_FIELDS.items()},
            **{f"after_{setting}": _changed(field, "after") for setting, field in _SETTING_FIELDS.items()},
        )
        .values("created_at", "job_type", *_PROJECTED)[: MAX_FLAG_SAVES + 1]
    )


def _too_large(rows: list[dict[str, Any]]) -> FlagHistoryNotCheckedReason | None:
    if len(rows) > MAX_FLAG_SAVES:
        return FlagHistoryNotCheckedReason.TOO_MANY_SAVES
    for row in rows:
        for groups in (row["before_groups"], row["after_groups"]):
            if isinstance(groups, list) and len(groups) > MAX_RELEASE_CONDITIONS:
                return FlagHistoryNotCheckedReason.TOO_MANY_CONDITIONS
    return None


def _flag_changes(rows: list[dict[str, Any]], *, feature_flag_id: int) -> tuple[FlagChange, ...]:
    changes: list[FlagChange] = []
    for row in rows:
        changed_at = row["created_at"]
        split_change = split_change_from_activity(
            changed_at=changed_at,
            job_type=row["job_type"],
            before_variants=row["before_variants"],
            after_variants=row["after_variants"],
        )
        if split_change is not None:
            changes.append(split_change)
        changes.extend(
            bucketing_changes_from_activity(
                changed_at=changed_at,
                feature_flag_id=feature_flag_id,
                before=_settings(row, "before"),
                after=_settings(row, "after"),
            )
        )
        conditions_change = conditions_change_from_activity(
            changed_at=changed_at,
            job_type=row["job_type"],
            before_groups=row["before_groups"],
            after_groups=row["after_groups"],
            before_aggregation=row["before_aggregation"],
            after_aggregation=row["after_aggregation"],
            before_variants=row["before_variants"],
            after_variants=row["after_variants"],
        )
        if conditions_change is not None:
            changes.append(conditions_change)
    return tuple(changes)


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

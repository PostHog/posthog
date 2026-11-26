"""The backtest of the observation windows on the history of a team.

It answers whether the windows would have found the bad rollouts before the people who made them rolled them back,
and how many alerts they would have raised for nothing.

1. Windows: every edit in the range that raised exposure opens a window, as the tick would open it.
2. Rollbacks: the first later version of the flag that no longer raises exposure over the config before the edit,
   within `rollback_within`. That is the rule that closes a window as reverted, so disabling and deleting count.
3. Labels: a rollback is a bad case when errors dropped after it, a signal that the score never reads. Either the people
   with an error of an issue first seen after the edit, or the error rate of the team. Too few errors leave the case
   doubtful, for a person to review. The answer to the rollback reason question replaces the automatic label.
4. Replay: each window advances hour by hour, and each tick reads only the buckets that ended before it. The queries
   read the whole span of each window once, because the counts since the edit of a bucket only hold events up to the
   end of that bucket. So one fetch serves every set of parameters and every way of matching the conditions.

A rollback that closes several windows, such as the one after a rollout in steps, is one case: a window that became
suspicious before it found the case. Every other suspicious window raised an alert that the backtest counts as
unnecessary, for a person to review: an error fixed forward is a real regression.

Two inputs are later than a tick would read them, so the matches by properties are a little optimistic: a relative
date in a condition counts back from the end of the range that one query reads, and a cohort holds its members of
today.
"""

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from posthog.dataclasses import frozen
from posthog.models import Team

from products.feature_flags.backend.exposure_change import (
    ExposureChange,
    ExposureChangeKind,
    ExposureDirection,
    FlagExposureConfig,
    classify_exposure_change,
)
from products.feature_flags.backend.facade.config import ConfigFormatError
from products.feature_flags.backend.flag_windows.baseline import (
    DAY,
    HOUR,
    BaselineHour,
    HourErrors,
    error_baseline,
    errors_by_hour,
)
from products.feature_flags.backend.flag_windows.errors import ErrorBucket, ErrorCounts, errors_by_bucket
from products.feature_flags.backend.flag_windows.exposure import ExposureBucket, exposure_by_bucket
from products.feature_flags.backend.flag_windows.history import FlagHistory, FlagVersion
from products.feature_flags.backend.flag_windows.last_values import LastValueBucket, last_values_by_bucket
from products.feature_flags.backend.flag_windows.opening import watched_edit
from products.feature_flags.backend.flag_windows.query import ConditionMatch, QueryLimits, WatchedEdit, query_limits
from products.feature_flags.backend.flag_windows.window import (
    WEB_WINDOW_PARAMETERS,
    CloseReason,
    ObservationWindow,
    WindowParameters,
    WindowState,
    advance_window,
)
from products.feature_flags.backend.rollback_reason import RollbackReason

BACKTEST_LIMITS = QueryLimits(timeout_seconds=600, max_threads=8)
# The edits that one query reads. Each edit adds columns, so a day with many edits splits into several queries.
EDITS_PER_QUERY = 10


@frozen
class BacktestParameters:
    # A version of the flag that no longer raises exposure this long after the edit is its rollback.
    rollback_within: timedelta
    # The errors of this long before the rollback are compared with the errors of this long after it.
    label_span: timedelta
    # Fewer people with errors than this before the rollback leave the case doubtful.
    min_label_errors: int
    # New errors stopped when the people with them after the rollback are at most this share of those before it.
    stopped_share: float
    # The error rate of the team dropped when the one-sided z of the drop reaches this, and the rate fell by at least
    # this share. On a large team a small dip reaches any z, because the hours count the same people again.
    drop_z: float
    min_relative_drop: float
    window: WindowParameters = WEB_WINDOW_PARAMETERS

    def __post_init__(self) -> None:
        if self.rollback_within > self.window.max_duration:
            raise ValueError(
                f"A rollback after the window expires can't close it, got {self.rollback_within} for a window of "
                f"{self.window.max_duration}"
            )
        if self.label_span < HOUR:
            raise ValueError(f"The label compares whole hours, got a span of {self.label_span}")


DEFAULT_PARAMETERS = BacktestParameters(
    rollback_within=timedelta(hours=72),
    label_span=timedelta(hours=6),
    min_label_errors=10,
    stopped_share=0.25,
    drop_z=3.0,
    min_relative_drop=0.2,
)

# The ways that level 1 finds the people in the watched conditions. None compares everyone with the flag.
CONDITION_MATCHES: tuple[ConditionMatch | None, ...] = (ConditionMatch.REASON, ConditionMatch.PROPERTIES, None)


class Label(StrEnum):
    BAD = "bad"
    NOT_BAD = "not_bad"
    DOUBTFUL = "doubtful"


_LABEL_BY_REASON = {
    RollbackReason.ERRORS: Label.BAD,
    RollbackReason.METRICS: Label.NOT_BAD,
    RollbackReason.PLANNED: Label.NOT_BAD,
    RollbackReason.WRONG_CONFIGURATION: Label.NOT_BAD,
    RollbackReason.OTHER: Label.DOUBTFUL,
}


@frozen
class Rollback:
    at: datetime
    activity_log_id: str | None
    reason: RollbackReason | None


@frozen
class BacktestWindow:
    flag_id: int
    window: ObservationWindow
    kinds: frozenset[ExposureChangeKind]
    rollback: Rollback | None

    @property
    def edit(self) -> WatchedEdit:
        return self.window.edit


@frozen
class TriggerMiss:
    """A rollback that no window watches, because the edit before it didn't raise exposure as the flag stores it, for
    example a cohort edit or a payload edit."""

    flag_id: int
    at: datetime
    activity_log_id: str | None
    reason: RollbackReason | None


@frozen
class Candidates:
    windows: tuple[BacktestWindow, ...]
    misses: tuple[TriggerMiss, ...]
    unreadable: int


def find_candidates(
    histories: Iterable[FlagHistory],
    start: datetime,
    end: datetime,
    parameters: BacktestParameters,
    excluded_flag_ids: frozenset[int] = frozenset(),
) -> Candidates:
    """The windows that the edits in `[start, end)` open, and the rollbacks that no window watches. A flag in
    `excluded_flag_ids`, such as one that another product owns, opens no window."""
    windows: list[BacktestWindow] = []
    misses: list[TriggerMiss] = []
    unreadable = 0
    for history in histories:
        if history.flag_id in excluded_flag_ids:
            continue
        flag_windows: list[BacktestWindow] = []
        directions: dict[int, ExposureDirection] = {}
        for index, version in enumerate(history.versions):
            if version.since is None or not start <= version.since < end or version.config is None:
                continue
            before = _config_before(history.versions[index - 1].config if index else None, version.config)
            try:
                change = classify_exposure_change(before=before, after=version.config)
                directions[index] = change.direction
                if change.direction == ExposureDirection.RAISES:
                    flag_windows.append(_window(history, index, before, change, parameters))
                elif change.direction == ExposureDirection.LOWERS and (
                    successor := _successor(history, index, flag_windows, parameters)
                ):
                    flag_windows.append(successor)
            except ConfigFormatError:
                unreadable += 1
        windows += flag_windows
        misses += [
            TriggerMiss(
                flag_id=history.flag_id,
                at=version.since,
                activity_log_id=version.activity_log_id,
                reason=version.rollback_reason,
            )
            for index, direction in directions.items()
            if direction == ExposureDirection.LOWERS
            and (version := history.versions[index]).since is not None
            and not _watched(version.since, flag_windows, parameters)
            and _follows_edit(history, index, directions, parameters.rollback_within)
        ]
    return Candidates(windows=tuple(windows), misses=tuple(misses), unreadable=unreadable)


def _config_before(previous: FlagExposureConfig | None, after: FlagExposureConfig) -> FlagExposureConfig:
    # A flag created in the range served nobody before.
    return previous if previous is not None else replace(after, active=False)


def _window(
    history: FlagHistory, index: int, before: FlagExposureConfig, change: ExposureChange, parameters: BacktestParameters
) -> BacktestWindow:
    version = history.versions[index]
    assert version.since is not None and version.config is not None
    edit = watched_edit(
        edit_id=version.activity_log_id or f"{history.flag_id}-{version.since.isoformat()}",
        edited_at=version.since,
        before=before,
        after=version.config,
        change=change,
    )
    return BacktestWindow(
        flag_id=history.flag_id,
        window=ObservationWindow(edit=edit, config_before=before, config_after=version.config, state=WindowState.OPEN),
        kinds=change.kinds,
        rollback=_rollback(history.versions[index + 1 :], before, version.since + parameters.rollback_within),
    )


def _successor(
    history: FlagHistory, index: int, earlier: Sequence[BacktestWindow], parameters: BacktestParameters
) -> BacktestWindow | None:
    """The window that watches what is left of the latest window after an edit that lowers exposure without reverting
    it, as the tick opens it after closing that window as superseded."""
    version = history.versions[index]
    if not earlier or version.since is None or version.config is None:
        return None
    latest = earlier[-1]
    if version.since >= latest.edit.edited_at + parameters.window.max_duration:
        return None
    if latest.rollback is not None and latest.rollback.at <= version.since:
        return None
    before = latest.window.config_before
    change = classify_exposure_change(before=before, after=version.config)
    if change.direction != ExposureDirection.RAISES:
        return None
    return _window(history, index, before, change, parameters)


def _rollback(later: Sequence[FlagVersion], before: FlagExposureConfig, until: datetime) -> Rollback | None:
    for version in later:
        if version.since is None or version.since > until or version.config is None:
            return None
        try:
            change = classify_exposure_change(before=before, after=version.config)
        except ConfigFormatError:
            return None
        if change.direction != ExposureDirection.RAISES:
            return Rollback(at=version.since, activity_log_id=version.activity_log_id, reason=version.rollback_reason)
    return None


def _watched(moment: datetime, windows: Sequence[BacktestWindow], parameters: BacktestParameters) -> bool:
    """Whether a window of the flag watched it at `moment`, so a lowering then is its rollback or its successor."""
    for window in windows:
        closes_at = window.rollback.at if window.rollback else window.edit.edited_at + parameters.window.max_duration
        if window.edit.edited_at <= moment <= closes_at:
            return True
    return False


def _follows_edit(
    history: FlagHistory, index: int, directions: Mapping[int, ExposureDirection], within: timedelta
) -> bool:
    """Whether an edit that didn't lower exposure came at most `within` before the version at `index`, or the person
    said that errors drove it. A ramp down in steps is planned, so a lowering after a lowering doesn't count."""
    version = history.versions[index]
    if version.rollback_reason == RollbackReason.ERRORS:
        return True
    assert version.since is not None
    return any(
        (other.since is not None and version.since - within <= other.since < version.since)
        and directions.get(earlier) != ExposureDirection.LOWERS
        for earlier, other in enumerate(history.versions[:index])
    )


@frozen
class WindowData:
    exposure: tuple[ExposureBucket, ...]
    errors: tuple[ErrorBucket, ...]
    # None when the query of the counts by last value ran out of time or memory.
    last_values: tuple[LastValueBucket, ...] | None


@frozen
class BacktestData:
    team_id: int
    windows: Mapping[str, WindowData]
    # By kind of actor: None for persons, or the group type index. Then by the start of each UTC hour.
    hours: Mapping[int | None, Mapping[datetime, HourErrors]]
    baseline: Mapping[int | None, Mapping[datetime, BaselineHour]]
    # The UTC days whose hours and baseline the data holds.
    days: frozenset[datetime]
    # The data holds nothing from this time on.
    until: datetime


def fetch_data(
    team: Team,
    windows: Sequence[BacktestWindow],
    parameters: BacktestParameters,
    now: datetime,
    earlier: BacktestData | None = None,
    checkpoint: Callable[[BacktestData], None] | None = None,
) -> BacktestData:
    """Reads what the windows need, with one set of queries per day of edits. It skips what `earlier` holds, and
    passes what it has read so far to `checkpoint` after each day, so that a failed query doesn't lose the run."""
    if earlier is not None and earlier.team_id != team.pk:
        raise ValueError(f"The data of team {earlier.team_id} can't serve team {team.pk}")
    until = earlier.until if earlier is not None else _hour(now)
    span = max(parameters.window.max_duration, parameters.rollback_within + parameters.label_span) + HOUR
    actor_kinds = sorted(
        {window.edit.group_type_index for window in windows}, key=lambda kind: -1 if kind is None else kind
    )
    data: dict[str, WindowData] = dict(earlier.windows) if earlier is not None else {}
    hours: dict[int | None, dict[datetime, HourErrors]] = {kind: {} for kind in actor_kinds}
    baseline: dict[int | None, dict[datetime, BaselineHour]] = {kind: {} for kind in actor_kinds}
    days: set[datetime] = set()
    if earlier is not None:
        for kind in actor_kinds:
            hours[kind] |= earlier.hours.get(kind, {})
            baseline[kind] |= earlier.baseline.get(kind, {})
        days |= earlier.days

    def snapshot() -> BacktestData:
        return BacktestData(
            team_id=team.pk, windows=data, hours=hours, baseline=baseline, days=frozenset(days), until=until
        )

    by_day: dict[datetime, list[WatchedEdit]] = {}
    for window in windows:
        if window.edit.id not in data:
            by_day.setdefault(_day(window.edit.edited_at), []).append(window.edit)
    with query_limits(BACKTEST_LIMITS):
        for day, edits in sorted(by_day.items()):
            end = min(day + DAY + span, until)
            if end <= day:
                continue
            for chunk in _chunks(edits, EDITS_PER_QUERY):
                exposure = exposure_by_bucket(team, chunk, day, end, HOUR)
                errors = errors_by_bucket(team, chunk, day, end, HOUR)
                last_values = last_values_by_bucket(team, chunk, day, end, HOUR)
                for edit in chunk:
                    values = last_values.get(edit.id)
                    data[edit.id] = WindowData(
                        exposure=tuple(exposure[edit.id]),
                        errors=tuple(errors[edit.id]),
                        last_values=tuple(values) if values is not None else None,
                    )
            if checkpoint is not None:
                checkpoint(snapshot())

        edit_days = {_day(window.edit.edited_at) for window in windows}
        needed = {day + offset * DAY for day in edit_days for offset in range(math.ceil(span / DAY) + 1)}
        for day in sorted(needed - days):
            if day >= until:
                break
            for kind, by_hour in errors_by_hour(team, actor_kinds, day.date()).items():
                hours[kind] |= {day + hour * HOUR: counts for hour, counts in enumerate(by_hour)}
            for kind, baseline_hours in error_baseline(team, actor_kinds, day.date()).items():
                baseline[kind] |= {hour.start: hour for hour in baseline_hours}
            days.add(day)
            if checkpoint is not None:
                checkpoint(snapshot())
    return snapshot()


@frozen
class Replay:
    suspicious_at: datetime | None
    close_reason: CloseReason | None
    closed_at: datetime | None
    max_score: float


def replay_window(
    window: BacktestWindow,
    history: FlagHistory,
    data: BacktestData,
    parameters: WindowParameters,
    condition_match: ConditionMatch | None,
) -> Replay:
    """Advances the window by one tick at the end of each hour, from the first hour after the edit, until it closes or
    the data ends."""
    edit = window.edit
    window_data = data.windows[edit.id]
    hours = data.hours.get(edit.group_type_index, {})
    baseline = data.baseline.get(edit.group_type_index, {})
    first_hour = _hour(edit.edited_at)
    observed = window.window
    if condition_match is None and edit.conditions:
        # The score compares the people in the watched conditions only when it has a way to find them, so with no
        # restriction the window reads as one that watches the whole flag.
        observed = replace(observed, edit=replace(edit, conditions=()))
    suspicious_at: datetime | None = None
    max_score = 0.0
    tick = first_hour + HOUR
    last_tick = min(edit.edited_at + parameters.max_duration + HOUR, data.until)
    while tick <= last_tick:
        flag = history.config_at(tick)
        if flag is None:
            raise ValueError(f"The flag of edit {edit.id} has no config at {tick}")
        outcome = advance_window(
            observed,
            flag=flag,
            now=tick,
            exposure=_before(window_data.exposure, tick),
            errors_since_edit=_errors_since_edit(window_data.errors, tick),
            hours={start: counts for start, counts in hours.items() if first_hour <= start and start + HOUR <= tick},
            baseline=[hour for start, hour in sorted(baseline.items()) if first_hour <= start and start + HOUR <= tick],
            last_values=_before(window_data.last_values, tick) if window_data.last_values is not None else None,
            parameters=parameters,
            condition_match=condition_match,
        )
        if outcome.score is not None:
            max_score = max(max_score, outcome.score.score)
        if outcome.state == WindowState.SUSPICIOUS and suspicious_at is None:
            suspicious_at = tick
        if outcome.state == WindowState.CLOSED:
            return Replay(
                suspicious_at=suspicious_at, close_reason=outcome.close_reason, closed_at=tick, max_score=max_score
            )
        observed = replace(observed, state=outcome.state)
        tick += HOUR
    return Replay(suspicious_at=suspicious_at, close_reason=None, closed_at=None, max_score=max_score)


def _before(buckets: Sequence[Any], tick: datetime) -> list[Any]:
    return [bucket for bucket in buckets if bucket.start + HOUR <= tick]


def _errors_since_edit(errors: Sequence[ErrorBucket], tick: datetime) -> ErrorCounts:
    complete = _before(errors, tick)
    return complete[-1].since_edit if complete else ErrorCounts(with_errors=0, with_new_errors=0, by_variant={})


@frozen
class LabelEvidence:
    # The hours on each side of the rollback. Both sides hold as many, so their sums compare.
    hours: int
    # People with an error of an issue first seen after the edit, summed over the hours of each side.
    new_errors_before: int
    new_errors_after: int
    # The share of the active people of the team with an error, per hour, on each side.
    rate_before: float
    rate_after: float
    drop_z: float


def label_window(
    window: BacktestWindow, data: BacktestData, parameters: BacktestParameters
) -> tuple[Label, LabelEvidence] | None:
    """The label of the rollback of the window, or None when it has none or the data ends before the label span.
    The hour of the rollback holds both sides, so it is left out. A rollback in the hour of the edit leaves no hour
    before it, so only a rollback reason can label it."""
    rollback = window.rollback
    if rollback is None:
        return None
    rollback_hour = _hour(rollback.at)
    span = min(parameters.label_span, rollback_hour - _hour(window.edit.edited_at))
    after_start = rollback_hour + HOUR
    if after_start + parameters.label_span > data.until:
        return None
    before_start, after_end = rollback_hour - span, after_start + span

    errors = data.windows[window.edit.id].errors
    new_before = sum(b.in_bucket.with_new_errors for b in errors if before_start <= b.start < rollback_hour)
    new_after = sum(b.in_bucket.with_new_errors for b in errors if after_start <= b.start < after_end)
    hours = data.hours.get(window.edit.group_type_index, {})
    before = [counts for start, counts in hours.items() if before_start <= start < rollback_hour]
    after = [counts for start, counts in hours.items() if after_start <= start < after_end]
    rate_before, rate_after, z = _rate_drop(before, after)
    evidence = LabelEvidence(
        hours=int(span / HOUR),
        new_errors_before=new_before,
        new_errors_after=new_after,
        rate_before=rate_before,
        rate_after=rate_after,
        drop_z=z,
    )
    if rollback.reason is not None:
        return _LABEL_BY_REASON[rollback.reason], evidence
    new_errors_stopped = (
        new_before >= parameters.min_label_errors and new_after <= parameters.stopped_share * new_before
    )
    rate_dropped = (
        z >= parameters.drop_z and rate_before > 0 and 1 - rate_after / rate_before >= parameters.min_relative_drop
    )
    if new_errors_stopped or rate_dropped:
        return Label.BAD, evidence
    errors_before = sum(counts.with_errors for counts in before)
    if errors_before < parameters.min_label_errors and new_before < parameters.min_label_errors:
        return Label.DOUBTFUL, evidence
    return Label.NOT_BAD, evidence


def _rate_drop(before: Sequence[HourErrors], after: Sequence[HourErrors]) -> tuple[float, float, float]:
    """The error rates of both sides, and the z of the drop from before to after."""
    active_before, errors_before = sum(h.active for h in before), sum(h.with_errors for h in before)
    active_after, errors_after = sum(h.active for h in after), sum(h.with_errors for h in after)
    if not active_before or not active_after:
        return 0.0, 0.0, 0.0
    rate_before, rate_after = errors_before / active_before, errors_after / active_after
    pooled = (errors_before + errors_after) / (active_before + active_after)
    variance = pooled * (1 - pooled) * (1 / active_before + 1 / active_after)
    z = (rate_before - rate_after) / math.sqrt(variance) if variance > 0 else 0.0
    return rate_before, rate_after, z


@frozen
class WindowResult:
    window: BacktestWindow
    label: Label | None
    evidence: LabelEvidence | None
    replays: Mapping[str, Replay]


def run_backtest(
    candidates: Candidates,
    histories: Mapping[int, FlagHistory],
    data: BacktestData,
    parameters: BacktestParameters,
) -> list[WindowResult]:
    results = []
    for window in candidates.windows:
        if window.edit.id not in data.windows:
            continue
        labeled = label_window(window, data, parameters)
        matches = CONDITION_MATCHES if window.edit.conditions else (None,)
        results.append(
            WindowResult(
                window=window,
                label=labeled[0] if labeled else None,
                evidence=labeled[1] if labeled else None,
                replays={
                    _match_name(match): replay_window(window, histories[window.flag_id], data, parameters.window, match)
                    for match in matches
                },
            )
        )
    return results


@frozen
class _Case:
    """The windows that one rollback closes, or one window without a rollback. A rollout in steps opens a window per
    step, and the rollback after the last step reverts them all, so it is one case."""

    results: tuple[WindowResult, ...]

    @property
    def rollback(self) -> Rollback | None:
        return self.results[0].window.rollback

    @property
    def label(self) -> Label | None:
        labels = {result.label for result in self.results}
        return next((label for label in (Label.BAD, Label.DOUBTFUL, Label.NOT_BAD) if label in labels), None)

    def first_alert(self, match: str) -> datetime | None:
        alerts = [
            replay.suspicious_at
            for result in self.results
            if (replay := result.replays.get(match) or result.replays[_match_name(None)]).suspicious_at is not None
        ]
        return min(alerts, default=None)


def summarize(
    results: Sequence[WindowResult], candidates: Candidates, start: datetime, end: datetime
) -> dict[str, Any]:
    """The bad cases found and missed, the alerts that weren't needed per week and the lead times, for each condition
    match. A window without watched conditions counts the same under each match."""
    weeks = max((end - start) / timedelta(weeks=1), 1 / 7)
    grouped: dict[str, list[WindowResult]] = {}
    for result in results:
        rollback = result.window.rollback
        key = f"rollback:{rollback.activity_log_id or rollback.at.isoformat()}" if rollback else result.window.edit.id
        grouped.setdefault(f"{result.window.flag_id}:{key}", []).append(result)
    cases = [_Case(results=tuple(group)) for group in grouped.values()]
    bad = [case for case in cases if case.label == Label.BAD]

    by_match: dict[str, dict[str, Any]] = {}
    for name in (_match_name(match) for match in CONDITION_MATCHES):
        lead_times: list[float] = []
        unnecessary: list[_Case] = []
        doubtful: list[_Case] = []
        unlabeled: list[_Case] = []
        for case in cases:
            alerted_at = case.first_alert(name)
            rollback = case.rollback
            if alerted_at is None:
                continue
            if case.label == Label.BAD:
                if rollback is not None and alerted_at < rollback.at:
                    lead_times.append((rollback.at - alerted_at) / HOUR)
            elif case.label == Label.DOUBTFUL:
                doubtful.append(case)
            elif rollback is not None and case.label is None:
                unlabeled.append(case)
            else:
                unnecessary.append(case)
        by_match[name] = {
            "bad_cases_found": len(lead_times),
            "bad_cases_missed": len(bad) - len(lead_times),
            "found_share": len(lead_times) / len(bad) if bad else None,
            "unnecessary_alerts": len(unnecessary),
            "unnecessary_alerts_per_week": len(unnecessary) / weeks,
            "alerts_on_doubtful_cases": len(doubtful),
            "alerts_on_unlabeled_rollbacks": len(unlabeled),
            "lead_time_hours_median": _median(lead_times),
            "lead_time_hours": sorted(lead_times),
            "alerts_to_review": [case.results[0].window.edit.id for case in unnecessary],
        }
    return {
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "windows": len(candidates.windows),
        "windows_replayed": len(results),
        "unreadable_edits": candidates.unreadable,
        "rollbacks": sum(1 for case in cases if case.rollback is not None),
        "labels": {label.value: sum(1 for case in cases if case.label == label) for label in Label},
        "doubtful_to_review": [case.results[0].window.edit.id for case in cases if case.label == Label.DOUBTFUL],
        "trigger_misses": len(candidates.misses),
        "trigger_misses_answered_errors": sum(1 for miss in candidates.misses if miss.reason == RollbackReason.ERRORS),
        "by_condition_match": by_match,
    }


def _match_name(match: ConditionMatch | None) -> str:
    return match.value if match is not None else "none"


def _median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def _hour(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def _day(moment: datetime) -> datetime:
    return _hour(moment).replace(hour=0)


def _chunks(items: Sequence[WatchedEdit], size: int) -> Iterable[list[WatchedEdit]]:
    for index in range(0, len(items), size):
        yield list(items[index : index + size])

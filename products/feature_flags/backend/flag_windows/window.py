"""The state machine of an observation window: what one tick does to an open or suspicious window.

A window watches one flag edit that raised exposure. Each tick runs these checks in order and stops at the first that
applies:

1. Unreadable config: the flag moved to a config format that the comparison with the edit can't read, such as version
   2. The window can't tell a revert from another edit, so it stops watching.
2. Reverted: the flag gives nobody a value that it didn't give before the edit, for example because someone on the team
   disabled it or put the old config back. This check comes before the score, so the scout never reports an edit that
   the team already rolled back.
3. Superseded: the flag changed again in a way that moves people, and still gives somebody a value that it didn't give
   before the edit. When that edit raises exposure too, the next window watches it. Otherwise, such as after a partial
   revert, the next window watches what is left of this edit, so that the people who keep the new value stay watched.
   Either way it keeps the baseline of this window, and counts the exposure and the errors, in total and by hour, from
   the edit of this window on. So the errors of an earlier rollout step stay out of the baseline of the next step, and
   each tick computes the score again from those counts.
4. Expired: `max_duration` passed since the edit.
5. A suspicious window waits for the verdict of the judgment, and asks for the judgment again on each tick.
6. No reach: nobody is exposed `no_reach_after` the edit.
7. The score: a suspicious score makes the window suspicious and asks for the judgment.
8. No regression: the exposure share of the complete hours became stable, and `post_stable` passed since then.

The module reads no data and stores nothing, so the tick and the backtest replay share one order of checks. The verdicts
of the scout (reported, dismissed, and the expiry of a proposal) are out of scope.
"""

import math
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from enum import StrEnum

from posthog.dataclasses import frozen

from products.feature_flags.backend.exposure_change import (
    ExposureDirection,
    FlagExposureConfig,
    classify_exposure_change,
)
from products.feature_flags.backend.facade.config import is_v1_config
from products.feature_flags.backend.flag_windows.baseline import HOUR, BaselineHour, HourErrors
from products.feature_flags.backend.flag_windows.errors import ErrorCounts
from products.feature_flags.backend.flag_windows.exposure import ExposureBucket, exposure_share
from products.feature_flags.backend.flag_windows.query import ConditionMatch, WatchedEdit
from products.feature_flags.backend.flag_windows.score import WEB_PARAMETERS, ScoreParameters, WindowScore, score_window


class WindowState(StrEnum):
    OPEN = "open"
    SUSPICIOUS = "suspicious"
    CLOSED = "closed"


class CloseReason(StrEnum):
    UNREADABLE_CONFIG = "unreadable_config"
    REVERTED = "reverted"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    NO_REACH = "no_reach"
    NO_REGRESSION = "no_regression"


@frozen
class WindowParameters:
    # When nobody is exposed this long after the edit, the edit reached nobody.
    no_reach_after: timedelta
    # The exposure share is stable when it stays in a band narrower than `stable_share_change` for at least the latest
    # `stable_buckets` buckets.
    stable_buckets: int
    stable_share_change: float
    post_stable: timedelta
    max_duration: timedelta
    score: ScoreParameters

    def __post_init__(self) -> None:
        for name, duration in (
            ("no reach delay", self.no_reach_after),
            ("post stable delay", self.post_stable),
            ("maximum duration", self.max_duration),
        ):
            if duration <= timedelta(0):
                raise ValueError(f"The window needs a positive {name}, got {duration}")
        if self.stable_buckets < 2:
            raise ValueError(f"Stability needs at least 2 buckets to compare, got {self.stable_buckets}")
        if not 0 < self.stable_share_change < 1:
            raise ValueError(f"The stable share change must be between 0 and 1, got {self.stable_share_change}")
        # An edit in the last minutes of an hour completes its first bucket at once, so the first stable run ends just
        # over `stable_buckets - 1` hours after the edit.
        no_regression_after = self.post_stable + (self.stable_buckets - 1) * HOUR
        if self.no_reach_after >= self.max_duration or no_regression_after >= self.max_duration:
            raise ValueError(
                f"The window would expire after {self.max_duration} before it can close as no reach after "
                f"{self.no_reach_after} or as no regression after {no_regression_after}"
            )


# Placeholders until the phase 0 backtest tunes them.
WEB_WINDOW_PARAMETERS = WindowParameters(
    no_reach_after=timedelta(hours=12),
    stable_buckets=3,
    stable_share_change=0.02,
    post_stable=timedelta(hours=24),
    max_duration=timedelta(days=7),
    score=WEB_PARAMETERS,
)


@frozen
class ObservationWindow:
    edit: WatchedEdit
    config_before: FlagExposureConfig
    config_after: FlagExposureConfig
    state: WindowState


@frozen
class TickOutcome:
    state: WindowState
    close_reason: CloseReason | None
    # What the window that replaces a superseded window compares the flag with, as its `config_before`. None unless the
    # window closed as superseded.
    successor_config_before: FlagExposureConfig | None = None
    # None when the tick stopped before the score.
    score: WindowScore | None = None

    @property
    def trigger_judgment(self) -> bool:
        return self.state == WindowState.SUSPICIOUS


def advance_window(
    window: ObservationWindow,
    *,
    flag: FlagExposureConfig,
    now: datetime,
    exposure: Sequence[ExposureBucket],
    errors_since_edit: ErrorCounts | None,
    hours: Mapping[datetime, HourErrors],
    baseline: Sequence[BaselineHour],
    parameters: WindowParameters = WEB_WINDOW_PARAMETERS,
    condition_match: ConditionMatch | None = None,
) -> TickOutcome:
    """Advances the window by the tick at `now`. `flag` holds the fields of the flag at `now`. The other inputs are the
    ones that `score_window` takes. Raises `ConfigFormatError` when a config of the window is not version 1."""
    if window.state == WindowState.CLOSED:
        raise ValueError(f"A closed window doesn't tick, got the window of edit {window.edit.id}")
    edited_at = window.edit.edited_at
    if now < edited_at:
        raise ValueError(f"The tick at {now} comes before the edit at {edited_at}")

    if not is_v1_config(flag.filters):
        return _closed(CloseReason.UNREADABLE_CONFIG)
    # The classification compares who gets which value, not the stored config, so a revert that keeps a payload change
    # counts. A partial revert still raises exposure over the old config, so the next check finds it as another edit.
    if classify_exposure_change(before=window.config_before, after=flag).direction != ExposureDirection.RAISES:
        return _closed(CloseReason.REVERTED)
    # An edit that moves nobody, such as a payload change, leaves the window open.
    change_since_edit = classify_exposure_change(before=window.config_after, after=flag)
    if change_since_edit.kinds:
        return _closed(
            CloseReason.SUPERSEDED,
            successor_config_before=(
                window.config_after if change_since_edit.direction == ExposureDirection.RAISES else window.config_before
            ),
        )
    if now >= edited_at + parameters.max_duration:
        return _closed(CloseReason.EXPIRED)
    if window.state == WindowState.SUSPICIOUS:
        return TickOutcome(state=WindowState.SUSPICIOUS, close_reason=None)
    # The exposure query has no bucket before the edit, so the share at the previous level is unknown. The level that it
    # can show is zero: nobody exposed. That is the previous level of an edit that enables the flag or adds a condition,
    # which the counts in the watched conditions see apart from the rest of the flag. An edit from a level above zero
    # that reaches nobody closes later, as no regression.
    if now >= edited_at + parameters.no_reach_after and not _exposed_since_edit(exposure, condition_match):
        return _closed(CloseReason.NO_REACH)

    score = score_window(
        window.edit, exposure, errors_since_edit, hours, baseline, parameters.score, condition_match=condition_match
    )
    if score.suspicious:
        return TickOutcome(state=WindowState.SUSPICIOUS, close_reason=None, score=score)
    stable_since = _stable_since(exposure, now, parameters)
    if stable_since is not None and now >= stable_since + parameters.post_stable:
        return _closed(CloseReason.NO_REGRESSION, score=score)
    return TickOutcome(state=WindowState.OPEN, close_reason=None, score=score)


def _closed(
    reason: CloseReason, *, successor_config_before: FlagExposureConfig | None = None, score: WindowScore | None = None
) -> TickOutcome:
    return TickOutcome(
        state=WindowState.CLOSED,
        close_reason=reason,
        successor_config_before=successor_config_before,
        score=score,
    )


def _exposed_since_edit(exposure: Sequence[ExposureBucket], condition_match: ConditionMatch | None) -> int:
    """The number of people (or groups) exposed since the edit in the watched conditions, or in the whole flag when those
    have no counts."""
    if not exposure:
        return 0
    since_edit = exposure[-1].since_edit
    if condition_match is not None and condition_match in since_edit.in_condition:
        return since_edit.in_condition[condition_match].exposed
    return since_edit.exposed


def _stable_since(exposure: Sequence[ExposureBucket], now: datetime, parameters: WindowParameters) -> datetime | None:
    """The end of the bucket in which the share had stayed in the band for `stable_buckets` buckets, or None when the
    latest buckets aren't stable. A share that moves out of the band starts the count again. The hour in progress holds
    only the first minutes of people, so its share is noise and stays out."""
    complete = [bucket for bucket in exposure if bucket.start + HOUR <= now]
    run_start = len(complete)
    low, high = math.inf, -math.inf
    for index in range(len(complete) - 1, -1, -1):
        share = exposure_share(complete[index].in_bucket)
        low, high = min(low, share), max(high, share)
        if high - low >= parameters.stable_share_change:
            break
        run_start = index
    if len(complete) - run_start < parameters.stable_buckets:
        return None
    return complete[run_start + parameters.stable_buckets - 1].start + HOUR

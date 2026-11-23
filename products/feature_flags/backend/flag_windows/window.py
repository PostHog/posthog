"""The state machine of an observation window: what one tick does to an open or suspicious window.

A window watches one flag edit that raised exposure. Each tick checks the closes first and stops at the first that
applies, in this order:

1. Reverted: the flag gives nobody a value that it didn't give before the edit, for example because a person disabled
   it or put the old config back. This check comes first, so the scout never reports an edit that a person already
   rolled back.
2. Superseded: the flag changed again in a way that moves people. When that edit raises exposure too, the next window
   keeps the baseline and the evidence of this one, so the errors of an earlier rollout step stay out of the baseline of
   the next step.
3. Expired: `max_duration` passed since the edit.
4. A suspicious window waits for the verdict of the judgment, and asks for the judgment again on each tick.
5. No reach: nobody is exposed `no_reach_after` the edit.
6. The score: a suspicious score makes the window suspicious and asks for the judgment.
7. No regression: the exposure share became stable, and `post_stable` passed since then.

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
from products.feature_flags.backend.flag_windows.baseline import HOUR, BaselineHour, HourErrors
from products.feature_flags.backend.flag_windows.errors import ErrorCounts
from products.feature_flags.backend.flag_windows.exposure import ExposureBucket
from products.feature_flags.backend.flag_windows.query import ConditionMatch, WatchedEdit
from products.feature_flags.backend.flag_windows.score import (
    WEB_PARAMETERS,
    ScoreParameters,
    WindowScore,
    exposure_share,
    score_window,
)


class WindowState(StrEnum):
    OPEN = "open"
    SUSPICIOUS = "suspicious"
    CLOSED = "closed"


class CloseReason(StrEnum):
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
        if self.no_reach_after >= self.max_duration or self.post_stable >= self.max_duration:
            raise ValueError(
                f"The window would expire after {self.max_duration} before it can close as no reach after "
                f"{self.no_reach_after} or as no regression after {self.post_stable}"
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
    trigger_judgment: bool
    # The edit that superseded the window raises exposure too, so the window of that edit keeps the baseline and the
    # evidence of this window.
    successor_keeps_evidence: bool = False
    # None when the tick stopped before the score.
    score: WindowScore | None = None

    def __post_init__(self) -> None:
        if (self.state == WindowState.CLOSED) != (self.close_reason is not None):
            raise ValueError(f"Only a closed window has a close reason, got {self.state} with {self.close_reason}")
        if self.successor_keeps_evidence and self.close_reason != CloseReason.SUPERSEDED:
            raise ValueError(f"Only a superseded window has a successor, got {self.close_reason}")


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
    ones that `score_window` takes. Raises `ConfigFormatError` when a config is not version 1."""
    if window.state == WindowState.CLOSED:
        raise ValueError(f"A closed window doesn't tick, got the window of edit {window.edit.id}")
    edited_at = window.edit.edited_at
    if now < edited_at:
        raise ValueError(f"The tick at {now} comes before the edit at {edited_at}")

    # The classification compares who gets which value, not the stored config, so a revert that keeps a payload change
    # counts. A partial revert still raises exposure over the old config, so the next check finds it as another edit.
    if classify_exposure_change(before=window.config_before, after=flag).direction != ExposureDirection.RAISES:
        return _closed(CloseReason.REVERTED)
    # An edit that moves nobody, such as a payload change, leaves the window open.
    change_since_edit = classify_exposure_change(before=window.config_after, after=flag)
    if change_since_edit.kinds:
        return _closed(
            CloseReason.SUPERSEDED,
            successor_keeps_evidence=change_since_edit.direction == ExposureDirection.RAISES,
        )
    if now >= edited_at + parameters.max_duration:
        return _closed(CloseReason.EXPIRED)
    if window.state == WindowState.SUSPICIOUS:
        return TickOutcome(state=WindowState.SUSPICIOUS, close_reason=None, trigger_judgment=True)
    if now >= edited_at + parameters.no_reach_after and not _exposed_since_edit(exposure, condition_match):
        return _closed(CloseReason.NO_REACH)

    score = score_window(
        window.edit, exposure, errors_since_edit, hours, baseline, parameters.score, condition_match=condition_match
    )
    if score.suspicious:
        return TickOutcome(state=WindowState.SUSPICIOUS, close_reason=None, trigger_judgment=True, score=score)
    stable_since = _stable_since(exposure, parameters)
    if stable_since is not None and now >= stable_since + parameters.post_stable:
        return _closed(CloseReason.NO_REGRESSION, score=score)
    return TickOutcome(state=WindowState.OPEN, close_reason=None, trigger_judgment=False, score=score)


def _closed(
    reason: CloseReason, *, successor_keeps_evidence: bool = False, score: WindowScore | None = None
) -> TickOutcome:
    return TickOutcome(
        state=WindowState.CLOSED,
        close_reason=reason,
        trigger_judgment=False,
        successor_keeps_evidence=successor_keeps_evidence,
        score=score,
    )


def _exposed_since_edit(exposure: Sequence[ExposureBucket], condition_match: ConditionMatch | None) -> int:
    """The exposure query has no bucket before the edit, so the share at the previous level is unknown. The level that
    it can show is zero: nobody exposed. That is the previous level of an edit that enables the flag or adds a
    condition, which the counts in the watched conditions see apart from the rest of the flag. An edit from a level
    above zero that reaches nobody closes later, as no regression."""
    if not exposure:
        return 0
    since_edit = exposure[-1].since_edit
    if condition_match is not None and condition_match in since_edit.in_condition:
        return since_edit.in_condition[condition_match].exposed
    return since_edit.exposed


def _stable_since(exposure: Sequence[ExposureBucket], parameters: WindowParameters) -> datetime | None:
    """The end of the bucket in which the share had stayed in the band for `stable_buckets` buckets, or None when the
    latest buckets aren't stable. A share that moves out of the band starts the count again."""
    run_start = len(exposure)
    low, high = math.inf, -math.inf
    for index in range(len(exposure) - 1, -1, -1):
        share = exposure_share(exposure[index].in_bucket)
        low, high = min(low, share), max(high, share)
        if high - low >= parameters.stable_share_change:
            break
        run_start = index
    if len(exposure) - run_start < parameters.stable_buckets:
        return None
    return exposure[run_start + parameters.stable_buckets - 1].start + HOUR

"""What one tick does to the windows of a team, from the flag edits since the previous tick. It reads no data.

The tick goes over the versions of each flag, oldest first. Each version first ticks the windows of the flag that it
comes after, at the time of the version, with the checks of the state machine that read only the config. Then a version
that raises exposure opens a window. A version that closes a window as superseded without a raise of its own opens the
successor window, which watches what is left of the closed one. Last, the tick checks each open window against the
flag as it is now, so a window closes when it expires or when the flag leaves the watch.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timedelta

from posthog.dataclasses import frozen

from products.feature_flags.backend.exposure_change import (
    ExposureDirection,
    FlagExposureConfig,
    classify_exposure_change,
)
from products.feature_flags.backend.facade.config import ConfigFormatError
from products.feature_flags.backend.flag_windows.history import FlagHistory
from products.feature_flags.backend.flag_windows.opening import watched_edit
from products.feature_flags.backend.flag_windows.window import (
    CloseReason,
    ObservationWindow,
    TickOutcome,
    WindowState,
    close_by_config,
)


@frozen
class TrackedWindow:
    """A window that is not closed. The activity log entry of the edit that the window watches identifies it."""

    flag_id: int
    activity_log_id: str
    window: ObservationWindow


@frozen
class OpenedWindow:
    flag_id: int
    activity_log_id: str
    edited_at: datetime
    config_before: FlagExposureConfig
    config_after: FlagExposureConfig
    previous_activity_log_id: str | None


@frozen
class ClosedWindow:
    activity_log_id: str
    reason: CloseReason
    closed_at: datetime


@frozen
class TickPlan:
    opened: tuple[OpenedWindow, ...]
    # Can hold a window from `opened`, when a later version of the same tick closes it.
    closed: tuple[ClosedWindow, ...]


def observation_window(
    *,
    activity_log_id: str,
    edited_at: datetime,
    config_before: FlagExposureConfig,
    config_after: FlagExposureConfig,
    state: WindowState,
) -> ObservationWindow:
    """The window of an edit that raised exposure from `config_before` to `config_after`."""
    change = classify_exposure_change(before=config_before, after=config_after)
    edit = watched_edit(
        edit_id=activity_log_id, edited_at=edited_at, before=config_before, after=config_after, change=change
    )
    return ObservationWindow(edit=edit, config_before=config_before, config_after=config_after, state=state)


def plan_tick(
    histories: Iterable[FlagHistory],
    windows: Sequence[TrackedWindow],
    *,
    current: Mapping[int, FlagExposureConfig],
    known_edits: frozenset[str],
    excluded_flag_ids: frozenset[int],
    now: datetime,
    max_duration: timedelta,
) -> TickPlan:
    """The windows that the tick at `now` opens and closes.

    `histories` hold the versions since the previous tick, and can repeat versions that an earlier tick already read.
    `windows` are the windows that are not closed. `current` holds the config of each flag of `windows` at `now`.
    `known_edits` are the activity log entries that already have a window, closed or not, so a version that an earlier
    tick read opens no second window. A flag in `excluded_flag_ids` opens no window, and its open windows close."""
    tick = _Tick(max_duration=max_duration)
    for window in windows:
        tick.track(window)
    for history in histories:
        if history.flag_id not in excluded_flag_ids:
            tick.read(history, known_edits)
    for window in tick.still_open():
        if window.flag_id in excluded_flag_ids:
            tick.close(window, CloseReason.EXCLUDED, now)
        elif (flag := current.get(window.flag_id)) is not None:
            if (outcome := tick.check(window, flag, now)) is not None and outcome.close_reason is not None:
                # A change that no activity log entry shows, such as a data migration, leaves no edit to watch.
                tick.close(window, outcome.close_reason, now)
    return TickPlan(opened=tuple(tick.opened), closed=tuple(tick.closed))


@frozen
class _Superseded:
    activity_log_id: str
    successor_config_before: FlagExposureConfig


class _Tick:
    def __init__(self, *, max_duration: timedelta) -> None:
        self.max_duration = max_duration
        self.open: dict[str, TrackedWindow] = {}
        self.opened: list[OpenedWindow] = []
        self.closed: list[ClosedWindow] = []

    def track(self, window: TrackedWindow) -> None:
        self.open[window.activity_log_id] = window

    def still_open(self) -> list[TrackedWindow]:
        return list(self.open.values())

    def close(self, window: TrackedWindow, reason: CloseReason, at: datetime) -> None:
        del self.open[window.activity_log_id]
        self.closed.append(ClosedWindow(activity_log_id=window.activity_log_id, reason=reason, closed_at=at))

    def check(self, window: TrackedWindow, flag: FlagExposureConfig, at: datetime) -> TickOutcome | None:
        try:
            return close_by_config(window.window, flag=flag, now=at, max_duration=self.max_duration)
        except ConfigFormatError:
            return TickOutcome(state=WindowState.CLOSED, close_reason=CloseReason.UNREADABLE_CONFIG)

    def read(self, history: FlagHistory, known_edits: frozenset[str]) -> None:
        for index, version in enumerate(history.versions):
            if version.since is None or version.config is None or version.activity_log_id is None:
                continue
            superseded = self._advance(history.flag_id, version.since, version.config)
            if version.activity_log_id in known_edits:
                continue
            previous = history.versions[index - 1].config if index else None
            # A flag created in the range served nobody before.
            before = previous if previous is not None else replace(version.config, active=False)
            if _raises(before, version.config):
                config_before = before
            elif superseded is not None and _raises(superseded.successor_config_before, version.config):
                config_before = superseded.successor_config_before
            else:
                continue
            self._open(
                flag_id=history.flag_id,
                activity_log_id=version.activity_log_id,
                edited_at=version.since,
                config_before=config_before,
                config_after=version.config,
                previous=superseded.activity_log_id if superseded is not None else None,
            )

    def _advance(self, flag_id: int, at: datetime, flag: FlagExposureConfig) -> "_Superseded | None":
        """Ticks the windows of the flag that started before `at`. Returns the window that the version superseded, or
        None when it superseded no window."""
        superseded = None
        for window in [window for window in self.open.values() if window.flag_id == flag_id]:
            # A version that an earlier tick read again comes before the windows that it or a later version opened.
            if window.window.edit.edited_at >= at:
                continue
            expires_at = window.window.edit.edited_at + self.max_duration
            if at >= expires_at:
                self.close(window, CloseReason.EXPIRED, expires_at)
                continue
            outcome = self.check(window, flag, at)
            if outcome is None or outcome.close_reason is None:
                continue
            self.close(window, outcome.close_reason, at)
            if outcome.close_reason == CloseReason.SUPERSEDED and outcome.successor_config_before is not None:
                superseded = _Superseded(
                    activity_log_id=window.activity_log_id, successor_config_before=outcome.successor_config_before
                )
        return superseded

    def _open(
        self,
        *,
        flag_id: int,
        activity_log_id: str,
        edited_at: datetime,
        config_before: FlagExposureConfig,
        config_after: FlagExposureConfig,
        previous: str | None,
    ) -> None:
        self.opened.append(
            OpenedWindow(
                flag_id=flag_id,
                activity_log_id=activity_log_id,
                edited_at=edited_at,
                config_before=config_before,
                config_after=config_after,
                previous_activity_log_id=previous,
            )
        )
        self.track(
            TrackedWindow(
                flag_id=flag_id,
                activity_log_id=activity_log_id,
                window=observation_window(
                    activity_log_id=activity_log_id,
                    edited_at=edited_at,
                    config_before=config_before,
                    config_after=config_after,
                    state=WindowState.OPEN,
                ),
            )
        )


def _raises(before: FlagExposureConfig, after: FlagExposureConfig) -> bool:
    try:
        return classify_exposure_change(before=before, after=after).direction == ExposureDirection.RAISES
    except ConfigFormatError:
        return False

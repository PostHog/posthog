from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from django.test import SimpleTestCase

from parameterized import param, parameterized

from products.feature_flags.backend.exposure_change import FlagExposureConfig
from products.feature_flags.backend.flag_windows.history import FlagHistory, FlagVersion
from products.feature_flags.backend.flag_windows.life_cycle import TrackedWindow, observation_window, plan_tick
from products.feature_flags.backend.flag_windows.window import CloseReason, WindowState

EDITED_AT = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)
MAX_DURATION = timedelta(days=7)
FLAG_ID = 1


def _flag(rollout: float) -> FlagExposureConfig:
    return FlagExposureConfig(
        active=True,
        filters={"groups": [{"properties": [], "rollout_percentage": rollout, "variant": None}]},
        key="new-checkout",
        bucketing_identifier=None,
        ensure_experience_continuity=False,
    )


def _history(*versions: tuple[timedelta | None, float | None, str | None]) -> FlagHistory:
    """Each version as (time since the first edit, rollout, activity log entry). A rollout of None is a flag that the
    first entry created."""
    return FlagHistory(
        flag_id=FLAG_ID,
        versions=tuple(
            FlagVersion(
                since=EDITED_AT + offset if offset is not None else None,
                config=_flag(rollout) if rollout is not None else None,
                activity_log_id=entry,
            )
            for offset, rollout, entry in versions
        ),
    )


def _window(entry: str, before: float, after: float, offset: timedelta = timedelta(0)) -> TrackedWindow:
    return TrackedWindow(
        flag_id=FLAG_ID,
        activity_log_id=entry,
        window=observation_window(
            activity_log_id=entry,
            edited_at=EDITED_AT + offset,
            config_before=_flag(before),
            config_after=_flag(after),
            state=WindowState.OPEN,
        ),
    )


def _describe(config: FlagExposureConfig) -> str:
    rollout = (config.filters or {})["groups"][0]["rollout_percentage"]
    return f"{rollout}%" if config.active else "off"


class TestPlanTick(SimpleTestCase):
    @parameterized.expand(
        [
            param(
                "a_raise_opens_a_window",
                histories=[_history((None, 10, None), (timedelta(0), 25, "a"))],
                opened=[("a", "10%", "25%", None)],
            ),
            param(
                "a_flag_created_enabled_opens_a_window_from_off",
                histories=[_history((None, None, None), (timedelta(0), 25, "a"))],
                opened=[("a", "off", "25%", None)],
            ),
            param("a_lowering_opens_no_window", histories=[_history((None, 25, None), (timedelta(0), 10, "a"))]),
            param(
                "a_version_that_an_earlier_tick_read_changes_nothing",
                histories=[_history((None, 10, None), (timedelta(0), 25, "a"))],
                windows=[_window("a", 10, 25)],
                known=frozenset({"a"}),
            ),
            param(
                "a_revert_closes_the_window",
                histories=[_history((None, 25, None), (HOUR, 10, "b"))],
                windows=[_window("a", 10, 25)],
                closed=[("a", CloseReason.REVERTED, HOUR)],
            ),
            param(
                "a_ramp_up_supersedes_the_window_and_the_next_window_keeps_it",
                histories=[_history((None, 25, None), (HOUR, 50, "b"))],
                windows=[_window("a", 10, 25)],
                opened=[("b", "25%", "50%", "a")],
                closed=[("a", CloseReason.SUPERSEDED, HOUR)],
            ),
            param(
                "a_partial_revert_watches_what_is_left_of_the_edit",
                histories=[_history((None, 50, None), (HOUR, 25, "b"))],
                windows=[_window("a", 10, 50)],
                opened=[("b", "10%", "25%", "a")],
                closed=[("a", CloseReason.SUPERSEDED, HOUR)],
            ),
            param(
                "a_raise_and_its_revert_in_one_tick",
                histories=[_history((None, 10, None), (timedelta(0), 25, "a"), (HOUR, 10, "b"))],
                opened=[("a", "10%", "25%", None)],
                closed=[("a", CloseReason.REVERTED, HOUR)],
            ),
            param(
                "a_window_expires_before_a_later_edit",
                histories=[_history((None, 25, None), (MAX_DURATION + HOUR, 50, "b"))],
                windows=[_window("a", 10, 25)],
                now=EDITED_AT + MAX_DURATION + 2 * HOUR,
                opened=[("b", "25%", "50%", None)],
                closed=[("a", CloseReason.EXPIRED, MAX_DURATION)],
            ),
            param(
                "a_window_expires_at_the_tick",
                windows=[_window("a", 10, 25)],
                current=_flag(25),
                now=EDITED_AT + MAX_DURATION,
                closed=[("a", CloseReason.EXPIRED, MAX_DURATION)],
            ),
            param(
                "an_excluded_flag_opens_no_window_and_its_window_closes",
                histories=[_history((None, 25, None), (HOUR, 50, "b"))],
                windows=[_window("a", 10, 25)],
                excluded=frozenset({FLAG_ID}),
                closed=[("a", CloseReason.EXCLUDED, 2 * HOUR)],
            ),
            param(
                "a_change_without_an_entry_closes_the_window_without_a_successor",
                windows=[_window("a", 10, 25)],
                current=_flag(50),
                closed=[("a", CloseReason.SUPERSEDED, 2 * HOUR)],
            ),
        ]
    )
    def test_plan_tick(
        self,
        _name: str,
        histories: Sequence[FlagHistory] = (),
        windows: Sequence[TrackedWindow] = (),
        current: FlagExposureConfig | None = None,
        known: frozenset[str] = frozenset(),
        excluded: frozenset[int] = frozenset(),
        now: datetime = EDITED_AT + 2 * HOUR,
        opened: Sequence[tuple[Any, ...]] = (),
        closed: Sequence[tuple[Any, ...]] = (),
    ) -> None:
        plan = plan_tick(
            histories,
            windows,
            current={FLAG_ID: current} if current is not None else {},
            known_edits=known,
            excluded_flag_ids=excluded,
            now=now,
            max_duration=MAX_DURATION,
        )

        assert [
            (
                window.activity_log_id,
                _describe(window.config_before),
                _describe(window.config_after),
                window.previous_activity_log_id,
            )
            for window in plan.opened
        ] == list(opened)
        assert [
            (window.activity_log_id, window.reason, window.closed_at - EDITED_AT) for window in plan.closed
        ] == list(closed)

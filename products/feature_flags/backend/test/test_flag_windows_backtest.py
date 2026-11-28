import dataclasses
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.test import SimpleTestCase

from parameterized import param, parameterized

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.test.persons import create_person

from products.feature_flags.backend.exposure_change import FlagExposureConfig, classify_exposure_change
from products.feature_flags.backend.flag_windows.backtest import (
    DEFAULT_PARAMETERS,
    ActorHours,
    BacktestData,
    BacktestWindow,
    Label,
    WindowData,
    dump_data,
    fetch_data,
    find_candidates,
    label_window,
    load_data,
    replay_window,
    run_backtest,
    summarize,
)
from products.feature_flags.backend.flag_windows.baseline import HOUR, BaselineHour, HourErrors
from products.feature_flags.backend.flag_windows.errors import ErrorBucket, ErrorCounts
from products.feature_flags.backend.flag_windows.exposure import ExposureBucket
from products.feature_flags.backend.flag_windows.history import FlagHistory, FlagVersion, flag_histories
from products.feature_flags.backend.flag_windows.opening import watched_edit
from products.feature_flags.backend.flag_windows.query import WatchedCondition
from products.feature_flags.backend.flag_windows.window import CloseReason
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.rollback_reason import RollbackReason
from products.feature_flags.backend.test.flag_window_fixtures import exposure_counts, split

EDITED_AT = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
ROLLBACK_AT = EDITED_AT + timedelta(hours=6, minutes=30)
PEOPLE = 1000


def _flag(
    *rollouts: float,
    active: bool = True,
    payloads: Mapping[str, Any] | None = None,
    variants: Sequence[Mapping[str, Any]] | None = None,
) -> FlagExposureConfig:
    filters: dict[str, Any] = {
        "groups": [
            {"properties": [{"key": f"plan_{index}", "value": "pro", "type": "person"}], "rollout_percentage": rollout}
            for index, rollout in enumerate(rollouts)
        ]
    }
    if payloads is not None:
        filters["payloads"] = payloads
    if variants is not None:
        filters["multivariate"] = {"variants": list(variants)}
    return FlagExposureConfig(
        active=active,
        filters=filters,
        key="new-checkout",
        bucketing_identifier=None,
        ensure_experience_continuity=False,
    )


def _history(*versions: tuple[timedelta | None, FlagExposureConfig, RollbackReason | None]) -> FlagHistory:
    return FlagHistory(
        flag_id=1,
        versions=tuple(
            FlagVersion(
                since=EDITED_AT + offset if offset is not None else None,
                config=config,
                activity_log_id=f"entry-{index}" if offset is not None else None,
                rollback_reason=reason,
            )
            for index, (offset, config, reason) in enumerate(versions)
        ),
    )


ROLLED_BACK = _history(
    (None, _flag(10), None),
    (timedelta(0), _flag(25), None),
    (ROLLBACK_AT - EDITED_AT, _flag(25, active=False), None),
)


def _window() -> BacktestWindow:
    candidates = find_candidates([ROLLED_BACK], EDITED_AT, EDITED_AT + timedelta(days=1), DEFAULT_PARAMETERS)
    return candidates.windows[0]


def _data(
    errors_from_hour: int, new_errors: tuple[int, int] = (30, 0), until: timedelta = timedelta(days=2)
) -> BacktestData:
    """Exposure buckets whose errors make level 1 suspicious from `errors_from_hour` on, and new errors per hour before
    and after the rollback."""
    exposure = [
        ExposureBucket(
            start=EDITED_AT + hour * HOUR,
            in_bucket=exposure_counts(split(250, 750)),
            since_edit=exposure_counts(split(PEOPLE, PEOPLE, (200, 10) if hour >= errors_from_hour else (0, 0))),
        )
        for hour in range(12)
    ]
    rollback_hour = int((ROLLBACK_AT - EDITED_AT) / HOUR)
    errors = [
        ErrorBucket(
            start=EDITED_AT + hour * HOUR,
            in_bucket=ErrorCounts(with_errors=0, with_new_errors=new_errors[hour > rollback_hour], by_variant={}),
            since_edit=ErrorCounts(with_errors=0, with_new_errors=0, by_variant={}),
        )
        for hour in range(12)
        if hour != rollback_hour
    ]
    return BacktestData(
        team_id=1,
        windows={"entry-1": WindowData(exposure=tuple(exposure), errors=tuple(errors), last_values=None)},
        actors=(),
        until=EDITED_AT + until,
    )


class TestFindCandidates(SimpleTestCase):
    @parameterized.expand(
        [
            param("disabled_within_the_limit", disabled_after=timedelta(hours=6), rollback=True),
            param("disabled_after_the_limit", disabled_after=timedelta(hours=73), rollback=False),
        ]
    )
    def test_a_raise_opens_a_window_with_its_rollback(self, _: str, disabled_after: timedelta, rollback: bool) -> None:
        history = _history(
            (None, _flag(10), None),
            (timedelta(0), _flag(25), None),
            (disabled_after, _flag(25, active=False), None),
        )

        candidates = find_candidates([history], EDITED_AT, EDITED_AT + timedelta(days=1), DEFAULT_PARAMETERS)

        assert [window.edit.id for window in candidates.windows] == ["entry-1"]
        assert (candidates.windows[0].rollback is not None) == rollback
        assert candidates.misses == ()

    def test_a_partial_revert_opens_a_window_on_what_is_left_and_shares_the_rollback(self) -> None:
        history = _history(
            (None, _flag(0), None),
            (timedelta(0), _flag(50), None),
            (timedelta(hours=2), _flag(20), None),
            (timedelta(hours=5), _flag(20, active=False), None),
        )

        candidates = find_candidates([history], EDITED_AT, EDITED_AT + timedelta(days=1), DEFAULT_PARAMETERS)

        assert [
            (window.edit.id, window.window.config_before, window.rollback and window.rollback.activity_log_id)
            for window in candidates.windows
        ] == [("entry-1", _flag(0), "entry-3"), ("entry-2", _flag(0), "entry-3")]
        assert candidates.misses == ()

    @parameterized.expand(
        [
            param("from_the_start", steps=[_flag(100), _flag(50), _flag(0)], misses=[]),
            param(
                "after_an_edit_that_kept_exposure",
                steps=[_flag(100), _flag(100, payloads={"true": "{}"}), _flag(50), _flag(0)],
                misses=["entry-2"],
            ),
        ]
    )
    def test_a_ramp_down_in_steps_misses_at_most_its_first_step(
        self, _: str, steps: list[FlagExposureConfig], misses: list[str]
    ) -> None:
        history = _history(
            (None, steps[0], None), *((timedelta(hours=index), step, None) for index, step in enumerate(steps[1:]))
        )

        candidates = find_candidates([history], EDITED_AT, EDITED_AT + timedelta(days=1), DEFAULT_PARAMETERS)

        assert [miss.activity_log_id for miss in candidates.misses] == misses

    def test_a_rollback_after_an_edit_that_kept_exposure_is_a_trigger_miss(self) -> None:
        history = _history(
            (None, _flag(25), None),
            (timedelta(0), _flag(25, payloads={"true": "{}"}), None),
            (timedelta(hours=2), _flag(25, active=False), RollbackReason.ERRORS),
        )

        candidates = find_candidates([history], EDITED_AT, EDITED_AT + timedelta(days=1), DEFAULT_PARAMETERS)

        assert candidates.windows == ()
        assert [(miss.activity_log_id, miss.reason) for miss in candidates.misses] == [
            ("entry-2", RollbackReason.ERRORS)
        ]


class TestReplay(SimpleTestCase):
    def test_a_tick_reads_only_the_buckets_that_ended_before_it(self) -> None:
        window = _window()

        replay = replay_window(
            window, ROLLED_BACK, _data(errors_from_hour=3), DEFAULT_PARAMETERS.window, condition_match=None
        )

        assert replay.suspicious_at == EDITED_AT + 4 * HOUR
        assert (replay.close_reason, replay.closed_at) == (CloseReason.REVERTED, EDITED_AT + 7 * HOUR)

    @parameterized.expand(
        [
            param("alert_before_the_rollback", errors_from_hour=3, found=1, unnecessary=0, lead_times=[2.5]),
            param("no_alert", errors_from_hour=99, found=0, unnecessary=0, lead_times=[]),
        ]
    )
    def test_the_summary_counts_a_bad_case_found_before_its_rollback(
        self, _: str, errors_from_hour: int, found: int, unnecessary: int, lead_times: list[float]
    ) -> None:
        candidates = find_candidates([ROLLED_BACK], EDITED_AT, EDITED_AT + timedelta(days=1), DEFAULT_PARAMETERS)

        results = run_backtest(candidates, {1: ROLLED_BACK}, _data(errors_from_hour), DEFAULT_PARAMETERS)
        summary = summarize(results, candidates, EDITED_AT, EDITED_AT + timedelta(weeks=1))["by_condition_match"]

        assert summary["none"] | {"alerts_to_review": None} == {
            "bad_cases_found": found,
            "bad_cases_missed": 1 - found,
            "found_share": float(found),
            "unnecessary_alerts": unnecessary,
            "unnecessary_alerts_per_week": float(unnecessary),
            "alerts_on_doubtful_cases": 0,
            "alerts_on_unlabeled_rollbacks": 0,
            "lead_time_hours_median": lead_times[0] if lead_times else None,
            "lead_time_hours": lead_times,
            "alerts_to_review": None,
        }


class TestSummary(SimpleTestCase):
    def test_a_rollout_in_steps_with_one_rollback_is_one_bad_case(self) -> None:
        history = _history(
            (None, _flag(0), None),
            (timedelta(0), _flag(10), None),
            (timedelta(hours=3), _flag(50), None),
            (ROLLBACK_AT - EDITED_AT, _flag(50, active=False), None),
        )
        candidates = find_candidates([history], EDITED_AT, EDITED_AT + timedelta(days=1), DEFAULT_PARAMETERS)
        data = _data(errors_from_hour=1)
        # The second step reads the same counts, so only its window alerts before the rollback.
        data = dataclasses.replace(
            data, windows={**data.windows, "entry-2": dataclasses.replace(data.windows["entry-1"], exposure=())}
        )

        results = run_backtest(candidates, {1: history}, data, DEFAULT_PARAMETERS)
        summary = summarize(results, candidates, EDITED_AT, EDITED_AT + timedelta(weeks=1))

        assert (summary["rollbacks"], summary["labels"]["bad"]) == (1, 1)
        assert {
            key: summary["by_condition_match"]["none"][key]
            for key in ("bad_cases_found", "bad_cases_missed", "unnecessary_alerts")
        } == {"bad_cases_found": 1, "bad_cases_missed": 0, "unnecessary_alerts": 0}


class TestLabelWindow(SimpleTestCase):
    @parameterized.expand(
        [
            param("new_errors_stop", new_errors=(30, 0), reason=None, expected=Label.BAD),
            param("new_errors_go_on", new_errors=(30, 30), reason=None, expected=Label.NOT_BAD),
            param("too_few_errors", new_errors=(1, 0), reason=None, expected=Label.DOUBTFUL),
            param("planned_rollback", new_errors=(30, 0), reason=RollbackReason.PLANNED, expected=Label.NOT_BAD),
            param("answered_errors", new_errors=(0, 0), reason=RollbackReason.ERRORS, expected=Label.BAD),
        ]
    )
    def test_label(self, _: str, new_errors: tuple[int, int], reason: RollbackReason | None, expected: Label) -> None:
        window = _window()
        assert window.rollback is not None
        window = dataclasses.replace(window, rollback=dataclasses.replace(window.rollback, reason=reason))

        labeled = label_window(window, _data(errors_from_hour=99, new_errors=new_errors), DEFAULT_PARAMETERS)

        assert labeled is not None and labeled[0] == expected

    def test_a_quick_rollback_compares_as_many_hours_on_both_sides(self) -> None:
        history = _history(
            (None, _flag(10), None),
            (timedelta(0), _flag(25), None),
            (timedelta(hours=1, minutes=30), _flag(25, active=False), None),
        )
        [window] = find_candidates([history], EDITED_AT, EDITED_AT + timedelta(days=1), DEFAULT_PARAMETERS).windows
        errors = tuple(
            ErrorBucket(
                start=EDITED_AT + hour * HOUR,
                in_bucket=ErrorCounts(with_errors=0, with_new_errors=20 if hour == 0 else 4, by_variant={}),
                since_edit=ErrorCounts(with_errors=0, with_new_errors=0, by_variant={}),
            )
            for hour in (0, *range(2, 10))
        )
        data = dataclasses.replace(
            _data(errors_from_hour=99), windows={"entry-1": WindowData(exposure=(), errors=errors, last_values=None)}
        )

        labeled = label_window(window, data, DEFAULT_PARAMETERS)

        assert labeled is not None
        assert (labeled[0], labeled[1].hours, labeled[1].new_errors_before, labeled[1].new_errors_after) == (
            Label.BAD,
            1,
            20,
            4,
        )

    def test_no_label_before_the_data_covers_the_span_after_the_rollback(self) -> None:
        assert (
            label_window(_window(), _data(errors_from_hour=99, until=timedelta(hours=10)), DEFAULT_PARAMETERS) is None
        )


class TestDataFile(SimpleTestCase):
    def test_the_data_reads_back_as_it_was_written(self) -> None:
        data = dataclasses.replace(
            _data(errors_from_hour=3),
            actors=tuple(
                ActorHours(
                    group_type_index=kind,
                    hours={EDITED_AT: HourErrors(active=10, with_errors=1)},
                    baseline={EDITED_AT: BaselineHour(start=EDITED_AT, weeks=(HourErrors(active=9, with_errors=0),))},
                    days=frozenset({EDITED_AT.replace(hour=0)}),
                )
                for kind in (None, 0)
            ),
        )

        assert load_data(dump_data(data)) == data


class TestWatchedEdit(SimpleTestCase):
    @parameterized.expand(
        [
            param(
                "rollout_of_one_condition",
                before=_flag(100, 10),
                after=_flag(100, 50),
                enables=False,
                positions=[1],
                earlier=[0],
            ),
            param("enabling", before=_flag(100, 10, active=False), after=_flag(100, 10), enables=True, positions=[]),
            param(
                "new_split",
                before=_flag(100, 10, variants=[{"key": "a", "rollout_percentage": 100}]),
                after=_flag(
                    100,
                    50,
                    variants=[{"key": "a", "rollout_percentage": 50}, {"key": "b", "rollout_percentage": 50}],
                ),
                enables=False,
                positions=[],
            ),
        ]
    )
    def test_watches_the_conditions_whose_people_the_edit_moves(
        self,
        _: str,
        before: FlagExposureConfig,
        after: FlagExposureConfig,
        enables: bool,
        positions: list[int],
        earlier: list[int] | None = None,
    ) -> None:
        edit = watched_edit(
            edit_id="edit",
            edited_at=EDITED_AT,
            before=before,
            after=after,
            change=classify_exposure_change(before=before, after=after),
        )

        groups = (after.filters or {})["groups"]
        assert edit.enables == enables
        assert edit.conditions == tuple(
            WatchedCondition(
                position=position,
                properties=tuple(groups[position]["properties"]),
                earlier_at_full_rollout=tuple(tuple(groups[index]["properties"]) for index in earlier or ()),
            )
            for position in positions
        )


class TestFlagHistories(BaseTest):
    def _log(self, flag: FeatureFlag, activity: str, at: datetime, detail: dict[str, Any]) -> None:
        entry = ActivityLog.objects.create(
            team_id=self.team.pk, scope="FeatureFlag", item_id=str(flag.pk), activity=activity, detail=detail
        )
        ActivityLog.objects.filter(pk=entry.pk).update(created_at=at)

    def test_undoes_the_entries_from_the_newest_back_to_the_creation(self) -> None:
        filters_at: dict[int, dict[str, Any]] = {
            rollout: {"groups": [{"properties": [], "rollout_percentage": rollout}]} for rollout in (10, 25)
        }
        flag = FeatureFlag.objects.create(
            team=self.team, key="new-checkout:deleted:1", filters=filters_at[25], active=True, deleted=True
        )
        # Creating the row logs an entry of its own, now.
        ActivityLog.objects.filter(team_id=self.team.pk, item_id=str(flag.pk)).delete()
        self._log(flag, "created", EDITED_AT, {"changes": None, "name": "new-checkout"})
        self._log(
            flag,
            "updated",
            EDITED_AT + HOUR,
            {"changes": [{"field": "filters", "before": filters_at[10], "after": filters_at[25]}]},
        )
        # A bulk delete renames the flag and logs no change.
        self._log(flag, "deleted", EDITED_AT + 2 * HOUR, {"changes": [], "name": "new-checkout"})

        [history] = flag_histories(self.team.pk, EDITED_AT - HOUR)

        assert [
            (version.since, (version.config.key, version.config.deleted, version.config.filters))
            if version.config
            else (version.since, None)
            for version in history.versions
        ] == [
            (None, None),
            (EDITED_AT, ("new-checkout", False, filters_at[10])),
            (EDITED_AT + HOUR, ("new-checkout", False, filters_at[25])),
            (EDITED_AT + 2 * HOUR, ("new-checkout:deleted:1", True, filters_at[25])),
        ]


class TestFetchData(ClickhouseTestMixin, BaseTest):
    def test_reads_the_hours_of_each_window_from_its_edit_on(self) -> None:
        create_person(team=self.team, distinct_ids=["person"])
        for event, minutes, properties in (
            ("$pageview", -30, {"$feature/new-checkout": False}),
            ("$pageview", 30, {"$feature/new-checkout": True}),
            ("$exception", 90, {"$feature/new-checkout": True}),
        ):
            _create_event(
                team=self.team,
                event=event,
                distinct_id="person",
                timestamp=EDITED_AT + timedelta(minutes=minutes),
                properties=properties,
            )
        flush_persons_and_events()

        data = fetch_data(self.team, [_window()], DEFAULT_PARAMETERS, now=EDITED_AT + timedelta(days=3))

        window = data.windows["entry-1"]
        assert [(bucket.start, bucket.since_edit.exposed) for bucket in window.exposure] == [
            (EDITED_AT, 1),
            (EDITED_AT + HOUR, 1),
        ]
        assert [(bucket.start, bucket.in_bucket.with_errors) for bucket in window.errors] == [(EDITED_AT + HOUR, 1)]
        assert data.actor(None).hours[EDITED_AT + HOUR].with_errors == 1
        assert data.until == EDITED_AT + timedelta(days=3)

    def test_a_rerun_reads_what_the_earlier_data_lacks(self) -> None:
        create_person(team=self.team, distinct_ids=["person"])
        _create_event(
            team=self.team,
            event="$exception",
            distinct_id="person",
            timestamp=EDITED_AT + timedelta(minutes=90),
            properties={"$feature/new-checkout": True},
        )
        flush_persons_and_events()
        now = EDITED_AT + timedelta(days=3)
        data = fetch_data(self.team, [_window()], DEFAULT_PARAMETERS, now=now)
        # The days that groups hold say nothing of the persons, and a last value query that failed runs again.
        earlier = dataclasses.replace(
            data,
            windows={"entry-1": dataclasses.replace(data.windows["entry-1"], last_values=None)},
            actors=(ActorHours(group_type_index=0, hours={}, baseline={}, days=data.actor(None).days),),
        )

        again = fetch_data(self.team, [_window()], DEFAULT_PARAMETERS, now=now, earlier=earlier)

        assert again.windows["entry-1"].last_values is not None
        assert again.actor(None).hours[EDITED_AT + HOUR].with_errors == 1

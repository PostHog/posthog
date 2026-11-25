import math
import statistics
import dataclasses
from collections.abc import Iterable, Mapping, Sequence
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from django.test import SimpleTestCase

from parameterized import parameterized

from products.feature_flags.backend.flag_windows.baseline import HOUR, BaselineHour, HourErrors
from products.feature_flags.backend.flag_windows.errors import ConditionErrors, ErrorCounts
from products.feature_flags.backend.flag_windows.exposure import ConditionExposure, ExposureBucket, ExposureCounts
from products.feature_flags.backend.flag_windows.last_values import LastValueBucket, LastValueCounts
from products.feature_flags.backend.flag_windows.query import ConditionMatch, WatchedCondition, WatchedEdit
from products.feature_flags.backend.flag_windows.score import ScoreParameters, WindowScore, score_window

EDITED_AT = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
PEOPLE = 1000
BASELINE_RATES = (0.010, 0.012, 0.009, 0.011)
BASELINE_RATE = statistics.fmean(BASELINE_RATES)
RISE_RATE = 0.08
SMALL_HOUR = HourErrors(active=1, with_errors=0)
HOUR_TO_COME = HourErrors(active=0, with_errors=0)

EDIT = WatchedEdit(
    id="edit",
    flag_key="new-checkout",
    edited_at=EDITED_AT,
    group_type_index=None,
    variants=(),
    enables=True,
)
EDIT_WITH_CONDITIONS = dataclasses.replace(
    EDIT,
    conditions=(
        WatchedCondition(position=1, properties=({"key": "email", "value": "@example.com", "operator": "icontains"},)),
    ),
)

PARAMETERS = ScoreParameters(
    alpha=0.05,
    weight_level_2=0.9,
    weight_level_4=0.7,
    weight_level_5=0.6,
    rise_z=3.0,
    full_strength_z=6.0,
    min_share_step=0.05,
    decay=timedelta(hours=6),
    threshold=0.5,
    min_exposed=100,
    min_with_errors=10,
    min_active=50,
)


def _exposure(
    shares: Sequence[float],
    exposed: int = PEOPLE,
    in_condition: Mapping[ConditionMatch, ConditionExposure] | None = None,
) -> list[ExposureBucket]:
    since_edit = ExposureCounts(
        with_flag=2 * PEOPLE,
        exposed=exposed,
        unexposed=2 * PEOPLE - exposed,
        by_variant={},
        in_condition=in_condition or {},
    )
    return [
        ExposureBucket(
            start=EDITED_AT + index * HOUR,
            in_bucket=ExposureCounts(
                with_flag=PEOPLE, exposed=round(share * PEOPLE), unexposed=PEOPLE - round(share * PEOPLE), by_variant={}
            ),
            since_edit=since_edit,
        )
        for index, share in enumerate(shares)
    ]


def _errors(
    exposed_with_errors: int,
    unexposed_with_errors: int,
    in_condition: Mapping[ConditionMatch, ConditionErrors] | None = None,
) -> ErrorCounts:
    return ErrorCounts(
        with_errors=exposed_with_errors + unexposed_with_errors,
        with_new_errors=0,
        exposed_with_errors=exposed_with_errors,
        unexposed_with_errors=unexposed_with_errors,
        by_variant={},
        in_condition=in_condition or {},
    )


def _last_values(
    shares: Sequence[float],
    exposed_with_errors: int,
    unexposed_with_errors: int,
    exposed: int = PEOPLE,
) -> list[LastValueBucket]:
    """The buckets of `_exposure`, with the errors of people whose events may not carry the flag."""
    errors = {"exposed_with_errors": exposed_with_errors, "unexposed_with_errors": unexposed_with_errors}
    return [
        LastValueBucket(
            start=bucket.start,
            in_bucket=_last_value_counts(bucket.in_bucket, **errors),
            since_edit=_last_value_counts(bucket.since_edit, **errors),
        )
        for bucket in _exposure(shares, exposed=exposed)
    ]


def _last_value_counts(
    counts: ExposureCounts, *, exposed_with_errors: int, unexposed_with_errors: int
) -> LastValueCounts:
    return LastValueCounts(
        with_flag=counts.with_flag,
        exposed=counts.exposed,
        unexposed=counts.unexposed,
        exposed_with_errors=exposed_with_errors,
        unexposed_with_errors=unexposed_with_errors,
    )


def _hours(rates: Sequence[float]) -> dict[datetime, HourErrors]:
    return {
        EDITED_AT + index * HOUR: HourErrors(active=PEOPLE, with_errors=round(rate * PEOPLE))
        for index, rate in enumerate(rates)
    }


def _baseline(starts: Iterable[datetime], rates: Sequence[float] = BASELINE_RATES) -> list[BaselineHour]:
    weeks = tuple(HourErrors(active=PEOPLE, with_errors=round(rate * PEOPLE)) for rate in rates)
    return [BaselineHour(start=start, weeks=weeks) for start in starts]


def _rates(hours: int, rises: Mapping[int, float]) -> list[float]:
    return [rises.get(index, BASELINE_RATE) for index in range(hours)]


def _score(
    exposure: Sequence[ExposureBucket],
    errors: ErrorCounts,
    rates: Sequence[float],
    parameters: ScoreParameters = PARAMETERS,
    edit: WatchedEdit = EDIT,
    condition_match: ConditionMatch | None = None,
    replaced_hours: Mapping[int, HourErrors] | None = None,
    last_values: Sequence[LastValueBucket] | None = None,
) -> WindowScore:
    hours = _hours(rates)
    for index, counts in (replaced_hours or {}).items():
        hours[EDITED_AT + index * HOUR] = counts
    return score_window(
        edit,
        exposure,
        errors,
        hours,
        _baseline(hours),
        parameters,
        condition_match=condition_match,
        last_values=last_values,
    )


class TestScoreWindow(SimpleTestCase):
    @parameterized.expand(
        [
            ("enough_volume", PARAMETERS, _errors(100, 20), True),
            (
                "below_the_minimum_volume",
                dataclasses.replace(PARAMETERS, min_exposed=5 * PEOPLE),
                _errors(100, 20),
                False,
            ),
            ("exposed_group_better", PARAMETERS, _errors(20, 100), False),
            ("more_errors_than_unexposed_people", PARAMETERS, _errors(20, 1500), False),
        ]
    )
    def test_a_worse_exposed_group_is_suspicious_however_old_the_window(
        self, _name: str, parameters: ScoreParameters, errors: ErrorCounts, suspicious: bool
    ) -> None:
        result = _score(_exposure([0.5]), errors, [BASELINE_RATE] * 48, parameters)

        assert result.level_1 is not None and result.level_1.is_significant
        assert result.proximity < 0.01
        assert result.suspicious is suspicious

    @parameterized.expand(
        [
            ("with_the_exposure_rise", {0: RISE_RATE}, PARAMETERS, 1.0, True),
            ("two_days_later", {48: RISE_RATE}, PARAMETERS, 1.0, False),
            ("more_errors_than_active_people", {0: 1.001}, PARAMETERS, 1.0, True),
            ("a_rise_below_rise_z", {0: 0.02}, PARAMETERS, 0.343, False),
            (
                "a_weak_rise_with_the_exposure_rise_and_a_strong_one_later",
                {0: 0.027, 48: RISE_RATE},
                PARAMETERS,
                0.520,
                False,
            ),
            (
                "a_weak_rise_with_the_exposure_rise_and_a_strong_one_three_hours_later",
                {0: 0.027, 3: RISE_RATE},
                PARAMETERS,
                1.0,
                False,
            ),
            ("a_rise_that_grows_after_its_first_hour", {0: 0.03, 1: 0.05}, PARAMETERS, 0.939, True),
            (
                "with_the_exposure_rise_below_the_minimum_volume",
                {0: RISE_RATE},
                dataclasses.replace(PARAMETERS, min_exposed=5 * PEOPLE),
                1.0,
                False,
            ),
        ]
    )
    def test_an_error_rise_over_the_baseline_counts_by_its_distance_from_the_exposure_rise(
        self, _name: str, rises: Mapping[int, float], parameters: ScoreParameters, level_5: float, suspicious: bool
    ) -> None:
        result = _score(_exposure([0.5, 0.5]), _errors(45, 40), _rates(49, rises), parameters)

        assert result.level_1 is not None and not result.level_1.is_significant
        assert result.level_5 == pytest.approx(level_5, abs=1e-3)
        assert result.suspicious is suspicious

    @parameterized.expand(
        [
            ("traffic_arrives_late", True, [0.0, 0.0, 0.0, 0.5, 0.5, 0.5], [3], 1.0),
            ("a_step_after_an_edit_that_doesnt_enable", False, [0.5, 0.5, 0.5, 0.7, 0.7, 0.7], [3], 1.0),
            ("small_moves_after_an_edit_that_doesnt_enable", False, [0.5, 0.49, 0.5, 0.52], [0], 1.0),
            ("no_exposure_rise_after_an_edit_mid_hour", False, [0.5, 0.5], [0], 1.0, EDITED_AT + timedelta(minutes=30)),
            ("errors_rise_an_hour_before_the_exposure_rise", True, [0.0, 0.0, 0.0, 0.5, 0.5, 0.5], [2], 0.0),
            ("errors_rise_at_a_small_step_before_a_larger_one", True, [0.1, 0.1, 0.1, 0.7, 0.7, 0.7], [0], 1.0),
            ("errors_rise_at_a_small_step_after_a_larger_one", True, [0.0, 0.6, 0.6, 0.7, 0.7, 0.7], [3], 1.0),
            ("errors_rise_in_the_hour_of_an_edit_that_doesnt_enable", False, [0.5, 0.5, 0.5, 0.7], [0], 1.0),
            ("errors_rise_before_the_exposure_rise_and_stay_up", True, [0.0, 0.0, 0.0, 1.0], [2, 3], 0.0),
            ("errors_rise_before_a_slow_exposure_climb", True, [0.0, 0.0, 0.0, 0.04, 0.08, 0.12], [1], 0.0),
            ("errors_rise_when_the_share_recovers_from_a_dip", True, [0.5, 0.5, 0.5, 0.4, 0.5], [4], math.exp(-4 / 6)),
            ("errors_rise_before_the_exposure_rise_and_again_at_it", True, [0.0, 0.0, 0.0, 0.5], [0, 3], 1.0),
            (
                "errors_stay_up_across_a_small_hour_at_the_exposure_rise",
                True,
                [0.0, 0.0, 0.0, 0.5, 0.5],
                [2, 4],
                0.0,
                EDITED_AT,
                {3: SMALL_HOUR},
            ),
            (
                "first_bucket_hours_after_an_edit_that_doesnt_enable",
                False,
                [0.5, 0.5],
                [0],
                math.exp(-3 / 6),
                EDITED_AT - 3 * HOUR,
            ),
            ("errors_rise_while_the_share_stays_below_a_step", True, [0.02, 0.03], [0], 1.0),
        ]
    )
    def test_the_proximity_counts_from_the_latest_exposure_step_before_the_error_rise(
        self,
        _name: str,
        enables: bool,
        shares: list[float],
        rise_hours: list[int],
        proximity: float,
        edited_at: datetime = EDITED_AT,
        replaced_hours: Mapping[int, HourErrors] | None = None,
    ) -> None:
        edit = dataclasses.replace(EDIT, enables=enables, edited_at=edited_at)

        result = _score(
            _exposure(shares),
            _errors(40, 40),
            _rates(len(shares), dict.fromkeys(rise_hours, RISE_RATE)),
            edit=edit,
            replaced_hours=replaced_hours,
        )

        assert result.score == pytest.approx(PARAMETERS.weight_level_5 * proximity)
        assert result.suspicious is (proximity == 1.0)

    @parameterized.expand(
        [
            ("before_the_edit", EDITED_AT - HOUR, HourErrors(active=PEOPLE, with_errors=80), BASELINE_RATES),
            ("without_a_baseline", EDITED_AT + HOUR, HourErrors(active=PEOPLE, with_errors=80), None),
            ("with_one_earlier_week", EDITED_AT + HOUR, HourErrors(active=PEOPLE, with_errors=80), BASELINE_RATES[:1]),
            ("below_the_minimum_activity", EDITED_AT + HOUR, HourErrors(active=1, with_errors=1), BASELINE_RATES),
            ("no_errors_in_the_hour_or_earlier_weeks", EDITED_AT, HourErrors(active=PEOPLE, with_errors=0), (0.0,) * 4),
        ]
    )
    def test_an_hour_that_cant_show_an_error_rise_adds_no_strength(
        self, _name: str, start: datetime, counts: HourErrors, baseline_rates: Sequence[float] | None
    ) -> None:
        hours = {**_hours([BASELINE_RATE]), start: counts}
        baseline = _baseline([EDITED_AT] if baseline_rates is None else hours, baseline_rates or BASELINE_RATES)

        result = score_window(EDIT, _exposure([0.5]), _errors(40, 40), hours, baseline, PARAMETERS, last_values=None)

        assert result.level_5 == 0.0
        assert not result.suspicious

    def test_an_earlier_week_below_the_minimum_activity_is_left_out_of_the_baseline(self) -> None:
        hours = _hours([RISE_RATE])
        weeks = (*_baseline(hours)[0].weeks[:2], HourErrors(active=2, with_errors=1))

        result = score_window(
            EDIT,
            _exposure([0.5]),
            _errors(40, 40),
            hours,
            [BaselineHour(start=EDITED_AT, weeks=weeks)],
            PARAMETERS,
            last_values=None,
        )

        assert result.level_5 == 1.0

    def test_a_window_without_exposure_or_errors_yet_is_not_suspicious(self) -> None:
        hours = _hours([BASELINE_RATE])

        result = score_window(EDIT, [], None, hours, _baseline(hours), PARAMETERS, last_values=None)

        assert result.level_1 is None and result.level_2 is None
        assert not result.suspicious

    @parameterized.expand(
        [
            ("everyone", EDIT, None, False),
            ("everyone_with_watched_conditions", EDIT_WITH_CONDITIONS, None, None),
            ("in_the_watched_conditions", EDIT_WITH_CONDITIONS, ConditionMatch.REASON, True),
            ("not_found_without_watched_conditions", EDIT, ConditionMatch.PROPERTIES, False),
            ("not_found_with_watched_conditions", EDIT_WITH_CONDITIONS, ConditionMatch.PROPERTIES, None),
            (
                "found_by_the_exposure_query_only",
                EDIT_WITH_CONDITIONS,
                ConditionMatch.PROPERTIES,
                None,
                (ConditionMatch.REASON, ConditionMatch.PROPERTIES),
            ),
        ]
    )
    def test_level_1_compares_the_people_that_the_condition_match_selects(
        self,
        _name: str,
        edit: WatchedEdit,
        condition_match: ConditionMatch | None,
        significant: bool | None,
        exposure_matches: Sequence[ConditionMatch] = (ConditionMatch.REASON,),
    ) -> None:
        in_condition = ConditionExposure(with_flag=PEOPLE, exposed=PEOPLE // 2, unexposed=PEOPLE // 2)
        exposure = _exposure([0.5], in_condition=dict.fromkeys(exposure_matches, in_condition))
        errors = _errors(
            40,
            40,
            in_condition={ConditionMatch.REASON: ConditionErrors(exposed_with_errors=40, unexposed_with_errors=5)},
        )

        result = _score(exposure, errors, [BASELINE_RATE], edit=edit, condition_match=condition_match)

        assert (None if result.level_1 is None else result.level_1.is_significant) is significant

    @parameterized.expand(
        [
            ("five_exposed_and_nobody_with_errors", 5, False),
            ("four_exposed", 4, None),
        ]
    )
    def test_level_1_runs_on_groups_of_at_least_five_people_even_without_errors(
        self, _name: str, exposed: int, significant: bool | None
    ) -> None:
        result = _score(_exposure([0.5], exposed=exposed), _errors(0, 0), [BASELINE_RATE])

        assert (None if result.level_1 is None else result.level_1.is_significant) is significant

    def test_the_minimum_volume_applies_to_the_people_that_level_1_compares(self) -> None:
        exposure = _exposure(
            [0.5], in_condition={ConditionMatch.REASON: ConditionExposure(with_flag=520, exposed=20, unexposed=500)}
        )
        errors = _errors(
            40,
            40,
            in_condition={ConditionMatch.REASON: ConditionErrors(exposed_with_errors=20, unexposed_with_errors=5)},
        )

        result = _score(exposure, errors, [BASELINE_RATE], condition_match=ConditionMatch.REASON)

        assert result.level_1 is not None and result.level_1.is_significant
        assert not result.suspicious

    @parameterized.expand(
        [
            ("proportional_steps", [0.1, 0.2, 0.3], [0.02, 0.03, 0.04], 1.0),
            ("a_larger_second_step", [0.1, 0.2, 0.3], [0.02, 0.03, 0.06], 1 / 3),
            ("errors_fall_on_a_step", [0.1, 0.2, 0.3], [0.02, 0.03, 0.025], 0.0),
            ("one_step", [0.1, 0.2], [0.02, 0.03], None),
            ("steps_below_the_minimum", [0.1, 0.12, 0.14], [0.02, 0.03, 0.04], None),
            ("errors_within_the_baseline_noise", [0.1, 0.2, 0.3], [0.010, 0.011, 0.012], None),
            (
                "too_few_active_people_between_steps",
                [0.1, 0.2, 0.3, 0.4],
                [0.02, 0.03, 0.04, 0.05],
                None,
                {2: SMALL_HOUR},
            ),
            ("errors_flat_across_steps", [0.2, 0.4, 0.6], [0.08, 0.08, 0.08], 0.0),
            ("an_error_rise_only_before_the_steps", [0.0, 0.0, 0.0, 0.3, 0.6], [0.08, 0.01, 0.01, 0.011, 0.012], None),
        ]
    )
    def test_level_4_compares_the_error_rise_of_each_exposure_step(
        self,
        _name: str,
        shares: list[float],
        rates: list[float],
        expected: float | None,
        replaced_hours: Mapping[int, HourErrors] | None = None,
    ) -> None:
        by_event = _score(_exposure(shares), _errors(40, 40), rates, replaced_hours=replaced_hours)
        by_last_value = _score(
            [], _errors(40, 40), rates, replaced_hours=replaced_hours, last_values=_last_values(shares, 0, 0)
        )

        assert by_event.level_4 == pytest.approx(expected)
        assert by_last_value.level_4 == pytest.approx(expected)

    @parameterized.expand(
        [
            (
                "level_2_with_a_later_spike",
                [0.5] * 4,
                [0.027, BASELINE_RATE, BASELINE_RATE, RISE_RATE],
                (50, 10),
                0.72,
            ),
            (
                "level_4_with_a_later_spike",
                [0.2, 0.5, 0.8, 0.8, 0.8, 0.8],
                [0.015, 0.021, 0.027, BASELINE_RATE, BASELINE_RATE, RISE_RATE],
                None,
                0.7,
            ),
            ("level_4_with_errors_already_up", [0.0, 0.0, 0.3, 0.6, 0.6], [0.08, 0.08, 0.11, 0.14, 0.14], None, 0.7),
            (
                "level_2_with_hours_of_the_day_to_come",
                [0.5],
                [BASELINE_RATE],
                (50, 10),
                0.72,
                dict.fromkeys(range(1, 12), HOUR_TO_COME),
            ),
            (
                "level_2_with_a_rise_before_the_exposure_rise",
                [0.0, 0.0, 0.5, 0.5],
                [RISE_RATE, BASELINE_RATE, BASELINE_RATE, BASELINE_RATE],
                (50, 10),
                0.72 * math.exp(-1 / 6),
            ),
            (
                "errors_already_up_move_by_noise_at_a_step",
                [0.0, 0.0, 0.0, 1.0],
                [BASELINE_RATE, BASELINE_RATE, 0.08, 0.09],
                None,
                0.0,
            ),
            (
                "errors_already_up_dip_and_come_back_at_a_step",
                [0.0, 0.0, 0.0, 0.0, 1.0],
                [BASELINE_RATE, BASELINE_RATE, 0.12, 0.08, 0.12],
                None,
                0.0,
            ),
        ]
    )
    def test_the_score_weighs_levels_by_the_error_rise_at_an_exposure_step(
        self,
        _name: str,
        shares: list[float],
        rates: list[float],
        errors_by_last_value: tuple[int, int] | None,
        score: float,
        replaced_hours: Mapping[int, HourErrors] | None = None,
    ) -> None:
        last_values = _last_values(shares, *errors_by_last_value) if errors_by_last_value else None

        result = _score(
            [] if last_values else _exposure(shares),
            _errors(40, 40),
            rates,
            replaced_hours=replaced_hours,
            last_values=last_values,
        )

        assert result.score == pytest.approx(score)

    @parameterized.expand(
        [
            ("without_the_counts_by_last_value", None, PEOPLE, None),
            ("exposed_people_worse", (50, 10), PEOPLE, 0.8),
            ("exposed_people_better", (10, 50), PEOPLE, 0.0),
            (
                "more_errors_than_exposed_people",
                (1500, 10),
                PEOPLE,
                0.99,
            ),
            ("no_exposed_errors", (0, 50), PEOPLE, 0.0),
            (
                "too_few_errors_with_a_value",
                (1, 0),
                PEOPLE,
                None,
            ),
            ("nobody_exposed", (50, 10), 0, None),
            (
                "an_edit_with_watched_conditions",
                (50, 10),
                PEOPLE,
                None,
                EDIT_WITH_CONDITIONS,
            ),
        ]
    )
    def test_level_2_is_the_share_of_exposed_errors_that_the_flag_explains(
        self,
        _name: str,
        errors_by_last_value: tuple[int, int] | None,
        exposed: int,
        expected: float | None,
        edit: WatchedEdit = EDIT,
    ) -> None:
        last_values = _last_values([0.5], *errors_by_last_value, exposed=exposed) if errors_by_last_value else None

        # No event carries the flag, as for a flag that only a backend evaluates.
        result = _score([], _errors(40, 0), [BASELINE_RATE], edit=edit, last_values=last_values)

        assert result.level_2 == pytest.approx(expected)
        assert result.score == pytest.approx(PARAMETERS.weight_level_2 * (expected or 0.0))
        assert result.suspicious == (result.score >= PARAMETERS.threshold)

    @parameterized.expand(
        [
            # Level 5 alone makes the window suspicious when the curve has enough exposed people.
            ("last_values_win_over_the_events", 0, PEOPLE, True),
            ("nobody_with_a_last_value_wins_over_the_events", PEOPLE, None, False),
        ]
    )
    def test_the_volume_comes_from_the_last_values(
        self, _name: str, exposed_on_events: int, exposed_by_last_value: int | None, suspicious: bool
    ) -> None:
        last_values = (
            _last_values([0.0, 1.0], 0, 0, exposed=exposed_by_last_value) if exposed_by_last_value is not None else []
        )

        result = _score(
            _exposure([0.0, 1.0], exposed=exposed_on_events),
            _errors(20, 20),
            [BASELINE_RATE, RISE_RATE],
            last_values=last_values,
        )

        assert result.suspicious == suspicious

    @parameterized.expand(
        [
            (
                "hour_on_a_utc_hour_in_a_half_hour_time_zone",
                EDITED_AT.astimezone(ZoneInfo("Asia/Kolkata")),
                "hours",
                False,
            ),
            ("hour_on_a_utc_half_hour", EDITED_AT + timedelta(minutes=30), "hours", True),
            ("exposure_bucket_on_a_utc_half_hour", EDITED_AT + timedelta(minutes=30), "exposure", True),
            ("last_value_bucket_on_a_utc_half_hour", EDITED_AT + timedelta(minutes=30), "last_values", True),
        ]
    )
    def test_buckets_must_start_on_a_utc_hour(self, _name: str, start: datetime, moved: str, raises: bool) -> None:
        starts = {"exposure": EDITED_AT, "hours": EDITED_AT, "last_values": EDITED_AT, moved: start}
        [exposure] = _exposure([0.5])
        [last_values] = _last_values([0.5], 0, 0)

        with self.assertRaises(ValueError) if raises else nullcontext():
            score_window(
                EDIT,
                [dataclasses.replace(exposure, start=starts["exposure"])],
                _errors(40, 40),
                {starts["hours"]: HourErrors(active=PEOPLE, with_errors=10)},
                _baseline([EDITED_AT]),
                PARAMETERS,
                last_values=[dataclasses.replace(last_values, start=starts["last_values"])],
            )

    @parameterized.expand(
        [
            ("no_active_people", {"min_active": 0}),
            ("no_exposure_share_step", {"min_share_step": 0.0}),
            ("no_full_strength_z", {"full_strength_z": 0.0}),
            ("no_proximity_decay", {"decay": timedelta(0)}),
        ]
    )
    def test_parameters_that_would_divide_by_zero_raise(self, _name: str, changes: dict[str, Any]) -> None:
        with self.assertRaises(ValueError):
            dataclasses.replace(PARAMETERS, **changes)

import dataclasses
from collections.abc import Mapping, Sequence
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from django.test import SimpleTestCase

from parameterized import parameterized

from products.feature_flags.backend.flag_windows.baseline import BaselineHour, HourErrors
from products.feature_flags.backend.flag_windows.errors import (
    ConditionErrors,
    ErrorBucket,
    ErrorCounts,
    ErrorsByLastValue,
)
from products.feature_flags.backend.flag_windows.exposure import ConditionExposure, ExposureBucket, ExposureCounts
from products.feature_flags.backend.flag_windows.query import ConditionMatch, WatchedEdit
from products.feature_flags.backend.flag_windows.score import ScoreParameters, WindowScore, score_window

EDITED_AT = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)
PEOPLE = 1000
BASELINE_RATES = (0.010, 0.012, 0.009, 0.011)
BASELINE_RATE = 0.0105

EDIT = WatchedEdit(
    id="edit",
    flag_key="new-checkout",
    edited_at=EDITED_AT,
    group_type_index=None,
    variants=(),
    enables=True,
)

PARAMETERS = ScoreParameters(
    condition_match=None,
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
)


def _exposure(
    shares: Sequence[float],
    exposed: int = PEOPLE,
    in_condition: Mapping[ConditionMatch, ConditionExposure] | None = None,
) -> list[ExposureBucket]:
    since_edit = ExposureCounts(with_flag=2 * PEOPLE, exposed=exposed, by_variant={}, in_condition=in_condition or {})
    return [
        ExposureBucket(
            start=EDITED_AT + index * HOUR,
            in_bucket=ExposureCounts(with_flag=PEOPLE, exposed=round(share * PEOPLE), by_variant={}),
            since_edit=since_edit,
        )
        for index, share in enumerate(shares)
    ]


def _errors(
    exposed_with_errors: int,
    unexposed_with_errors: int,
    by_last_value: ErrorsByLastValue | None = None,
    in_condition: Mapping[ConditionMatch, ConditionErrors] | None = None,
) -> list[ErrorBucket]:
    counts = ErrorCounts(
        with_errors=exposed_with_errors + unexposed_with_errors,
        with_new_errors=0,
        exposed_with_errors=exposed_with_errors,
        unexposed_with_errors=unexposed_with_errors,
        by_variant={},
        in_condition=in_condition or {},
        by_last_value=by_last_value,
    )
    return [ErrorBucket(start=EDITED_AT, in_bucket=counts, since_edit=counts)]


def _hours(rates: Sequence[float]) -> dict[datetime, HourErrors]:
    return {
        EDITED_AT + index * HOUR: HourErrors(active=PEOPLE, with_errors=round(rate * PEOPLE))
        for index, rate in enumerate(rates)
    }


def _baseline(hours: int) -> list[BaselineHour]:
    weeks = tuple(HourErrors(active=PEOPLE, with_errors=round(rate * PEOPLE)) for rate in BASELINE_RATES)
    return [BaselineHour(start=EDITED_AT + index * HOUR, weeks=weeks) for index in range(hours)]


def _score(
    exposure: Sequence[ExposureBucket],
    errors: Sequence[ErrorBucket],
    rates: Sequence[float],
    parameters: ScoreParameters = PARAMETERS,
) -> WindowScore:
    return score_window(EDIT, exposure, errors, _hours(rates), _baseline(len(rates)), parameters)


class TestScoreWindow(SimpleTestCase):
    @parameterized.expand(
        [
            ("enough_volume", PARAMETERS, True),
            ("below_the_minimum_volume", dataclasses.replace(PARAMETERS, min_exposed=5 * PEOPLE), False),
        ]
    )
    def test_a_worse_exposed_group_is_suspicious_however_old_the_window(
        self, _name: str, parameters: ScoreParameters, suspicious: bool
    ) -> None:
        result = _score(_exposure([0.5]), _errors(100, 20), [BASELINE_RATE] * 48, parameters)

        assert result.proximity < 0.01
        assert result.suspicious is suspicious

    @parameterized.expand(
        [
            ("with_the_exposure_rise", 0, True),
            ("two_days_later", 48, False),
        ]
    )
    def test_an_error_rise_over_the_baseline_counts_by_its_distance_from_the_exposure_rise(
        self, _name: str, rise_hour: int, suspicious: bool
    ) -> None:
        rates = [BASELINE_RATE] * 49
        rates[rise_hour] = 0.08

        result = _score(_exposure([0.5, 0.5]), _errors(40, 40), rates)

        assert result.level_1 is not None and not result.level_1.is_significant
        assert result.level_5 == 1.0
        assert result.suspicious is suspicious

    @parameterized.expand(
        [
            ("everyone", None, False),
            ("in_the_watched_conditions", ConditionMatch.REASON, True),
        ]
    )
    def test_level_1_compares_the_people_that_the_condition_match_selects(
        self, _name: str, condition_match: ConditionMatch | None, significant: bool
    ) -> None:
        exposure = _exposure(
            [0.5], in_condition={ConditionMatch.REASON: ConditionExposure(with_flag=PEOPLE, exposed=PEOPLE // 2)}
        )
        errors = _errors(
            40,
            40,
            in_condition={ConditionMatch.REASON: ConditionErrors(exposed_with_errors=40, unexposed_with_errors=5)},
        )

        result = _score(
            exposure, errors, [BASELINE_RATE], dataclasses.replace(PARAMETERS, condition_match=condition_match)
        )

        assert result.level_1 is not None
        assert result.level_1.is_significant is significant

    @parameterized.expand(
        [
            ("proportional_steps", [0.1, 0.2, 0.3], [0.02, 0.03, 0.04], 1.0),
            ("a_larger_second_step", [0.1, 0.2, 0.3], [0.02, 0.03, 0.06], 1 / 3),
            ("errors_fall_on_a_step", [0.1, 0.2, 0.3], [0.02, 0.03, 0.025], 0.0),
            ("one_step", [0.1, 0.2], [0.02, 0.03], None),
        ]
    )
    def test_level_4_compares_the_error_rise_of_each_exposure_step(
        self, _name: str, shares: list[float], rates: list[float], expected: float | None
    ) -> None:
        result = _score(_exposure(shares), _errors(40, 40), rates)

        assert result.level_4 == pytest.approx(expected)

    @parameterized.expand(
        [
            ("without_the_counts_by_last_value", None, None),
            ("exposed_people_worse", ErrorsByLastValue(exposed_with_errors=50, unexposed_with_errors=10), 0.8),
            ("exposed_people_better", ErrorsByLastValue(exposed_with_errors=10, unexposed_with_errors=50), 0.0),
        ]
    )
    def test_level_2_is_the_share_of_exposed_errors_that_the_flag_explains(
        self, _name: str, by_last_value: ErrorsByLastValue | None, expected: float | None
    ) -> None:
        result = _score(_exposure([0.5]), _errors(0, 0, by_last_value=by_last_value), [BASELINE_RATE])

        assert result.level_2 == pytest.approx(expected)

    def test_the_minimum_volume_applies_to_the_people_that_level_1_compares(self) -> None:
        exposure = _exposure([0.5], in_condition={ConditionMatch.REASON: ConditionExposure(with_flag=520, exposed=20)})
        errors = _errors(
            40,
            40,
            in_condition={ConditionMatch.REASON: ConditionErrors(exposed_with_errors=20, unexposed_with_errors=5)},
        )

        result = _score(
            exposure, errors, [BASELINE_RATE], dataclasses.replace(PARAMETERS, condition_match=ConditionMatch.REASON)
        )

        assert result.level_1 is not None and result.level_1.is_significant
        assert not result.suspicious

    @parameterized.expand(
        [
            ("on_a_utc_hour_in_a_half_hour_time_zone", EDITED_AT.astimezone(ZoneInfo("Asia/Kolkata")), False),
            ("on_a_utc_half_hour", EDITED_AT + timedelta(minutes=30), True),
        ]
    )
    def test_buckets_must_start_on_a_utc_hour(self, _name: str, start: datetime, raises: bool) -> None:
        hours = {start: HourErrors(active=PEOPLE, with_errors=10)}

        with self.assertRaises(ValueError) if raises else nullcontext():
            score_window(EDIT, _exposure([0.5]), _errors(40, 40), hours, _baseline(1), PARAMETERS)

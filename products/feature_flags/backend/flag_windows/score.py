"""The score of an observation window: whether the errors after a flag edit look like the edit caused them.

The evidence goes from strongest to weakest:

- Level 1 compares the error rate of the exposed people with the rest of the people with the flag. It uses the
  sequential test of experiments, so the window can run it again on every tick. When the exposed people are worse, the
  window is suspicious however much time has passed.
- Level 2 makes the same comparison by the value that each person had at the error.
- Level 4 checks that each step up in exposure brings errors up by the same amount.
- Level 5 checks only that errors rose over the baseline.

Levels 2, 4 and 5 are weaker, so the score multiplies them by the proximity in time between the exposure rise and the
error rise. Level 3 needs code search, so only the scout runs it.

Levels 4 and 5 compare each hour with the same hour of earlier weeks, so the exposure and error buckets must be one UTC
hour long.
"""

import math
import statistics
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from itertools import pairwise

from posthog.dataclasses import frozen

from products.experiments.backend.facade.contracts import Proportion, ProportionTestResult
from products.experiments.backend.facade.stats import sequential_proportion_test
from products.feature_flags.backend.flag_windows.baseline import HOUR, BaselineHour, HourErrors
from products.feature_flags.backend.flag_windows.errors import (
    ConditionErrors,
    ErrorBucket,
    ErrorCounts,
    ErrorsByLastValue,
)
from products.feature_flags.backend.flag_windows.exposure import ConditionExposure, ExposureBucket, ExposureCounts
from products.feature_flags.backend.flag_windows.query import ConditionMatch, WatchedEdit


@frozen
class ScoreParameters:
    # Level 1 compares only the people in the watched conditions that this source finds. None compares everyone with
    # the flag.
    condition_match: ConditionMatch | None
    alpha: float
    weight_level_2: float
    weight_level_4: float
    weight_level_5: float
    # An hour is an error rise when its excess over the baseline is at least this many standard deviations.
    rise_z: float
    # Level 5 has full strength at this many standard deviations.
    full_strength_z: float
    # The smallest rise in exposure share from one hour to the next that level 4 counts as a step.
    min_share_step: float
    # The proximity falls to 1/e when the error rise is this far from the exposure rise.
    decay: timedelta
    threshold: float
    # Below these counts, variation is noise. A group flag counts groups, so one large customer can't meet them alone.
    min_exposed: int
    min_with_errors: int


# Placeholders until the phase 0 backtest tunes them.
WEB_PARAMETERS = ScoreParameters(
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


@frozen
class WindowScore:
    # None when the test can't run: too few people in a group, or only one outcome in each.
    level_1: ProportionTestResult | None
    # In [0, 1]. None without the counts by last value, when nobody is exposed, or when everyone with the flag is.
    level_2: float | None
    # In [0, 1]. None with fewer than two exposure steps.
    level_4: float | None
    # In [0, 1].
    level_5: float
    # In [0, 1].
    proximity: float
    score: float
    suspicious: bool


@frozen
class _Groups:
    exposed: Proportion
    unexposed: Proportion


@frozen
class _Excess:
    # The error rate of the hour minus the mean rate of the same hour in earlier weeks.
    rate: float
    z: float


def score_window(
    edit: WatchedEdit,
    exposure: Sequence[ExposureBucket],
    errors: Sequence[ErrorBucket],
    hours: Mapping[datetime, HourErrors],
    baseline: Sequence[BaselineHour],
    parameters: ScoreParameters = WEB_PARAMETERS,
) -> WindowScore:
    """Scores the window from the one-hour buckets of the edit so far, oldest first. `hours` holds the errors of the
    window by the start of each UTC hour, and `baseline` the same hours of earlier weeks."""
    for start in [*(bucket.start for bucket in exposure), *(bucket.start for bucket in errors), *hours]:
        # Queries return times in the team's time zone, which can be a half hour off UTC.
        if start != _utc_hour(start):
            raise ValueError(f"The score needs one-hour buckets that start on the hour, got one at {start}")

    exposed = exposure[-1].since_edit if exposure else None
    with_errors = errors[-1].since_edit if errors else None
    shares = {bucket.start: _share(bucket.in_bucket) for bucket in exposure}
    excess = _excess_by_hour(edit, hours, baseline)

    level_1_groups = _level_1_groups(exposed, with_errors, parameters.condition_match)
    level_1 = (
        sequential_proportion_test(level_1_groups.exposed, level_1_groups.unexposed, alpha=parameters.alpha)
        if level_1_groups
        else None
    )
    level_2 = _level_2(exposed, with_errors)
    level_4 = _level_4(shares, excess, parameters.min_share_step)
    level_5 = min(1.0, max([0.0, *(hour.z for hour in excess.values())]) / parameters.full_strength_z)

    exposure_rise = _exposure_rise(edit, exposure)
    # Without an error rise, the latest hour stands in for it, so weak evidence counts less as the window gets older.
    latest = max([*shares, *(bucket.start for bucket in errors), *excess], default=edit.edited_at)
    error_rise = next((start for start, hour in excess.items() if hour.z >= parameters.rise_z), latest)
    proximity = math.exp(-abs(error_rise - exposure_rise) / parameters.decay)

    strengths = [parameters.weight_level_5 * level_5]
    if level_2 is not None:
        strengths.append(parameters.weight_level_2 * level_2)
    if level_4 is not None:
        strengths.append(parameters.weight_level_4 * level_4)
    score = max(strengths) * proximity

    enough = (
        exposed is not None
        and with_errors is not None
        and _enough(exposed.exposed, with_errors.with_errors, parameters)
    )
    # Level 1 can compare only the people in the watched conditions, so the minimum volume applies to them.
    confirmed = (
        level_1_groups is not None
        and _enough(
            level_1_groups.exposed.trials,
            level_1_groups.exposed.successes + level_1_groups.unexposed.successes,
            parameters,
        )
        and level_1 is not None
        and level_1.is_significant
        and level_1.difference > 0
    )
    return WindowScore(
        level_1=level_1,
        level_2=level_2,
        level_4=level_4,
        level_5=level_5,
        proximity=proximity,
        score=score,
        suspicious=confirmed or (enough and score >= parameters.threshold),
    )


def _utc_hour(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def _enough(exposed: int, with_errors: int, parameters: ScoreParameters) -> bool:
    return exposed >= parameters.min_exposed and with_errors >= parameters.min_with_errors


def _share(counts: ExposureCounts) -> float:
    return counts.exposed / counts.with_flag if counts.with_flag else 0.0


def _groups(
    with_flag: int, exposed: int, errors: ErrorCounts | ConditionErrors | ErrorsByLastValue | None
) -> _Groups | None:
    unexposed = with_flag - exposed
    if exposed <= 0 or unexposed <= 0:
        return None
    exposed_with_errors = errors.exposed_with_errors if errors else 0
    unexposed_with_errors = errors.unexposed_with_errors if errors else 0
    # A person whose value changed counts only as exposed, but their errors before the change count as unexposed. So
    # the unexposed group can show more people with errors than people, and its rate runs high, which hides a
    # difference rather than inventing one.
    return _Groups(
        exposed=Proportion(trials=exposed, successes=min(exposed_with_errors, exposed)),
        unexposed=Proportion(trials=unexposed, successes=min(unexposed_with_errors, unexposed)),
    )


def _level_1_groups(
    exposure: ExposureCounts | None, errors: ErrorCounts | None, match: ConditionMatch | None
) -> _Groups | None:
    if exposure is None:
        return None
    counts: ExposureCounts | ConditionExposure = exposure
    error_counts: ErrorCounts | ConditionErrors | None = errors
    if match is not None and match in exposure.in_condition:
        counts = exposure.in_condition[match]
        error_counts = errors.in_condition.get(match) if errors else None
    return _groups(counts.with_flag, counts.exposed, error_counts)


def _level_2(exposure: ExposureCounts | None, errors: ErrorCounts | None) -> float | None:
    if exposure is None or errors is None or errors.by_last_value is None:
        return None
    groups = _groups(exposure.with_flag, exposure.exposed, errors.by_last_value)
    if groups is None:
        return None
    exposed_rate = groups.exposed.successes / groups.exposed.trials
    unexposed_rate = groups.unexposed.successes / groups.unexposed.trials
    if not exposed_rate:
        return 0.0
    # The share of the errors of the exposed people that the flag explains: 0 when they are no worse than the rest,
    # 1 when only they have errors.
    return max(0.0, 1 - unexposed_rate / exposed_rate)


def _level_4(
    shares: Mapping[datetime, float], excess: Mapping[datetime, _Excess], min_share_step: float
) -> float | None:
    ratios = []
    for previous, current in pairwise(start for start in excess if start in shares):
        share_step = shares[current] - shares[previous]
        if current - previous == HOUR and share_step >= min_share_step:
            ratios.append((excess[current].rate - excess[previous].rate) / share_step)
    if len(ratios) < 2:
        return None
    if min(ratios) <= 0:
        return 0.0
    # When the flag causes the errors, each point of exposure share adds the same error rate, so the ratios are equal.
    return min(ratios) / max(ratios)


def _excess_by_hour(
    edit: WatchedEdit, hours: Mapping[datetime, HourErrors], baseline: Sequence[BaselineHour]
) -> dict[datetime, _Excess]:
    """The excess error rate of each hour from the edit on, oldest first. An hour without activity, or without activity
    in all earlier weeks, has no entry."""
    earlier = {hour.start: hour.weeks for hour in baseline}
    edit_hour = _utc_hour(edit.edited_at)
    excess: dict[datetime, _Excess] = {}
    for start, counts in sorted(hours.items()):
        rates = [week.with_errors / week.active for week in earlier.get(start, ()) if week.active]
        if start < edit_hour or not counts.active or not rates:
            continue
        rate = counts.with_errors / counts.active
        excess_rate = rate - statistics.fmean(rates)
        # The spread of the earlier weeks, and the sampling noise of the hour itself.
        spread = math.hypot(statistics.pstdev(rates), math.sqrt(rate * (1 - rate) / counts.active))
        z = excess_rate / spread if spread else (math.inf if excess_rate > 0 else 0.0)
        excess[start] = _Excess(rate=excess_rate, z=z)
    return excess


def _exposure_rise(edit: WatchedEdit, exposure: Sequence[ExposureBucket]) -> datetime:
    """The start of the bucket in which the exposure share rises the most. The edit time when no event carries the flag,
    or when the share never rises."""
    rise, largest_step = edit.edited_at, 0.0
    # Before an edit that enables the flag, nobody is exposed. Before other edits, the share is unknown, so the first
    # bucket has no step.
    previous = 0.0 if edit.enables else None
    for bucket in exposure:
        share = _share(bucket.in_bucket)
        if previous is not None and share - previous > largest_step:
            rise, largest_step = bucket.start, share - previous
        previous = share
    return rise

"""The score of an observation window: whether the errors after a flag edit look like the edit caused them.

The evidence goes from strongest to weakest:

- Level 1 compares the error rate of the exposed people with the rest of the people with the flag. It uses the
  sequential test of experiments, so the window can run it again on every tick. When the exposed people are worse, the
  window is suspicious however much time has passed.
- Level 2 makes the same comparison by the value that each person had at the error, for edits without watched
  conditions.
- Level 4 checks that each step up in exposure brings errors up by the same amount.
- Level 5 checks only that errors rose over the baseline.

Levels 2, 4 and 5 are weaker, so the score multiplies them by the proximity in time between the error rise and the
latest exposure step at or before it. Level 3 needs code search, so only the scout runs it.

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
from products.feature_flags.backend.flag_windows.errors import ConditionErrors, ErrorCounts, ErrorsByLastValue
from products.feature_flags.backend.flag_windows.exposure import ConditionExposure, ExposureBucket, ExposureCounts
from products.feature_flags.backend.flag_windows.query import ConditionMatch, WatchedEdit


@frozen
class ScoreParameters:
    """An hour is an error rise when its excess over the baseline is at least `rise_z` standard deviations, and level 5
    has full strength at `full_strength_z`. An exposure step is a rise in exposure share of at least `min_share_step`.
    Level 4 measures it from one hour to the next. The proximity measures it over the highest share so far, so a share
    that dips and comes back makes no step, and it also counts the hour of an edit that doesn't enable the flag as a
    step. The proximity falls to 1/e when the error rise is `decay` after the latest step at or before it. Variation
    is noise below `min_exposed` and `min_with_errors`, and in an hour or earlier week with fewer than `min_active`
    active people. A group flag counts groups, so one large customer can't meet these minimums alone."""

    alpha: float
    weight_level_2: float
    weight_level_4: float
    weight_level_5: float
    rise_z: float
    full_strength_z: float
    min_share_step: float
    decay: timedelta
    threshold: float
    min_exposed: int
    min_with_errors: int
    min_active: int

    def __post_init__(self) -> None:
        if self.min_active < 1:
            raise ValueError(f"The score needs at least 1 active person per hour, got {self.min_active}")
        if self.min_share_step <= 0:
            raise ValueError(f"The score needs a positive exposure share step, got {self.min_share_step}")


MIN_GROUP_SIZE = 5

# Placeholders until the phase 0 backtest tunes them.
WEB_PARAMETERS = ScoreParameters(
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


@frozen
class WindowScore:
    """Levels 2, 4 and 5 and the proximity are in [0, 1]. Level 1 is None when the test can't run: no exposure, nobody
    exposed or nobody unexposed, fewer than 5 people in a group, or an edit with watched conditions when
    `condition_match` is None or this source doesn't find it. Level 2 is None without exposure, when nobody is exposed
    or nobody is unexposed, without the counts by last value, below the minimum volume, or for an edit with watched
    conditions. Level 4 is None without an error rise or with fewer than two exposure steps. `proximity` is that of the
    error rise closest after an exposure step, and weighs levels 2 and 4. Level 5 is weighed by the proximity of its
    own error rise.

    The window is suspicious when level 1 finds the exposed people significantly worse with enough volume, or when the
    volume is enough and `score` reaches the threshold."""

    level_1: ProportionTestResult | None
    level_2: float | None
    level_4: float | None
    level_5: float
    proximity: float
    score: float
    suspicious: bool


@frozen
class _Split:
    exposed: Proportion
    unexposed: Proportion


@frozen
class _Excess:
    """`rate` is the error rate of the hour minus the mean rate of the same hour in earlier weeks, and `spread` is its
    standard deviation."""

    rate: float
    spread: float
    z: float


def score_window(
    edit: WatchedEdit,
    exposure: Sequence[ExposureBucket],
    errors_since_edit: ErrorCounts | None,
    hours: Mapping[datetime, HourErrors],
    baseline: Sequence[BaselineHour],
    parameters: ScoreParameters = WEB_PARAMETERS,
    *,
    condition_match: ConditionMatch | None = None,
) -> WindowScore:
    """Scores the window from the one-hour exposure buckets of the edit so far, oldest first, and the errors from the
    edit to the latest bucket. `hours` holds the errors of the window by the start of each UTC hour, and `baseline` the
    same hours of earlier weeks. `condition_match` is how the exposure and error queries found the watched conditions.
    For an edit with watched conditions, level 1 compares only the people in them, so it needs the match. For an edit
    without them, level 1 compares everyone with the flag."""
    for start in [*(bucket.start for bucket in exposure), *hours]:
        # Queries return times in the team's time zone, which can be a half hour off UTC.
        if start != _utc_hour(start):
            raise ValueError(f"The score needs one-hour buckets that start on the hour, got one at {start}")

    exposure_since_edit = exposure[-1].since_edit if exposure else None
    shares = {bucket.start: _share(bucket.in_bucket) for bucket in exposure}
    excess = _excess_by_hour(edit, hours, baseline, parameters.min_active)

    level_1: ProportionTestResult | None = None
    level_1_confirms = False
    split = _level_1_split(edit, exposure_since_edit, errors_since_edit, condition_match)
    if split is not None:
        level_1 = _level_1(split, parameters.alpha)
        level_1_confirms = (
            level_1 is not None
            and level_1.is_significant
            and level_1.difference > 0
            and _split_has_volume(split, parameters)
        )
    level_2 = _level_2(edit, exposure_since_edit, errors_since_edit, parameters)

    exposure_steps = _exposure_steps(edit, exposure, parameters.min_share_step)
    error_rises = _error_rises(excess, parameters.rise_z)
    # Without an error rise, the steps of the error rate are noise, and equal noise steps would look like a dose.
    level_4 = _level_4(shares, excess, parameters.min_share_step) if error_rises else None
    if error_rises:
        proximities = {start: _proximity(start, exposure_steps, parameters) for start in error_rises}
        # Each rise counts by its own distance, so that a strong rise days later can't lend strength to an early one.
        level_5_rise = max(
            error_rises, key=lambda start: _strength(error_rises[start], parameters) * proximities[start]
        )
        level_5 = _strength(error_rises[level_5_rise], parameters)
        level_5_proximity = proximities[level_5_rise]
        # Levels 2 and 4 don't come from one hour, so a later rise that the flag didn't cause can't weaken them.
        proximity = max(proximities.values())
    else:
        # Without an error rise, the latest hour stands in for it, so weak evidence counts less as the window ages.
        latest_hour = max([*shares, *hours], default=edit.edited_at)
        level_5 = max([0.0, *(_strength(hour_excess, parameters) for hour_excess in excess.values())])
        proximity = level_5_proximity = _proximity(latest_hour, exposure_steps, parameters)

    weighted = [parameters.weight_level_5 * level_5 * level_5_proximity]
    if level_2 is not None:
        weighted.append(parameters.weight_level_2 * level_2 * proximity)
    if level_4 is not None:
        weighted.append(parameters.weight_level_4 * level_4 * proximity)
    score = max(weighted)

    enough_volume = (
        exposure_since_edit is not None
        and errors_since_edit is not None
        and _enough_volume(exposure_since_edit.exposed, errors_since_edit.with_errors, parameters)
    )
    return WindowScore(
        level_1=level_1,
        level_2=level_2,
        level_4=level_4,
        level_5=level_5,
        proximity=proximity,
        score=score,
        suspicious=level_1_confirms or (enough_volume and score >= parameters.threshold),
    )


def _utc_hour(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def _enough_volume(exposed: int, with_errors: int, parameters: ScoreParameters) -> bool:
    return exposed >= parameters.min_exposed and with_errors >= parameters.min_with_errors


def _split_has_volume(split: _Split, parameters: ScoreParameters) -> bool:
    return _enough_volume(split.exposed.trials, split.exposed.successes + split.unexposed.successes, parameters)


def _strength(hour_excess: _Excess, parameters: ScoreParameters) -> float:
    return min(1.0, max(0.0, hour_excess.z) / parameters.full_strength_z)


def _error_rises(excess: Mapping[datetime, _Excess], rise_z: float) -> dict[datetime, _Excess]:
    """A run of consecutive hours at least `rise_z` over the baseline is one error rise. It starts in the first hour of
    the run, so errors that rose before an exposure step stay before it, and it has the excess of the strongest hour.
    An hour whose excess tops the highest of the run by `rise_z` of its spread starts a new rise, so errors that rise
    again at a later exposure step still count from there."""
    runs: list[list[datetime]] = []
    for start, hour_excess in excess.items():
        if hour_excess.z < rise_z:
            continue
        if runs and start - runs[-1][-1] == HOUR:
            highest = max(excess[hour].rate for hour in runs[-1])
            if hour_excess.rate - highest < rise_z * hour_excess.spread:
                runs[-1].append(start)
                continue
        runs.append([start])
    return {run[0]: max((excess[start] for start in run), key=lambda hour_excess: hour_excess.z) for run in runs}


def _proximity(error_rise: datetime, exposure_steps: Sequence[datetime], parameters: ScoreParameters) -> float:
    # Errors that rise before any exposure step can't come from the people that the flag exposes.
    latest_step = max((step for step in exposure_steps if step <= error_rise), default=None)
    if latest_step is None:
        return 0.0
    return math.exp(-(error_rise - latest_step) / parameters.decay)


def _share(counts: ExposureCounts) -> float:
    return counts.exposed / counts.with_flag if counts.with_flag else 0.0


def _split_people(
    exposed: int, unexposed: int, errors: ErrorCounts | ConditionErrors | ErrorsByLastValue | None
) -> _Split | None:
    if exposed <= 0 or unexposed <= 0:
        return None
    exposed_with_errors = errors.exposed_with_errors if errors else 0
    unexposed_with_errors = errors.unexposed_with_errors if errors else 0
    # A person whose value changed is in both groups, each with the errors of that value, which hides a difference
    # rather than inventing one. Separate `uniq` estimates can put the errors above the people, and the test raises on
    # that.
    return _Split(
        exposed=Proportion(trials=exposed, successes=min(exposed_with_errors, exposed)),
        unexposed=Proportion(trials=unexposed, successes=min(unexposed_with_errors, unexposed)),
    )


def _level_1_split(
    edit: WatchedEdit, exposure: ExposureCounts | None, errors: ErrorCounts | None, match: ConditionMatch | None
) -> _Split | None:
    if exposure is None:
        return None
    counts: ExposureCounts | ConditionExposure = exposure
    error_counts: ErrorCounts | ConditionErrors | None = errors
    if match is not None and match in exposure.in_condition:
        counts = exposure.in_condition[match]
        error_counts = errors.in_condition.get(match) if errors else None
    elif edit.conditions:
        # Everyone with the flag would compare the people in the edited conditions with people outside them.
        return None
    return _split_people(counts.exposed, counts.unexposed, error_counts)


def _level_1(split: _Split, alpha: float) -> ProportionTestResult | None:
    groups = (split.exposed, split.unexposed)
    if min(group.trials for group in groups) < MIN_GROUP_SIZE:
        return None
    # A group at 0% or 100% has no variance, so five people would look significant and no errors would give no result.
    exposed, unexposed = (Proportion(trials=group.trials + 2, successes=group.successes + 1) for group in groups)
    return sequential_proportion_test(exposed, unexposed, alpha=alpha)


def _level_2(
    edit: WatchedEdit, exposure: ExposureCounts | None, errors: ErrorCounts | None, parameters: ScoreParameters
) -> float | None:
    if edit.conditions or exposure is None or errors is None or errors.by_last_value is None:
        return None
    split = _split_people(exposure.exposed, exposure.unexposed, errors.by_last_value)
    if split is None or not _split_has_volume(split, parameters):
        return None
    exposed_rate = split.exposed.successes / split.exposed.trials
    unexposed_rate = split.unexposed.successes / split.unexposed.trials
    if not exposed_rate:
        return 0.0
    # The share of the exposed errors that the flag explains: 0 when the exposed are no worse, 1 when only they err.
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
    edit: WatchedEdit, hours: Mapping[datetime, HourErrors], baseline: Sequence[BaselineHour], min_active: int
) -> dict[datetime, _Excess]:
    """The excess error rate of each hour from the edit on, oldest first. An hour with fewer than `min_active` active
    people, or without two earlier weeks that have `min_active`, has no entry."""
    earlier = {hour.start: hour.weeks for hour in baseline}
    edit_hour = _utc_hour(edit.edited_at)
    excess: dict[datetime, _Excess] = {}
    for start, counts in sorted(hours.items()):
        # In a small hour, such as one that just started, one error is a rate of 1 with no sampling noise.
        rates = [week.with_errors / week.active for week in earlier.get(start, ()) if week.active >= min_active]
        if start < edit_hour or counts.active < min_active or len(rates) < 2:
            continue
        # The two counts are separate `uniq` estimates, so the errors can come out above the active people.
        rate = min(1.0, counts.with_errors / counts.active)
        excess_rate = rate - statistics.fmean(rates)
        spread = math.hypot(statistics.stdev(rates), math.sqrt(rate * (1 - rate) / counts.active))
        z = excess_rate / spread if spread else (math.inf if excess_rate > 0 else 0.0)
        excess[start] = _Excess(rate=excess_rate, spread=spread, z=z)
    return excess


def _exposure_steps(edit: WatchedEdit, exposure: Sequence[ExposureBucket], min_share_step: float) -> list[datetime]:
    """The starts of the buckets in which the exposure share rises at least `min_share_step` over the highest share
    before them, and the hour of an edit that doesn't enable the flag. For an edit that enables the flag, only the hour
    of the edit when no event carries the flag, or when the share never rises that much."""
    edit_hour = _utc_hour(edit.edited_at)
    # An edit that doesn't enable the flag changes at once who gets which value, and its share before the edit is
    # unknown, so its hour is the step instead of its first bucket. Before an edit that enables it, nobody is exposed.
    steps = [] if edit.enables else [edit_hour]
    highest = 0.0 if edit.enables else None
    for bucket in exposure:
        share = _share(bucket.in_bucket)
        # A share that falls by chance and comes back exposes nobody new, so a step must top the highest share.
        if highest is not None and share - highest >= min_share_step:
            steps.append(bucket.start)
        highest = share if highest is None else max(highest, share)
    return steps or [edit_hour]

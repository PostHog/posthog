import math
import unicodedata
from collections.abc import Mapping
from dataclasses import replace
from datetime import date, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

from scipy.stats import chi2_contingency, chisquare

from posthog.schema import SampleRatioMismatch

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.utils.breakdowns import BREAKDOWN_NULL_STRING_LABEL, BREAKDOWN_OTHER_STRING_LABEL

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
    ExperimentHealthValueKey,
)
from products.experiments.backend.health.checks.bias_risk import multiple_variant_count
from products.experiments.backend.health.checks.change_wording import RESET_EFFECT, suggested_start
from products.experiments.backend.health.checks.forced_variant import (
    SOME_CONDITIONS_PINNED,
    assigns_nobody_by_split,
    set_names,
)
from products.experiments.backend.health.checks.split_changed import split_changed_mid_run
from products.experiments.backend.health.context import (
    ExposureSegment,
    ExposureTotals,
    FlagHistory,
    FlagHistoryNotChecked,
    FlagState,
    HealthContext,
    ReachableCondition,
    split_changed_after_the_end,
)
from products.experiments.backend.health.pinned_share import pinned_variant_keys
from products.experiments.backend.health.skips import (
    NEEDS_EXPOSURES,
    RUNS_AFTER_LAUNCH,
    SPLIT_ASSIGNS_NOBODY,
    SPLIT_CHANGED_AFTER_END,
    CheckOutcome,
    CheckValues,
    fewer_than_two_in_split,
    not_applicable,
)
from products.experiments.backend.hogql_queries.experiment_exposure_query_builder import ExposureSegmentDimension
from products.feature_flags.backend.facade.edits import SplitChange

SAMPLE_RATIO_MISMATCH_P_VALUE = 0.001
SRM_MINIMUM_SAMPLE_SIZE = 100
# The share of persons or groups that would have to switch variants to match the split. Below it, a mismatch moves too
# few of them to change the results much, so it is info. A large experiment reaches the p-value with a far smaller skew.
MATERIAL_SHARE_OFF_SPLIT = 0.01
TOP_SEGMENT_VALUES = 5
# Below this, a skew of a few points passes the homogeneity test for lack of power, and would read as the same skew
# everywhere. Two segments this large are needed before the finding calls a dimension uniform.
UNIFORM_SEGMENT_MINIMUM_SIZE = 1000
SEGMENT_LABEL_MAX_LENGTH = 60
# The detail names the located segments furthest from the split, up to this many.
NAMED_SEGMENTS = 2
# One variant fills a segment when the other variants have less than this share of their expected count in it. The
# expected count comes from the split, so on a 90/10 split a segment at 95% control doesn't count as filled by control.
BARELY_EXPOSED_SHARE = 0.1

# pinned: the subcode is sent as `finding_subcode` on the health finding events, so insights group on it.
SPLIT_CHANGED = "split_changed"


class SrmReason(StrEnum):
    # pinned: the finding's `reason`.
    LIBRARY = ExposureSegmentDimension.LIBRARY.value
    LIBRARY_VERSION = ExposureSegmentDimension.LIBRARY_VERSION.value
    PAGE = ExposureSegmentDimension.PAGE.value
    SCREEN = ExposureSegmentDimension.SCREEN.value
    VARIANT_SEGMENTS = "variant_segments"
    UNIFORM = "uniform"


_DIMENSION_PLURALS = {
    ExposureSegmentDimension.LIBRARY: "SDK libraries",
    ExposureSegmentDimension.LIBRARY_VERSION: "SDK versions",
    ExposureSegmentDimension.PAGE: "pages",
    ExposureSegmentDimension.SCREEN: "screens",
}


def sample_ratio_test(observed: Mapping[str, int], weights: Mapping[str, float]) -> SampleRatioMismatch | None:
    """Chi-squared goodness-of-fit test of the observed counts against the weights of the variants in the split.
    None when there is too little data."""
    # Iterate over the weights, not the observed counts, so that a variant with 0 exposures still enters the
    # chi-square and sum(observed) == sum(expected).
    total_observed = sum(observed.get(key, 0) for key in weights)
    if total_observed < SRM_MINIMUM_SAMPLE_SIZE:
        return None
    # After dropping holdout and excluded variants, the remaining percentages may not sum to 100.
    # Normalize so that the chi-square expected counts sum to total_observed.
    total_weight = sum(weights.values())
    if total_weight <= 0 or len(weights) < 2:
        return None
    expected = {key: (weight / total_weight) * total_observed for key, weight in weights.items()}
    _, p_value = chisquare([float(observed.get(key, 0)) for key in weights], list(expected.values()))
    return SampleRatioMismatch(expected=expected, p_value=float(p_value))


def reads_flag_history(ctx: HealthContext) -> bool:
    """Whether `srm` reads the flag history in this context. The exposure query loads the history only then, because
    the load reads the flag's activity log and can query the exposures."""
    p_value = ctx.exposures.sample_ratio_mismatch_p_value if ctx.exposures else None
    return p_value is not None and p_value < SAMPLE_RATIO_MISMATCH_P_VALUE


def reads_segments(ctx: HealthContext) -> bool:
    """Whether `srm` reports a mismatch that a split change doesn't explain, which it then looks for in the segments
    of the exposures. After a split change, that is a mismatch among the users first exposed after the change, and
    the segments count only them (`segments_first_exposed_after`). The exposure query loads the segments only then,
    because their query scans the exposure events."""
    # With an activation, the segments would come from the activation event, not from the flag call that assigned
    # the variant.
    if ctx.exposure_events is not None and ctx.exposure_events.activation is not None:
        return False
    outcome = srm(ctx)
    if not isinstance(outcome, ExperimentHealthFinding):
        return False
    # A variant override can explain a mismatch, but a segment that locates it names the cause more precisely.
    if outcome.subcode != SPLIT_CHANGED:
        return True
    retest_p_value = outcome.evidence.get("p_value_after_split_change")
    return isinstance(retest_p_value, float) and retest_p_value < SAMPLE_RATIO_MISMATCH_P_VALUE


def segments_first_exposed_after(ctx: HealthContext) -> date | None:
    """The day after which the segments count the users, in the team's timezone. None for the whole run. After a split
    change, the users first exposed before it got their variants from another split, so they would fail the test
    against the current split in any segment they fill."""
    split_changes = _split_change_cause(ctx)
    return None if split_changes is None else split_changes.last_day


def srm_values(ctx: HealthContext) -> CheckValues:
    exposures = ctx.exposures
    if exposures is None:
        return {}
    # The test compares the variants of `sample_ratio_expected`. Below its minimum the test doesn't run and leaves that
    # empty, so the variants come from the split, as the exposure query picks them.
    compared = exposures.sample_ratio_expected.keys() or _variants_in_split(ctx)
    values: dict[ExperimentHealthValueKey, int | float | None] = {
        ExperimentHealthValueKey.P_VALUE: exposures.sample_ratio_mismatch_p_value,
        ExperimentHealthValueKey.COMPARED_COUNT: sum(exposures.total_exposures.get(key, 0) for key in compared),
    }
    multiple = multiple_variant_count(exposures)
    if multiple is not None:
        values[ExperimentHealthValueKey.MULTIPLE_VARIANT_COUNT] = multiple
    return values


def _variants_in_split(ctx: HealthContext) -> list[str]:
    """The variants with a share of the split that the analysis keeps, which the exposure query compares."""
    return [
        variant.key
        for variant in (ctx.flag.variants if ctx.flag else ())
        if variant.key and (variant.rollout_percentage or 0) > 0 and variant.key not in ctx.excluded_variant_keys
    ]


def srm(ctx: HealthContext) -> CheckOutcome:
    exposures = ctx.exposures
    if exposures is None:
        return not_applicable(RUNS_AFTER_LAUNCH)
    # The split then serves nobody, so the test compares nothing. `forced_variant_release_condition` explains it.
    overrides = _flag_of_the_run(ctx)
    if overrides is not None and assigns_nobody_by_split(overrides):
        return not_applicable(SPLIT_ASSIGNS_NOBODY)
    p_value = exposures.sample_ratio_mismatch_p_value
    if p_value is None:
        # The exposure query compares only the variants with a share of the split that the analysis keeps, so after
        # a variant ships there is nothing to compare however many users are exposed.
        if len(_variants_in_split(ctx)) < 2:
            return fewer_than_two_in_split(exposures.total_exposures)
        return not_applicable(NEEDS_EXPOSURES)
    if p_value >= SAMPLE_RATIO_MISMATCH_P_VALUE:
        return None
    # The test compares the run's exposures with the flag's current split, and the exposures count only its variants.
    if _split_changed_after_the_end(ctx):
        return not_applicable(SPLIT_CHANGED_AFTER_END)
    share_off_split = _share_off_split(exposures.total_exposures, exposures.sample_ratio_expected)
    split_changes = _split_changes(ctx)
    ruled_out = False
    if split_changes is not None:
        if not _skew_predates_the_change(ctx, exposures, split_changes):
            return _after_split_change(ctx, exposures, split_changes, p_value, share_off_split)
        ruled_out = True
    cause = _segment_cause(exposures, exposures.unit)
    pinned = _pinned_cause(ctx, exposures)
    if pinned and not cause.locates_the_mismatch:
        return _pinned_mismatch(exposures, pinned, p_value, share_off_split, cause)
    return _mismatch(exposures, p_value, share_off_split, cause, split_change_ruled_out=ruled_out)


def _severity(share_off_split: float) -> ExperimentHealthFindingSeverity:
    if share_off_split < MATERIAL_SHARE_OFF_SPLIT:
        return ExperimentHealthFindingSeverity.INFO
    return ExperimentHealthFindingSeverity.WARNING


def _small_mismatch(share_off_split: float, unit: str) -> list[str]:
    if share_off_split >= MATERIAL_SHARE_OFF_SPLIT:
        return []
    # Rounded down, so that a share just under the floor doesn't read as the floor. The epsilon keeps a share of 0.008
    # that float arithmetic computes as 0.00799… at 0.8%.
    tenths = math.floor(share_off_split * 1000 + 1e-9)
    share = f"Only {tenths / 10:g}%" if tenths else "Fewer than 0.1%"
    return [
        f"{share} of {unit}s would have to switch variants to match the split, so the difference is unlikely to "
        "change the results."
    ]


def _after_split_change(
    ctx: HealthContext,
    exposures: ExposureTotals,
    split_changes: "_SplitChanges",
    p_value: float,
    share_off_split: float,
) -> ExperimentHealthFinding:
    # A retest that passes keeps the severity: the users exposed after the change are fewer than those the test covers,
    # so it can't rule out a mismatch with another cause. The retest only adds evidence.
    unit = exposures.unit
    retest, p_value_after_change = _retest_after_change(ctx, exposures, split_changes, unit)
    evidence: dict[str, str | int | float | None] = {
        "p_value": p_value,
        "share_off_split": round(share_off_split, 4),
        "p_value_after_split_change": p_value_after_change,
    }
    cause = (
        _segment_cause(exposures, unit)
        if p_value_after_change is not None and p_value_after_change < SAMPLE_RATIO_MISMATCH_P_VALUE
        else None
    )
    if cause is not None:
        evidence.update(cause.evidence)
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.SRM,
        subcode=SPLIT_CHANGED,
        reason=cause.reason if cause is not None else None,
        severity=_severity(share_off_split),
        title=f"{unit.capitalize()}s are not split as configured after a split change",
        detail=" ".join(
            [
                f"The distribution of {unit}s across variants doesn't match your current rollout percentages "
                f"(p < {SAMPLE_RATIO_MISMATCH_P_VALUE}).",
                *_small_mismatch(share_off_split, unit),
                _changed_while_exposed(split_changes, unit),
                *retest,
                *(cause.sentences if cause is not None else ()),
                *_next_step(ctx, split_changes),
            ]
        ),
        evidence=evidence,
        actions=(),
        diagnostic_ref="A2",
    )


def _changed_while_exposed(split_changes: "_SplitChanges", unit: str) -> str:
    if split_changes.warning_title is None:
        return (
            f"The variant split changed after launch, and {unit}s exposed before the change got their variants from "
            "another split, which can cause this."
        )
    return (
        f"The variant split changed after launch while {unit}s were exposed, and some of them got their variants from "
        "another split, which can cause this."
    )


def _next_step(ctx: HealthContext, split_changes: "_SplitChanges") -> list[str]:
    if split_changes.warning_title is None:
        start_at = suggested_start(split_changes.changes[-1].changed_at, split_changes.team_timezone)
        # A reset also clears the end date and the conclusion, which would undo an ended experiment's decision.
        if ctx.has_ended:
            return [f"Move the start date to {start_at}."]
        return [f"Move the start date to {start_at}, or reset the experiment.", RESET_EFFECT]
    # The split check doesn't run after the end, so its finding isn't there to follow.
    return [] if ctx.has_ended else [f'Follow the steps in "{split_changes.warning_title}" to fix the results.']


def _retest_after_change(
    ctx: HealthContext, exposures: ExposureTotals, split_changes: "_SplitChanges", unit: str
) -> tuple[list[str], float | None]:
    """The sentence about the test of the users first exposed after the day of the last split change, who got their
    variants from the current split alone, and its p-value."""
    events = ctx.exposure_events
    if events is None:
        return [], None
    # With an activation, the exposure query dates a user by the activation, but the flag call before it assigned the
    # variant. Users dated after the change can then carry a variant from before it.
    if events.activation is not None:
        return [
            f"The exposure criteria count {unit}s at an activation, so the {unit}s exposed after the change can't "
            "be tested alone."
        ], None
    changed_on = split_changes.last_day
    after_change = sample_ratio_test(
        {
            variant: sum(count for day, count in daily.items() if day > changed_on)
            for variant, daily in exposures.daily_exposures.items()
        },
        exposures.sample_ratio_expected,
    )
    if after_change is None:
        return [f"Too few {unit}s were first exposed after the day of the change to test them alone."], None
    if after_change.p_value < SAMPLE_RATIO_MISMATCH_P_VALUE:
        return [
            f"The {unit}s first exposed after the day of the change don't match the current split either "
            f"(p < {SAMPLE_RATIO_MISMATCH_P_VALUE}), so look for another cause too."
        ], after_change.p_value
    return [
        f"The {unit}s first exposed after the day of the change match the current split "
        f"(p = {after_change.p_value:.2g})."
    ], after_change.p_value


@frozen
class _SplitChanges:
    """The split changes after launch that can have moved users who were already exposed, in time order."""

    changes: tuple[SplitChange, ...]
    team_timezone: str
    # None when the split check couldn't compare the changes with the exposures, so its finding has no steps to follow.
    warning_title: str | None

    @property
    def first_day(self) -> date:
        return _day_in(self.team_timezone, self.changes[0].changed_at)

    @property
    def last_day(self) -> date:
        return _day_in(self.team_timezone, self.changes[-1].changed_at)


def _day_in(team_timezone: str, at: datetime) -> date:
    return at.astimezone(ZoneInfo(team_timezone)).date()


def _split_changes(ctx: HealthContext) -> _SplitChanges | None:
    """The split changes that the split check reports, from the first that can have moved an exposed user."""
    finding = _split_change_finding(ctx)
    history = ctx.flag_history
    if finding is None or ctx.exposures is None:
        return None
    if isinstance(history, FlagHistory):
        if finding.severity != ExperimentHealthFindingSeverity.WARNING:
            return None
        return _SplitChanges(
            changes=history.counted(SplitChange), team_timezone=history.team_timezone, warning_title=finding.title
        )
    if not isinstance(history, FlagHistoryNotChecked):
        return None
    # A change on the first day of exposures may predate them all. It counts, as when the split check's query fails.
    first_day = min(
        (day for daily in ctx.exposures.daily_exposures.values() for day, count in daily.items() if count > 0),
        default=None,
    )
    if first_day is None:
        return None
    changes = tuple(
        change
        for change in history.of_kind(SplitChange)
        if _day_in(history.team_timezone, change.changed_at) >= first_day
    )
    if not changes:
        return None
    return _SplitChanges(changes=changes, team_timezone=history.team_timezone, warning_title=None)


def _split_change_cause(ctx: HealthContext) -> _SplitChanges | None:
    """The split changes, when they can explain the mismatch."""
    split_changes = _split_changes(ctx)
    if split_changes is None or ctx.exposures is None:
        return None
    return None if _skew_predates_the_change(ctx, ctx.exposures, split_changes) else split_changes


def _skew_predates_the_change(ctx: HealthContext, exposures: ExposureTotals, split_changes: _SplitChanges) -> bool:
    """Whether the users first exposed before the first split change, those first exposed after the last one and all
    exposed users show the same shares, and those after it don't match the current split. Mixing assignments then
    can't explain the mismatch, because each group of users alone shows it."""
    events = ctx.exposure_events
    if events is None or events.activation is not None:
        return False
    first_day = split_changes.first_day
    last_day = split_changes.last_day
    weights = exposures.sample_ratio_expected
    # A user first exposed on the day of a change can have either split, so neither group counts them.
    before = {
        variant: sum(count for day, count in exposures.daily_exposures.get(variant, {}).items() if day < first_day)
        for variant in weights
    }
    after = {
        variant: sum(count for day, count in exposures.daily_exposures.get(variant, {}).items() if day > last_day)
        for variant in weights
    }
    retest = sample_ratio_test(after, weights)
    if retest is None or retest.p_value >= SAMPLE_RATIO_MISMATCH_P_VALUE:
        return False
    if sum(before.values()) < SRM_MINIMUM_SAMPLE_SIZE:
        return False
    # The users between the changes and on a change day fill neither group, so all users must show the shares too.
    return (
        _share_off_split(before, after) < MATERIAL_SHARE_OFF_SPLIT
        and _share_off_split(exposures.total_exposures, after) < MATERIAL_SHARE_OFF_SPLIT
    )


def _split_changed_after_the_end(ctx: HealthContext) -> bool:
    history = ctx.flag_history
    return isinstance(history, FlagHistory | FlagHistoryNotChecked) and split_changed_after_the_end(
        history.changes, ctx.ended_at
    )


def _during_the_run(ctx: HealthContext) -> HealthContext:
    """The context as the split check reads it before the end. After the end that check stops, because the flag often
    holds the shipped decision. Without a split change after the end, the flag's split is still the run's."""
    if ctx.has_ended and not _split_changed_after_the_end(ctx):
        return replace(ctx, has_ended=False)
    return ctx


def _split_change_finding(ctx: HealthContext) -> ExperimentHealthFinding | None:
    try:
        outcome = split_changed_mid_run(_during_the_run(ctx))
    except Exception as error:
        # The health endpoint reports the failure of the split check itself. Here it must not hide the mismatch.
        capture_exception(error)
        return None
    return outcome if isinstance(outcome, ExperimentHealthFinding) else None


def _flag_of_the_run(ctx: HealthContext) -> FlagState | None:
    """The flag whose variant overrides can explain the mismatch. None after the end, because the flag then often
    holds the shipped decision and not the setup of the run, like `flag_to_check` says."""
    return None if ctx.has_ended else ctx.flag


def _pinned_cause(ctx: HealthContext, exposures: ExposureTotals) -> tuple[ReachableCondition, ...]:
    """The release conditions with a variant override in the test, when one of them pins the variant furthest above
    its expected count. Their users don't follow the split, so they can cause the mismatch."""
    expected = exposures.sample_ratio_expected
    flag = _flag_of_the_run(ctx)
    if flag is None or not expected:
        return ()
    pinned = tuple(condition for condition in flag.reachable_conditions if condition.pinned_variant in expected)
    over = max(expected, key=lambda variant: exposures.total_exposures.get(variant, 0) - expected[variant])
    return pinned if any(condition.pinned_variant == over for condition in pinned) else ()


def _pinned_mismatch(
    exposures: ExposureTotals,
    pinned: tuple[ReachableCondition, ...],
    p_value: float,
    share_off_split: float,
    segments: "_SegmentCause",
) -> ExperimentHealthFinding:
    unit = exposures.unit
    numbers = [condition.number for condition in pinned]
    keys = pinned_variant_keys(pinned)
    if len(numbers) == 1:
        cause = (
            f'{set_names(numbers)} sets the variant override "{keys[0]}", so the {unit}s it matches get "{keys[0]}" '
            "instead of a variant from the split, which can cause this."
        )
        overrides = "the override"
    else:
        quoted = ", ".join(f'"{key}"' for key in keys)
        cause = (
            f"{set_names(numbers)} set variant overrides ({quoted}), so the {unit}s they match get the variant of "
            "their condition instead of one from the split, which can cause this."
        )
        overrides = "the overrides"
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.SRM,
        subcode=SOME_CONDITIONS_PINNED,
        reason=None,
        severity=_severity(share_off_split),
        title=f"{unit.capitalize()}s are not split as configured because of variant overrides",
        detail=" ".join(
            [
                f"The distribution of {unit}s across variants doesn't match your configured rollout percentages "
                f"(p < {SAMPLE_RATIO_MISMATCH_P_VALUE}).",
                *_small_mismatch(share_off_split, unit),
                cause,
                "If these are internal or test users, check that the filter for internal and test users excludes "
                f"them from the results. Otherwise remove {overrides}.",
            ]
        ),
        evidence={
            "p_value": p_value,
            "share_off_split": round(share_off_split, 4),
            "pinned_conditions": ",".join(str(number) for number in numbers),
            "pinned_variants": ",".join(keys),
            **segments.evidence,
        },
        actions=(),
        diagnostic_ref="A2",
    )


def _mismatch(
    exposures: ExposureTotals,
    p_value: float,
    share_off_split: float,
    cause: "_SegmentCause",
    *,
    split_change_ruled_out: bool,
) -> ExperimentHealthFinding:
    unit = exposures.unit
    ruled_out = (
        [
            f"The variant split changed after launch, but the {unit}s first exposed before the change show the same "
            "mismatch as those first exposed after it, so the change doesn't explain it."
        ]
        if split_change_ruled_out
        else []
    )
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.SRM,
        subcode=None,
        reason=cause.reason,
        severity=_severity(share_off_split),
        title=f"{unit.capitalize()}s are not split across variants as configured",
        detail=" ".join(
            [
                f"The distribution of {unit}s across variants doesn't match your configured rollout percentages "
                f"(p < {SAMPLE_RATIO_MISMATCH_P_VALUE}).",
                *_small_mismatch(share_off_split, unit),
                *ruled_out,
                *(cause.sentences or ("This may indicate issues with randomization or data collection.",)),
            ]
        ),
        evidence={
            "p_value": p_value,
            "share_off_split": round(share_off_split, 4),
            **({"split_change_ruled_out": True} if split_change_ruled_out else {}),
            **cause.evidence,
        },
        actions=(),
        diagnostic_ref="A2",
    )


@frozen
class _SegmentTest:
    segment: ExposureSegment
    # None when the segment holds too few persons or groups for the test.
    p_value: float | None

    @property
    def fails(self) -> bool:
        return self.p_value is not None and self.p_value < SAMPLE_RATIO_MISMATCH_P_VALUE


@frozen
class _Verdict:
    dimension: ExposureSegmentDimension
    homogeneity_p_value: float | None
    powered: bool
    located: ExposureSegment | None
    distance: float


@frozen
class _SegmentCause:
    """What the segments say about the mismatch: the sentences that follow it, the finding's reason, and the
    segments as evidence. Without a verdict the sentences are empty and the reason is None."""

    sentences: tuple[str, ...]
    reason: str | None
    evidence: dict[str, str | int | float | None]

    @property
    def locates_the_mismatch(self) -> bool:
        # A variant override also sends the users it matches to segments that one variant fills, so the override
        # finding comes before `variant_segments`.
        return self.reason not in (None, SrmReason.UNIFORM, SrmReason.VARIANT_SEGMENTS)


def _segment_cause(exposures: ExposureTotals, unit: str) -> _SegmentCause:
    tests = _segment_tests(exposures)
    verdicts = [_verdict(tests, dimension, exposures.sample_ratio_expected) for dimension in ExposureSegmentDimension]
    sentences, reason = _cause(verdicts, _variant_segments(tests, exposures), unit)
    evidence = _segment_evidence(tests, verdicts)
    located = _located(verdicts)
    if located:
        evidence["located_dimensions"] = ",".join(segment.dimension.value for segment in located)
    return _SegmentCause(sentences=tuple(sentences), reason=None if reason is None else reason.value, evidence=evidence)


def _segment_tests(exposures: ExposureTotals) -> list[_SegmentTest]:
    """The sample ratio test of each segment against the split of the whole test, largest segment first."""
    segments = sorted(exposures.segments or (), key=lambda segment: -sum(segment.exposed_by_variant.values()))
    tests = []
    for segment in segments:
        result = sample_ratio_test(segment.exposed_by_variant, exposures.sample_ratio_expected)
        tests.append(_SegmentTest(segment=segment, p_value=result.p_value if result else None))
    return tests


def _verdict(tests: list[_SegmentTest], dimension: ExposureSegmentDimension, weights: Mapping[str, float]) -> _Verdict:
    # A test per segment would blame the largest segment for a skew that every segment shares, because the same skew
    # reaches significance first in the most users. The homogeneity test asks whether the segments differ at all.
    compared = [test for test in tests if test.segment.dimension == dimension and test.p_value is not None]
    variants = [
        variant for variant in weights if any(test.segment.exposed_by_variant.get(variant, 0) for test in compared)
    ]
    if len(compared) < 2 or len(variants) < 2:
        return _Verdict(dimension=dimension, homogeneity_p_value=None, powered=False, located=None, distance=0.0)
    table = [[test.segment.exposed_by_variant.get(variant, 0) for variant in variants] for test in compared]
    homogeneity_p_value = float(chi2_contingency(table).pvalue)
    powered = sum(1 for row in table if sum(row) >= UNIFORM_SEGMENT_MINIMUM_SIZE) >= 2
    located: ExposureSegment | None = None
    if homogeneity_p_value < SAMPLE_RATIO_MISMATCH_P_VALUE:
        failing = [test.segment for test in compared if test.fails]
        # The detail says the mismatch comes from the segment, which reads as if the other segments match the split.
        located = failing[0] if len(failing) == 1 else None
    return _Verdict(
        dimension=dimension,
        homogeneity_p_value=homogeneity_p_value,
        powered=powered,
        located=located,
        distance=_share_off_split(located.exposed_by_variant, weights) if located is not None else 0.0,
    )


def _share_off_split(exposed_by_variant: Mapping[str, int], weights: Mapping[str, float]) -> float:
    """The share of the persons or groups that would have to move between variants to match the weights."""
    total = sum(exposed_by_variant.get(variant, 0) for variant in weights)
    total_weight = sum(weights.values())
    if total <= 0 or total_weight <= 0:
        return 0.0
    return (
        sum(
            abs(exposed_by_variant.get(variant, 0) / total - weight / total_weight)
            for variant, weight in weights.items()
        )
        / 2
    )


def _variant_segments(tests: list[_SegmentTest], exposures: ExposureTotals) -> list[tuple[ExposureSegment, str]]:
    """The segments that a variant with fewer exposures than expected fills, each with its variant, the largest
    segment of each variant first."""
    expected = exposures.sample_ratio_expected
    total_expected = sum(expected.values())
    # The detail says that users are missing from the variant that sends its exposure from its own place. A variant
    # with more exposures than expected can fill segments for another reason, such as a variant override.
    short = _short_variants(exposures.segments or (), expected)
    found: dict[str, ExposureSegment] = {}
    for test in tests:
        segment = test.segment
        # The segment must also fail the test on its own, so that a small segment doesn't count by chance.
        if not test.fails or segment.value == BREAKDOWN_OTHER_STRING_LABEL:
            continue
        compared = sum(segment.exposed_by_variant.get(variant, 0) for variant in expected)
        variant = max(expected, key=lambda key: segment.exposed_by_variant.get(key, 0))
        others = compared - segment.exposed_by_variant.get(variant, 0)
        if variant in short and others < BARELY_EXPOSED_SHARE * compared * (1 - expected[variant] / total_expected):
            found.setdefault(variant, segment)
    return [(segment, variant) for variant, segment in found.items()][:NAMED_SEGMENTS]


def _short_variants(segments: tuple[ExposureSegment, ...], expected: Mapping[str, float]) -> set[str]:
    """The variants with a smaller share of the segments than of the split."""
    # Each person or group is in exactly one library segment, so the library segments count everyone the segments
    # count. After a split change that is only those first exposed after it, which the totals of the whole run are not.
    counted = {
        variant: sum(
            segment.exposed_by_variant.get(variant, 0)
            for segment in segments
            if segment.dimension == ExposureSegmentDimension.LIBRARY
        )
        for variant in expected
    }
    total_counted = sum(counted.values())
    total_expected = sum(expected.values())
    return {variant for variant in expected if counted[variant] * total_expected < expected[variant] * total_counted}


def _cause(
    verdicts: list[_Verdict], variant_segments: list[tuple[ExposureSegment, str]], unit: str
) -> tuple[list[str], SrmReason | None]:
    """The sentences that follow the mismatch, and the finding's reason. Empty without a verdict."""
    named = _without_libraries_of_located_versions(_located(verdicts))[:NAMED_SEGMENTS]
    if named:
        places = ", and from ".join(f"{unit}s {_segment_place(segment)}" for segment in named)
        return [
            f"The mismatch comes from {places}.",
            f"Check that the code there sends the exposure for every {unit} in every variant.",
        ], SrmReason(named[0].dimension.value)
    if variant_segments:
        filled = ", and ".join(
            f'{unit}s {_segment_place(segment)} are almost all in "{variant}"' for segment, variant in variant_segments
        )
        return [
            f"{filled[0].upper()}{filled[1:]}, so the variants send their exposures from different places.",
            f"When each variant has its own page or site, {unit}s who leave before their variant's exposure is sent "
            "are missing from that variant, which can cause this.",
            "Send the exposure at the same point in every variant, before any redirect.",
        ], SrmReason.VARIANT_SEGMENTS
    compared = {
        verdict.dimension: verdict.homogeneity_p_value
        for verdict in verdicts
        if verdict.homogeneity_p_value is not None
    }
    powered = [verdict.dimension for verdict in verdicts if verdict.powered]
    if powered and all(p_value >= SAMPLE_RATIO_MISMATCH_P_VALUE for p_value in compared.values()):
        across = _joined([_DIMENSION_PLURALS[dimension] for dimension in powered])
        return [
            f"The mismatch looks the same across {across}, which points at how {unit}s get their variants rather "
            "than at one integration."
        ], SrmReason.UNIFORM
    return [], None


def _located(verdicts: list[_Verdict]) -> list[ExposureSegment]:
    """The located segments, the one furthest from the split first."""
    ranked = sorted((verdict for verdict in verdicts if verdict.located is not None), key=lambda v: -v.distance)
    return [verdict.located for verdict in ranked if verdict.located is not None]


def _without_libraries_of_located_versions(located: list[ExposureSegment]) -> list[ExposureSegment]:
    """A located version of a located library says the same more precisely, so the library isn't named too."""
    versioned = {
        segment.library for segment in located if segment.dimension == ExposureSegmentDimension.LIBRARY_VERSION
    }
    return [
        segment
        for segment in located
        if not (segment.dimension == ExposureSegmentDimension.LIBRARY and segment.value in versioned)
    ]


def _joined(words: list[str]) -> str:
    return " and ".join(filter(None, [", ".join(words[:-1]), words[-1]]))


def _segment_place(segment: ExposureSegment) -> str:
    match segment.dimension:
        case ExposureSegmentDimension.LIBRARY:
            if segment.value == BREAKDOWN_OTHER_STRING_LABEL:
                return f"whose first exposure was sent by a library other than the {TOP_SEGMENT_VALUES} most common"
            if segment.value == BREAKDOWN_NULL_STRING_LABEL:
                return "whose first exposure was sent by an unknown library"
            return f"whose first exposure was sent by the {_segment_label(segment.value)} library"
        case ExposureSegmentDimension.LIBRARY_VERSION:
            if segment.value == BREAKDOWN_OTHER_STRING_LABEL:
                return (
                    "whose first exposure was sent by a library version other than the "
                    f"{TOP_SEGMENT_VALUES} most common"
                )
            library = segment.library
            by_library = (
                "an unknown library"
                if library is None or library == BREAKDOWN_NULL_STRING_LABEL
                else f"the {_segment_label(library)} library"
            )
            if segment.value == BREAKDOWN_NULL_STRING_LABEL:
                return f"whose first exposure was sent by an unknown version of {by_library}"
            return f"whose first exposure was sent by version {_segment_label(segment.value)} of {by_library}"
        case ExposureSegmentDimension.PAGE:
            if segment.value == BREAKDOWN_OTHER_STRING_LABEL:
                return f"first exposed on a page other than the {TOP_SEGMENT_VALUES} most common"
            return f"first exposed on the page {_segment_label(segment.value)}"
        case ExposureSegmentDimension.SCREEN:
            if segment.value == BREAKDOWN_OTHER_STRING_LABEL:
                return f"first exposed on a screen other than the {TOP_SEGMENT_VALUES} most common"
            return f"first exposed on the screen {_segment_label(segment.value)}"


def _segment_label(value: str) -> str:
    """The value quoted for the detail. It comes from an event property, so anyone with the project's token writes
    it, and agents read the detail as PostHog's own words. A double quote would end the quotes early, so the label
    drops it. The evidence keeps the raw value."""
    printable = "".join(char for char in value if char != '"' and not unicodedata.category(char).startswith("C"))
    if len(printable) > SEGMENT_LABEL_MAX_LENGTH:
        printable = printable[: SEGMENT_LABEL_MAX_LENGTH - 1] + "…"
    return f'"{printable}"'


def _segment_evidence(tests: list[_SegmentTest], verdicts: list[_Verdict]) -> dict[str, str | int | float | None]:
    """Each segment in the keys `<dimension>_N` (the value), `<dimension>_N_library` (the library of a version),
    `<dimension>_N_p_value` and `<dimension>_N_exposed_<variant>`, and each compared dimension in
    `<dimension>_homogeneity_p_value`."""
    evidence: dict[str, str | int | float | None] = {}
    for verdict in verdicts:
        dimension = verdict.dimension
        if verdict.homogeneity_p_value is not None:
            evidence[f"{dimension.value}_homogeneity_p_value"] = verdict.homogeneity_p_value
        in_dimension = [test for test in tests if test.segment.dimension == dimension]
        for index, test in enumerate(in_dimension, start=1):
            key = f"{dimension.value}_{index}"
            evidence[key] = test.segment.value
            if test.segment.library is not None:
                evidence[f"{key}_library"] = test.segment.library
            evidence[f"{key}_p_value"] = test.p_value
            for variant, exposed in test.segment.exposed_by_variant.items():
                evidence[f"{key}_exposed_{variant}"] = exposed
    return evidence

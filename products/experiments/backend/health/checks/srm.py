from collections.abc import Mapping
from zoneinfo import ZoneInfo

from scipy.stats import chisquare

from posthog.schema import SampleRatioMismatch

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.utils.breakdowns import BREAKDOWN_NULL_STRING_LABEL, BREAKDOWN_OTHER_STRING_LABEL

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.checks.split_changed import split_changed_mid_run
from products.experiments.backend.health.context import ExposureSegment, ExposureTotals, FlagHistory, HealthContext
from products.experiments.backend.health.skips import RUNS_AFTER_LAUNCH, CheckOutcome, not_applicable
from products.experiments.backend.hogql_queries.experiment_exposure_query_builder import ExposureSegmentDimension
from products.feature_flags.backend.facade.edits import SplitChange

SAMPLE_RATIO_MISMATCH_P_VALUE = 0.001
SRM_MINIMUM_SAMPLE_SIZE = 100
TOP_SEGMENT_VALUES = 5
_NAMED_SEGMENTS = 3

# pinned: the subcodes are sent as `finding_variant` on the health finding events, so insights group on them.
SPLIT_CHANGED = "split_changed"
SEGMENT_MISMATCH = "segment_mismatch"


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
    """Whether `srm` reports a mismatch that no split change explains, which it then looks for in the segments of the
    exposures. The exposure query loads the segments only then, because their query scans the exposure events."""
    outcome = srm(ctx)
    return isinstance(outcome, ExperimentHealthFinding) and outcome.subcode != SPLIT_CHANGED


def srm(ctx: HealthContext) -> CheckOutcome:
    exposures = ctx.exposures
    if exposures is None:
        return not_applicable(RUNS_AFTER_LAUNCH)
    p_value = exposures.sample_ratio_mismatch_p_value
    if p_value is None:
        # The exposure query compares only the variants with a share of the split that the analysis keeps, so after
        # a variant ships there is nothing to compare however many users are exposed.
        variants_in_split = [
            variant
            for variant in (ctx.flag.variants if ctx.flag else ())
            if variant.key and (variant.rollout_percentage or 0) > 0 and variant.key not in ctx.excluded_variant_keys
        ]
        if len(variants_in_split) < 2:
            return not_applicable("Needs two or more variants in the split")
        return not_applicable("Runs once enough users are exposed")
    if p_value >= SAMPLE_RATIO_MISMATCH_P_VALUE:
        return None
    split_change = _split_change_warning(ctx)
    history = ctx.flag_history
    if split_change is None or not isinstance(history, FlagHistory):
        return _mismatch(exposures, p_value)
    # The warning stays a warning: the users exposed after the change are fewer than those the test covers, so a
    # retest that passes can't rule out a mismatch with another cause. The retest only adds evidence.
    unit = "group" if exposures.counts_groups else "user"
    retest, p_value_after_change = _retest_after_change(ctx, exposures, history, unit)
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.SRM,
        subcode=SPLIT_CHANGED,
        severity=ExperimentHealthFindingSeverity.WARNING,
        title=f"{unit.capitalize()}s are not split as configured after a split change",
        detail=" ".join(
            [
                f"The distribution of {unit}s across variants doesn't match your current rollout percentages "
                f"(p < {SAMPLE_RATIO_MISMATCH_P_VALUE}).",
                f"The variant split changed after launch while {unit}s were exposed, and some of them got their "
                "variants from another split, which can cause this.",
                *retest,
                f'Follow the steps in "{split_change.title}" to fix the results.',
            ]
        ),
        evidence={"p_value": p_value, "p_value_after_split_change": p_value_after_change},
        actions=(),
        diagnostic_ref="A2",
    )


def _retest_after_change(
    ctx: HealthContext, exposures: ExposureTotals, history: FlagHistory, unit: str
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
    changed_on = history.counted(SplitChange)[-1].changed_at.astimezone(ZoneInfo(history.team_timezone)).date()
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


def _split_change_warning(ctx: HealthContext) -> ExperimentHealthFinding | None:
    try:
        outcome = split_changed_mid_run(ctx)
    except Exception as error:
        # The health endpoint reports the failure of the split check itself. Here it must not hide the mismatch.
        capture_exception(error)
        return None
    if isinstance(outcome, ExperimentHealthFinding) and outcome.severity == ExperimentHealthFindingSeverity.WARNING:
        return outcome
    return None


def _mismatch(exposures: ExposureTotals, p_value: float) -> ExperimentHealthFinding:
    unit = "group" if exposures.counts_groups else "user"
    tests = _segment_tests(exposures)
    located = [sentence for dimension in ExposureSegmentDimension for sentence in _located(tests, dimension, unit)]
    cause = (
        [*located, f"Check that the code there sends the exposure for every {unit} in every variant."]
        if located
        else ["This may indicate issues with randomization or data collection."]
    )
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.SRM,
        subcode=SEGMENT_MISMATCH if located else None,
        severity=ExperimentHealthFindingSeverity.WARNING,
        title=f"{unit.capitalize()}s are not split across variants as configured",
        detail=" ".join(
            [
                f"The distribution of {unit}s across variants doesn't match your configured rollout percentages "
                f"(p < {SAMPLE_RATIO_MISMATCH_P_VALUE}).",
                *cause,
            ]
        ),
        evidence={"p_value": p_value, **_segment_evidence(tests)},
        actions=(),
        diagnostic_ref="A2",
    )


@frozen
class _SegmentTest:
    segment: ExposureSegment
    # None when the segment holds too few persons or groups for the test.
    p_value: float | None

    @property
    def mismatched(self) -> bool:
        return self.p_value is not None and self.p_value < SAMPLE_RATIO_MISMATCH_P_VALUE


def _segment_tests(exposures: ExposureTotals) -> list[_SegmentTest]:
    """The sample ratio test of each segment against the split of the whole test, largest segment first."""
    segments = sorted(exposures.segments or (), key=lambda segment: -sum(segment.exposed_by_variant.values()))
    tests = []
    for segment in segments:
        result = sample_ratio_test(segment.exposed_by_variant, exposures.sample_ratio_expected)
        tests.append(_SegmentTest(segment=segment, p_value=result.p_value if result else None))
    return tests


def _located(tests: list[_SegmentTest], dimension: ExposureSegmentDimension, unit: str) -> list[str]:
    """The sentences that name the segments of the dimension with the mismatch. Empty unless other segments of the
    dimension match the split, because a mismatch in every segment doesn't point at one."""
    tested = [test for test in tests if test.segment.dimension == dimension and test.p_value is not None]
    mismatched = [test for test in tested if test.mismatched]
    matched = [test for test in tested if not test.mismatched]
    if not mismatched or not matched:
        return []
    exposed = (
        "whose first exposure was sent by" if dimension == ExposureSegmentDimension.LIBRARY else "first exposed on"
    )
    matched_p_value = f" (p = {matched[0].p_value:.2g})" if len(matched) == 1 else ""
    return [
        f"The mismatch comes from {unit}s {exposed} {_segment_list(mismatched)}.",
        f"{unit.capitalize()}s {exposed} {_segment_list(matched)} match the split{matched_p_value}.",
    ]


def _segment_list(tests: list[_SegmentTest]) -> str:
    names = [_segment_name(test.segment) for test in tests[:_NAMED_SEGMENTS]]
    if len(tests) > _NAMED_SEGMENTS:
        names.append(f"{len(tests) - _NAMED_SEGMENTS} more")
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _segment_name(segment: ExposureSegment) -> str:
    if segment.dimension == ExposureSegmentDimension.LIBRARY:
        if segment.value == BREAKDOWN_OTHER_STRING_LABEL:
            return "other libraries"
        if segment.value == BREAKDOWN_NULL_STRING_LABEL:
            return "an unknown library"
        return f'the "{segment.value}" library'
    if segment.value == BREAKDOWN_OTHER_STRING_LABEL:
        return "other pages"
    if segment.value == BREAKDOWN_NULL_STRING_LABEL:
        return "a page without a path"
    return f"the page {segment.value}"


def _segment_evidence(tests: list[_SegmentTest]) -> dict[str, str | int | float | None]:
    """Each segment in the keys `<dimension>_N` (the value), `<dimension>_N_p_value` and `<dimension>_N_exposed_<variant>`."""
    evidence: dict[str, str | int | float | None] = {}
    for dimension in ExposureSegmentDimension:
        in_dimension = [test for test in tests if test.segment.dimension == dimension]
        for index, test in enumerate(in_dimension, start=1):
            key = f"{dimension.value}_{index}"
            evidence[key] = test.segment.value
            evidence[f"{key}_p_value"] = test.p_value
            for variant, exposed in test.segment.exposed_by_variant.items():
                evidence[f"{key}_exposed_{variant}"] = exposed
    return evidence

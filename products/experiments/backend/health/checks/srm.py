from collections.abc import Mapping
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
)
from products.experiments.backend.health.checks.split_changed import split_changed_mid_run
from products.experiments.backend.health.context import ExposureSegment, ExposureTotals, FlagHistory, HealthContext
from products.experiments.backend.health.skips import RUNS_AFTER_LAUNCH, CheckOutcome, not_applicable
from products.experiments.backend.hogql_queries.experiment_exposure_query_builder import ExposureSegmentDimension
from products.feature_flags.backend.facade.edits import SplitChange

SAMPLE_RATIO_MISMATCH_P_VALUE = 0.001
SRM_MINIMUM_SAMPLE_SIZE = 100
TOP_SEGMENT_VALUES = 5

# pinned: the subcode is sent as `finding_variant` on the health finding events, so insights group on it.
SPLIT_CHANGED = "split_changed"

# pinned: sent as `finding_reason` on the health finding events, so insights group on them.
REASON_LIBRARY_AND_PAGE = "library_and_page"
REASON_UNIFORM = "uniform"


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
    # With an activation, the segments would come from the activation event, not from the flag call that assigned
    # the variant.
    if ctx.exposure_events is not None and ctx.exposure_events.activation is not None:
        return False
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
    verdicts = [_verdict(tests, dimension, exposures.sample_ratio_expected) for dimension in ExposureSegmentDimension]
    cause, reason = _cause(verdicts, unit)
    evidence: dict[str, str | int | float | None] = {"p_value": p_value, **_segment_evidence(tests, verdicts)}
    if reason is not None:
        evidence["reason"] = reason
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.SRM,
        subcode=None,
        severity=ExperimentHealthFindingSeverity.WARNING,
        title=f"{unit.capitalize()}s are not split across variants as configured",
        detail=" ".join(
            [
                f"The distribution of {unit}s across variants doesn't match your configured rollout percentages "
                f"(p < {SAMPLE_RATIO_MISMATCH_P_VALUE}).",
                *cause,
            ]
        ),
        evidence=evidence,
        actions=(),
        diagnostic_ref="A2",
    )


@frozen
class _SegmentTest:
    segment: ExposureSegment
    # None when the segment holds too few persons or groups for the test.
    p_value: float | None


@frozen
class _Verdict:
    dimension: ExposureSegmentDimension
    homogeneity_p_value: float | None
    located: ExposureSegment | None


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
        return _Verdict(dimension=dimension, homogeneity_p_value=None, located=None)
    table = [[test.segment.exposed_by_variant.get(variant, 0) for variant in variants] for test in compared]
    homogeneity_p_value = float(chi2_contingency(table).pvalue)
    if homogeneity_p_value >= SAMPLE_RATIO_MISMATCH_P_VALUE:
        return _Verdict(dimension=dimension, homogeneity_p_value=homogeneity_p_value, located=None)
    failing = [
        test.segment for test in compared if test.p_value is not None and test.p_value < SAMPLE_RATIO_MISMATCH_P_VALUE
    ]
    located = max(failing, key=lambda segment: _distance_from_split(segment, weights), default=None)
    return _Verdict(dimension=dimension, homogeneity_p_value=homogeneity_p_value, located=located)


def _distance_from_split(segment: ExposureSegment, weights: Mapping[str, float]) -> float:
    """The share of the segment's persons or groups that would have to move between variants to match the split."""
    total = sum(segment.exposed_by_variant.get(variant, 0) for variant in weights)
    total_weight = sum(weights.values())
    return (
        sum(
            abs(segment.exposed_by_variant.get(variant, 0) / total - weight / total_weight)
            for variant, weight in weights.items()
        )
        / 2
    )


def _cause(verdicts: list[_Verdict], unit: str) -> tuple[list[str], str | None]:
    """The sentences that follow the mismatch, and the finding's reason."""
    located = [verdict.located for verdict in verdicts if verdict.located is not None]
    if located:
        places = ", and from ".join(f"{unit}s {_segment_place(segment)}" for segment in located)
        return [
            f"The mismatch comes from {places}.",
            f"Check that the code there sends the exposure for every {unit} in every variant.",
        ], REASON_LIBRARY_AND_PAGE if len(located) > 1 else located[0].dimension.value
    compared = {
        verdict.dimension: verdict.homogeneity_p_value
        for verdict in verdicts
        if verdict.homogeneity_p_value is not None
    }
    if compared and all(p_value >= SAMPLE_RATIO_MISMATCH_P_VALUE for p_value in compared.values()):
        across = " and ".join(
            "SDK libraries" if dimension == ExposureSegmentDimension.LIBRARY else "pages" for dimension in compared
        )
        return [
            f"The mismatch looks the same across {across}, which points at how {unit}s get their variants rather "
            "than at one integration."
        ], REASON_UNIFORM
    return ["This may indicate issues with randomization or data collection."], None


def _segment_place(segment: ExposureSegment) -> str:
    if segment.dimension == ExposureSegmentDimension.LIBRARY:
        if segment.value == BREAKDOWN_OTHER_STRING_LABEL:
            return f"whose first exposure was sent by a library other than the {TOP_SEGMENT_VALUES} most common"
        if segment.value == BREAKDOWN_NULL_STRING_LABEL:
            return "whose first exposure was sent by an unknown library"
        return f'whose first exposure was sent by the "{segment.value}" library'
    if segment.value == BREAKDOWN_OTHER_STRING_LABEL:
        return f"first exposed on a page other than the {TOP_SEGMENT_VALUES} most common"
    return f"first exposed on the page {segment.value}"


def _segment_evidence(tests: list[_SegmentTest], verdicts: list[_Verdict]) -> dict[str, str | int | float | None]:
    """Each segment in the keys `<dimension>_N` (the value), `<dimension>_N_p_value` and
    `<dimension>_N_exposed_<variant>`, and each compared dimension in `<dimension>_homogeneity_p_value`."""
    evidence: dict[str, str | int | float | None] = {}
    for verdict in verdicts:
        dimension = verdict.dimension
        if verdict.homogeneity_p_value is not None:
            evidence[f"{dimension.value}_homogeneity_p_value"] = verdict.homogeneity_p_value
        in_dimension = [test for test in tests if test.segment.dimension == dimension]
        for index, test in enumerate(in_dimension, start=1):
            key = f"{dimension.value}_{index}"
            evidence[key] = test.segment.value
            evidence[f"{key}_p_value"] = test.p_value
            for variant, exposed in test.segment.exposed_by_variant.items():
                evidence[f"{key}_exposed_{variant}"] = exposed
    return evidence

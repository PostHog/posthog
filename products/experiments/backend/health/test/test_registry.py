from dataclasses import replace
from typing import Any

from unittest import TestCase
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import MultipleVariantHandling

from products.experiments.backend.facade.contracts import ExperimentHealthFindingCode
from products.experiments.backend.health import registry
from products.experiments.backend.health.checks.bias_risk import bias_risk_multiple_excluded
from products.experiments.backend.health.checks.multiple_variants import multiple_variants_share
from products.experiments.backend.health.context import ExposureTotals, FlagState, FlagVariant, HealthContext
from products.experiments.backend.health.registry import EXPOSURE_HEALTH_CHECKS, evaluate
from products.experiments.backend.health.test.factories import RUNNING_CONTEXT

UNEVEN_SPLIT_TOTALS = ExposureTotals(
    total_exposures={"control": 800, "test": 200, "$multiple": 20},
    multiple_variant_handling=MultipleVariantHandling.EXCLUDE,
    sample_ratio_mismatch_p_value=None,
    hours_since_launch=72,
    counts_groups=False,
)

RUNNING_UNEVEN_SPLIT = replace(
    RUNNING_CONTEXT,
    flag=FlagState(
        active=True,
        deleted=False,
        release_groups=(),
        variants=(
            FlagVariant(key="control", rollout_percentage=80),
            FlagVariant(key="test", rollout_percentage=20),
        ),
        reachable_conditions=(),
    ),
    exposures=UNEVEN_SPLIT_TOTALS,
)

NO_EXPOSURES = replace(UNEVEN_SPLIT_TOTALS, total_exposures={"control": 0, "test": 0})
ENDED: dict[str, Any] = {"is_running": False, "has_ended": True}
EVEN_SPLIT_FLAG = FlagState(
    active=True,
    deleted=False,
    release_groups=(),
    variants=(FlagVariant(key="control", rollout_percentage=50), FlagVariant(key="test", rollout_percentage=50)),
    reachable_conditions=(),
)


def _totals_with_multiple(multiple: int, total: int) -> ExposureTotals:
    single = total - multiple
    return replace(
        UNEVEN_SPLIT_TOTALS,
        total_exposures={"control": single - single // 2, "test": single // 2, "$multiple": multiple},
    )


def _raise(_ctx: HealthContext) -> Any:
    raise ValueError("malformed")


class TestEvaluate(TestCase):
    @parameterized.expand(
        [
            ("bias_risk_on_an_uneven_split", {}, [ExperimentHealthFindingCode.BIAS_RISK_MULTIPLE_EXCLUDED]),
            ("nothing_without_exposure_totals", {"exposures": None}, []),
            ("no_bias_risk_after_the_end", ENDED, []),
            (
                "srm_below_the_threshold",
                {**ENDED, "exposures": replace(UNEVEN_SPLIT_TOTALS, sample_ratio_mismatch_p_value=0.0009)},
                [ExperimentHealthFindingCode.SRM],
            ),
            (
                "no_srm_at_the_threshold",
                {**ENDED, "exposures": replace(UNEVEN_SPLIT_TOTALS, sample_ratio_mismatch_p_value=0.001)},
                [],
            ),
            (
                "zero_exposures_a_day_after_launch",
                {"exposures": replace(NO_EXPOSURES, hours_since_launch=24)},
                [ExperimentHealthFindingCode.ZERO_EXPOSURES],
            ),
            ("no_zero_exposures_in_the_first_day", {"exposures": replace(NO_EXPOSURES, hours_since_launch=23.9)}, []),
            (
                "no_zero_exposures_before_launch",
                {"is_launched": False, "is_running": False, "exposures": NO_EXPOSURES},
                [],
            ),
            (
                "no_zero_exposures_with_only_multiple_variant_users",
                {
                    **ENDED,
                    "exposures": replace(NO_EXPOSURES, total_exposures={"control": 0, "test": 0, "$multiple": 3}),
                },
                [],
            ),
            (
                "multiple_variants_share_on_an_even_split",
                {"flag": EVEN_SPLIT_FLAG, "exposures": _totals_with_multiple(60, 1000)},
                [ExperimentHealthFindingCode.MULTIPLE_VARIANTS_SHARE],
            ),
            (
                "multiple_variants_share_after_the_end",
                {**ENDED, "exposures": _totals_with_multiple(60, 1000)},
                [ExperimentHealthFindingCode.MULTIPLE_VARIANTS_SHARE],
            ),
            ("no_multiple_variants_share_at_the_threshold", {**ENDED, "exposures": _totals_with_multiple(5, 100)}, []),
            ("no_multiple_variants_share_under_5_users", {**ENDED, "exposures": _totals_with_multiple(4, 40)}, []),
            (
                "multiple_variants_share_under_100_exposures",
                {**ENDED, "exposures": _totals_with_multiple(5, 60)},
                [ExperimentHealthFindingCode.MULTIPLE_VARIANTS_SHARE],
            ),
        ]
    )
    def test_exposure_checks(
        self, _name: str, changes: dict[str, Any], expected: list[ExperimentHealthFindingCode]
    ) -> None:
        findings = evaluate(replace(RUNNING_UNEVEN_SPLIT, **changes), EXPOSURE_HEALTH_CHECKS)

        self.assertEqual([finding.code for finding in findings], expected)

    @parameterized.expand(
        [
            ("persons", False, "Many users were exposed to multiple variants"),
            ("groups", True, "Many groups were exposed to multiple variants"),
        ]
    )
    def test_multiple_variants_share_names_the_counted_unit(self, _name: str, counts_groups: bool, title: str) -> None:
        exposures = replace(_totals_with_multiple(60, 1000), counts_groups=counts_groups)
        findings = evaluate(replace(RUNNING_UNEVEN_SPLIT, **ENDED, exposures=exposures), (multiple_variants_share,))

        self.assertEqual([finding.title for finding in findings], [title])

    def test_a_failing_check_does_not_hide_the_other_findings(self) -> None:
        with patch.object(registry, "capture_exception") as capture:
            findings = evaluate(RUNNING_UNEVEN_SPLIT, (_raise, bias_risk_multiple_excluded))

        self.assertEqual(
            [finding.code for finding in findings], [ExperimentHealthFindingCode.BIAS_RISK_MULTIPLE_EXCLUDED]
        )
        capture.assert_called_once()

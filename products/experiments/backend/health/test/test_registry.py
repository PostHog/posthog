from dataclasses import replace
from typing import Any

from unittest import TestCase
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import MultipleVariantHandling

from products.experiments.backend.facade.contracts import ExperimentHealthFindingCode
from products.experiments.backend.health import registry
from products.experiments.backend.health.checks.bias_risk import bias_risk_multiple_excluded
from products.experiments.backend.health.context import ExposureTotals, FlagState, FlagVariant, HealthContext
from products.experiments.backend.health.registry import EXPOSURE_HEALTH_CHECKS, evaluate

UNEVEN_SPLIT_TOTALS = ExposureTotals(
    total_exposures={"control": 800, "test": 200, "$multiple": 20},
    multiple_variant_handling=MultipleVariantHandling.EXCLUDE,
    sample_ratio_mismatch_p_value=None,
    hours_since_launch=72,
)

RUNNING_UNEVEN_SPLIT = HealthContext(
    is_launched=True,
    has_ended=False,
    archived=False,
    flag=FlagState(
        active=True,
        deleted=False,
        release_groups=(),
        variants=(
            FlagVariant(key="control", rollout_percentage=80),
            FlagVariant(key="test", rollout_percentage=20),
        ),
    ),
    primary_metric_count=1,
    secondary_metric_count=0,
    exposures=UNEVEN_SPLIT_TOTALS,
)

NO_EXPOSURES = replace(UNEVEN_SPLIT_TOTALS, total_exposures={"control": 0, "test": 0})


def _raise(_ctx: HealthContext) -> Any:
    raise ValueError("malformed")


class TestEvaluate(TestCase):
    @parameterized.expand(
        [
            ("bias_risk_on_an_uneven_split", {}, [ExperimentHealthFindingCode.BIAS_RISK_MULTIPLE_EXCLUDED]),
            ("nothing_without_exposure_totals", {"exposures": None}, []),
            ("no_bias_risk_after_the_end", {"has_ended": True}, []),
            (
                "srm_below_the_threshold",
                {"has_ended": True, "exposures": replace(UNEVEN_SPLIT_TOTALS, sample_ratio_mismatch_p_value=0.0009)},
                [ExperimentHealthFindingCode.SRM],
            ),
            (
                "no_srm_at_the_threshold",
                {"has_ended": True, "exposures": replace(UNEVEN_SPLIT_TOTALS, sample_ratio_mismatch_p_value=0.001)},
                [],
            ),
            (
                "zero_exposures_a_day_after_launch",
                {"exposures": replace(NO_EXPOSURES, hours_since_launch=24)},
                [ExperimentHealthFindingCode.ZERO_EXPOSURES],
            ),
            ("no_zero_exposures_in_the_first_day", {"exposures": replace(NO_EXPOSURES, hours_since_launch=23.9)}, []),
            ("no_zero_exposures_before_launch", {"is_launched": False, "exposures": NO_EXPOSURES}, []),
            (
                "no_zero_exposures_with_only_multiple_variant_users",
                {
                    "has_ended": True,
                    "exposures": replace(NO_EXPOSURES, total_exposures={"control": 0, "test": 0, "$multiple": 3}),
                },
                [],
            ),
        ]
    )
    def test_exposure_checks(
        self, _name: str, changes: dict[str, Any], expected: list[ExperimentHealthFindingCode]
    ) -> None:
        findings = evaluate(replace(RUNNING_UNEVEN_SPLIT, **changes), EXPOSURE_HEALTH_CHECKS)

        self.assertEqual([finding.code for finding in findings], expected)

    def test_a_failing_check_does_not_hide_the_other_findings(self) -> None:
        with patch.object(registry, "capture_exception") as capture:
            findings = evaluate(RUNNING_UNEVEN_SPLIT, (_raise, bias_risk_multiple_excluded))

        self.assertEqual(
            [finding.code for finding in findings], [ExperimentHealthFindingCode.BIAS_RISK_MULTIPLE_EXCLUDED]
        )
        capture.assert_called_once()

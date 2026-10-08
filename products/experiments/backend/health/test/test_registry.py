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
from products.experiments.backend.health.registry import evaluate

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
    exposures=ExposureTotals(
        total_exposures={"control": 800, "test": 200, "$multiple": 20},
        multiple_variant_handling=MultipleVariantHandling.EXCLUDE,
    ),
)


def _raise(_ctx: HealthContext) -> Any:
    raise ValueError("malformed")


class TestEvaluate(TestCase):
    def test_reports_bias_risk_from_exposure_totals(self) -> None:
        findings = evaluate(RUNNING_UNEVEN_SPLIT)

        self.assertEqual(
            [finding.code for finding in findings], [ExperimentHealthFindingCode.BIAS_RISK_MULTIPLE_EXCLUDED]
        )

    @parameterized.expand(
        [
            ("without_exposure_totals", {"exposures": None}),
            ("after_the_end", {"has_ended": True}),
        ]
    )
    def test_no_bias_risk_finding(self, _name: str, changes: dict[str, Any]) -> None:
        codes = [finding.code for finding in evaluate(replace(RUNNING_UNEVEN_SPLIT, **changes))]

        self.assertNotIn(ExperimentHealthFindingCode.BIAS_RISK_MULTIPLE_EXCLUDED, codes)

    def test_a_failing_check_does_not_hide_the_other_findings(self) -> None:
        checks = (_raise, bias_risk_multiple_excluded)
        with patch.object(registry, "HEALTH_CHECKS", checks), patch.object(registry, "capture_exception") as capture:
            findings = evaluate(RUNNING_UNEVEN_SPLIT)

        self.assertEqual(
            [finding.code for finding in findings], [ExperimentHealthFindingCode.BIAS_RISK_MULTIPLE_EXCLUDED]
        )
        capture.assert_called_once()

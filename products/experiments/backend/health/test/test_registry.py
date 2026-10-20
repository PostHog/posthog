from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from unittest import TestCase
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import MultipleVariantHandling

from products.experiments.backend.facade.contracts import (
    ExperimentHealthCheckKey,
    ExperimentHealthCheckStatus,
    ExperimentHealthFindingCode,
)
from products.experiments.backend.health import registry
from products.experiments.backend.health.context import (
    ExposureTotals,
    FlagHistoryNotCheckedReason,
    FlagState,
    FlagVariant,
    HealthContext,
)
from products.experiments.backend.health.registry import (
    EXPERIMENT_HEALTH_CHECKS,
    EXPOSURE_HEALTH_CHECKS,
    HealthCheck,
    evaluate,
)
from products.experiments.backend.health.test.factories import DRAFT, RUNNING_CONTEXT, flag_history

UNEVEN_SPLIT_TOTALS = ExposureTotals(
    total_exposures={"control": 800, "test": 200, "$multiple": 20},
    multiple_variant_handling=MultipleVariantHandling.EXCLUDE,
    sample_ratio_mismatch_p_value=None,
    hours_since_launch=72,
)

UNEVEN_FLAG = FlagState(
    active=True,
    deleted=False,
    release_groups=(),
    variants=(
        FlagVariant(key="control", rollout_percentage=80),
        FlagVariant(key="test", rollout_percentage=20),
    ),
    reachable_conditions=(),
)

RUNNING_UNEVEN_SPLIT = replace(RUNNING_CONTEXT, flag=UNEVEN_FLAG, exposures=UNEVEN_SPLIT_TOTALS)

NO_EXPOSURES = replace(UNEVEN_SPLIT_TOTALS, total_exposures={"control": 0, "test": 0})
ENDED: dict[str, Any] = {"is_running": False, "has_ended": True}
LAUNCHED_AT = datetime(2026, 10, 1, tzinfo=UTC)

Key = ExperimentHealthCheckKey
Status = ExperimentHealthCheckStatus
NOT_LOOKED = (Status.NOT_APPLICABLE, Status.NOT_CHECKED)
FLAG_CHANGE_KEYS = (Key.SPLIT_CHANGED_MID_RUN, Key.BUCKETING_CHANGED_MID_RUN, Key.RELEASE_CONDITIONS_CHANGED_MID_RUN)


def _raise(_ctx: HealthContext) -> Any:
    raise ValueError("malformed")


FAILING_CHECK = HealthCheck(key=Key.FLAG_STATE, name="Failing", find=_raise, skip=lambda _ctx: None)


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
        ]
    )
    def test_exposure_checks(
        self, _name: str, changes: dict[str, Any], expected: list[ExperimentHealthFindingCode]
    ) -> None:
        health = evaluate(replace(RUNNING_UNEVEN_SPLIT, **changes), EXPOSURE_HEALTH_CHECKS)

        self.assertEqual([finding.code for finding in health.findings], expected)

    @parameterized.expand(
        [
            (
                "a_draft_is_not_checked_for_what_needs_a_launch",
                {**DRAFT, "flag": replace(UNEVEN_FLAG, active=False), "exposures": None},
                {
                    Key.FLAG_STATE: Status.PASSED,
                    Key.FLAG_VARIANTS_MISMATCH: Status.PASSED,
                    Key.FLAG_HISTORY: Status.NOT_APPLICABLE,
                    **dict.fromkeys(FLAG_CHANGE_KEYS, Status.NOT_APPLICABLE),
                    Key.NO_METRIC: Status.NOT_APPLICABLE,
                    Key.ZERO_EXPOSURES: Status.NOT_APPLICABLE,
                    Key.SRM: Status.NOT_APPLICABLE,
                },
            ),
            (
                "flag_changes_are_not_checked_without_the_history",
                {
                    "flag_history": flag_history(
                        [], launched_at=LAUNCHED_AT, not_checked=FlagHistoryNotCheckedReason.NO_HISTORY_ACCESS
                    )
                },
                {Key.FLAG_HISTORY: Status.FINDING, **dict.fromkeys(FLAG_CHANGE_KEYS, Status.NOT_CHECKED)},
            ),
            (
                "flag_changes_pass_with_a_history_without_changes",
                {"flag_history": flag_history([], launched_at=LAUNCHED_AT)},
                {Key.FLAG_HISTORY: Status.PASSED, **dict.fromkeys(FLAG_CHANGE_KEYS, Status.PASSED)},
            ),
            (
                "zero_exposures_is_not_checked_in_the_first_day",
                {"exposures": replace(NO_EXPOSURES, hours_since_launch=23.9)},
                {Key.ZERO_EXPOSURES: Status.NOT_APPLICABLE, Key.SRM: Status.NOT_APPLICABLE},
            ),
            (
                "zero_exposures_finds_a_day_after_launch",
                {"exposures": replace(NO_EXPOSURES, hours_since_launch=24)},
                {Key.ZERO_EXPOSURES: Status.FINDING},
            ),
        ]
    )
    def test_check_statuses(self, _name: str, changes: dict[str, Any], expected: dict[Key, Status]) -> None:
        health = evaluate(
            replace(RUNNING_UNEVEN_SPLIT, **changes), (*EXPERIMENT_HEALTH_CHECKS, *EXPOSURE_HEALTH_CHECKS)
        )

        statuses = {check.key: check.status for check in health.checks}
        self.assertEqual({key: statuses[key] for key in expected}, expected)
        self.assertEqual(
            [check.key for check in health.checks if (check.reason is None) == (check.status in NOT_LOOKED)], []
        )

    def test_a_failing_check_does_not_hide_the_other_findings(self) -> None:
        with patch.object(registry, "capture_exception") as capture:
            health = evaluate(RUNNING_UNEVEN_SPLIT, (FAILING_CHECK, *EXPOSURE_HEALTH_CHECKS))

        self.assertEqual(
            [finding.code for finding in health.findings], [ExperimentHealthFindingCode.BIAS_RISK_MULTIPLE_EXCLUDED]
        )
        self.assertEqual(health.checks[0].status, Status.NOT_CHECKED)
        capture.assert_called_once()

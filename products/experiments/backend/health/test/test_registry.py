from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from unittest import TestCase
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import MultipleVariantHandling, PropertyOperator

from products.experiments.backend.facade.contracts import (
    ExperimentHealthCheckKey,
    ExperimentHealthCheckStatus,
    ExperimentHealthFindingCode,
)
from products.experiments.backend.health import registry
from products.experiments.backend.health.context import (
    ExposureEvents,
    ExposureTotals,
    FlagHistoryNotCheckedReason,
    FlagKeyFilter,
    FlagState,
    HealthContext,
    MetricEvents,
)
from products.experiments.backend.health.registry import (
    EXPERIMENT_HEALTH_CHECKS,
    EXPOSURE_HEALTH_CHECKS,
    HealthCheck,
    evaluate,
)
from products.experiments.backend.health.test.factories import DRAFT, RUNNING_CONTEXT, flag_history
from products.feature_flags.backend.facade.edits import FlagVariant

UNEVEN_SPLIT_TOTALS = ExposureTotals(
    total_exposures={"control": 800, "test": 200, "$multiple": 20},
    multiple_variant_handling=MultipleVariantHandling.EXCLUDE,
    sample_ratio_mismatch_p_value=None,
    hours_since_launch=72,
    counts_groups=False,
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
EVENT_KEYS = (Key.METRIC_EVENT_NOT_INGESTED, Key.EXPOSURE_CRITERIA_CANNOT_MATCH)


def _events(name: str, received: dict[str, bool]) -> dict[str, Any]:
    return {
        "metric_events": (MetricEvents(name="Metric", role="primary", events=(name,)),),
        "exposure_events": ExposureEvents(
            custom_event=name, required_flag_key=None, variant_property="$feature/flag", flag_key_filters=()
        ),
        "events_received": received,
    }


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


MULTIPLE_VARIANTS_CHECK = next(check for check in EXPOSURE_HEALTH_CHECKS if check.key == Key.MULTIPLE_VARIANTS_SHARE)
FAILING_CHECK = HealthCheck(key=Key.FLAG_STATE, name="Failing", run=_raise)


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
                    Key.METRIC_EVENT_NOT_INGESTED: Status.NOT_APPLICABLE,
                    Key.EXPOSURE_CRITERIA_CANNOT_MATCH: Status.PASSED,
                    Key.ZERO_EXPOSURES: Status.NOT_APPLICABLE,
                    Key.SRM: Status.NOT_APPLICABLE,
                    Key.MULTIPLE_VARIANTS_SHARE: Status.NOT_APPLICABLE,
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
                "multiple_variants_are_not_counted_under_first_seen",
                {
                    "exposures": replace(
                        _totals_with_multiple(60, 1000), multiple_variant_handling=MultipleVariantHandling.FIRST_SEEN
                    )
                },
                {Key.MULTIPLE_VARIANTS_SHARE: Status.NOT_CHECKED, Key.BIAS_RISK_MULTIPLE_EXCLUDED: Status.PASSED},
            ),
            (
                "flag_traffic_is_left_to_zero_exposures_after_launch",
                {"flag_called": False},
                {Key.NEW_FLAG_NO_TRAFFIC: Status.NOT_APPLICABLE},
            ),
            (
                "early_significance_needs_the_primary_metrics_results",
                {"primary_metric": None},
                {Key.EARLY_SIGNIFICANCE: Status.NOT_CHECKED},
            ),
            (
                "zero_exposures_finds_a_day_after_launch",
                {"exposures": replace(NO_EXPOSURES, hours_since_launch=24)},
                {Key.ZERO_EXPOSURES: Status.FINDING},
            ),
            (
                "events_not_received_are_not_reported_after_the_end",
                {**ENDED, **_events("purchase", {"purchase": False})},
                dict.fromkeys(EVENT_KEYS, Status.NOT_APPLICABLE),
            ),
            (
                "event_names_that_get_no_definition_are_not_checked",
                _events("$$plugin_metrics", {}),
                dict.fromkeys(EVENT_KEYS, Status.NOT_CHECKED),
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

    @parameterized.expand(
        [
            ("too_few_exposures", UNEVEN_FLAG, "Runs once enough users are exposed"),
            (
                "one_variant_in_the_split_after_a_ship",
                replace(
                    UNEVEN_FLAG,
                    variants=(
                        FlagVariant(key="control", rollout_percentage=0),
                        FlagVariant(key="test", rollout_percentage=100),
                    ),
                ),
                "Needs two or more variants in the split",
            ),
        ]
    )
    def test_srm_says_why_it_did_not_run(self, _name: str, flag: FlagState, reason: str) -> None:
        health = evaluate(replace(RUNNING_UNEVEN_SPLIT, flag=flag), EXPOSURE_HEALTH_CHECKS)

        srm = next(check for check in health.checks if check.key == Key.SRM)
        self.assertEqual((srm.status, srm.reason), (Status.NOT_APPLICABLE, reason))

    @parameterized.expand(
        [
            ("persons", False, "Many users were exposed to multiple variants"),
            ("groups", True, "Many groups were exposed to multiple variants"),
        ]
    )
    def test_multiple_variants_share_names_the_counted_unit(self, _name: str, counts_groups: bool, title: str) -> None:
        exposures = replace(_totals_with_multiple(60, 1000), counts_groups=counts_groups)
        health = evaluate(replace(RUNNING_UNEVEN_SPLIT, **ENDED, exposures=exposures), (MULTIPLE_VARIANTS_CHECK,))

        self.assertEqual([finding.title for finding in health.findings], [title])

    @parameterized.expand(
        [
            (
                "exposure_event_never_received",
                _events("checkout_viewed", {"checkout_viewed": False}),
                ExperimentHealthFindingCode.EXPOSURE_CRITERIA_CANNOT_MATCH,
            ),
            (
                "filter_on_another_flag",
                {
                    "exposure_events": ExposureEvents(
                        custom_event=None,
                        required_flag_key="checkout-test",
                        variant_property="$feature_flag_response",
                        flag_key_filters=(FlagKeyFilter(operator=PropertyOperator.EXACT, values=("pricing-test",)),),
                    )
                },
                ExperimentHealthFindingCode.EXPOSURE_CRITERIA_CANNOT_MATCH,
            ),
            (
                "exposure_event_never_received_after_the_end",
                {**_events("checkout_viewed", {"checkout_viewed": False}), **ENDED},
                ExperimentHealthFindingCode.ZERO_EXPOSURES,
            ),
            (
                "exposure_event_received",
                _events("checkout_viewed", {"checkout_viewed": True}),
                ExperimentHealthFindingCode.ZERO_EXPOSURES,
            ),
        ]
    )
    def test_one_check_reports_an_experiment_without_exposures(
        self, _name: str, changes: dict[str, Any], expected: ExperimentHealthFindingCode
    ) -> None:
        ctx = replace(RUNNING_CONTEXT, flag=EVEN_SPLIT_FLAG, exposures=replace(NO_EXPOSURES, hours_since_launch=48))

        health = evaluate(replace(ctx, **changes), (*EXPERIMENT_HEALTH_CHECKS, *EXPOSURE_HEALTH_CHECKS))

        reporting = {finding.code for finding in health.findings} & {
            ExperimentHealthFindingCode.ZERO_EXPOSURES,
            ExperimentHealthFindingCode.EXPOSURE_CRITERIA_CANNOT_MATCH,
        }
        zero_exposures = next(check for check in health.checks if check.key == Key.ZERO_EXPOSURES)
        self.assertEqual(
            (reporting, zero_exposures.status),
            (
                {expected},
                Status.FINDING if expected == ExperimentHealthFindingCode.ZERO_EXPOSURES else Status.NOT_APPLICABLE,
            ),
        )

    def test_a_failing_check_does_not_hide_the_other_findings(self) -> None:
        with patch.object(registry, "capture_exception") as capture:
            health = evaluate(RUNNING_UNEVEN_SPLIT, (FAILING_CHECK, *EXPOSURE_HEALTH_CHECKS))

        self.assertEqual(
            [finding.code for finding in health.findings], [ExperimentHealthFindingCode.BIAS_RISK_MULTIPLE_EXCLUDED]
        )
        self.assertEqual(health.checks[0].status, Status.NOT_CHECKED)
        capture.assert_called_once()

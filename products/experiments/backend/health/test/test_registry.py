from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from unittest import TestCase
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import MultipleVariantHandling, PropertyOperator

from products.experiments.backend.facade.contracts import (
    ExperimentHealthCheckKey,
    ExperimentHealthCheckStatus,
    ExperimentHealthFindingCode,
    ExperimentHealthValueKey,
)
from products.experiments.backend.health import registry
from products.experiments.backend.health.checks.filtered_exposures import reads_share_kept_by_test_account_filter
from products.experiments.backend.health.context import (
    ExposureEvents,
    ExposureTotals,
    FlagHistoryNotCheckedReason,
    FlagKeyFilter,
    FlagReleaseGroup,
    FlagState,
    HealthContext,
    LatestCalculation,
    MetricEvents,
    MetricWindow,
    ReachableCondition,
)
from products.experiments.backend.health.registry import (
    EXPERIMENT_HEALTH_CHECKS,
    EXPOSURE_HEALTH_CHECKS,
    HealthCheck,
    evaluate,
)
from products.experiments.backend.health.test.factories import DRAFT, RUNNING_CONTEXT, flag_history
from products.experiments.backend.hogql_queries.experiment_exposures_query_runner import ExperimentExposuresQueryRunner
from products.feature_flags.backend.facade.edits import FlagVariant

UNEVEN_SPLIT_TOTALS = ExposureTotals(
    total_exposures={"control": 800, "test": 200, "$multiple": 20},
    multiple_variant_handling=MultipleVariantHandling.EXCLUDE,
    sample_ratio_mismatch_p_value=None,
    sample_ratio_expected={},
    daily_exposures={},
    hours_since_launch=72,
    counts_groups=False,
    filters_test_accounts=False,
    has_positive_test_account_filter=False,
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
Value = ExperimentHealthValueKey
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


def _filtered_totals(counted: int, exposed_without_filter: int | None) -> ExposureTotals:
    return replace(
        UNEVEN_SPLIT_TOTALS,
        total_exposures={"control": counted - counted // 2, "test": counted // 2},
        filters_test_accounts=True,
        has_positive_test_account_filter=True,
        exposed_without_test_account_filter=exposed_without_filter,
    )


def _raise(_ctx: HealthContext) -> Any:
    raise ValueError("malformed")


UNSERVED_CONTROL_FLAG = replace(
    UNEVEN_FLAG,
    variants=(FlagVariant(key="control", rollout_percentage=0), FlagVariant(key="test", rollout_percentage=100)),
    reachable_conditions=(ReachableCondition(number=1, pinned_variant=None, variant_property=None),),
    saved_at=LAUNCHED_AT,
)
UNSERVED_CONTROL_TOTALS = replace(
    UNEVEN_SPLIT_TOTALS, daily_exposures={"control": {date(2026, 10, 3): 30}, "test": {date(2026, 10, 3): 70}}
)

MULTIPLE_VARIANTS_CHECK = next(check for check in EXPOSURE_HEALTH_CHECKS if check.key == Key.MULTIPLE_VARIANTS_SHARE)
FAILING_CHECK = HealthCheck(key=Key.FLAG_STATE, name="Failing", description="Fails.", run=_raise)


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
            (
                "test_account_filter_keeps_4_percent",
                {"exposures": _filtered_totals(40, 1000)},
                [ExperimentHealthFindingCode.TEST_ACCOUNT_FILTER_REMOVES_EXPOSURES],
            ),
            (
                "test_account_filter_keeps_9_percent_after_the_end",
                {**ENDED, "exposures": _filtered_totals(90, 1000)},
                [ExperimentHealthFindingCode.TEST_ACCOUNT_FILTER_REMOVES_EXPOSURES],
            ),
            ("test_account_filter_keeps_95_percent", {"exposures": _filtered_totals(950, 1000)}, []),
            ("test_account_filter_under_100_users_without_it", {"exposures": _filtered_totals(4, 99)}, []),
            (
                "test_account_filter_keeps_nobody",
                {"exposures": _filtered_totals(0, 1000)},
                [ExperimentHealthFindingCode.ZERO_EXPOSURES],
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
                        [], start_date=LAUNCHED_AT, not_checked=FlagHistoryNotCheckedReason.NO_HISTORY_ACCESS
                    )
                },
                {Key.FLAG_HISTORY: Status.FINDING, **dict.fromkeys(FLAG_CHANGE_KEYS, Status.NOT_CHECKED)},
            ),
            (
                "flag_changes_pass_with_a_history_without_changes",
                {"flag_history": flag_history([], start_date=LAUNCHED_AT)},
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
                {
                    Key.MULTIPLE_VARIANTS_SHARE: Status.NOT_CHECKED,
                    Key.BIAS_RISK_MULTIPLE_EXCLUDED: Status.NOT_APPLICABLE,
                },
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
                "metrics_not_matured_needs_the_primary_metric_windows",
                {"only_count_matured_users": True},
                {Key.METRICS_NOT_MATURED: Status.NOT_CHECKED},
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
            (
                "test_account_filter_waits_for_enough_exposures",
                {"exposures": _filtered_totals(5, 60)},
                {Key.TEST_ACCOUNT_FILTER_REMOVES_EXPOSURES: Status.NOT_APPLICABLE},
            ),
            (
                "bias_risk_does_not_apply_to_an_even_split",
                {"flag": EVEN_SPLIT_FLAG},
                {Key.BIAS_RISK_MULTIPLE_EXCLUDED: Status.NOT_APPLICABLE},
            ),
            (
                "bias_risk_waits_for_exposures",
                {"exposures": NO_EXPOSURES},
                {Key.BIAS_RISK_MULTIPLE_EXCLUDED: Status.NOT_APPLICABLE},
            ),
            (
                "bias_risk_does_not_apply_when_the_split_assigns_nobody",
                {
                    "flag": replace(
                        UNEVEN_FLAG,
                        reachable_conditions=(
                            ReachableCondition(number=1, pinned_variant="test", variant_property=None),
                        ),
                    ),
                    "exposures": _totals_with_multiple(60, 1000),
                },
                {Key.BIAS_RISK_MULTIPLE_EXCLUDED: Status.NOT_APPLICABLE},
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
        self.assertEqual(
            sorted(finding.check for finding in health.findings if finding.check),
            sorted(check.key for check in health.checks if check.status == Status.FINDING),
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
                "The split now serves one variant, so the split of the run isn't tested",
            ),
            (
                "a_flag_with_one_variant",
                replace(UNEVEN_FLAG, variants=(FlagVariant(key="test", rollout_percentage=100),)),
                "Needs two or more variants in the split",
                {"test": 500},
            ),
        ]
    )
    def test_srm_says_why_it_did_not_run(
        self, _name: str, flag: FlagState, reason: str, total_exposures: dict[str, int] | None = None
    ) -> None:
        exposures = UNEVEN_SPLIT_TOTALS
        if total_exposures is not None:
            exposures = replace(exposures, total_exposures=total_exposures)
        health = evaluate(replace(RUNNING_UNEVEN_SPLIT, flag=flag, exposures=exposures), EXPOSURE_HEALTH_CHECKS)

        srm = next(check for check in health.checks if check.key == Key.SRM)
        self.assertEqual((srm.status, srm.reason), (Status.NOT_APPLICABLE, reason))

    @parameterized.expand(
        [
            ("few_counted_a_day_after_launch", {}, True),
            ("1000_counted", {"total_exposures": {"control": 500, "test": 500}}, False),
            ("in_the_first_day", {"hours_since_launch": 23.9}, False),
            ("none_counted", {"total_exposures": {"control": 0, "test": 0}}, False),
            ("filter_off", {"filters_test_accounts": False}, False),
            ("no_positive_filter", {"has_positive_test_account_filter": False}, False),
            ("precomputed_exposures", {"reads_precomputed_exposures": True}, False),
        ]
    )
    def test_the_count_without_the_test_account_filter_runs_only_on_few_exposures(
        self, _name: str, changes: dict[str, Any], counts: bool
    ) -> None:
        ctx = replace(RUNNING_UNEVEN_SPLIT, exposures=replace(_filtered_totals(40, None), **changes))

        health = evaluate(ctx, EXPOSURE_HEALTH_CHECKS)

        status = next(check.status for check in health.checks if check.key == Key.TEST_ACCOUNT_FILTER_REMOVES_EXPOSURES)
        self.assertEqual(
            (reads_share_kept_by_test_account_filter(ctx), status),
            (counts, Status.NOT_CHECKED if counts else Status.NOT_APPLICABLE),
        )

    @parameterized.expand([("one_decimal", 40, 1000, "(4.0%)"), ("under_a_tenth", 1, 20_000, "(less than 0.1%)")])
    def test_test_account_filter_finding_states_the_kept_share(
        self, _name: str, counted: int, exposed: int, share: str
    ) -> None:
        ctx = replace(RUNNING_UNEVEN_SPLIT, exposures=_filtered_totals(counted, exposed))

        health = evaluate(ctx, EXPOSURE_HEALTH_CHECKS)

        finding = next(
            f for f in health.findings if f.code == ExperimentHealthFindingCode.TEST_ACCOUNT_FILTER_REMOVES_EXPOSURES
        )
        self.assertIn(share, finding.detail)

    @parameterized.expand(
        [
            (
                "srm_compares_the_variants_without_multiple",
                Key.SRM,
                {"exposures": replace(UNEVEN_SPLIT_TOTALS, sample_ratio_mismatch_p_value=0.71)},
                Status.PASSED,
                {Value.P_VALUE: 0.71, Value.COMPARED_COUNT: 1000, Value.MULTIPLE_VARIANT_COUNT: 20},
            ),
            (
                "srm_leaves_out_the_multiple_count_under_first_seen",
                Key.SRM,
                {
                    "exposures": replace(
                        UNEVEN_SPLIT_TOTALS,
                        total_exposures={"control": 800, "test": 200},
                        multiple_variant_handling=MultipleVariantHandling.FIRST_SEEN,
                        sample_ratio_mismatch_p_value=0.71,
                    )
                },
                Status.PASSED,
                {Value.P_VALUE: 0.71, Value.COMPARED_COUNT: 1000},
            ),
            (
                "bias_risk_divides_by_every_exposure",
                Key.BIAS_RISK_MULTIPLE_EXCLUDED,
                {},
                Status.FINDING,
                {
                    Value.EXPOSED_COUNT: 1020,
                    Value.MULTIPLE_VARIANT_COUNT: 20,
                    Value.MULTIPLE_VARIANT_PERCENTAGE: 20 / 1020 * 100,
                    Value.MULTIPLE_VARIANT_HANDLING: "exclude",
                },
            ),
            (
                "multiple_variants_share",
                Key.MULTIPLE_VARIANTS_SHARE,
                {"exposures": _totals_with_multiple(30, 1000)},
                Status.PASSED,
                {
                    Value.EXPOSED_COUNT: 1000,
                    Value.MULTIPLE_VARIANT_COUNT: 30,
                    Value.MULTIPLE_VARIANT_PERCENTAGE: 3.0,
                    Value.MULTIPLE_VARIANT_HANDLING: "exclude",
                },
            ),
            (
                "multiple_variants_are_not_counted_under_first_seen",
                Key.MULTIPLE_VARIANTS_SHARE,
                {
                    "exposures": replace(
                        _totals_with_multiple(30, 1000), multiple_variant_handling=MultipleVariantHandling.FIRST_SEEN
                    )
                },
                Status.NOT_CHECKED,
                {Value.EXPOSED_COUNT: 1000, Value.MULTIPLE_VARIANT_HANDLING: "first_seen"},
            ),
            (
                "kept_share",
                Key.TEST_ACCOUNT_FILTER_REMOVES_EXPOSURES,
                {"exposures": _filtered_totals(400, 1000)},
                Status.PASSED,
                {
                    Value.EXPOSED_COUNT: 400,
                    Value.EXPOSED_WITHOUT_TEST_ACCOUNT_FILTER_COUNT: 1000,
                    Value.KEPT_BY_TEST_ACCOUNT_FILTER_PERCENTAGE: 40.0,
                },
            ),
            (
                "kept_share_without_the_count_without_the_filter",
                Key.TEST_ACCOUNT_FILTER_REMOVES_EXPOSURES,
                {"exposures": _filtered_totals(400, None)},
                Status.NOT_CHECKED,
                {Value.EXPOSED_COUNT: 400},
            ),
            (
                "zero_exposures_in_the_first_day",
                Key.ZERO_EXPOSURES,
                {"exposures": replace(NO_EXPOSURES, hours_since_launch=23.94)},
                Status.NOT_APPLICABLE,
                {Value.EXPOSED_COUNT: 0, Value.SINCE_LAUNCH_HOURS: 23.9},
            ),
            (
                "metrics_not_matured_with_the_setting_off",
                Key.METRICS_NOT_MATURED,
                {},
                Status.NOT_APPLICABLE,
                {Value.ONLY_COUNT_MATURED_USERS: False},
            ),
            (
                "metrics_not_matured_counts_the_metrics_without_users",
                Key.METRICS_NOT_MATURED,
                {
                    "only_count_matured_users": True,
                    "primary_metric_windows": (
                        MetricWindow(name="Day", window_seconds=86_400, first_users_count_at=LAUNCHED_AT),
                        MetricWindow(name="Week", window_seconds=7 * 86_400, first_users_count_at=LAUNCHED_AT),
                    ),
                },
                Status.PASSED,
                {Value.ONLY_COUNT_MATURED_USERS: True, Value.PRIMARY_METRIC_COUNT: 2, Value.WAITING_METRIC_COUNT: 1},
            ),
            (
                "metric_calculation",
                Key.METRIC_CALCULATION_FAILED,
                {
                    "latest_calculation": LatestCalculation(
                        metric_count=3,
                        finished_at=datetime(2026, 10, 2, 12, tzinfo=ZoneInfo("Europe/Berlin")),
                        failures=(),
                        completed_count=3,
                        completed_exposures_paths=frozenset(),
                    )
                },
                Status.PASSED,
                {
                    Value.METRIC_COUNT: 3,
                    Value.COMPLETED_METRIC_COUNT: 3,
                    Value.FAILED_METRIC_COUNT: 0,
                    Value.CALCULATED_AT: "2026-10-02T10:00:00+00:00",
                },
            ),
            (
                "flag_state_names_a_shipped_variant",
                Key.FLAG_STATE,
                {
                    "flag": replace(
                        UNEVEN_FLAG,
                        release_groups=(FlagReleaseGroup(rollout_percentage=100, property_count=0),),
                        variants=(
                            FlagVariant(key="control", rollout_percentage=0),
                            FlagVariant(key="test", rollout_percentage=100),
                        ),
                    )
                },
                Status.FINDING,
                {
                    Value.FLAG_ACTIVE: True,
                    Value.FLAG_DELETED: False,
                    Value.FLAG_ROLLED_OUT: True,
                    Value.SHIPPED_VARIANT: "test",
                },
            ),
            (
                "unserved_variants_read_the_users_first_exposed_after_the_save",
                Key.UNSERVED_VARIANT_EXPOSURES,
                {"flag": UNSERVED_CONTROL_FLAG, "exposures": UNSERVED_CONTROL_TOTALS},
                Status.FINDING,
                {Value.UNSERVED_EXPOSED_COUNT: 30, Value.UNSERVED_EXPOSED_PERCENTAGE: 30.0},
            ),
            (
                "unserved_variants_read_nothing_when_they_dont_judge",
                Key.UNSERVED_VARIANT_EXPOSURES,
                {"flag": UNSERVED_CONTROL_FLAG, "exposures": UNSERVED_CONTROL_TOTALS, **ENDED},
                Status.NOT_APPLICABLE,
                {},
            ),
            (
                "stale_experiment_reads_when_the_daily_calculation_ends",
                Key.STALE_EXPERIMENT,
                {"hours_since_start": 72, "daily_calculation_ends_at": datetime(2026, 11, 30, 9, 0, tzinfo=UTC)},
                Status.PASSED,
                {Value.SINCE_START_HOURS: 72, Value.DAILY_CALCULATION_ENDS_AT: "2026-11-30T09:00:00+00:00"},
            ),
            (
                "new_flag_reads_its_last_call_before_launch",
                Key.NEW_FLAG_NO_TRAFFIC,
                {**DRAFT, "flag_called": True, "flag_last_called_at": datetime(2026, 11, 11, 10, 42, tzinfo=UTC)},
                Status.PASSED,
                {Value.FLAG_LAST_CALLED_AT: "2026-11-11T10:42:00+00:00"},
            ),
        ]
    )
    def test_a_check_reports_what_it_read(
        self, _name: str, key: Key, changes: dict[str, Any], status: Status, values: dict[Value, Any]
    ) -> None:
        health = evaluate(
            replace(RUNNING_UNEVEN_SPLIT, **changes), (*EXPERIMENT_HEALTH_CHECKS, *EXPOSURE_HEALTH_CHECKS)
        )

        check = next(check for check in health.checks if check.key == key)
        self.assertEqual((check.status, dict(check.values)), (status, values))

    @parameterized.expand(
        [
            (Key.SRM, {"exposures": replace(UNEVEN_SPLIT_TOTALS, sample_ratio_mismatch_p_value=0.71)}),
            (Key.BIAS_RISK_MULTIPLE_EXCLUDED, {"exposures": _totals_with_multiple(30, 1000)}),
            (Key.MULTIPLE_VARIANTS_SHARE, {"exposures": _totals_with_multiple(30, 1000)}),
            (Key.TEST_ACCOUNT_FILTER_REMOVES_EXPOSURES, {"exposures": _filtered_totals(400, 1000)}),
            (Key.ZERO_EXPOSURES, {}),
            (Key.UNSERVED_VARIANT_EXPOSURES, {"flag": UNSERVED_CONTROL_FLAG}),
            (Key.STALE_EXPERIMENT, {}),
        ]
    )
    def test_a_rule_names_values_that_its_check_reads(self, key: Key, changes: dict[str, Any]) -> None:
        health = evaluate(
            replace(RUNNING_UNEVEN_SPLIT, **changes), (*EXPERIMENT_HEALTH_CHECKS, *EXPOSURE_HEALTH_CHECKS)
        )

        check = next(check for check in health.checks if check.key == key)
        assert check.rule is not None
        rule_keys = {check.rule.value, *([check.rule.minimum.value] if check.rule.minimum else [])}
        self.assertEqual(rule_keys - check.values.keys(), set(), (check.status, check.values))

    @parameterized.expand([(check.key.value, check) for check in EXPOSURE_HEALTH_CHECKS if check.rule])
    def test_an_exposure_rule_converts_to_the_exposure_schema(self, _name: str, check: HealthCheck) -> None:
        assert check.rule is not None

        rule = ExperimentExposuresQueryRunner._health_check_rule(check.rule)

        self.assertEqual(rule.value.value, check.rule.value.value)

    def test_a_failing_read_keeps_the_status(self) -> None:
        check = replace(MULTIPLE_VARIANTS_CHECK, read=_raise)

        with patch.object(registry, "capture_exception") as capture:
            health = evaluate(replace(RUNNING_UNEVEN_SPLIT, exposures=_totals_with_multiple(60, 1000)), (check,))

        self.assertEqual(
            (health.checks[0].status, dict(health.checks[0].values), len(health.findings)), (Status.FINDING, {}, 1)
        )
        capture.assert_called_once()

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

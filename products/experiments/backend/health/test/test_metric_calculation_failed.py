from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest import TestCase

from django.utils import timezone

from parameterized import parameterized

from posthog.exceptions import ClickHouseClusterMemoryLimitExceeded
from posthog.models.scoping import team_scope

from products.experiments.backend.facade.api import get_experiment_health
from products.experiments.backend.facade.contracts import (
    ExperimentHealth,
    ExperimentHealthCheckKey,
    ExperimentHealthCheckStatus,
    ExperimentHealthFinding,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
    ExperimentHealthMetricCompileErrorKind,
    ExperimentHealthReaderAccess,
)
from products.experiments.backend.facade.enums import ExposuresPath
from products.experiments.backend.health.checks.metric_calculation_failed import metric_calculation_failed
from products.experiments.backend.health.context import (
    ExposureFilterSource,
    ExposureFilterWithoutColumn,
    LatestCalculation,
    MetricCalculationFailure,
    MetricCompileFailure,
    MetricCompiles,
)
from products.experiments.backend.health.skips import CheckSkip
from products.experiments.backend.health.test.factories import ENDED, RUNNING_CONTEXT
from products.experiments.backend.metric_calculation.config import get_metric_calculation_config
from products.experiments.backend.metric_calculation.results import MetricResultStore
from products.experiments.backend.models.experiment import Experiment, ExperimentMetricsRecalculation
from products.feature_flags.backend.models.feature_flag import FeatureFlag

CODE = ExperimentHealthFindingCode.METRIC_CALCULATION_FAILED
KEY = ExperimentHealthCheckKey.METRIC_CALCULATION_FAILED
WARNING = ExperimentHealthFindingSeverity.WARNING
INFO = ExperimentHealthFindingSeverity.INFO
NO_QUERIES = ExperimentHealthReaderAccess(
    can_read_flag_history=False, can_query_events=False, denied_event_properties=frozenset()
)
FINISHED_AT = datetime(2026, 10, 26, 9, 30, tzinfo=UTC)
OUT_OF_MEMORY = "This query ran out of memory before it could finish."
PLAN_FILTER = ExposureFilterWithoutColumn(type="group", key="plan", source=ExposureFilterSource.EXPOSURE_CRITERIA)
DIRECT = ExposuresPath.DIRECT_SCAN
PRECOMPUTED = ExposuresPath.PRECOMPUTED
NO_CAUSE = (None, 'primary metric "Revenue" failed. Its query needed more memory than PostHog allows for one')
CLICKHOUSE_MESSAGE = (
    "Code: 215. DB::Exception: Column `properties` is not under aggregate function and not in GROUP BY keys. "
    "In query SELECT properties FROM events"
)


def _failure(
    message: str,
    *,
    error_type: str | None,
    step: str | None = "calculation",
    role: str = "primary",
    retriable: bool = True,
    can_quote_evaluation_rules: bool = False,
    exposures_path: ExposuresPath | None = None,
) -> MetricCalculationFailure:
    return MetricCalculationFailure(
        metric_id=f"{role}-metric",
        name="Revenue",
        role="primary" if role == "primary" else "secondary",
        error_type=error_type,
        step=step,
        message=message,
        can_quote_evaluation_rules=can_quote_evaluation_rules,
        retriable=retriable,
        definition={"kind": "ExperimentMetric", "metric_type": "mean"},
        exposures_path=exposures_path,
    )


def _limited(exposures_path: ExposuresPath | None, role: str = "primary") -> MetricCalculationFailure:
    return _failure(OUT_OF_MEMORY, error_type="out_of_memory", role=role, exposures_path=exposures_path)


def _outcome(
    *failures: MetricCalculationFailure, completed: tuple[ExposuresPath | None, ...] = (), **changes: Any
) -> ExperimentHealthFinding | CheckSkip | None:
    calculation = LatestCalculation(
        metric_count=len(failures) + len(completed),
        finished_at=FINISHED_AT,
        failures=failures,
        completed_count=len(completed),
        completed_exposures_paths=frozenset(path for path in completed if path is not None),
    )
    return metric_calculation_failed(replace(RUNNING_CONTEXT, latest_calculation=calculation, **changes))


def _mean(uuid: str) -> dict[str, Any]:
    return {
        "kind": "ExperimentMetric",
        "metric_type": "mean",
        "uuid": uuid,
        "name": f"Metric {uuid}",
        "source": {"kind": "EventsNode", "event": "purchase"},
    }


class TestMetricCalculationFailed(TestCase):
    @parameterized.expand(
        [
            (
                "busy",
                _failure("Queries are a little too busy right now.", error_type="rate_limited"),
                {},
                ("busy", INFO, None, "PostHog was too busy"),
            ),
            (
                "busy_after_the_end_with_a_retry",
                _failure("Queries are a little too busy right now.", error_type="rate_limited"),
                ENDED,
                ("busy", INFO, None, "Try again in a few minutes."),
            ),
            (
                "busy_after_the_end_without_a_retry",
                _failure("Queries are a little too busy right now.", error_type=None, retriable=False),
                ENDED,
                ("busy", INFO, None, "Contact support to calculate it again."),
            ),
            (
                "cluster_out_of_memory",
                _failure(str(ClickHouseClusterMemoryLimitExceeded()), error_type="out_of_memory", retriable=False),
                {},
                ("busy", INFO, None, "PostHog was too busy"),
            ),
            (
                "read_limit_stored_as_a_builder_message",
                _failure(
                    "[ErrorDetail(string='Limit for rows or bytes to read exceeded, max bytes: 2.00 GiB, current "
                    "bytes: 2.10 GiB', code='invalid')]",
                    error_type="validation_error",
                ),
                {},
                ("query_limit", WARNING, "read_limit", "needed to read more data than PostHog allows"),
            ),
            (
                "memory_limit_stored_without_a_class",
                _failure("This query ran out of memory before it could finish.", error_type=None),
                {},
                ("query_limit", WARNING, "memory_limit", "needed more memory than PostHog allows for one calculation"),
            ),
            (
                "query_too_long",
                _failure("Query size exceeded.", error_type="server_error"),
                {},
                ("query_limit", WARNING, "query_size", "A filter with a long list of values"),
            ),
            (
                "socket_timeout",
                _failure(
                    "Code: 209. DB::NetException: Timeout exceeded while reading from socket (10.0.0.1:9000, 300000 ms)",
                    error_type="timeout",
                ),
                {},
                ("busy", INFO, None, "PostHog was too busy"),
            ),
            (
                "builder_message",
                _failure(
                    "[ErrorDetail(string='Data warehouse metric properties cannot contain aggregate functions; "
                    "reference a column or a per-row expression instead.', code='invalid')]",
                    error_type="validation_error",
                ),
                {},
                ("settings", WARNING, "rejected", "Data warehouse metric properties cannot contain aggregate"),
            ),
            (
                "builder_message_without_exposures",
                _failure(
                    "[ErrorDetail(string=\"No exposures for the 'control' variant yet. Results can be calculated "
                    "once it has data.\", code='no_data')]",
                    error_type="validation_error",
                ),
                {},
                ("not_enough_data", INFO, None, "No exposures for the 'control' variant yet."),
            ),
            (
                "not_enough_data_after_the_end",
                _failure("No control variant found", error_type=None),
                ENDED,
                ("not_enough_data", INFO, None, "before the experiment ended"),
            ),
            (
                "error_of_posthog_stored_as_a_validation_error",
                _failure(
                    "[ErrorDetail(string='Unable to retrieve experiment data. Please try refreshing the page.', "
                    "code='invalid')]",
                    error_type=None,
                ),
                {},
                ("unexpected_error", INFO, None, "unexpected error"),
            ),
            (
                "deleted_cohort",
                _failure("Cohort matching query does not exist.", error_type="server_error"),
                {},
                ("settings", WARNING, "deleted_cohort", "uses a cohort that doesn't exist anymore"),
            ),
            (
                "type_mismatch",
                _failure("DB::Exception: There is no supertype for types String, Float64", error_type="server_error"),
                {},
                ("settings", WARNING, "type_mismatch", "compares values of different types"),
            ),
            (
                "clickhouse_message",
                _failure(CLICKHOUSE_MESSAGE, error_type="validation_error"),
                {},
                ("settings", WARNING, "other", "A setting of the metric makes its query fail."),
            ),
            (
                "hogql_message_that_can_quote_evaluation_rules",
                _failure(
                    "Invalid behavioral property filter", error_type="validation_error", can_quote_evaluation_rules=True
                ),
                {},
                ("settings", WARNING, "other", "A setting of the metric makes its query fail."),
            ),
            (
                "metric_unknown_to_the_run",
                _failure("Metric m not found in experiment 1", error_type="validation_error", step="discovery"),
                {},
                ("unexpected_error", INFO, None, "unexpected error"),
            ),
            (
                "error_of_posthog_stored_without_a_class",
                _failure("Decimal overflow while executing query.", error_type=None),
                {},
                ("unexpected_error", INFO, None, "Try again, and contact support"),
            ),
            (
                "experiment_too_old",
                _failure("This experiment started too long ago.", error_type="recalculation_window_too_long"),
                {},
                ("experiment_too_old", WARNING, None, "move the start date closer to today"),
            ),
            (
                "secondary_metric_only",
                _failure("Query has hit the max execution time.", error_type="timeout", role="secondary"),
                {},
                ("query_limit", INFO, "time_limit", 'the secondary metric "Revenue"'),
            ),
            (
                "primary_metric_after_the_end",
                _failure("Query has hit the max execution time.", error_type="timeout"),
                ENDED,
                ("query_limit", WARNING, "time_limit", "took longer"),
            ),
        ]
    )
    def test_words_why_the_latest_calculation_failed(
        self,
        _name: str,
        failure: MetricCalculationFailure,
        status: dict[str, Any],
        expected: tuple[str, ExperimentHealthFindingSeverity, str | None, str],
    ) -> None:
        finding = _outcome(failure, **status)

        assert isinstance(finding, ExperimentHealthFinding)
        subcode, severity, error, words = expected
        self.assertEqual(
            (finding.subcode, finding.severity, finding.evidence["metric_1_error"]), (subcode, severity, error)
        )
        self.assertIn(words, finding.detail)
        self.assertNotIn("DB::Exception", finding.detail + str(finding.evidence))

    def test_a_metric_that_needs_a_fix_leads_and_sets_the_severity(self) -> None:
        finding = _outcome(
            _failure("Queries are a little too busy right now.", error_type="rate_limited"),
            _failure("Limit for rows or bytes to read exceeded", error_type="byte_limit", role="secondary"),
            replace(_failure("Query has hit the max execution time.", error_type="timeout"), metric_id="third"),
        )

        assert isinstance(finding, ExperimentHealthFinding)
        self.assertEqual(
            (finding.subcode, finding.severity, finding.title, finding.evidence["calculated_at"]),
            ("query_limit", WARNING, "Latest calculation failed for 3 metrics", FINISHED_AT.isoformat()),
        )
        self.assertEqual(
            [finding.evidence[f"metric_{number}_failure"] for number in (1, 2, 3)],
            ["query_limit", "busy", "query_limit"],
        )

    @parameterized.expand(
        [
            (
                "exposure_query_does_not_compile",
                "Cohort 7 does not exist",
                "validation_error",
                True,
                ("settings", "exposure_query", "can't be built into a query"),
            ),
            (
                "experiment_too_old",
                "This experiment started too long ago.",
                "recalculation_window_too_long",
                False,
                ("experiment_too_old", None, "started too long ago"),
            ),
        ]
    )
    def test_words_a_failure_of_the_experiment_once(
        self,
        _name: str,
        message: str,
        error_type: str,
        exposure_query_fails: bool,
        expected: tuple[str, str | None, str],
    ) -> None:
        compiles = MetricCompiles(
            metric_count=2, failures=(), unknown_count=0, no_access_count=0, exposure_query_fails=exposure_query_fails
        )

        finding = _outcome(
            _failure(message, error_type=error_type),
            _failure(message, error_type=error_type, role="secondary"),
            metric_compiles=compiles,
        )

        assert isinstance(finding, ExperimentHealthFinding)
        subcode, error, words = expected
        self.assertEqual(
            (finding.subcode, finding.severity, finding.evidence["metric_1_error"], finding.evidence["metric_2_error"]),
            (subcode, WARNING, error, error),
        )
        self.assertEqual(finding.detail.count(words), 1)
        self.assertNotIn("Revenue", finding.detail)

    @parameterized.expand(
        [
            (
                "every_metric_read_the_events_and_reached_a_limit",
                (_limited(DIRECT), _limited(DIRECT, "secondary")),
                (),
                (PLAN_FILTER,),
                ("exposure_criteria", 'filter on the group property "plan", which makes each query read all group'),
            ),
            (
                "the_only_metric_read_the_events_and_reached_a_limit",
                (_limited(DIRECT),),
                (),
                (PLAN_FILTER,),
                (
                    "exposure_criteria",
                    'primary metric "Revenue" failed. Its query needed more memory than PostHog allows for one '
                    'calculation. The likely cause is the exposure criteria\'s filter on the group property "plan"',
                ),
            ),
            (
                "two_limits_and_two_filters_of_different_kinds",
                (
                    _limited(DIRECT),
                    _failure(
                        "Limit for rows or bytes to read exceeded",
                        error_type="byte_limit",
                        role="secondary",
                        exposures_path=DIRECT,
                    ),
                ),
                (),
                (
                    PLAN_FILTER,
                    ExposureFilterWithoutColumn(type="event", key="$device", source=ExposureFilterSource.TEST_ACCOUNTS),
                ),
                (
                    "exposure_criteria",
                    "Every metric's query needed more resources than PostHog allows for one calculation. The likely "
                    'cause is the exposure criteria\'s filter on the group property "plan" and the test account filter '
                    'on the event property "$device", which make each query read all group and event properties. '
                    "Change these filters, or turn off the test account filter in the exposure criteria, or contact",
                ),
            ),
            (
                "the_filter_is_in_the_exposure_action",
                (_limited(DIRECT),),
                (),
                (
                    ExposureFilterWithoutColumn(
                        type="event", key="campaign", source=ExposureFilterSource.EXPOSURE_ACTION
                    ),
                ),
                (
                    "exposure_criteria",
                    'The likely cause is the exposure action\'s filter on the event property "campaign", which makes '
                    "the query read all event properties. Remove or change the filter, or contact support for help.",
                ),
            ),
            (
                "one_property_in_the_exposure_criteria_and_the_test_account_filters",
                (_limited(DIRECT),),
                (),
                (
                    ExposureFilterWithoutColumn(
                        type="event", key="plan", source=ExposureFilterSource.EXPOSURE_CRITERIA
                    ),
                    ExposureFilterWithoutColumn(type="event", key="plan", source=ExposureFilterSource.TEST_ACCOUNTS),
                ),
                (
                    "exposure_criteria",
                    'the exposure criteria\'s filter on the event property "plan" and the test account filter on the '
                    'event property "plan", which make the query read all event properties. Change these filters, or '
                    "turn off the test account filter in the exposure criteria",
                ),
            ),
            (
                "one_query_read_precomputed_exposures",
                (_limited(DIRECT), _limited(PRECOMPUTED, "secondary")),
                (),
                (PLAN_FILTER,),
                NO_CAUSE,
            ),
            (
                "every_query_read_precomputed_exposures",
                (_limited(PRECOMPUTED), _limited(PRECOMPUTED, "secondary")),
                (),
                (PLAN_FILTER,),
                NO_CAUSE,
            ),
            (
                "failures_do_not_say_where_they_read",
                (_limited(None), _limited(None, "secondary")),
                (),
                (PLAN_FILTER,),
                NO_CAUSE,
            ),
            ("no_filter_reads_all_the_properties", (_limited(DIRECT), _limited(DIRECT, "secondary")), (), (), NO_CAUSE),
            ("filters_could_not_be_read", (_limited(DIRECT), _limited(DIRECT, "secondary")), (), None, NO_CAUSE),
            (
                "a_metric_ran_out_of_the_workflow_time_without_a_stored_read",
                (_limited(DIRECT), _limited(None, "secondary")),
                (),
                (PLAN_FILTER,),
                ("exposure_criteria", 'filter on the group property "plan", which makes each query read all group'),
            ),
            (
                "another_metric_failed_for_another_reason",
                (
                    _limited(DIRECT),
                    _failure(
                        "Queries are a little too busy right now.",
                        error_type="rate_limited",
                        role="secondary",
                        exposures_path=DIRECT,
                    ),
                ),
                (),
                (PLAN_FILTER,),
                NO_CAUSE,
            ),
            (
                "another_metric_completed_the_same_read_of_the_events",
                (_limited(DIRECT),),
                (DIRECT,),
                (PLAN_FILTER,),
                ("metric", "while another metric of the experiment returned results. Simplify this metric"),
            ),
            (
                "another_metric_completed_the_same_read_of_precomputed_exposures",
                (_limited(PRECOMPUTED),),
                (PRECOMPUTED,),
                None,
                ("metric", "while another metric of the experiment returned results. Simplify this metric"),
            ),
            (
                "completed_metric_read_the_exposures_another_way",
                (_limited(DIRECT),),
                (PRECOMPUTED,),
                (PLAN_FILTER,),
                NO_CAUSE,
            ),
            ("completed_result_does_not_say_where_it_read", (_limited(DIRECT),), (None,), (PLAN_FILTER,), NO_CAUSE),
            ("failure_does_not_say_where_it_read", (_limited(None),), (DIRECT,), (PLAN_FILTER,), NO_CAUSE),
        ]
    )
    def test_names_the_cause_of_a_query_limit(
        self,
        _name: str,
        failures: tuple[MetricCalculationFailure, ...],
        completed: tuple[ExposuresPath | None, ...],
        filters: tuple[ExposureFilterWithoutColumn, ...] | None,
        expected: tuple[str | None, str],
    ) -> None:
        finding = _outcome(*failures, completed=completed, exposure_filters_without_column=filters)

        assert isinstance(finding, ExperimentHealthFinding)
        reason, words = expected
        self.assertEqual((finding.subcode, finding.severity, finding.reason), ("query_limit", WARNING, reason))
        self.assertEqual(finding.detail.count(words), 1)
        names_the_filters = reason == "exposure_criteria"
        self.assertEqual("properties" in finding.evidence, names_the_filters)
        self.assertEqual(bool(finding.actions), names_the_filters)

    def test_waits_for_a_metric_that_the_experiment_calculates(self) -> None:
        calculation = LatestCalculation(
            metric_count=0, finished_at=None, failures=(), completed_count=0, completed_exposures_paths=frozenset()
        )

        outcome = metric_calculation_failed(
            replace(RUNNING_CONTEXT, latest_calculation=calculation, primary_metric_count=0, secondary_metric_count=0)
        )

        self.assertEqual(
            outcome,
            CheckSkip(
                status=ExperimentHealthCheckStatus.NOT_APPLICABLE, reason="Runs once the experiment has a metric"
            ),
        )

    def test_leaves_a_metric_whose_query_does_not_compile_to_that_check(self) -> None:
        compiles = MetricCompiles(
            metric_count=1,
            failures=(
                MetricCompileFailure(
                    metric_id="primary-metric",
                    name="Revenue",
                    role="primary",
                    kind=ExperimentHealthMetricCompileErrorKind.QUERY,
                    message="Unable to resolve field: revenue",
                    definition={},
                ),
            ),
            unknown_count=0,
            no_access_count=0,
            exposure_query_fails=False,
        )

        outcome = _outcome(
            _failure("Unable to resolve field: revenue", error_type="validation_error"), metric_compiles=compiles
        )

        self.assertEqual(
            outcome,
            CheckSkip(
                status=ExperimentHealthCheckStatus.NOT_APPLICABLE,
                reason='Reported under "Invalid metric definitions"',
            ),
        )


class TestMetricCalculationFailedFromStoredRuns(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="checkout-test",
            created_by=self.user,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                },
            },
        )
        self.experiment = Experiment.objects.create(
            team=self.team,
            name="Checkout",
            feature_flag=flag,
            start_date=timezone.now() - timedelta(days=3),
            metrics=[_mean("primary"), _mean("rejected")],
            metrics_secondary=[_mean("secondary")],
        )

    def _run(
        self,
        *,
        status: str,
        created_at: datetime,
        metric_errors: dict[str, dict[str, Any]] | None = None,
        failed_rows: tuple[str, ...] = (),
        completed_rows: tuple[str, ...] = (),
        completed_read_precomputed: bool = False,
    ) -> None:
        with team_scope(self.team.id):
            query_to = created_at + timedelta(minutes=1)
            run = ExperimentMetricsRecalculation.objects.create(
                team=self.team,
                experiment=self.experiment,
                status=ExperimentMetricsRecalculation.Status.IN_PROGRESS,
                metric_uuids=["primary", "rejected", "secondary"],
                query_to=query_to,
            )
            store = MetricResultStore(experiment_id=self.experiment.id)
            for metric_uuid in failed_rows + completed_rows:
                calculation_config = get_metric_calculation_config(self.experiment, metric_uuid)
                assert calculation_config is not None
                query_from = self.experiment.start_date
                assert query_from is not None
                if metric_uuid in failed_rows:
                    store.record_run_failure(
                        str(run.id),
                        calculation_config,
                        window=query_to,
                        query_from=query_from,
                        error_message="Unable to resolve field: purchase. Did you mean: purchase_total?",
                        query_id=None,
                    )
                else:
                    store.record_run_result(
                        str(run.id),
                        calculation_config,
                        window=query_to,
                        query_from=query_from,
                        result={"variant_results": [], "is_precomputed": completed_read_precomputed},
                        query_id=None,
                    )
            terminal = status in (
                ExperimentMetricsRecalculation.Status.COMPLETED,
                ExperimentMetricsRecalculation.Status.FAILED,
            )
            ExperimentMetricsRecalculation.objects.filter(id=run.id).update(
                status=status,
                created_at=created_at,
                completed_at=query_to if terminal else None,
                metric_errors=metric_errors or {},
            )

    def _health(self) -> ExperimentHealth:
        return get_experiment_health(
            team_id=self.team.id, experiment_id=self.experiment.id, reader_access=NO_QUERIES, user=self.user
        )

    def test_reports_the_failures_that_the_results_page_shows(self) -> None:
        self._run(
            status=ExperimentMetricsRecalculation.Status.FAILED,
            created_at=timezone.now() - timedelta(hours=2),
            metric_errors={
                "primary": {"step": "calculation", "message": "Queries are too busy.", "error_type": "rate_limited"},
                # A rejected run keeps the earlier results, so its error doesn't show on a metric that has one.
                "rejected": {"step": "request", "message": "Too old.", "error_type": "recalculation_window_too_long"},
                "removed": {"step": "calculation", "message": "Query timed out", "error_type": "timeout"},
            },
            failed_rows=("secondary",),
            completed_rows=("rejected",),
        )

        [finding] = [finding for finding in self._health().findings if finding.code == CODE]

        self.assertEqual(
            [(finding.evidence[f"metric_{n}"], finding.evidence[f"metric_{n}_failure"]) for n in (1, 2)],
            [("Metric primary", "busy"), ("Metric secondary", "settings")],
        )
        self.assertNotIn("metric_3", finding.evidence)
        self.assertNotIn("purchase_total", finding.detail + str(finding.evidence))
        self.assertIsNone(finding.evidence["metric_2_message"])

    @parameterized.expand(
        [
            (
                "every_metric_read_the_events",
                (),
                "direct_scan",
                False,
                ("exposure_criteria", 'filter on the group property "plan"'),
            ),
            (
                "other_metrics_completed_the_same_read",
                ("rejected", "secondary"),
                "direct_scan",
                False,
                ("metric", "while other metrics of the experiment returned results"),
            ),
            (
                "other_metrics_read_precomputed_exposures",
                ("rejected", "secondary"),
                "direct_scan",
                True,
                (None, "read more data than PostHog allows for one calculation"),
            ),
            (
                "failures_stored_without_their_read",
                (),
                None,
                False,
                (None, "read more data than PostHog allows for one calculation"),
            ),
        ]
    )
    def test_names_the_cause_of_a_query_limit_from_the_stored_run(
        self,
        _name: str,
        completed_rows: tuple[str, ...],
        exposures_path: str | None,
        completed_read_precomputed: bool,
        expected: tuple[str | None, str],
    ) -> None:
        self.experiment.exposure_criteria = {
            "exposure_config": {
                "kind": "ExperimentEventExposureConfig",
                "event": "$feature_flag_called",
                "properties": [
                    {"key": "plan", "type": "group", "group_type_index": 0, "operator": "exact", "value": ["pro"]}
                ],
            }
        }
        self.experiment.save()
        read_limit = {
            "step": "calculation",
            "message": "Query read too much data",
            "error_type": "byte_limit",
            "exposures_path": exposures_path,
        }
        self._run(
            status=ExperimentMetricsRecalculation.Status.FAILED,
            created_at=timezone.now() - timedelta(hours=2),
            metric_errors={
                uuid: read_limit for uuid in ("primary", "rejected", "secondary") if uuid not in completed_rows
            },
            completed_rows=completed_rows,
            completed_read_precomputed=completed_read_precomputed,
        )

        [finding] = [finding for finding in self._health().findings if finding.code == CODE]

        reason, words = expected
        self.assertEqual(finding.reason, reason)
        self.assertIn(words, finding.detail)

    @parameterized.expand(
        [
            ("no_finished_calculation", None, ExperimentHealthCheckStatus.NOT_APPLICABLE),
            (
                "later_calculation_completed",
                ExperimentMetricsRecalculation.Status.COMPLETED,
                ExperimentHealthCheckStatus.PASSED,
            ),
            (
                "later_calculation_still_running",
                ExperimentMetricsRecalculation.Status.IN_PROGRESS,
                ExperimentHealthCheckStatus.FINDING,
            ),
        ]
    )
    def test_reads_the_latest_finished_calculation(
        self, _name: str, later_status: str | None, expected: ExperimentHealthCheckStatus
    ) -> None:
        now = timezone.now()
        if later_status is not None:
            self._run(
                status=ExperimentMetricsRecalculation.Status.FAILED,
                created_at=now - timedelta(hours=5),
                metric_errors={
                    "primary": {"step": "calculation", "message": "Query timed out", "error_type": "timeout"}
                },
            )
            self._run(status=later_status, created_at=now - timedelta(hours=1), completed_rows=("primary",))

        statuses = {check.key: check.status for check in self._health().checks}

        self.assertEqual(statuses[KEY], expected)

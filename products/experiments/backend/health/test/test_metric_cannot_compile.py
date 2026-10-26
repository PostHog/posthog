from contextlib import nullcontext
from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.utils import timezone

from parameterized import parameterized

from posthog.hogql.errors import InternalHogQLError

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership

from products.access_control.backend.models.access_control import AccessControl
from products.experiments.backend.facade.api import get_experiment_health
from products.experiments.backend.facade.contracts import (
    ExperimentHealth,
    ExperimentHealthCheckKey,
    ExperimentHealthCheckStatus,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
    ExperimentHealthReaderAccess,
)
from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable

NO_QUERIES = ExperimentHealthReaderAccess(
    can_read_flag_history=False, can_query_events=False, denied_event_properties=frozenset()
)
CODE = ExperimentHealthFindingCode.METRIC_CANNOT_COMPILE
KEY = ExperimentHealthCheckKey.METRIC_CANNOT_COMPILE
WARNING = ExperimentHealthFindingSeverity.WARNING
INFO = ExperimentHealthFindingSeverity.INFO
NOT_CHECKED = ExperimentHealthCheckStatus.NOT_CHECKED
NOT_APPLICABLE = ExperimentHealthCheckStatus.NOT_APPLICABLE
COMPOUND = "sum(properties.revenue) / count()"


def _events(**fields: Any) -> dict[str, Any]:
    return {"kind": "EventsNode", "event": "purchase", **fields}


def _hogql(expression: str) -> dict[str, Any]:
    return _events(math="hogql", math_hogql=expression)


def _mean(source: dict[str, Any], **fields: Any) -> dict[str, Any]:
    return {
        "kind": "ExperimentMetric",
        "metric_type": "mean",
        "uuid": "m",
        "name": "Revenue",
        "source": source,
        **fields,
    }


def _cohort(cohort_id: int) -> dict[str, Any]:
    return {"key": "id", "type": "cohort", "value": cohort_id}


def _warehouse_sum(table_name: str) -> dict[str, Any]:
    return _mean(
        {
            "kind": "ExperimentDataWarehouseNode",
            "table_name": table_name,
            "timestamp_field": "created",
            "events_join_key": "person.properties.email",
            "data_warehouse_join_key": "email",
            "math": "sum",
            "math_property": "amount",
        }
    )


class TestMetricCannotCompile(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.flag = FeatureFlag.objects.create(
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

    def _experiment(self, **fields: Any) -> Experiment:
        return Experiment.objects.create(team=self.team, name="Checkout", feature_flag=self.flag, **fields)

    def _health(self, experiment: Experiment) -> ExperimentHealth:
        return get_experiment_health(
            team_id=self.team.id, experiment_id=experiment.id, reader_access=NO_QUERIES, user=self.user
        )

    @parameterized.expand(
        [
            ("compiles", "metrics", _mean(_hogql("sum(toFloat(properties.revenue))")), None),
            (
                "compound_aggregation",
                "metrics",
                _mean(_hogql(COMPOUND)),
                ("compound_aggregation", WARNING, "use a ratio metric"),
            ),
            (
                "aggregation_with_a_condition",
                "metrics",
                _mean(_hogql("uniqIf(person_id, properties.plan = 'pro')")),
                ("aggregation_arguments", WARNING, "Use uniq, and set the condition as a filter"),
            ),
            (
                "function_arguments",
                "metrics",
                _mean(_hogql("sum(round(properties.revenue, 1, 2))")),
                ("function_arguments", WARNING, "calls round with 3 arguments, and round takes at most 2"),
            ),
            (
                "unknown_function",
                "metrics",
                _mean(_hogql("sum(toFlot(properties.revenue))")),
                ("unknown_function", WARNING, "Did you mean toFloat?"),
            ),
            (
                "field_outside_properties",
                "metrics",
                _mean(_hogql("sum(order_total)")),
                ("unknown_field", WARNING, "If order_total is an event property, write properties.order_total."),
            ),
            (
                "syntax_error",
                "metrics",
                _mean(_hogql("sum(properties.revenue NOT)")),
                ("syntax_error", WARNING, "has a syntax error"),
            ),
            (
                "deleted_cohort_in_a_funnel_step",
                "metrics",
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "funnel",
                    "uuid": "f",
                    "name": "Checkout funnel",
                    "series": [_events(properties=[_cohort(999999)])],
                },
                ("deleted_cohort", WARNING, "(ID 999999)"),
            ),
            (
                "lookahead_regex",
                "metrics",
                _mean(
                    _events(
                        properties=[{"key": "$current_url", "type": "event", "operator": "regex", "value": "^/a(?!b)"}]
                    )
                ),
                ("invalid_regex", WARNING, '"^/a(?!b)"'),
            ),
            (
                "element_selector_operator",
                "metrics",
                _mean(
                    _events(
                        properties=[{"key": "selector", "type": "element", "operator": "icontains", "value": "button"}]
                    )
                ),
                ("unsupported_element_operator", WARNING, "on the element's CSS selector"),
            ),
            (
                "behavioral_filter_without_a_time_range",
                "metrics",
                _mean(
                    _events(
                        properties=[
                            {
                                "key": "$pageview",
                                "type": "behavioral",
                                "value": "performed_event",
                                "event_type": "events",
                            }
                        ]
                    )
                ),
                ("incomplete_behavioral_filter", WARNING, "behavioral filter of the metric is incomplete"),
            ),
            (
                "missing_warehouse_table",
                "metrics",
                _mean(
                    {
                        "kind": "ExperimentDataWarehouseNode",
                        "table_name": "stripe_charges",
                        "timestamp_field": "created",
                        "events_join_key": "person.properties.email",
                        "data_warehouse_join_key": "email",
                        "math": "sum",
                        "math_property": "amount",
                    }
                ),
                ("missing_warehouse_table", WARNING, '"stripe_charges"'),
            ),
            (
                "rejected_by_the_builder",
                "metrics",
                _mean(_events(), breakdownFilter={"breakdowns": [{"type": "element", "property": "tag_name"}]}),
                ("rejected", WARNING, "Element breakdowns are not supported"),
            ),
            (
                "stored_definition_the_schema_rejects",
                "metrics",
                _mean(_events(math="median_of_sums")),
                ("invalid_definition", WARNING, "source"),
            ),
            (
                "secondary_metric_only",
                "metrics_secondary",
                _mean(_hogql(COMPOUND)),
                ("compound_aggregation", INFO, 'the secondary metric "Revenue"'),
            ),
            (
                "primary_metric_after_the_end",
                "metrics",
                _mean(_hogql(COMPOUND)),
                ("compound_aggregation", INFO, 'the primary metric "Revenue"'),
                {"start_date": timezone.now() - timedelta(days=10), "end_date": timezone.now() - timedelta(days=1)},
            ),
        ]
    )
    def test_words_why_a_metric_cannot_be_calculated(
        self,
        _name: str,
        field: str,
        metric: dict[str, Any],
        expected: tuple[str, ExperimentHealthFindingSeverity, str] | None,
        fields: dict[str, Any] | None = None,
    ) -> None:
        health = self._health(self._experiment(**{field: [metric]}, **(fields or {})))

        findings = [finding for finding in health.findings if finding.code == CODE]
        if expected is None:
            self.assertEqual(findings, [])
            self.assertEqual(
                {check.key: check.status for check in health.checks}[KEY], ExperimentHealthCheckStatus.PASSED
            )
            return
        subcode, severity, words = expected
        [finding] = findings
        self.assertEqual(
            (finding.subcode, finding.severity, finding.evidence["metric_1_error"]), (subcode, severity, subcode)
        )
        self.assertIn(words, finding.detail)

    def test_a_metric_with_evaluation_markers_shows_no_compiler_message(self) -> None:
        health = self._health(self._experiment(metrics=[_mean(_hogql("sum(aiEvaluationPassed())"))]))

        [finding] = [finding for finding in health.findings if finding.code == CODE]
        self.assertEqual(
            (finding.subcode, finding.detail, finding.evidence["metric_1_message"]),
            (
                "other",
                "PostHog can't calculate the primary metric \"Revenue\". Building its query fails. Check the metric's "
                "settings, or contact support if they look right.",
                None,
            ),
        )

    @parameterized.expand(
        [
            (
                "exposure_criteria_that_do_not_compile",
                {
                    "metrics": [_mean(_events())],
                    "exposure_criteria": {
                        "exposure_config": {
                            "kind": "ExperimentEventExposureConfig",
                            "event": "checkout_viewed",
                            "properties": [_cohort(999999)],
                        }
                    },
                },
                None,
                (NOT_CHECKED, "Couldn't check because the exposure criteria can't be built into a query"),
            ),
            (
                "error_of_the_compiler_itself",
                {"metrics": [_mean(_hogql(COMPOUND))]},
                InternalHogQLError("Unexpected node"),
                (NOT_CHECKED, "Couldn't check 1 metric"),
            ),
            (
                "legacy_metrics_only",
                {"metrics": [{"kind": "ExperimentTrendsQuery"}]},
                None,
                (NOT_APPLICABLE, "Runs once the experiment has a metric in the current format"),
            ),
        ]
    )
    def test_does_not_blame_the_metric_for_what_it_did_not_cause(
        self,
        _name: str,
        fields: dict[str, Any],
        compile_error: Exception | None,
        expected: tuple[ExperimentHealthCheckStatus, str],
    ) -> None:
        with (
            patch.object(ExperimentQueryRunner, "compile_query", side_effect=compile_error)
            if compile_error
            else nullcontext()
        ):
            health = self._health(self._experiment(**fields))

        self.assertNotIn(CODE, [finding.code for finding in health.findings])
        [check] = [check for check in health.checks if check.key == KEY]
        self.assertEqual((check.status, check.reason), expected)

    @parameterized.expand(
        [
            (
                "table_the_reader_may_not_query",
                "stripe_charges",
                True,
                (NOT_CHECKED, "Couldn't check 1 metric that reads data you don't have access to"),
            ),
            (
                "suggestion_for_a_reader_who_may_query_the_table",
                "stripe_charge",
                False,
                (ExperimentHealthCheckStatus.FINDING, "Unknown table `stripe_charge`. Did you mean: stripe_charges?"),
            ),
            (
                "no_suggestion_of_a_table_the_reader_may_not_query",
                "stripe_charge",
                True,
                (ExperimentHealthCheckStatus.FINDING, "Unknown table `stripe_charge`."),
            ),
        ]
    )
    # The flag `hogql-warehouse-access-control` turns on warehouse access control.
    @patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
    def test_compiles_with_the_readers_warehouse_access(
        self, _name: str, table_name: str, denied: bool, expected: tuple[ExperimentHealthCheckStatus, str]
    ) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).update(
            level=OrganizationMembership.Level.MEMBER
        )
        DataWarehouseTable.objects.create(
            team=self.team,
            name="stripe_charges",
            columns={
                "email": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)"},
                "amount": {"hogql": "FloatDatabaseField", "clickhouse": "Nullable(Float64)"},
                "created": {"hogql": "DateTimeDatabaseField", "clickhouse": "Nullable(DateTime64(3, 'UTC'))"},
            },
            credential=DataWarehouseCredential.objects.create(team=self.team, access_key="key", access_secret="secret"),
            url_pattern="",
        )
        if denied:
            AccessControl.objects.create(team=self.team, resource="warehouse_objects", access_level="none")

        health = self._health(self._experiment(metrics=[_warehouse_sum(table_name)]))

        [check] = [check for check in health.checks if check.key == KEY]
        findings = [finding for finding in health.findings if finding.code == CODE]
        self.assertEqual(
            (check.status, findings[0].evidence["metric_1_message"] if findings else check.reason), expected
        )

    def test_the_answer_is_cached_until_the_metric_changes(self) -> None:
        experiment = self._experiment(metrics=[_mean(_hogql(COMPOUND))])

        with patch.object(
            ExperimentQueryRunner, "compile_query", autospec=True, side_effect=ExperimentQueryRunner.compile_query
        ) as compile_query:
            first = self._health(experiment)
            second = self._health(experiment)
            experiment.metrics = [_mean(_hogql("sum(toFloat(properties.revenue))"))]
            experiment.save()
            fixed = self._health(experiment)

        self.assertEqual(compile_query.call_count, 2)
        self.assertEqual(first.findings, second.findings)
        self.assertIn(CODE, [finding.code for finding in first.findings])
        self.assertNotIn(CODE, [finding.code for finding in fixed.findings])

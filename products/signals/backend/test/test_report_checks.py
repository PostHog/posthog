from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import PropertyDefinition, Team

from products.access_control.backend.facade.contracts import PropertyAccessLevel
from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportCheck
from products.signals.backend.report_check_execution import (
    CHECK_ERROR_RETRY_AFTER,
    CheckVerdict,
    collect_due_checks,
    evaluate_check_value,
    expire_overdue_checks,
    record_check_verdict,
    resolve_check_query,
    run_due_report_checks,
)
from products.signals.backend.report_checks import (
    DEFAULT_CHECK_EXPIRY_AFTER_LAST_RUN,
    MAX_ACTIVE_CHECKS_PER_REPORT,
    MAX_CHECK_HORIZON,
    MAX_CHECK_INTERVAL_MINUTES,
    MAX_CHECK_RUNS,
    MAX_CONSECUTIVE_CHECK_ERRORS,
    MIN_CHECK_INTERVAL_MINUTES,
    CheckComparison,
    CheckConfigValidationError,
    MetricThresholdConfig,
    parse_check_config,
)
from products.signals.backend.report_metric_refresh import MetricMeasurement
from products.signals.backend.serializers import CHECK_RESULT_HIDDEN_EXPLANATION, SignalReportCheckWriteSerializer
from products.signals.backend.test.report_metric_test_fixtures import trends_metric_query
from products.signals.backend.views import SignalReportCheckViewSet

_MEASURE = "products.signals.backend.report_check_execution.measure_metric"

_PAGEVIEWS = trends_metric_query(series=[{"kind": "EventsNode", "event": "$pageview"}])


def _threshold_config(**overrides: object) -> dict:
    return {"query": _PAGEVIEWS, "comparison": {"operator": "lte", "value": 10}, **overrides}


class TestCheckComparison(SimpleTestCase):
    @parameterized.expand(
        [
            ("lte_under", {"operator": "lte", "value": 10}, 4.0, "passed"),
            ("lte_on_bound", {"operator": "lte", "value": 10}, 10.0, "passed"),
            ("lte_over", {"operator": "lte", "value": 10}, 11.0, "failed"),
            ("gte_over", {"operator": "gte", "value": 10}, 12.0, "passed"),
            ("gte_on_bound", {"operator": "gte", "value": 10}, 10.0, "passed"),
            ("gte_under", {"operator": "gte", "value": 10}, 9.0, "failed"),
            ("between_inside", {"operator": "between", "bounds": {"lower": 1, "upper": 5}}, 3.0, "passed"),
            ("between_below", {"operator": "between", "bounds": {"lower": 1, "upper": 5}}, 0.5, "failed"),
            ("between_above", {"operator": "between", "bounds": {"lower": 1, "upper": 5}}, 9.0, "failed"),
        ]
    )
    def test_operator_maps_to_the_bound_it_names(self, _name, comparison, observed, expected_outcome) -> None:
        verdict = evaluate_check_value(
            comparison=CheckComparison.model_validate(comparison),
            observed_value=observed,
            subject="Checkout errors",
        )
        assert verdict.outcome == expected_outcome
        assert verdict.observed_value == observed
        assert verdict.explanation.strip()

    @parameterized.expand(
        [
            ("between_without_bounds", {"operator": "between", "value": 3}),
            ("lte_without_value", {"operator": "lte"}),
            ("lte_with_bounds", {"operator": "lte", "bounds": {"lower": 1, "upper": 2}}),
            ("inverted_bounds", {"operator": "between", "bounds": {"lower": 5, "upper": 1}}),
            ("boolean_value", {"operator": "lte", "value": True}),
        ]
    )
    def test_malformed_comparison_is_refused(self, _name, comparison) -> None:
        with self.assertRaises(CheckConfigValidationError):
            parse_check_config("metric_threshold", {"query": _PAGEVIEWS, "comparison": comparison})

    @parameterized.expand(
        [
            ("neither_source", {"comparison": {"operator": "lte", "value": 1}}),
            ("empty_metric_id", {"metric_id": "", "comparison": {"operator": "lte", "value": 1}}),
            (
                "unknown_config_key",
                {"query": _PAGEVIEWS, "comparison": {"operator": "lte", "value": 1}, "baselineValue": 3},
            ),
            (
                "unknown_comparison_key",
                {"query": _PAGEVIEWS, "comparison": {"operator": "lte", "value": 1, "tolerance": 2}},
            ),
            (
                "unknown_bounds_key",
                {
                    "query": _PAGEVIEWS,
                    "comparison": {"operator": "between", "bounds": {"lower": 1, "upper": 5, "step": 1}},
                },
            ),
            ("uppercase_metric_id", {"metric_id": "Checkout_Errors", "comparison": {"operator": "lte", "value": 1}}),
            (
                "unbounded_query",
                {
                    "query": trends_metric_query(
                        series=[{"kind": "EventsNode", "event": "$pageview"}], date_from="-400d"
                    ),
                    "comparison": {"operator": "lte", "value": 1},
                },
            ),
        ]
    )
    def test_malformed_metric_threshold_config_is_refused(self, _name, config) -> None:
        with self.assertRaises(CheckConfigValidationError):
            parse_check_config("metric_threshold", config)

    def test_a_padded_metric_reference_is_normalized_so_it_can_still_match(self) -> None:
        config = parse_check_config(
            "metric_threshold", {"metric_id": " checkout-errors ", "comparison": {"operator": "lte", "value": 1}}
        )

        assert isinstance(config, MetricThresholdConfig)
        assert config.metric_id == "checkout-errors"

    def test_unknown_kind_is_refused(self) -> None:
        with self.assertRaises(CheckConfigValidationError):
            parse_check_config("agent", {"instructions": "look again"})


class TestCheckScheduleValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("first_run_in_the_past", {"next_run_at": "2020-01-01T00:00:00Z"}, "next_run_at"),
            ("first_run_past_the_horizon", {"next_run_at": "2099-01-01T00:00:00Z"}, "next_run_at"),
            ("repeats_without_an_interval", {"runs_remaining": 3}, "run_interval_minutes"),
            (
                "interval_below_the_floor",
                {"run_interval_minutes": MIN_CHECK_INTERVAL_MINUTES - 1, "runs_remaining": 2},
                "run_interval_minutes",
            ),
            (
                "recurring_interval_past_the_horizon",
                {"run_interval_minutes": MAX_CHECK_INTERVAL_MINUTES + 1, "runs_remaining": 2},
                "run_interval_minutes",
            ),
            (
                "one_shot_interval_past_the_horizon",
                {"run_interval_minutes": 3_000_000_000},
                "run_interval_minutes",
            ),
            ("expiry_before_the_first_run", {"expires_at": "2020-01-01T00:00:00Z"}, "expires_at"),
            (
                "last_run_past_the_horizon",
                {"run_interval_minutes": 30 * 24 * 60, "runs_remaining": 5},
                "run_interval_minutes",
            ),
            ("both_a_metric_and_a_query", {"config": _threshold_config(metric_id="errors")}, "config"),
        ]
    )
    def test_an_impossible_request_is_refused(self, _name, overrides, field) -> None:
        serializer = SignalReportCheckWriteSerializer(
            data={"title": "Errors stay low", "kind": "metric_threshold", "config": _threshold_config(), **overrides}
        )
        assert not serializer.is_valid()
        assert field in serializer.errors

    def test_defaults_fill_in_a_whole_schedule(self) -> None:
        serializer = SignalReportCheckWriteSerializer(
            data={"title": "Errors stay low", "kind": "metric_threshold", "config": _threshold_config()}
        )
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["next_run_at"] > timezone.now()
        assert serializer.validated_data["expires_at"] > serializer.validated_data["next_run_at"]
        assert (
            serializer.validated_data["expires_at"]
            == serializer.validated_data["next_run_at"] + DEFAULT_CHECK_EXPIRY_AFTER_LAST_RUN
        )
        assert serializer.validated_data["runs_remaining"] == 1

    @parameterized.expand(
        [
            ("one_shot_beyond_the_padding", 61, None, 1),
            ("recurring_to_the_run_ceiling", 7, 7 * 24 * 60, MAX_CHECK_RUNS),
        ]
    )
    def test_an_omitted_expiry_never_pushes_a_legal_schedule_past_the_horizon(
        self, _name, first_run_in_days, interval, runs
    ) -> None:
        overrides: dict = {
            "next_run_at": (timezone.now() + timedelta(days=first_run_in_days)).isoformat(),
            "runs_remaining": runs,
        }
        if interval is not None:
            overrides["run_interval_minutes"] = interval

        before = timezone.now()
        serializer = SignalReportCheckWriteSerializer(
            data={"title": "Errors stay low", "kind": "metric_threshold", "config": _threshold_config(), **overrides}
        )
        valid = serializer.is_valid()
        after = timezone.now()

        assert valid, serializer.errors
        assert before + MAX_CHECK_HORIZON <= serializer.validated_data["expires_at"] <= after + MAX_CHECK_HORIZON


class TestReportCheckExecution(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.RESOLVED, title="Fix")

    def _check(self, **overrides) -> SignalReportCheck:
        now = timezone.now()
        fields: dict = {
            "team": self.team,
            "report": self.report,
            "title": "Checkout errors stay low",
            "kind": SignalReportCheck.Kind.METRIC_THRESHOLD,
            "config": _threshold_config(),
            "next_run_at": now - timedelta(minutes=1),
            "expires_at": now + timedelta(days=30),
        }
        fields.update(overrides)
        return SignalReportCheck.objects.for_team(self.team.id).create(**fields)

    def _results(self) -> list[SignalReportArtefact]:
        return list(
            SignalReportArtefact.objects.filter(
                report=self.report, type=SignalReportArtefact.ArtefactType.CHECK_RESULT
            ).order_by("created_at")
        )

    def test_a_one_shot_check_that_holds_retires_as_passed_with_a_result(self) -> None:
        check = self._check()
        with patch(_MEASURE, return_value=MetricMeasurement(value=3.0, measured_at=timezone.now(), series=None)):
            summary = run_due_report_checks()

        assert summary.passed == 1
        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.PASSED
        assert check.last_outcome == SignalReportCheck.Outcome.PASSED
        assert check.last_run_at is not None
        results = self._results()
        assert len(results) == 1
        assert '"outcome":"passed"' in results[0].content
        assert '"observed_value":3.0' in results[0].content

    def test_a_check_that_breaches_retires_as_failed(self) -> None:
        check = self._check()
        with patch(_MEASURE, return_value=MetricMeasurement(value=42.0, measured_at=timezone.now(), series=None)):
            run_due_report_checks()

        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.FAILED
        assert '"outcome":"failed"' in self._results()[0].content

    def test_a_recurring_check_rearms_until_its_runs_are_spent(self) -> None:
        check = self._check(run_interval_minutes=MIN_CHECK_INTERVAL_MINUTES, runs_remaining=2)
        with patch(_MEASURE, return_value=MetricMeasurement(value=1.0, measured_at=timezone.now(), series=None)):
            run_due_report_checks()

        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.ACTIVE
        assert check.runs_remaining == 1
        assert check.next_run_at > timezone.now()

        check.next_run_at = timezone.now() - timedelta(minutes=1)
        check.save(update_fields=["next_run_at"])
        with patch(_MEASURE, return_value=MetricMeasurement(value=1.0, measured_at=timezone.now(), series=None)):
            run_due_report_checks()

        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.PASSED
        assert len(self._results()) == 2

    def test_a_recurring_check_retires_rather_than_running_past_its_horizon(self) -> None:
        check = self._check(
            run_interval_minutes=MIN_CHECK_INTERVAL_MINUTES,
            runs_remaining=2,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        with patch(_MEASURE, return_value=MetricMeasurement(value=1.0, measured_at=timezone.now(), series=None)):
            run_due_report_checks()

        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.PASSED

    def test_a_check_that_cannot_be_measured_retries_then_retires(self) -> None:
        check = self._check()
        for _ in range(MAX_CONSECUTIVE_CHECK_ERRORS):
            check.refresh_from_db()
            check.next_run_at = timezone.now() - timedelta(minutes=1)
            check.save(update_fields=["next_run_at"])
            with patch(_MEASURE, side_effect=ValueError("query returned no series")):
                run_due_report_checks()

        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.ERRORED
        assert len(self._results()) == MAX_CONSECUTIVE_CHECK_ERRORS

    def test_a_single_failure_to_measure_only_delays_the_check(self) -> None:
        check = self._check()
        with patch(_MEASURE, side_effect=ValueError("boom")):
            summary = run_due_report_checks()

        assert summary.errored == 1
        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.ACTIVE
        assert check.consecutive_errors == 1
        assert check.next_run_at >= timezone.now() + CHECK_ERROR_RETRY_AFTER - timedelta(minutes=1)

    def test_a_check_whose_stored_config_stopped_parsing_records_an_errored_run(self) -> None:
        check = self._check()
        # A config that parsed when it was written and no longer does, as a tightened query rule leaves it.
        SignalReportCheck.objects.for_team(self.team.id).filter(id=check.id).update(
            config={"comparison": {"operator": "lte", "value": 10}}
        )

        summary = run_due_report_checks()

        assert summary.errored == 1
        check.refresh_from_db()
        assert check.consecutive_errors == 1
        assert check.next_run_at > timezone.now()
        results = self._results()
        assert len(results) == 1
        assert '"outcome":"errored"' in results[0].content

    def test_an_errored_run_publishes_our_reason_but_not_a_raw_query_error(self) -> None:
        check = self._check()
        with patch(_MEASURE, side_effect=ValueError("metric query returned no series")):
            run_due_report_checks()

        assert "metric query returned no series" in self._results()[0].content

        check.refresh_from_db()
        check.next_run_at = timezone.now() - timedelta(minutes=1)
        check.save(update_fields=["next_run_at"])
        server_error = RuntimeError("DB::Exception: syntax error\nStack trace:\n0. secret internals")
        with patch(_MEASURE, side_effect=server_error):
            run_due_report_checks()

        latest = self._results()[-1].content
        assert '"outcome":"errored"' in latest
        assert "Stack trace" not in latest
        assert "secret internals" not in latest
        # Named like the passed and failed lines, so a report with several checks stays readable.
        assert "Checkout errors stay low could not be measured" in latest

    def test_a_suppressed_report_pauses_its_checks(self) -> None:
        self._check()
        self.report.status = SignalReport.Status.SUPPRESSED
        self.report.save(update_fields=["status"])
        assert collect_due_checks(timezone.now()) == []

        self.report.status = SignalReport.Status.RESOLVED
        self.report.save(update_fields=["status"])
        assert len(collect_due_checks(timezone.now())) == 1

    def test_a_check_cancelled_while_its_query_ran_records_nothing(self) -> None:
        check = self._check()
        check.status = SignalReportCheck.Status.CANCELLED
        check.save(update_fields=["status"])

        record_check_verdict(check, CheckVerdict(outcome="passed", explanation="held", observed_value=1.0))

        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.CANCELLED
        assert self._results() == []

    def test_an_unrun_check_past_its_horizon_expires(self) -> None:
        check = self._check(
            next_run_at=timezone.now() + timedelta(days=1), expires_at=timezone.now() - timedelta(days=1)
        )
        assert expire_overdue_checks(timezone.now()) == 1
        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.EXPIRED
        assert self._results() == []

    def test_a_check_past_its_horizon_is_not_due_even_when_the_sweep_has_not_reached_it(self) -> None:
        now = timezone.now()
        # The state every check reaches at its horizon: due, still active, and past its expiry.
        self._check(next_run_at=now - timedelta(days=2), expires_at=now - timedelta(days=1))

        assert collect_due_checks(now) == []

    def test_one_team_with_a_backlog_does_not_starve_another_team(self) -> None:
        now = timezone.now()
        for minutes in (30, 20, 10):
            self._check(next_run_at=now - timedelta(minutes=minutes))
        other_team = self.organization.teams.create(name="Other")
        other_report = SignalReport.objects.create(
            team=other_team, status=SignalReport.Status.RESOLVED, title="Other fix"
        )
        other_check = SignalReportCheck.objects.for_team(other_team.id).create(
            team=other_team,
            report=other_report,
            title="Their checkout errors stay low",
            kind=SignalReportCheck.Kind.METRIC_THRESHOLD,
            config=_threshold_config(),
            next_run_at=now - timedelta(minutes=5),
            expires_at=now + timedelta(days=30),
        )

        due = collect_due_checks(now, limit=2)

        assert other_check.id in {check.id for check in due}

    def test_a_check_riding_a_report_metric_measures_that_metric(self) -> None:
        self.report.metrics = [
            {
                "metric_id": "checkout-errors",
                "title": "Checkout errors",
                "kind": "occurrences",
                "query": _PAGEVIEWS,
            }
        ]
        self.report.save(update_fields=["metrics"])
        config = MetricThresholdConfig.model_validate(
            {"metric_id": "checkout-errors", "comparison": {"operator": "lte", "value": 1}}
        )
        assert resolve_check_query(config, self.report) == _PAGEVIEWS

    def test_a_check_riding_a_metric_whose_query_stopped_conforming_errors(self) -> None:
        # The runner reads one series out of the result, so a breakdown would turn an arbitrary
        # slice into a recorded verdict.
        self.report.metrics = [
            {
                "metric_id": "checkout-errors",
                "title": "Checkout errors",
                "kind": "occurrences",
                "query": {
                    **_PAGEVIEWS,
                    "source": {**_PAGEVIEWS["source"], "breakdownFilter": {"breakdown": "$browser"}},
                },
            }
        ]
        self.report.save(update_fields=["metrics"])
        check = self._check(config={"metric_id": "checkout-errors", "comparison": {"operator": "lte", "value": 1}})

        with patch(
            _MEASURE, return_value=MetricMeasurement(value=0.0, measured_at=timezone.now(), series=None)
        ) as measure:
            run_due_report_checks()

        assert not measure.called
        check.refresh_from_db()
        assert check.last_outcome == SignalReportCheck.Outcome.ERRORED
        assert '"outcome":"errored"' in self._results()[0].content

    def test_a_check_riding_a_metric_the_report_dropped_errors_rather_than_crashing(self) -> None:
        check = self._check(config={"metric_id": "gone", "comparison": {"operator": "lte", "value": 1}})
        run_due_report_checks()

        check.refresh_from_db()
        assert check.last_outcome == SignalReportCheck.Outcome.ERRORED
        assert '"outcome":"errored"' in self._results()[0].content


class TestReportCheckAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.RESOLVED, title="Fix")
        self.url = f"/api/projects/{self.team.id}/signals/reports/{self.report.id}/checks/"

    def test_create_then_list_then_cancel(self) -> None:
        response = self.client.post(
            self.url,
            {"title": "Checkout errors stay low", "kind": "metric_threshold", "config": _threshold_config()},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        check_id = response.json()["id"]

        listed = self.client.get(self.url)
        assert [row["id"] for row in listed.json()["results"]] == [check_id]
        assert listed.json()["results"][0]["config"]["query"] == _PAGEVIEWS

        cancelled = self.client.delete(f"{self.url}{check_id}/")
        assert cancelled.status_code == status.HTTP_200_OK
        assert cancelled.json()["status"] == "cancelled"

        already_cancelled = self.client.delete(f"{self.url}{check_id}/")
        assert already_cancelled.status_code == status.HTTP_400_BAD_REQUEST

    def test_cancelling_does_not_overwrite_a_verdict_that_landed_first(self) -> None:
        created = self.client.post(
            self.url,
            {"title": "Checkout errors stay low", "kind": "metric_threshold", "config": _threshold_config()},
            format="json",
        )
        check_id = created.json()["id"]
        # The row the request read before a run committed its verdict.
        stale = SignalReportCheck.objects.for_team(self.team.id).get(id=check_id)
        SignalReportCheck.objects.for_team(self.team.id).filter(id=check_id).update(
            status=SignalReportCheck.Status.PASSED, last_outcome=SignalReportCheck.Outcome.PASSED
        )

        with patch.object(SignalReportCheckViewSet, "get_object", return_value=stale):
            refused = self.client.delete(f"{self.url}{check_id}/")

        assert refused.status_code == status.HTTP_400_BAD_REQUEST
        assert (
            SignalReportCheck.objects.for_team(self.team.id).get(id=check_id).status == SignalReportCheck.Status.PASSED
        )

    def test_a_metric_reference_is_resolved_and_copied_when_the_check_is_created(self) -> None:
        payload = {
            "title": "Checkout errors stay low",
            "kind": "metric_threshold",
            "config": {"metric_id": "checkout-errors", "comparison": {"operator": "lte", "value": 10}},
        }

        refused = self.client.post(self.url, payload, format="json")

        assert refused.status_code == status.HTTP_400_BAD_REQUEST
        assert not SignalReportCheck.objects.for_team(self.team.id).filter(report_id=self.report.id).exists()

        self.report.metrics = [
            {"metric_id": "checkout-errors", "title": "Checkout errors", "kind": "occurrences", "query": _PAGEVIEWS}
        ]
        self.report.save(update_fields=["metrics"])
        created = self.client.post(self.url, payload, format="json")
        assert created.status_code == status.HTTP_201_CREATED, created.json()
        stored = SignalReportCheck.objects.for_team(self.team.id).get(id=created.json()["id"])
        assert stored.config["metric_id"] == "checkout-errors"
        assert stored.config["query"] == _PAGEVIEWS

        # Rewriting the metric under the same id must not move the check's target.
        rewritten = trends_metric_query(series=[{"kind": "EventsNode", "event": "$autocapture"}])
        self.report.metrics = [{**self.report.metrics[0], "query": rewritten}]
        self.report.save(update_fields=["metrics"])
        SignalReportCheck.objects.for_team(self.team.id).filter(id=stored.id).update(
            next_run_at=timezone.now() - timedelta(minutes=1)
        )
        with patch(
            _MEASURE, return_value=MetricMeasurement(value=0.0, measured_at=timezone.now(), series=None)
        ) as measure:
            run_due_report_checks()
        assert measure.call_args.args[0] == _PAGEVIEWS

    def test_a_check_created_in_a_child_environment_stays_on_that_environment(self) -> None:
        child = Team.objects.create(organization=self.organization, name="Child", parent_team=self.team)
        report = SignalReport.objects.create(team=child, status=SignalReport.Status.RESOLVED, title="Fix")
        url = f"/api/projects/{child.id}/signals/reports/{report.id}/checks/"

        created = self.client.post(
            url, {"title": "Errors stay low", "kind": "metric_threshold", "config": _threshold_config()}, format="json"
        )
        assert created.status_code == status.HTTP_201_CREATED, created.json()
        check_id = created.json()["id"]

        assert [row["id"] for row in self.client.get(url).json()["results"]] == [check_id]
        assert SignalReportCheck.all_teams.get(id=check_id).team_id == child.id

        SignalReportCheck.all_teams.filter(id=check_id).update(next_run_at=timezone.now() - timedelta(minutes=1))
        with patch(_MEASURE, return_value=MetricMeasurement(value=0.0, measured_at=timezone.now(), series=None)):
            run_due_report_checks()
        result = SignalReportArtefact.objects.get(report=report, type=SignalReportArtefact.ArtefactType.CHECK_RESULT)
        assert result.team_id == child.id

    def test_a_property_restricted_member_cannot_read_a_checks_query_or_measured_values(self) -> None:
        secret_pageviews = trends_metric_query(
            series=[
                {
                    "kind": "EventsNode",
                    "event": "$pageview",
                    "properties": [
                        {"key": "secret_plan", "value": ["enterprise"], "operator": "exact", "type": "event"}
                    ],
                }
            ]
        )
        created = self.client.post(
            self.url,
            {
                "title": "Enterprise pageviews stay low",
                "kind": "metric_threshold",
                "config": _threshold_config(query=secret_pageviews, baseline_value=3),
            },
            format="json",
        )
        assert created.status_code == status.HTTP_201_CREATED, created.json()
        check_id = created.json()["id"]
        SignalReportCheck.objects.for_team(self.team.id).filter(id=check_id).update(
            next_run_at=timezone.now() - timedelta(minutes=1)
        )
        with patch(_MEASURE, return_value=MetricMeasurement(value=4.0, measured_at=timezone.now(), series=None)):
            run_due_report_checks()
        artefacts_url = f"/api/projects/{self.team.id}/signals/reports/{self.report.id}/artefacts/"

        def check_result() -> dict:
            return next(
                row["content"]
                for row in self.client.get(artefacts_url).json()["results"]
                if row["type"] == "check_result"
            )

        assert check_result()["observed_value"] == 4.0

        self.organization.available_product_features = [
            {"name": AvailableFeature.PROPERTY_ACCESS_CONTROL, "key": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=PropertyDefinition.objects.create(
                team=self.team, name="secret_plan", property_type="String", type=PropertyDefinition.Type.EVENT
            ),
            organization_member=self.organization_membership,
            access_level=PropertyAccessLevel.NONE.value,
        )

        config = self.client.get(f"{self.url}{check_id}/").json()["config"]
        assert config["query"] is None
        assert config["baseline_value"] is None
        assert config["comparison"] == {"operator": "lte", "value": 10}

        hidden = check_result()
        assert hidden["outcome"] == "passed"
        assert hidden["observed_value"] is None
        assert hidden["baseline_value"] is None
        assert hidden["explanation"] == CHECK_RESULT_HIDDEN_EXPLANATION

    def test_an_invalid_config_is_rejected_by_the_endpoint(self) -> None:
        response = self.client.post(
            self.url,
            {"title": "Nonsense", "kind": "metric_threshold", "config": {"comparison": {"operator": "lte"}}},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_a_report_carries_a_bounded_number_of_active_checks(self) -> None:
        payload = {"title": "Errors stay low", "kind": "metric_threshold", "config": _threshold_config()}
        for _ in range(MAX_ACTIVE_CHECKS_PER_REPORT):
            assert self.client.post(self.url, payload, format="json").status_code == status.HTTP_201_CREATED

        refused = self.client.post(self.url, payload, format="json")
        assert refused.status_code == status.HTTP_400_BAD_REQUEST

    def test_another_teams_report_is_not_reachable(self) -> None:
        other_team = self.organization.teams.create(name="Other")
        other_report = SignalReport.objects.create(team=other_team, status=SignalReport.Status.READY)
        response = self.client.get(
            f"/api/projects/{self.team.id}/signals/reports/{other_report.id}/checks/",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

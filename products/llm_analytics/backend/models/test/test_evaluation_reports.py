import datetime as dt

from posthog.test.base import BaseTest

from django.utils import timezone

from parameterized import parameterized

from products.llm_analytics.backend.models.evaluation_reports import (
    RRULE_WEEKDAY_MAP,
    EvaluationReport,
    EvaluationReportRun,
    _to_rrule_weekdays,
)
from products.llm_analytics.backend.models.evaluations import Evaluation


class TestToRruleWeekdays(BaseTest):
    def test_single_day(self):
        result = _to_rrule_weekdays(["monday"])
        self.assertEqual(len(result), 1)

    def test_multiple_days(self):
        result = _to_rrule_weekdays(["monday", "wednesday", "friday"])
        self.assertEqual(len(result), 3)

    def test_ignores_invalid_days(self):
        result = _to_rrule_weekdays(["monday", "invalid", "friday"])
        self.assertEqual(len(result), 2)

    def test_empty_list(self):
        result = _to_rrule_weekdays([])
        self.assertEqual(len(result), 0)

    @parameterized.expand(list(RRULE_WEEKDAY_MAP.keys()))
    def test_all_valid_weekdays(self, day):
        result = _to_rrule_weekdays([day])
        self.assertEqual(len(result), 1)


class TestEvaluationReportModel(BaseTest):
    def _create_evaluation(self) -> Evaluation:
        return Evaluation.objects.create(
            team=self.team,
            name="Test Eval",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "test"},
            output_type="boolean",
            output_config={},
            enabled=True,
            created_by=self.user,
            conditions=[{"id": "c1", "rollout_percentage": 100, "properties": []}],
        )

    def test_save_sets_next_delivery_date_on_create(self):
        now = timezone.now()
        evaluation = self._create_evaluation()
        report = EvaluationReport.objects.create(
            team=self.team,
            evaluation=evaluation,
            frequency="hourly",
            start_date=now - dt.timedelta(hours=2),
            delivery_targets=[{"type": "email", "value": "test@example.com"}],
        )
        self.assertIsNotNone(report.next_delivery_date)
        self.assertGreater(report.next_delivery_date, now)

    def test_hourly_rrule(self):
        now = timezone.now()
        evaluation = self._create_evaluation()
        start = now - dt.timedelta(hours=5)
        report = EvaluationReport(
            team=self.team,
            evaluation=evaluation,
            frequency="hourly",
            start_date=start,
            delivery_targets=[],
        )
        next_occurrence = report.rrule.after(now, inc=False)
        self.assertIsNotNone(next_occurrence)
        self.assertEqual(next_occurrence.minute, start.minute)

    def test_daily_rrule(self):
        now = timezone.now()
        evaluation = self._create_evaluation()
        start = now - dt.timedelta(days=2)
        report = EvaluationReport(
            team=self.team,
            evaluation=evaluation,
            frequency="daily",
            start_date=start,
            delivery_targets=[],
        )
        next_occurrence = report.rrule.after(now, inc=False)
        self.assertIsNotNone(next_occurrence)
        self.assertEqual(next_occurrence.hour, start.hour)

    def test_weekly_rrule_with_byweekday(self):
        now = timezone.now()
        evaluation = self._create_evaluation()
        report = EvaluationReport(
            team=self.team,
            evaluation=evaluation,
            frequency="weekly",
            byweekday=["monday", "friday"],
            start_date=now - dt.timedelta(weeks=1),
            delivery_targets=[],
        )
        next_occurrence = report.rrule.after(now, inc=False)
        self.assertIsNotNone(next_occurrence)
        self.assertIn(next_occurrence.weekday(), [0, 4])

    def test_set_next_delivery_date_uses_15min_buffer(self):
        now = timezone.now()
        evaluation = self._create_evaluation()
        report = EvaluationReport(
            team=self.team,
            evaluation=evaluation,
            frequency="hourly",
            start_date=now - dt.timedelta(hours=1),
            delivery_targets=[],
        )
        report.set_next_delivery_date()
        self.assertGreater(report.next_delivery_date, now + dt.timedelta(minutes=14))

    def test_set_next_delivery_date_from_custom_dt(self):
        now = timezone.now()
        evaluation = self._create_evaluation()
        from_dt = now + dt.timedelta(hours=2)
        report = EvaluationReport(
            team=self.team,
            evaluation=evaluation,
            frequency="hourly",
            start_date=now - dt.timedelta(hours=1),
            delivery_targets=[],
        )
        report.set_next_delivery_date(from_dt=from_dt)
        self.assertGreater(report.next_delivery_date, from_dt)


class TestEvaluationReportRunModel(BaseTest):
    def test_create_report_run(self):
        now = timezone.now()
        evaluation = Evaluation.objects.create(
            team=self.team,
            name="Test Eval",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "test"},
            output_type="boolean",
            output_config={},
            enabled=True,
            created_by=self.user,
            conditions=[{"id": "c1", "rollout_percentage": 100, "properties": []}],
        )
        report = EvaluationReport.objects.create(
            team=self.team,
            evaluation=evaluation,
            frequency="daily",
            start_date=now,
            delivery_targets=[{"type": "email", "value": "test@example.com"}],
        )
        run = EvaluationReportRun.objects.create(
            report=report,
            content={"executive_summary": {"content": "test", "referenced_generation_ids": []}},
            metadata={"total_runs": 10, "pass_rate": 80.0},
            period_start=now - dt.timedelta(hours=1),
            period_end=now,
        )
        self.assertEqual(run.delivery_status, "pending")
        self.assertEqual(run.delivery_errors, [])
        self.assertEqual(run.report, report)

import datetime as dt
from zoneinfo import ZoneInfo

from posthog.test.base import BaseTest

from django.utils import timezone

from products.llm_analytics.backend.models.evaluation_reports import EvaluationReport, EvaluationReportRun
from products.llm_analytics.backend.models.evaluations import Evaluation


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

    def _scheduled_report(self, **overrides) -> EvaluationReport:
        defaults = {
            "team": self.team,
            "evaluation": self._create_evaluation(),
            "frequency": EvaluationReport.Frequency.SCHEDULED,
            "rrule": "FREQ=HOURLY",
            "starts_at": timezone.now() - dt.timedelta(hours=5),
            "delivery_targets": [],
        }
        defaults.update(overrides)
        return EvaluationReport.objects.create(**defaults)

    def test_save_sets_next_delivery_date_on_scheduled_create(self):
        now = timezone.now()
        report = self._scheduled_report()
        assert report.next_delivery_date is not None
        self.assertGreater(report.next_delivery_date, now)

    def test_count_triggered_has_no_next_delivery_date(self):
        report = EvaluationReport.objects.create(
            team=self.team,
            evaluation=self._create_evaluation(),
            frequency=EvaluationReport.Frequency.EVERY_N,
            trigger_threshold=100,
            delivery_targets=[],
        )
        self.assertTrue(report.is_count_triggered)
        self.assertIsNone(report.next_delivery_date)
        with self.assertRaises(ValueError):
            _ = report.rrule_object

    def test_rrule_object_hourly(self):
        now = timezone.now()
        report = self._scheduled_report(rrule="FREQ=HOURLY", starts_at=now - dt.timedelta(hours=5))
        next_occurrence = report.rrule_object.after(now, inc=False)
        self.assertIsNotNone(next_occurrence)
        self.assertEqual(next_occurrence.minute, (now - dt.timedelta(hours=5)).minute)

    def test_rrule_object_weekly_with_byday(self):
        now = timezone.now()
        report = self._scheduled_report(
            rrule="FREQ=WEEKLY;BYDAY=MO,FR",
            starts_at=now - dt.timedelta(weeks=1),
        )
        next_occurrence = report.rrule_object.after(now, inc=False)
        self.assertIsNotNone(next_occurrence)
        self.assertIn(next_occurrence.weekday(), [0, 4])

    def test_set_next_delivery_date_uses_15min_buffer(self):
        now = timezone.now()
        report = self._scheduled_report(rrule="FREQ=HOURLY", starts_at=now - dt.timedelta(hours=1))
        report.set_next_delivery_date()
        assert report.next_delivery_date is not None
        self.assertGreater(report.next_delivery_date, now + dt.timedelta(minutes=14))

    def test_set_next_delivery_date_from_custom_dt(self):
        now = timezone.now()
        report = self._scheduled_report(rrule="FREQ=HOURLY", starts_at=now - dt.timedelta(hours=1))
        from_dt = now + dt.timedelta(hours=2)
        report.set_next_delivery_date(from_dt=from_dt)
        assert report.next_delivery_date is not None
        self.assertGreater(report.next_delivery_date, from_dt)

    def test_set_next_delivery_date_stays_at_local_wall_clock_across_dst(self):
        # 9am daily in New York: Sun 2026-03-01 14:00 UTC (EST = UTC-5).
        # After DST begins on 2026-03-08, 9am local == 13:00 UTC (EDT = UTC-4).
        # Naive `rrulestr(...).after()` would keep firing at 14:00 UTC, drifting to
        # 10am local. The workflows util expands in naive local then reattaches the
        # zoneinfo so the wall-clock stays at 09:00 across the transition.
        ny = ZoneInfo("America/New_York")
        anchor_utc = dt.datetime(2026, 3, 1, 14, 0, tzinfo=dt.UTC)  # 9am EST
        report = self._scheduled_report(
            rrule="FREQ=DAILY;BYHOUR=9;BYMINUTE=0;BYSECOND=0",
            starts_at=anchor_utc,
            timezone_name="America/New_York",
        )
        # Look for the first occurrence after DST started (2026-03-08 02:00 local).
        report.set_next_delivery_date(from_dt=dt.datetime(2026, 3, 10, 12, 0, tzinfo=dt.UTC))
        assert report.next_delivery_date is not None
        # Next fire should be at 09:00 local, i.e. 13:00 UTC (EDT), not 14:00 UTC.
        local = report.next_delivery_date.astimezone(ny)
        self.assertEqual(local.hour, 9)
        self.assertEqual(local.minute, 0)

    def test_save_with_update_fields_persists_changed_schedule_field(self):
        # Regression: save(update_fields=[...]) used to drop a changed schedule
        # field while still recomputing next_delivery_date from the new value,
        # leaving the DB inconsistent with the recomputed timestamp.
        report = self._scheduled_report(rrule="FREQ=HOURLY")
        report.rrule = "FREQ=WEEKLY"
        report.save(update_fields=["rrule"])

        report.refresh_from_db()
        self.assertEqual(report.rrule, "FREQ=WEEKLY")
        assert report.next_delivery_date is not None


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
            frequency=EvaluationReport.Frequency.SCHEDULED,
            rrule="FREQ=DAILY",
            starts_at=now,
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

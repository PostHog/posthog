import uuid

from django.test import TestCase

from posthog.models import Organization, Team

from products.signals.backend.models import SignalReport
from products.tasks.backend.management.commands.backfill_task_source_fields import backfill_task_source_fields
from products.tasks.backend.models import Task


class TestBackfillTaskSourceFields(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.team = Team.objects.create(organization=Organization.objects.create(name="Org"), name="Team")

    def _legacy_task(self, origin_product: str, **fields) -> Task:
        task = Task.objects.create(
            team=self.team, title="Task", description="d", origin_product=origin_product, **fields
        )
        Task.objects.filter(id=task.id).update(source_kind=None, source_id=None, idempotency_key=None)
        return task

    def test_fills_source_and_idempotency_fields_once(self) -> None:
        report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.READY)
        hog_flow_id = uuid.uuid4()
        from_report = self._legacy_task("signal_report", signal_report=report, origin_key="report:1")
        from_workflow = self._legacy_task("workflow", hog_flow_id=hog_flow_id, origin_key="workflow:1")
        plain = self._legacy_task("user_created")

        assert backfill_task_source_fields(dry_run=True) == 2
        assert Task.objects.get(id=from_report.id).source_kind is None

        assert backfill_task_source_fields(batch_size=1) == 2
        assert backfill_task_source_fields() == 0

        for task in (from_report, from_workflow, plain):
            task.refresh_from_db()
        assert (from_report.source_kind, from_report.source_id, from_report.idempotency_key) == (
            "signal_report",
            str(report.id),
            "report:1",
        )
        assert (from_workflow.source_kind, from_workflow.source_id, from_workflow.idempotency_key) == (
            "hog_flow",
            str(hog_flow_id),
            "workflow:1",
        )
        assert (plain.source_kind, plain.source_id, plain.idempotency_key) == (None, None, None)

from io import StringIO
from uuid import UUID, uuid4

from django.core.management import call_command
from django.db import connection
from django.test import TestCase

from parameterized import parameterized

from posthog.models import Organization, Team

from products.signals.backend.models import SignalReport
from products.tasks.backend.management.commands.backfill_task_sources import backfill_task_sources
from products.tasks.backend.models import Task

REPORT_ID = UUID("11111111-1111-4111-8111-111111111111")
FLOW_ID = UUID("22222222-2222-4222-8222-222222222222")
LOOP_ID = UUID("33333333-3333-4333-8333-333333333333")


class TestBackfillTaskSources(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.team = Team.objects.create(organization=Organization.objects.create(name="Org"), name="Team")
        SignalReport.objects.create(team=self.team, id=REPORT_ID)

    def _task(self, team: Team | None = None, **columns: object) -> Task:
        return Task.objects.create(
            team=team or self.team,
            title="Task",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
            **columns,
        )

    def _columns(self, task: Task) -> tuple[str | None, str | None, str | None]:
        task.refresh_from_db()
        return (task.source_kind, task.source_id, task.idempotency_key)

    @parameterized.expand(
        [
            ("nothing_to_fill", {}, (None, None, None)),
            ("report_only", {"signal_report_id": REPORT_ID}, ("signal_report", str(REPORT_ID), None)),
            ("flow_only", {"hog_flow_id": FLOW_ID}, ("hog_flow", str(FLOW_ID), None)),
            ("key_only", {"origin_key": "key"}, (None, None, "key")),
            (
                "report_and_key",
                {"signal_report_id": REPORT_ID, "origin_key": "key"},
                ("signal_report", str(REPORT_ID), "key"),
            ),
            (
                "source_filled_key_missing",
                {"hog_flow_id": FLOW_ID, "source_kind": "hog_flow", "source_id": str(FLOW_ID), "origin_key": "key"},
                ("hog_flow", str(FLOW_ID), "key"),
            ),
            (
                "key_filled_source_missing",
                {"hog_flow_id": FLOW_ID, "origin_key": "key", "idempotency_key": "key"},
                ("hog_flow", str(FLOW_ID), "key"),
            ),
            (
                "new_columns_win_over_old",
                {
                    "signal_report_id": REPORT_ID,
                    "origin_key": "old",
                    "source_kind": "loop",
                    "source_id": "loop-1",
                    "idempotency_key": "new",
                },
                ("loop", "loop-1", "new"),
            ),
        ]
    )
    def test_fills_the_columns_a_task_is_missing(
        self, _name: str, columns: dict, expected: tuple[str | None, str | None, str | None]
    ) -> None:
        task = self._task(**columns)

        list(backfill_task_sources())

        self.assertEqual(self._columns(task), expected)

    def test_fills_the_source_of_a_legacy_loop_task(self) -> None:
        task = self._task()
        with connection.cursor() as cursor:
            cursor.execute("UPDATE posthog_task SET loop_id = %s WHERE id = %s", [LOOP_ID, task.id])

        list(backfill_task_sources())

        self.assertEqual(self._columns(task), ("loop", str(LOOP_ID), None))

    def test_dry_run_counts_the_tasks_without_writing(self) -> None:
        task = self._task(origin_key="key")

        batches = list(backfill_task_sources(dry_run=True))

        self.assertEqual([batch.tasks for batch in batches], [1])
        self.assertEqual(self._columns(task), (None, None, None))

    def test_only_fills_the_requested_team(self) -> None:
        other_team = Team.objects.create(organization=self.team.organization, name="Other")
        task = self._task(origin_key="key")
        other = self._task(team=other_team, origin_key="other-key")

        list(backfill_task_sources(team_id=self.team.id))

        self.assertEqual(self._columns(task), (None, None, "key"))
        self.assertEqual(self._columns(other), (None, None, None))

    def test_resumes_after_the_cursor_of_an_earlier_run(self) -> None:
        tasks = [self._task(origin_key=f"key-{uuid4()}") for _ in range(3)]
        ordered = sorted(tasks, key=lambda task: task.id)

        first_batch = next(backfill_task_sources(batch_size=1))

        self.assertEqual(first_batch.cursor, str(ordered[0].id))
        self.assertIsNotNone(self._columns(ordered[0])[2])
        self.assertIsNone(self._columns(ordered[1])[2])

        resumed = list(backfill_task_sources(batch_size=1, after=first_batch.cursor))

        self.assertEqual([batch.cursor for batch in resumed], [str(task.id) for task in ordered[1:]])
        self.assertTrue(all(self._columns(task)[2] is not None for task in tasks))

    def test_command_prints_the_cursor_to_resume_from(self) -> None:
        task = self._task(hog_flow_id=FLOW_ID)
        out = StringIO()

        call_command("backfill_task_sources", "--sleep-seconds", "0", "--batch-size", "10", stdout=out)

        self.assertIn(f"resume after {task.id}", out.getvalue())
        self.assertEqual(self._columns(task), ("hog_flow", str(FLOW_ID), None))

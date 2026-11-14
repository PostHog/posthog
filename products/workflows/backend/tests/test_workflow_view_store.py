from threading import Event, Thread

from django.db import connection
from django.test import TransactionTestCase

from posthog.models import Organization, Team
from posthog.test.waiting import wait_until

from products.workflows.backend.facade.contracts import WorkflowViewConflict
from products.workflows.backend.models.workflow_view import WorkflowView
from products.workflows.backend.services.workflow_views import WorkflowViewStore


class TestWorkflowViewStoreConcurrency(TransactionTestCase):
    def setUp(self) -> None:
        organization = Organization.objects.create(name="Views")
        self.team = Team.objects.create(organization=organization, name="Views")
        self.store = WorkflowViewStore(self.team.id)
        self.view = self.store.create(name="Shared", state={"filters": [], "text": "", "columns": []})

    def _edit_while_holding_the_view(self, locked: Event, writer_pid: int, writer_blocked: Event) -> None:
        separate_session = connection.get_new_connection(connection.get_connection_params())
        try:
            with separate_session.cursor() as cursor:
                cursor.execute("BEGIN")
                cursor.execute("SELECT pg_backend_pid()")
                holder_pid = cursor.fetchone()[0]
                cursor.execute("SELECT id FROM workflows_workflowview WHERE id = %s FOR UPDATE", [self.view.id])
                locked.set()

                def writer_waits_on_this_session() -> bool:
                    cursor.execute("SELECT %s = ANY(pg_blocking_pids(%s))", [holder_pid, writer_pid])
                    row = cursor.fetchone()
                    return bool(row and row[0])

                wait_until(writer_waits_on_this_session, timeout=10, message="the writer never waited on the held view")
                writer_blocked.set()
                cursor.execute(
                    "UPDATE workflows_workflowview SET name = 'First', version = 2 WHERE id = %s", [self.view.id]
                )
                cursor.execute("COMMIT")
        finally:
            separate_session.close()

    def test_a_write_that_waits_on_a_locked_view_is_refused_once_a_newer_version_commits(self) -> None:
        locked = Event()
        writer_blocked = Event()
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            writer_pid = cursor.fetchone()[0]
        first = Thread(target=self._edit_while_holding_the_view, args=(locked, writer_pid, writer_blocked))
        first.start()
        self.assertTrue(locked.wait(timeout=10))

        with self.assertRaises(WorkflowViewConflict):
            self.store.update(self.view.id, 1, name="Second", state=None)
        first.join(timeout=10)
        self.assertTrue(writer_blocked.is_set())

        saved = WorkflowView.objects.for_team(self.team.id).get(pk=self.view.id)
        self.assertEqual((saved.name, saved.version), ("First", 2))

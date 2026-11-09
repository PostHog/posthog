import time
from threading import Event, Thread

from django.db import connection
from django.test import TransactionTestCase

from posthog.models import Organization, Team

from products.workflows.backend.facade.contracts import WorkflowViewConflict
from products.workflows.backend.models.workflow_view import WorkflowView
from products.workflows.backend.services.workflow_views import WorkflowViewStore


class TestWorkflowViewStoreConcurrency(TransactionTestCase):
    def setUp(self) -> None:
        organization = Organization.objects.create(name="Views")
        self.team = Team.objects.create(organization=organization, name="Views")
        self.store = WorkflowViewStore(self.team.id)
        self.view = self.store.create(name="Shared", state={"filters": [], "text": "", "columns": []})

    def _edit_while_holding_the_view(self, locked: Event) -> None:
        # Django shares its test connection across threads, so the other writer needs its own database session.
        other = connection.get_new_connection(connection.get_connection_params())
        try:
            with other.cursor() as cursor:
                cursor.execute("BEGIN")
                cursor.execute("SELECT id FROM workflows_workflowview WHERE id = %s FOR UPDATE", [self.view.id])
                locked.set()
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    cursor.execute(
                        "SELECT count(*) FROM pg_stat_activity"
                        " WHERE datname = current_database() AND wait_event_type = 'Lock'"
                    )
                    row = cursor.fetchone()
                    if row and row[0]:
                        break
                    time.sleep(0.01)
                cursor.execute(
                    "UPDATE workflows_workflowview SET name = 'First', version = 2 WHERE id = %s", [self.view.id]
                )
                cursor.execute("COMMIT")
        finally:
            other.close()

    def test_a_write_that_waits_on_a_locked_view_is_refused_once_a_newer_version_commits(self) -> None:
        locked = Event()
        first = Thread(target=self._edit_while_holding_the_view, args=(locked,))
        first.start()
        self.assertTrue(locked.wait(timeout=10))

        with self.assertRaises(WorkflowViewConflict):
            self.store.update(self.view.id, 1, name="Second", state=None)
        first.join(timeout=10)

        saved = WorkflowView.objects.for_team(self.team.id).get(pk=self.view.id)
        self.assertEqual((saved.name, saved.version), ("First", 2))

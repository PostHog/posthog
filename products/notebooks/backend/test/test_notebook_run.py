from posthog.test.base import APIBaseTest

from django.db import IntegrityError, transaction

from posthog.models.scoping import team_scope

from products.notebooks.backend.models import Notebook, NotebookRun


class TestNotebookRunModel(APIBaseTest):
    def _notebook(self) -> Notebook:
        return Notebook.objects.create(team=self.team, created_by=self.user)

    def _run(self, notebook: Notebook) -> NotebookRun:
        with team_scope(self.team.id):
            return NotebookRun.objects.create(team=self.team, notebook=notebook, user=self.user)

    def test_a_notebook_can_only_have_one_running_run(self) -> None:
        notebook = self._notebook()
        self._run(notebook)

        with self.assertRaises(IntegrityError), transaction.atomic():
            self._run(notebook)

    def test_a_finished_run_frees_the_notebook_for_the_next_one(self) -> None:
        notebook = self._notebook()
        first = self._run(notebook)
        first.status = NotebookRun.Status.DONE
        first.save(update_fields=["status"])

        self.assertEqual(self._run(notebook).status, NotebookRun.Status.RUNNING)

    def test_two_notebooks_run_at_the_same_time(self) -> None:
        self._run(self._notebook())
        self._run(self._notebook())

        with team_scope(self.team.id):
            self.assertEqual(NotebookRun.objects.count(), 2)

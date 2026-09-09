from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from posthog.models.scoping import team_scope

from products.notebooks.backend.models import Notebook, NotebookNodeRun, NotebookRun

RUNNABLE_MARKDOWN = (
    "# Report\n\n"
    '<SQLV2 nodeId="s1" code="select 1" returnVariable="df" />\n\n'
    '<PythonV2 nodeId="p1" code="out = df.head()" returnVariable="out" />\n'
)


def markdown_content(markdown: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "content": [
            {"type": "ph-markdown-notebook", "attrs": {"nodeId": "markdown-notebook-v2", "markdown": markdown}}
        ],
    }


@patch("products.notebooks.backend.presentation.views.notebook.start_notebook_run_workflow")
@patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
class TestNotebookRunApi(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.notebook = Notebook.objects.create(
            team=self.team, created_by=self.user, content=markdown_content(RUNNABLE_MARKDOWN)
        )
        self.runs_url = f"/api/projects/{self.team.id}/notebooks/{self.notebook.short_id}/runs/"

    def test_a_run_plans_every_runnable_cell_and_starts_the_workflow(self, _flag, workflow) -> None:
        response = self.client.post(self.runs_url, {}, format="json")

        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        self.assertEqual(payload["cell_count"], 2)
        workflow.assert_called_once()
        with team_scope(self.team.id):
            notebook_run = NotebookRun.objects.get(id=payload["run_id"])
        self.assertEqual(
            [entry["node_id"] for entry in notebook_run.cell_plan],
            ["s1", "p1"],
        )

    def test_a_notebook_with_nothing_to_run_is_refused(self, _flag, workflow) -> None:
        notebook = Notebook.objects.create(
            team=self.team, created_by=self.user, content=markdown_content("Just prose.\n")
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/runs/", {}, format="json"
        )

        self.assertEqual(response.status_code, 400, response.json())
        workflow.assert_not_called()

    def test_a_second_run_while_one_is_going_is_refused(self, _flag, _workflow) -> None:
        self.assertEqual(self.client.post(self.runs_url, {}, format="json").status_code, 200)

        response = self.client.post(self.runs_url, {}, format="json")

        self.assertEqual(response.status_code, 409, response.json())

    def test_variables_are_saved_before_the_run_reads_them(self, _flag, _workflow) -> None:
        response = self.client.post(
            self.runs_url,
            {"variables": [{"name": "country", "type": "string", "value": "US"}]},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.json())
        self.notebook.refresh_from_db()
        self.assertEqual(self.notebook.variables, [{"name": "country", "type": "string", "value": "US"}])
        with team_scope(self.team.id):
            notebook_run = NotebookRun.objects.get(id=response.json()["run_id"])
        self.assertEqual(notebook_run.variables, self.notebook.variables)

    def test_duplicate_variable_names_are_refused(self, _flag, workflow) -> None:
        response = self.client.post(
            self.runs_url,
            {
                "variables": [
                    {"name": "country", "type": "string", "value": "US"},
                    {"name": "country", "type": "string", "value": "GB"},
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.json())
        workflow.assert_not_called()

    def test_status_reports_each_planned_cell_and_the_run_it_produced(self, _flag, _workflow) -> None:
        run_id = self.client.post(self.runs_url, {}, format="json").json()["run_id"]
        with team_scope(self.team.id):
            node_run = NotebookNodeRun.objects.create(
                team=self.team,
                notebook=self.notebook,
                notebook_run_id=run_id,
                node_id="s1",
                code="select 1",
                status=NotebookNodeRun.Status.DONE,
            )

        payload = self.client.get(f"{self.runs_url}{run_id}/").json()

        self.assertEqual(payload["status"], "running")
        self.assertEqual([cell["node_id"] for cell in payload["cells"]], ["s1", "p1"])
        self.assertEqual(payload["cells"][0]["run_id"], str(node_run.id))
        self.assertEqual(payload["cells"][0]["status"], "done")
        self.assertIsNone(payload["cells"][1]["run_id"])

    def test_an_interrupt_stops_the_run_once(self, _flag, _workflow) -> None:
        run_id = self.client.post(self.runs_url, {}, format="json").json()["run_id"]

        first = self.client.post(f"{self.runs_url}{run_id}/interrupt/", {}, format="json")
        second = self.client.post(f"{self.runs_url}{run_id}/interrupt/", {}, format="json")

        self.assertEqual(first.json(), {"interrupted": True, "status": "interrupted"})
        self.assertEqual(second.json(), {"interrupted": False, "status": "interrupted"})

    def test_a_run_on_another_teams_notebook_is_not_found(self, _flag, _workflow) -> None:
        run_id = self.client.post(self.runs_url, {}, format="json").json()["run_id"]
        other = Notebook.objects.create(team=self.team, created_by=self.user, content=markdown_content("Prose.\n"))

        response = self.client.get(f"/api/projects/{self.team.id}/notebooks/{other.short_id}/runs/{run_id}/")

        self.assertEqual(response.status_code, 404)


class TestNotebookRunApiWithoutTheFlag(APIBaseTest):
    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=False)
    def test_every_run_endpoint_is_hidden(self, _flag) -> None:
        notebook = Notebook.objects.create(
            team=self.team, created_by=self.user, content=markdown_content(RUNNABLE_MARKDOWN)
        )
        base = f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/runs/"

        with self.settings(DEBUG=False):
            self.assertEqual(self.client.post(base, {}, format="json").status_code, 404)
            self.assertEqual(self.client.get(f"{base}0198f0e0-0000-7000-8000-000000000000/").status_code, 404)
            self.assertEqual(
                self.client.post(f"{base}0198f0e0-0000-7000-8000-000000000000/interrupt/", {}).status_code, 404
            )

from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from posthog.models.scoping import team_scope
from posthog.models.utils import UUIDT

from products.notebooks.backend.models import Notebook, NotebookNodeRun, NotebookRun
from products.notebooks.backend.notebook_run import node_run_request_for

_RUN_CELLS = (
    '<SQLV2 nodeId="s1" code="select 1" returnVariable="first" />\n\n'
    '<PythonV2 nodeId="p1" code="out = first.head()" returnVariable="out" />\n\n'
    '<Query nodeId="q1" query={{"kind":"SavedInsightNode","shortId":"abc"}} />\n'
)


def markdown_content(markdown: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "content": [
            {"type": "ph-markdown-notebook", "attrs": {"nodeId": "markdown-notebook-v2", "markdown": markdown}}
        ],
    }


@patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
@patch("products.notebooks.backend.presentation.views.notebook.start_notebook_run_workflow")
class TestNotebookRunEndpoints(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.notebook = Notebook.objects.create(
            team=self.team, short_id="nbrunapi", content=markdown_content(_RUN_CELLS)
        )
        self.runs_url = f"/api/projects/{self.team.id}/notebooks/{self.notebook.short_id}/runs/"

    def test_a_run_plans_only_the_runnable_cells_and_starts_the_workflow(self, mock_start, _flag) -> None:
        response = self.client.post(self.runs_url, data={}, format="json")

        assert response.status_code == 200, response.json()
        payload = response.json()
        assert payload["cell_count"] == 2
        with team_scope(self.team.id):
            notebook_run = NotebookRun.objects.get(id=payload["run_id"])
        assert [cell["node_id"] for cell in notebook_run.cell_plan] == ["s1", "p1"]
        assert mock_start.call_args.args[0].node_ids == ["s1", "p1"]

    def test_a_notebook_with_nothing_to_run_is_refused(self, mock_start, _flag) -> None:
        notebook = Notebook.objects.create(
            team=self.team, short_id="nbrunemp", content=markdown_content("# Just prose\n")
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/runs/", data={}, format="json"
        )

        assert response.status_code == 400, response.json()
        assert "nothing to run" in response.json()["detail"]
        mock_start.assert_not_called()

    def test_a_second_run_while_one_is_active_is_refused(self, _start, _flag) -> None:
        assert self.client.post(self.runs_url, data={}, format="json").status_code == 200

        response = self.client.post(self.runs_url, data={}, format="json")

        assert response.status_code == 409, response.json()

    def test_variables_are_saved_before_the_run_snapshots_them(self, _start, _flag) -> None:
        response = self.client.post(
            self.runs_url,
            data={"variables": [{"name": "country", "type": "string", "value": "US"}]},
            format="json",
        )

        assert response.status_code == 200, response.json()
        self.notebook.refresh_from_db()
        assert self.notebook.variables == [{"name": "country", "type": "string", "value": "US"}]
        with team_scope(self.team.id):
            notebook_run = NotebookRun.objects.get(id=response.json()["run_id"])
        assert notebook_run.variables == self.notebook.variables

    def test_a_refused_run_leaves_the_variables_alone(self, _start, _flag) -> None:
        # Saving them first is what lets the plan bind the caller's values, but a 409 must not
        # rewrite the notebook underneath the run already in flight.
        self.client.post(self.runs_url, data={}, format="json")

        response = self.client.post(
            self.runs_url,
            data={"variables": [{"name": "country", "type": "string", "value": "DE"}]},
            format="json",
        )

        assert response.status_code == 409, response.json()
        self.notebook.refresh_from_db()
        assert self.notebook.variables is None

    def test_the_plan_freezes_the_code_and_the_connection(self, _start, _flag) -> None:
        # The plan is the run's authority, so a cell edited after the run starts must not
        # change what it executes — notebook write and query access are separate grants.
        notebook = Notebook.objects.create(
            team=self.team,
            short_id="nbrunconn",
            content=markdown_content(
                '<SQLV2 nodeId="s1" code="select 1" returnVariable="first" '
                'connectionId="018e0e7a-9999-8888-7777-666666666666" sendRawQuery={true} />\n'
            ),
        )
        run_id = self.client.post(
            f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/runs/", data={}, format="json"
        ).json()["run_id"]

        notebook.content = markdown_content('<SQLV2 nodeId="s1" code="select 2" returnVariable="first" />\n')
        notebook.save(update_fields=["content"])

        with team_scope(self.team.id):
            notebook_run = NotebookRun.objects.get(id=run_id)
        planned = notebook_run.cell_plan[0]
        assert planned["code"] == "select 1"
        assert planned["connection_id"] == "018e0e7a-9999-8888-7777-666666666666"
        assert planned["send_raw_query"] is True

        request = node_run_request_for(notebook_run, 0)
        assert request.code == "select 1"
        assert str(request.connection_id) == "018e0e7a-9999-8888-7777-666666666666"
        assert request.send_raw_query is True

    def test_status_reports_every_planned_cell_and_the_one_in_flight(self, _start, _flag) -> None:
        run_id = self.client.post(self.runs_url, data={}, format="json").json()["run_id"]
        with team_scope(self.team.id):
            notebook_run = NotebookRun.objects.get(id=run_id)
            node_run = NotebookNodeRun.objects.create(
                team=self.team,
                notebook=self.notebook,
                notebook_run=notebook_run,
                node_id="s1",
                code="select 1",
                status=NotebookNodeRun.Status.DONE,
            )

        payload = self.client.get(f"{self.runs_url}{run_id}/").json()

        assert payload["status"] == "running"
        assert payload["cell_count"] == 2
        assert payload["current_node_id"] == "s1"
        assert [(cell["node_id"], cell["status"]) for cell in payload["cells"]] == [("s1", "done"), ("p1", None)]
        assert payload["cells"][0]["run_id"] == str(node_run.id)

    def test_a_cell_error_from_an_unreachable_source_is_withheld(self, _start, _flag) -> None:
        # Notebook plus query access does not imply source access, and an engine error can
        # carry its own detail. The cell-result endpoint refuses outright; this one serves
        # many cells, so it drops the error and keeps the rest readable.
        run_id = self.client.post(self.runs_url, data={}, format="json").json()["run_id"]
        source_id = UUIDT()
        with team_scope(self.team.id):
            notebook_run = NotebookRun.objects.get(id=run_id)
            NotebookNodeRun.objects.create(
                team=self.team,
                notebook=self.notebook,
                notebook_run=notebook_run,
                node_id="s1",
                code="select 1",
                connection_id=source_id,
                status=NotebookNodeRun.Status.FAILED,
                error='relation "secret_table" does not exist',
            )

        with patch(
            "products.notebooks.backend.presentation.views.notebook.get_direct_connection_source",
            return_value=None,
        ):
            withheld = self.client.get(f"{self.runs_url}{run_id}/").json()
        with patch(
            "products.notebooks.backend.presentation.views.notebook.get_direct_connection_source",
            return_value=object(),
        ):
            allowed = self.client.get(f"{self.runs_url}{run_id}/").json()

        assert withheld["cells"][0]["status"] == "failed"
        assert withheld["cells"][0]["error"] is None
        assert allowed["cells"][0]["error"] == 'relation "secret_table" does not exist'

    def test_interrupt_stops_the_run_and_is_idempotent(self, _start, _flag) -> None:
        run_id = self.client.post(self.runs_url, data={}, format="json").json()["run_id"]

        first = self.client.post(f"{self.runs_url}{run_id}/interrupt/")
        second = self.client.post(f"{self.runs_url}{run_id}/interrupt/")

        assert first.json() == {"interrupted": True, "status": "interrupted"}
        assert second.json() == {"interrupted": False, "status": "interrupted"}

    def test_a_stopped_run_leaves_the_notebook_free_to_run_again(self, _start, _flag) -> None:
        run_id = self.client.post(self.runs_url, data={}, format="json").json()["run_id"]
        self.client.post(f"{self.runs_url}{run_id}/interrupt/")

        assert self.client.post(self.runs_url, data={}, format="json").status_code == 200


class TestNotebookRunEndpointsBehindTheFlag(APIBaseTest):
    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=False)
    def test_the_run_endpoint_is_invisible_without_the_flag(self, _flag) -> None:
        notebook = Notebook.objects.create(team=self.team, short_id="nbrunoff", content=markdown_content(_RUN_CELLS))

        with self.settings(DEBUG=False):
            response = self.client.post(
                f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/runs/", data={}, format="json"
            )

        assert response.status_code == 404

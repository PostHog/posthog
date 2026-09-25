from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.db import connection
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized
from temporalio.exceptions import ApplicationError

from posthog.models.scoping import team_scope
from posthog.models.utils import UUIDT

from products.notebooks.backend.models import Notebook, NotebookNodeRun, NotebookRun
from products.notebooks.backend.notebook_run import node_run_request_for, plan_notebook_cells
from products.notebooks.backend.sql_v2_state import MAX_NOTEBOOK_CELLS, NotebookCellLimitExceeded
from products.notebooks.backend.temporal.notebook_run import (
    NotebookRunCellInput,
    NotebookRunInput,
    dispatch_notebook_cell_activity,
    read_notebook_run_status_activity,
)
from products.notebooks.backend.temporal.sql_v2 import SQLV2RunInput, dispatch_sql_v2_run_activity

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


class TestRunPlanCellShapes(APIBaseTest):
    """A SQL cell can hold its SQL in `query` rather than `code`, and the editor renders all
    of these. A run that planned only `code` cells skipped them without saying so."""

    @parameterized.expand(
        [
            ("raw_string", '<SQLV2 nodeId="s1" query="select 1" />'),
            ("prepared_insight", '<Query nodeId="s1" dataframeQuery="select 1" returnVariable="insight_df" />'),
            ("bare_hogql", '<SQLV2 nodeId="s1" query={{"kind":"HogQLQuery","query":"select 1"}} />'),
            (
                "wrapped_in_a_data_table",
                '<SQLV2 nodeId="s1" query={{"kind":"DataTableNode","source":{"kind":"HogQLQuery","query":"select 1"}}} />',
            ),
        ]
    )
    def test_a_sql_cell_carrying_its_query_prop_is_planned(self, _name: str, tag: str) -> None:
        notebook = Notebook(team=self.team, short_id="nbshape", content=markdown_content(f"# Doc\n\n{tag}\n"))

        plan = plan_notebook_cells(notebook, include_prepared_insights=True)
        assert [cell["node_id"] for cell in plan] == ["s1"]
        assert plan[0]["code"] == "select 1"
        assert plan[0]["cell_type"] == "sql"

    def test_prepared_insights_do_not_change_the_default_run_or_cell_limit(self) -> None:
        notebook = Notebook(
            team=self.team,
            content=markdown_content(
                '<SQLV2 nodeId="sql" code="select 1" />\n\n'
                + "\n\n".join(f'<Query nodeId="q{i}" dataframeQuery="select 1" />' for i in range(MAX_NOTEBOOK_CELLS))
            ),
        )
        assert [cell["node_id"] for cell in plan_notebook_cells(notebook)] == ["sql"]
        with self.assertRaises(NotebookCellLimitExceeded):
            plan_notebook_cells(notebook, include_prepared_insights=True)

    def test_code_still_wins_when_a_cell_carries_both(self) -> None:
        notebook = Notebook(
            team=self.team,
            short_id="nbshape2",
            content=markdown_content(
                '<SQLV2 nodeId="s1" code="select 2" query={{"kind":"HogQLQuery","query":"select 1"}} />\n'
            ),
        )

        assert plan_notebook_cells(notebook)[0]["code"] == "select 2"


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

    @parameterized.expand([(False, 404), (True, 200)])
    def test_prepared_insights_require_explicit_opt_in_and_widget_flag(
        self, mock_start: MagicMock, _flag: MagicMock, enabled: bool, expected_status: int
    ) -> None:
        self.notebook.content = markdown_content('<Query nodeId="insight" dataframeQuery="select 1" />')
        self.notebook.save(update_fields=["content"])
        with patch(
            "products.notebooks.backend.presentation.views.notebook.is_notebook_widget_enabled", return_value=enabled
        ):
            response = self.client.post(self.runs_url, data={"include_prepared_insights": True}, format="json")
        assert response.status_code == expected_status
        if enabled:
            assert response.json()["cell_count"] == 1
            assert mock_start.call_args.args[0].node_ids == ["insight"]
        else:
            mock_start.assert_not_called()

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

    @parameterized.expand([("at_limit", MAX_NOTEBOOK_CELLS, 200), ("over_limit", MAX_NOTEBOOK_CELLS + 1, 400)])
    def test_prepared_insights_obey_the_run_limit(
        self, mock_start: MagicMock, _flag: MagicMock, _name: str, count: int, status: int
    ) -> None:
        self.notebook.content = markdown_content(
            "\n\n".join(
                [
                    '<PythonV2 nodeId="python" code="print(1)" />',
                    '<Insight nodeId="display" id="example" />',
                    *(
                        f'<Query nodeId="i{index}" dataframeQuery="select 1" returnVariable="df_{index}" />'
                        for index in range(count - 1)
                    ),
                ]
            )
        )
        self.notebook.save(update_fields=["content"])
        with patch(
            "products.notebooks.backend.presentation.views.notebook.is_notebook_widget_enabled", return_value=True
        ):
            response = self.client.post(
                self.runs_url,
                data={
                    "include_prepared_insights": True,
                    "variables": [{"name": "country", "type": "string", "value": "US"}],
                },
                format="json",
            )
        assert response.status_code == status, response.json()
        if status == 200:
            assert response.json()["cell_count"] == count
        else:
            mock_start.assert_not_called()
            assert not NotebookRun.objects.for_team(self.team.id).filter(notebook=self.notebook).exists()
            self.notebook.refresh_from_db()
            assert self.notebook.variables is None

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

    def test_the_status_read_never_fetches_a_cell_result(self, _start, _flag) -> None:
        # The response carries no result envelopes, and must not pay for them either: a client
        # polls this every two seconds while the last cell runs, and a notebook may hold fifty
        # cells whose envelopes each run to megabytes.
        run_id = self.client.post(self.runs_url, data={}, format="json").json()["run_id"]
        with team_scope(self.team.id):
            NotebookNodeRun.objects.create(
                team=self.team,
                notebook=self.notebook,
                notebook_run=NotebookRun.objects.get(id=run_id),
                node_id="s1",
                code="select 1",
                envelope={"first_page": [["x" * 10_000]]},
                status=NotebookNodeRun.Status.DONE,
            )

        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(f"{self.runs_url}{run_id}/")

        assert response.status_code == 200, response.json()
        node_run_reads = [q["sql"] for q in captured.captured_queries if "posthog_notebooknoderun" in q["sql"]]
        assert node_run_reads, "expected the status read to query the cell runs at all"
        for sql in node_run_reads:
            assert "envelope" not in sql, sql

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

    @patch("products.notebooks.backend.sql_v2_dispatch.enqueue_direct_run")
    def test_a_retried_dispatch_reuses_the_cell_it_already_started(self, mock_enqueue, _start, _flag) -> None:
        # The worker can die between handing the cell off and Temporal recording the result, so
        # the activity runs again. It must recover the run it already started rather than
        # execute the cell a second time, which for a Python cell repeats its side effects.
        run_id = self.client.post(self.runs_url, data={}, format="json").json()["run_id"]
        cell = NotebookRunCellInput(notebook_run_id=run_id, team_id=self.team.id, index=0)

        first = dispatch_notebook_cell_activity(cell)
        # The query manager holds the query the first attempt submitted, which is how the
        # retry tells a landed handoff from one that never reached the lane.
        with patch("products.notebooks.backend.sql_v2_dispatch.direct_run_was_enqueued", return_value=True):
            second = dispatch_notebook_cell_activity(cell)

        assert first == second
        assert mock_enqueue.call_count == 1, "the retry submitted the query a second time"
        assert NotebookNodeRun.objects.for_team(self.team.id).filter(notebook_run_id=run_id).count() == 1

    @patch("products.notebooks.backend.sql_v2_dispatch.enqueue_direct_run")
    def test_a_retry_finishes_a_dispatch_that_never_reached_its_lane(self, mock_enqueue, _start, _flag) -> None:
        # The row is committed before the lane is told about it, so a worker that dies in
        # between leaves a row nothing drives. Finding that row is not proof the cell started:
        # the retry has to complete the handoff, or the orchestrator polls it until the cell
        # budget expires and fails a run whose cell never ran.
        run_id = self.client.post(self.runs_url, data={}, format="json").json()["run_id"]
        with team_scope(self.team.id):
            orphan = NotebookNodeRun.objects.create(
                team=self.team,
                notebook=self.notebook,
                notebook_run=NotebookRun.objects.get(id=run_id),
                node_id="s1",
                code="select 1",
                status=NotebookNodeRun.Status.RUNNING,
            )

        returned = dispatch_notebook_cell_activity(
            NotebookRunCellInput(notebook_run_id=run_id, team_id=self.team.id, index=0)
        )

        assert returned == str(orphan.id)
        assert mock_enqueue.call_count == 1, "the retry left the row undispatched"
        assert str(mock_enqueue.call_args.args[2].id) == str(orphan.id)
        # Still one row: resuming must not become a second execution.
        assert NotebookNodeRun.objects.for_team(self.team.id).filter(notebook_run_id=run_id).count() == 1

    @patch("products.notebooks.backend.notebook_run.interrupt_sql_v2_run", return_value=False)
    def test_stopping_a_cell_the_kernel_never_received_still_cancels_it(self, _interrupt, _start, _flag) -> None:
        # The interrupt returns False when the dispatch is still queued: there is nothing at
        # the kernel to stop. Left RUNNING the cell would start after the user was told the
        # run had stopped, and a second Stop returns early because the parent is terminal.
        run_id = self.client.post(self.runs_url, data={}, format="json").json()["run_id"]
        with team_scope(self.team.id):
            cell = NotebookNodeRun.objects.create(
                team=self.team,
                notebook=self.notebook,
                notebook_run=NotebookRun.objects.get(id=run_id),
                node_id="p1",
                code="print(1)",
                node_type=NotebookNodeRun.NodeType.PYTHON,
                status=NotebookNodeRun.Status.RUNNING,
            )

        assert self.client.post(f"{self.runs_url}{run_id}/interrupt/").status_code == 200

        cell.refresh_from_db()
        assert cell.status == NotebookNodeRun.Status.INTERRUPTED

    def test_a_queued_dispatch_refuses_a_cell_that_was_stopped(self, _start, _flag) -> None:
        # The other half: the row's status is the cancellation, and the sandbox dispatch is
        # the last point before the code leaves for the kernel, so it has to read it. It also
        # provisions a kernel when none is up, so running on would bill for the stopped cell.
        run_id = self.client.post(self.runs_url, data={}, format="json").json()["run_id"]
        with team_scope(self.team.id):
            cell = NotebookNodeRun.objects.create(
                team=self.team,
                notebook=self.notebook,
                notebook_run=NotebookRun.objects.get(id=run_id),
                node_id="p1",
                code="print(1)",
                node_type=NotebookNodeRun.NodeType.PYTHON,
                status=NotebookNodeRun.Status.INTERRUPTED,
            )

        with patch("products.notebooks.backend.temporal.sql_v2.dispatch_sql_v2_run") as mock_dispatch:
            dispatch_sql_v2_run_activity(
                SQLV2RunInput(
                    run_id=str(cell.id),
                    notebook_short_id=self.notebook.short_id,
                    team_id=self.team.id,
                    code="print(1)",
                    node_type="python",
                )
            )

        mock_dispatch.assert_not_called()

    def test_interrupt_stops_the_run_and_is_idempotent(self, _start, _flag) -> None:
        run_id = self.client.post(self.runs_url, data={}, format="json").json()["run_id"]

        first = self.client.post(f"{self.runs_url}{run_id}/interrupt/")
        second = self.client.post(f"{self.runs_url}{run_id}/interrupt/")

        assert first.json() == {"interrupted": True, "status": "interrupted"}
        assert second.json() == {"interrupted": False, "status": "interrupted"}

    @parameterized.expand(
        [
            ("poll_sql", "poll", NotebookNodeRun.NodeType.HOGQL),
            ("poll_python", "poll", NotebookNodeRun.NodeType.PYTHON),
            ("dispatch_sql", "dispatch", NotebookNodeRun.NodeType.HOGQL),
            ("dispatch_python", "dispatch", NotebookNodeRun.NodeType.PYTHON),
        ]
    )
    def test_deleting_the_notebook_stops_its_run_and_child(
        self, _name: str, phase: str, node_type: str, _start: MagicMock, _flag: MagicMock
    ) -> None:
        run_id = self.client.post(self.runs_url, data={}, format="json").json()["run_id"]
        cell = NotebookNodeRun.objects.for_team(self.team.id).create(
            team=self.team,
            notebook=self.notebook,
            notebook_run_id=run_id,
            node_id="s1",
            code="select 1",
            node_type=node_type,
            status=NotebookNodeRun.Status.RUNNING,
        )
        self.notebook.deleted = True
        self.notebook.save(update_fields=["deleted"])
        inputs = NotebookRunInput(notebook_run_id=run_id, team_id=self.team.id, node_ids=["s1", "p1"])

        with (
            patch("products.notebooks.backend.notebook_run.cancel_direct_run"),
            patch("products.notebooks.backend.notebook_run.interrupt_sql_v2_run", return_value=False),
            patch("products.notebooks.backend.sql_v2_dispatch.enqueue_direct_run") as enqueue,
        ):
            if phase == "dispatch":
                with self.assertRaises(ApplicationError) as raised:
                    dispatch_notebook_cell_activity(
                        NotebookRunCellInput(notebook_run_id=run_id, team_id=self.team.id, index=0)
                    )
                assert raised.exception.non_retryable
            assert read_notebook_run_status_activity(inputs) == NotebookRun.Status.INTERRUPTED
            assert read_notebook_run_status_activity(inputs) == NotebookRun.Status.INTERRUPTED

        enqueue.assert_not_called()
        cell.refresh_from_db()
        assert cell.status == NotebookNodeRun.Status.INTERRUPTED
        run = NotebookRun.objects.for_team(self.team.id).get(id=run_id)
        assert run.finished_at is not None
        assert run.error == "The notebook was deleted."

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

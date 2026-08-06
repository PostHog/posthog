from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from products.notebooks.backend.models import Notebook, NotebookNodeRun
from products.notebooks.backend.sql_v2_references import resolve_sql_v2_references
from products.notebooks.backend.sql_v2_state import build_dependency_edges, build_notebook_cell_state, extract_cells


def markdown_content(markdown: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "content": [
            {"type": "ph-markdown-notebook", "attrs": {"nodeId": "markdown-notebook-v2", "markdown": markdown}}
        ],
    }


class TestCellExtractionAndEdges(SimpleTestCase):
    def test_extracts_runnable_cells_and_skips_unknown_or_idless_tags(self) -> None:
        content = markdown_content(
            "# Doc\n\n"
            '<SQLV2 nodeId="s1" code="select 1" returnVariable="df" />\n\n'
            '<PythonV2 nodeId="p1" code="out = df.head()" returnVariable="out" />\n\n'
            '<Query nodeId="q1" query={{"kind":"SavedInsightNode","shortId":"abc"}} />\n\n'
            '<SQLV2 code="select 2" returnVariable="anon" />\n\n'
            '<RevenueCard metric="arr" />\n'
        )
        cells = extract_cells(content)
        assert [(c.node_id, c.cell_type, c.dataframe_name) for c in cells] == [
            ("s1", "sql", "df"),
            ("p1", "python", "out"),
            ("q1", "saved_insight", ""),
        ]

    def test_rich_text_content_yields_no_cells(self) -> None:
        assert extract_cells({"type": "doc", "content": [{"type": "paragraph"}]}) == []

    @parameterized.expand(
        [
            # SQL reference is found by parsing, not substring: quoted/aliased names don't count.
            ("sql_parse", '<SQLV2 nodeId="b" code="select * from df" returnVariable="" />', ["a"]),
            # A CTE named like the sibling shadows it — no edge.
            ("cte_shadow", '<SQLV2 nodeId="b" code="with df as (select 1) select * from df" returnVariable="" />', []),
            # Python deps come from globals analysis, so a comment mention is not an edge.
            ("python_comment", '<PythonV2 nodeId="b" code="# df\\nx = 1" returnVariable="" />', []),
            ("python_use", '<PythonV2 nodeId="b" code="x = df.head()" returnVariable="" />', ["a"]),
        ]
    )
    def test_dependency_edges(self, _name: str, downstream_tag: str, expected_depends_on: list[str]) -> None:
        content = markdown_content(f'<SQLV2 nodeId="a" code="select 1" returnVariable="df" />\n\n{downstream_tag}\n')
        cells = extract_cells(content)
        build_dependency_edges(cells)
        assert cells[1].depends_on == expected_depends_on
        assert cells[0].dependents == (["b"] if expected_depends_on else [])

    def test_sql_wins_dataframe_name_collision(self) -> None:
        content = markdown_content(
            '<PythonV2 nodeId="p" code="df = 1" returnVariable="df" />\n\n'
            '<SQLV2 nodeId="s" code="select 1" returnVariable="df" />\n\n'
            '<SQLV2 nodeId="user" code="select * from df" returnVariable="" />\n'
        )
        cells = extract_cells(content)
        build_dependency_edges(cells)
        assert cells[2].depends_on == ["s"]


class TestNotebookCellState(APIBaseTest):
    def _notebook(self, markdown: str) -> Notebook:
        return Notebook.objects.create(team=self.team, created_by=self.user, content=markdown_content(markdown))

    def _run(self, notebook: Notebook, node_id: str, code: str, run_status: str, node_type: str = "hogql") -> None:
        NotebookNodeRun.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            notebook=notebook,
            user=self.user,
            node_id=node_id,
            code=code,
            node_type=node_type,
            status=run_status,
        )

    @parameterized.expand(
        [
            ("never_run", None, "never_run"),
            ("running", NotebookNodeRun.Status.RUNNING, "running"),
            ("failed", NotebookNodeRun.Status.FAILED, "failed"),
            ("done_matches", NotebookNodeRun.Status.DONE, "done"),
        ]
    )
    def test_python_cell_status_reflects_latest_run(self, _name: str, run_status: str | None, expected: str) -> None:
        notebook = self._notebook('<PythonV2 nodeId="p" code="x = 1" returnVariable="x" />')
        if run_status is not None:
            self._run(notebook, "p", "x = 1", run_status, node_type="python")
        cells = build_notebook_cell_state(self.team.id, notebook)
        assert cells[0].status == expected

    def test_python_cell_goes_stale_on_code_edit_or_newer_upstream_run(self) -> None:
        notebook = self._notebook(
            '<SQLV2 nodeId="s" code="select 1" returnVariable="df" />\n\n'
            '<PythonV2 nodeId="p" code="x = df.head()" returnVariable="x" />'
        )
        self._run(notebook, "s", "select 1", NotebookNodeRun.Status.DONE)
        self._run(notebook, "p", "x = df.head()", NotebookNodeRun.Status.DONE, node_type="python")
        assert build_notebook_cell_state(self.team.id, notebook)[1].status == "done"

        # The upstream re-runs after this cell's run: the input frame changed underneath it.
        self._run(notebook, "s", "select 1", NotebookNodeRun.Status.DONE)
        assert build_notebook_cell_state(self.team.id, notebook)[1].status == "stale"

    def test_sql_cell_goes_stale_when_resolution_diverges_from_last_run(self) -> None:
        notebook = self._notebook(
            '<SQLV2 nodeId="up" code="select 1 as x" returnVariable="df" />\n\n'
            '<SQLV2 nodeId="down" code="select * from df" returnVariable="" />'
        )
        self._run(notebook, "up", "select 1 as x", NotebookNodeRun.Status.DONE)
        resolved = resolve_sql_v2_references("select * from df", {"df": "select 1 as x"})
        self._run(notebook, "down", resolved, NotebookNodeRun.Status.DONE)
        assert build_notebook_cell_state(self.team.id, notebook)[1].status == "done"

        # Editing the upstream definition changes what the downstream would resolve to now.
        self._run(notebook, "up", "select 2 as x", NotebookNodeRun.Status.DONE)
        assert build_notebook_cell_state(self.team.id, notebook)[1].status == "stale"

    def test_sql_cell_referencing_never_run_upstream_is_stale(self) -> None:
        notebook = self._notebook(
            '<SQLV2 nodeId="up" code="select 1" returnVariable="df" />\n\n'
            '<SQLV2 nodeId="down" code="select * from df" returnVariable="" />'
        )
        self._run(notebook, "down", "select * from df", NotebookNodeRun.Status.DONE)
        assert build_notebook_cell_state(self.team.id, notebook)[1].status == "stale"

    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    def test_state_endpoint_returns_cells_and_kernel(self, _mock_enabled) -> None:
        notebook = self._notebook(
            '<SQLV2 nodeId="s" code="select 1" returnVariable="df" />\n\n'
            '<PythonV2 nodeId="p" code="x = df.head()" returnVariable="x" />'
        )
        self._run(notebook, "s", "select 1", NotebookNodeRun.Status.DONE)

        response = self.client.get(f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/sql_v2/state/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["notebook_id"] == notebook.short_id
        assert '<SQLV2 nodeId="s"' in data["markdown"]
        assert data["content"] is None
        assert data["kernel"]["status"] == "stopped"
        by_node = {cell["node_id"]: cell for cell in data["cells"]}
        assert by_node["s"]["status"] == "done"
        assert by_node["s"]["dependents"] == ["p"]
        assert by_node["p"]["status"] == "never_run"
        assert by_node["p"]["depends_on"] == ["s"]
        assert by_node["s"]["last_run"]["run_id"]

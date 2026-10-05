from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.notebooks.backend.models import Notebook
from products.notebooks.backend.notebook_run import plan_notebook_cells
from products.notebooks.backend.sql_v2_state import MAX_NOTEBOOK_CELLS, NotebookCellLimitExceeded


def markdown_content(markdown: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "content": [
            {"type": "ph-markdown-notebook", "attrs": {"nodeId": "markdown-notebook-v2", "markdown": markdown}}
        ],
    }


class TestRunPlanCellShapes(SimpleTestCase):
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
        notebook = Notebook(team_id=1, short_id="nbshape", content=markdown_content(f"# Doc\n\n{tag}\n"))

        plan = plan_notebook_cells(notebook, include_prepared_insights=True)
        assert [cell["node_id"] for cell in plan] == ["s1"]
        assert plan[0]["code"] == "select 1"
        assert plan[0]["cell_type"] == "sql"

    def test_prepared_insights_do_not_change_the_default_run_or_cell_limit(self) -> None:
        notebook = Notebook(
            team_id=1,
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
            team_id=1,
            short_id="nbshape2",
            content=markdown_content(
                '<SQLV2 nodeId="s1" code="select 2" query={{"kind":"HogQLQuery","query":"select 1"}} />\n'
            ),
        )

        assert plan_notebook_cells(notebook)[0]["code"] == "select 2"

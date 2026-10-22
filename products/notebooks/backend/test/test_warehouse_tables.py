from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.data_warehouse.backend.facade.api import NotebookTableError
from products.notebooks.backend.models import Notebook, NotebookNodeRun
from products.notebooks.backend.warehouse_tables import finish_warehouse_table_save


class TestFinishWarehouseTableSave(BaseTest):
    @parameterized.expand(
        [
            ("saved", None, {"name": "scores", "error": None}, True),
            ("refused", NotebookTableError("Name taken."), {"name": "scores", "error": "Name taken."}, False),
            (
                "crashed",
                RuntimeError("boom"),
                {"name": "scores", "error": "The warehouse table couldn't be saved."},
                False,
            ),
        ]
    )
    def test_stores_the_outcome_on_the_run(self, _name, save_error, expected, synced):
        notebook = Notebook.objects.create(team=self.team, short_id="nbwh01")
        with team_scope(self.team.id):
            run = NotebookNodeRun.objects.create(
                team=self.team,
                notebook=notebook,
                user=self.user,
                node_id="cell-1",
                status=NotebookNodeRun.Status.DONE,
                warehouse_table_name="scores",
                envelope={"status": "ok", "warehouse_table": {"name": "scores", "error": None, "pending": True}},
            )
        with (
            patch(
                "products.notebooks.backend.warehouse_tables.save_notebook_table",
                side_effect=save_error,
                return_value="table-id",
            ) as save,
            patch("products.notebooks.backend.warehouse_tables.sync_notebook_table_to_dag") as sync_to_dag,
        ):
            finish_warehouse_table_save(self.team.id, str(run.id))

        save.assert_called_once_with(self.team.id, "scores", self.user.id, str(run.id))
        run = NotebookNodeRun.objects.for_team(self.team.id).get(id=run.id)
        self.assertEqual(run.envelope, {"status": "ok", "warehouse_table": expected})
        self.assertEqual(sync_to_dag.called, synced)
        if synced:
            sync_to_dag.assert_called_once_with(self.team.id, "scores", "table-id", [], "nbwh01", "cell-1")

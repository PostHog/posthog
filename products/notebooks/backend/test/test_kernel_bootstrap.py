import os
import tempfile

from django.test import SimpleTestCase

import pyarrow as pa

from products.notebooks.backend.sandbox.kernel.bootstrap import _MEDIA_MAX_FIGURES, KernelSession


class TestKernelSessionRunNode(SimpleTestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.session = KernelSession(data_dir=self._dir.name)

    def _write_frame(self, name: str, table: pa.Table) -> str:
        path = os.path.join(self._dir.name, "frames", f"{name}.arrow")
        with pa.OSFile(path, "wb") as sink:
            with pa.ipc.new_file(sink, table.schema) as writer:
                writer.write_table(table)
        return path

    def _run(self, code: str, inputs=None, output_name=None) -> dict:
        return self.session.run_node(
            {"node": {"type": "python", "code": code, "output_name": output_name}, "inputs": inputs or []}
        )

    def test_dataframe_last_expression_is_previewed(self):
        envelope = self._run("import pandas as pd\npd.DataFrame({'a': [1, 2], 'b': [3, 4]})")
        self.assertEqual(envelope["status"], "ok")
        self.assertEqual(envelope["columns"], ["a", "b"])
        self.assertEqual(envelope["first_page"], [[1, 3], [2, 4]])
        self.assertEqual(envelope["row_count"], 2)

    def test_output_name_frame_is_previewed_over_last_expression(self):
        envelope = self._run("import pandas as pd\nresult = pd.DataFrame({'x': [9]})\n1 + 1", output_name="result")
        self.assertEqual(envelope["columns"], ["x"])
        self.assertEqual(envelope["first_page"], [[9]])

    def test_row_count_and_has_more_reflect_the_full_frame(self):
        envelope = self.session.run_node(
            {"node": {"code": "import pandas as pd\npd.DataFrame({'n': range(120)})"}, "page_limit": 50}
        )
        self.assertEqual(envelope["row_count"], 120)
        self.assertEqual(len(envelope["first_page"]), 50)
        self.assertTrue(envelope["has_more"])

    def test_stdout_is_captured(self):
        envelope = self._run("print('hello from the kernel')")
        self.assertIn("hello from the kernel", envelope["stdout"])
        self.assertEqual(envelope["columns"], [])

    def test_matplotlib_figure_is_captured_as_png(self):
        envelope = self._run("import matplotlib.pyplot as plt\nplt.plot([1, 2, 3])")
        self.assertEqual(len(envelope["media"]), 1)
        self.assertEqual(envelope["media"][0]["mime_type"], "image/png")
        self.assertTrue(envelope["media"][0]["data"])

    def test_exception_surfaces_as_error_envelope(self):
        envelope = self._run("raise ValueError('boom')")
        self.assertEqual(envelope["status"], "error")
        self.assertIn("ValueError: boom", envelope["error"])

    def test_syntax_error_surfaces_as_error_envelope(self):
        # run_cell reports compile errors via error_before_exec (error_in_exec stays None);
        # they must not masquerade as a successful empty run stored as DONE.
        envelope = self._run("def = 1")
        self.assertEqual(envelope["status"], "error")
        self.assertIn("SyntaxError", envelope["error"])

    def test_hogql_input_is_bound_as_a_pandas_frame(self):
        # The server streams a CH result to a local Arrow file; the kernel must expose it as
        # a pandas frame the node code can filter — this is the Journey 4 materialization step.
        self._write_frame("df1", pa.table({"id": [1, 2, 3], "v": [10, 20, 30]}))
        path = os.path.join(self._dir.name, "frames", "df1.arrow")
        envelope = self._run("df1[df1.id > 1]", inputs=[{"name": "df1", "kind": "hogql", "path": path}])
        self.assertEqual(envelope["status"], "ok")
        self.assertEqual(envelope["columns"], ["id", "v"])
        self.assertEqual(envelope["first_page"], [[2, 20], [3, 30]])

    def test_missing_local_input_produces_a_clear_error(self):
        envelope = self._run("1 + 1", inputs=[{"name": "never_made", "kind": "local"}])
        self.assertEqual(envelope["status"], "error")
        self.assertIn("never_made", envelope["error"])

    def test_oversized_stdout_is_truncated(self):
        envelope = self._run("print('x' * 100_000)")
        self.assertLess(len(envelope["stdout"]), 33_000)
        self.assertIn("[output truncated", envelope["stdout"])

    def test_oversized_preview_cells_are_clipped(self):
        envelope = self._run("import pandas as pd\npd.DataFrame({'s': ['y' * 50_000]})")
        cell = envelope["first_page"][0][0]
        self.assertLessEqual(len(cell), 10_001)
        self.assertTrue(cell.endswith("…"))
        self.assertEqual(envelope["row_count"], 1)

    def test_figures_beyond_the_media_cap_are_omitted(self):
        envelope = self._run(
            "import matplotlib.pyplot as plt\n"
            f"for i in range({_MEDIA_MAX_FIGURES + 1}):\n"
            "    plt.figure()\n"
            "    plt.plot([1, i])\n"
        )
        self.assertEqual(envelope["status"], "ok")
        self.assertEqual(len(envelope["media"]), _MEDIA_MAX_FIGURES)
        self.assertIn("1 figure(s) omitted", envelope["stderr"])

    def _run_duckdb(self, code: str, inputs=None, output_name=None) -> dict:
        return self.session.run_node(
            {"node": {"type": "duckdb", "code": code, "output_name": output_name}, "inputs": inputs or []}
        )

    def test_duckdb_node_joins_a_hogql_frame_with_a_local_frame(self):
        # Journey 5 step 4: the local frame forces the join into DuckDB, over the mmapped
        # HogQL input and the pandas frame a Python node left in the namespace.
        path = self._write_frame("df2", pa.table({"id": [1, 2, 3], "name": ["a", "b", "c"]}))
        self._run("import pandas as pd\nnew_events = pd.DataFrame({'id': [2, 3], 'n': [20, 30]})")
        envelope = self._run_duckdb(
            "select df2.id, df2.name, new_events.n from df2 join new_events on df2.id = new_events.id order by df2.id",
            inputs=[{"name": "df2", "kind": "hogql", "path": path}, {"name": "new_events", "kind": "local"}],
            output_name="joined",
        )
        self.assertEqual(envelope["status"], "ok")
        self.assertEqual(envelope["columns"], ["id", "name", "n"])
        self.assertEqual(envelope["first_page"], [[2, "b", 20], [3, "c", 30]])
        self.assertTrue(envelope["result_id"])  # frame written for /page slicing

    def test_duckdb_output_is_usable_by_a_following_python_node(self):
        self._run("import pandas as pd\nnew_events = pd.DataFrame({'id': [1, 2]})")
        self._run_duckdb(
            "select id * 10 as scaled from new_events",
            inputs=[{"name": "new_events", "kind": "local"}],
            output_name="scaled_df",
        )
        envelope = self._run("scaled_df[scaled_df.scaled > 10]", inputs=[{"name": "scaled_df", "kind": "local"}])
        self.assertEqual(envelope["status"], "ok")
        self.assertEqual(envelope["first_page"], [[20]])

    def test_duckdb_rerun_sees_the_local_frames_current_value(self):
        # Re-registration per run: an updated upstream frame must not leave SQL reading the old one.
        self._run("import pandas as pd\nnew_events = pd.DataFrame({'id': [1]})")
        first = self._run_duckdb(
            "select count(*) as c from new_events", inputs=[{"name": "new_events", "kind": "local"}]
        )
        self._run("import pandas as pd\nnew_events = pd.DataFrame({'id': [1, 2, 3]})")
        second = self._run_duckdb(
            "select count(*) as c from new_events", inputs=[{"name": "new_events", "kind": "local"}]
        )
        self.assertEqual(first["first_page"], [[1]])
        self.assertEqual(second["first_page"], [[3]])

    def test_duckdb_error_surfaces_as_error_envelope(self):
        envelope = self._run_duckdb("select * from a_table_that_does_not_exist")
        self.assertEqual(envelope["status"], "error")
        self.assertIn("a_table_that_does_not_exist", envelope["error"])

    def test_duckdb_over_a_name_rebound_to_a_non_frame_errors_instead_of_reading_stale_rows(self):
        # The first run registers the frame in DuckDB; the rebind must not leave SQL silently
        # reading that stale registration — it must fail clearly.
        self._run("import pandas as pd\nnew_events = pd.DataFrame({'id': [1]})")
        self._run_duckdb("select * from new_events", inputs=[{"name": "new_events", "kind": "local"}])
        self._run("new_events = 5")
        envelope = self._run_duckdb("select * from new_events", inputs=[{"name": "new_events", "kind": "local"}])
        self.assertEqual(envelope["status"], "error")
        self.assertIn("not a dataframe", envelope["error"])

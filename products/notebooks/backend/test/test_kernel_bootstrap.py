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

import os
import json
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

    def test_keyboard_interrupt_surfaces_as_interrupted_with_captured_output(self):
        # A SIGINT lands in run_cell as KeyboardInterrupt: the run is `interrupted`, not a
        # red failure, and the output captured before the stop still ships in the envelope.
        envelope = self._run("print('partial output')\nraise KeyboardInterrupt")
        self.assertEqual(envelope["status"], "interrupted")
        self.assertEqual(envelope["error"], "Run interrupted.")
        self.assertIn("partial output", envelope["stdout"])

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

    def test_binary_column_degrades_the_preview_instead_of_failing_the_run(self):
        # ClickHouse's native Arrow output emits UUID/FixedString columns as fixed-size
        # binary, so a materialized frame can hold raw bytes. pandas' ujson preview encoder
        # raises OverflowError on them — that must degrade the display cell, not fail a run
        # whose compute succeeded (the incident: "kernel did not return a result").
        binary_column = pa.array([b"\x01" * 16, b"\xff" * 16], type=pa.binary(16))
        self._write_frame("df1", pa.table({"uid": binary_column, "v": [1, 2]}))
        path = os.path.join(self._dir.name, "frames", "df1.arrow")
        envelope = self._run("df1", inputs=[{"name": "df1", "kind": "hogql", "path": path}])
        self.assertEqual(envelope["status"], "ok")
        self.assertEqual(envelope["row_count"], 2)
        self.assertEqual(envelope["first_page"][0][1], 1)
        self.assertIsInstance(envelope["first_page"][0][0], str)  # degraded, JSON-safe cell

    def test_missing_local_input_produces_a_clear_error(self):
        envelope = self._run("1 + 1", inputs=[{"name": "never_made", "kind": "local"}])
        self.assertEqual(envelope["status"], "error")
        self.assertIn("never_made", envelope["error"])

    def test_python_output_name_binds_the_result_for_downstream_nodes(self):
        # Journey 5 step 3: the cell's code never assigns the output name itself — the
        # kernel must bind the last-expression frame so a later SQL node can read it.
        self._run("import pandas as pd\nevents_df = pd.DataFrame({'a': [1, 2, 3]})")
        envelope = self._run("events_df.head(2)", output_name="top_events_df")
        self.assertEqual(envelope["status"], "ok")
        self.assertIn("top_events_df", self.session.shell.user_ns)
        sql = self._run_duckdb(
            "select count(*) as c from top_events_df", inputs=[{"name": "top_events_df", "kind": "local"}]
        )
        self.assertEqual(sql["status"], "ok")
        self.assertEqual(sql["first_page"], [[2]])

    def test_python_rerun_shows_the_fresh_result_not_the_previously_bound_frame(self):
        # The output binding must not shadow a rerun: after upstream data changes, running
        # the same cell again has to preview and bind this run's result, not the old frame.
        self._run("import pandas as pd\nevents_df = pd.DataFrame({'a': [1]})")
        first = self._run("events_df.head(10)", output_name="top_events_df")
        self._run("import pandas as pd\nevents_df = pd.DataFrame({'a': [1, 2, 3]})")
        second = self._run("events_df.head(10)", output_name="top_events_df")
        self.assertEqual(first["row_count"], 1)
        self.assertEqual(second["row_count"], 3)

    def test_missed_save_names_the_created_frame_and_leaves_the_output_unbound(self):
        # The silent-miss footgun: the cell assigns `top50` while its output name says
        # `top50_people` — the run must say so instead of succeeding with an empty preview.
        envelope = self._run("import pandas as pd\ntop50 = pd.DataFrame({'id': [1, 2]})", output_name="top50_people")
        self.assertEqual(envelope["status"], "ok")
        self.assertIn("nothing was saved as 'top50_people'", envelope["stderr"])
        self.assertIn("'top50'", envelope["stderr"])
        self.assertNotIn("top50_people", self.session.shell.user_ns)

    def test_frameless_run_does_not_warn_about_a_missed_save(self):
        # Every cell carries a default output name, so a print-only cell warning on each
        # run would flag ordinary side-effect cells as failures (stderr renders red).
        self._run("import pandas as pd\ntop50 = pd.DataFrame({'id': [1, 2]})", output_name="top50")
        envelope = self._run("print(top50)", output_name="df")
        self.assertEqual(envelope["status"], "ok")
        self.assertNotIn("nothing was saved", envelope["stderr"])

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

    def test_duckdb_over_a_deleted_name_errors_instead_of_reading_stale_rows(self):
        # `del` leaves the name in DuckDB's registry but not the namespace — the third silent
        # state: neither re-registered nor rejected, serving the previous run's rows.
        self._run("import pandas as pd\nnew_events = pd.DataFrame({'id': [1, 2, 3]})")
        self._run_duckdb("select count(*) as c from new_events", inputs=[{"name": "new_events", "kind": "local"}])
        self._run("del new_events")
        envelope = self._run_duckdb(
            "select count(*) as c from new_events", inputs=[{"name": "new_events", "kind": "local"}]
        )
        self.assertEqual(envelope["status"], "error")
        self.assertIn("new_events", envelope["error"])

    def test_frameless_duckdb_rerun_invalidates_its_previous_output_binding(self):
        # A SELECT run binds output_name; a later frameless (DDL) run of the same node must
        # drop that binding, or downstream nodes keep reading the stale frame.
        self._run("import pandas as pd\nnew_events = pd.DataFrame({'id': [1]})")
        self._run_duckdb(
            "select * from new_events", inputs=[{"name": "new_events", "kind": "local"}], output_name="out"
        )
        self._run_duckdb("create table scratch as select 1", output_name="out")
        envelope = self._run_duckdb("select * from out", inputs=[{"name": "out", "kind": "local"}])
        self.assertEqual(envelope["status"], "error")
        self.assertIn("out", envelope["error"])

    def test_snapshot_lists_only_what_sql_can_select_from(self):
        # The browser's contract is "things you can SELECT from", so the snapshot is read from
        # DuckDB's catalog rather than the namespace. Walking user_ns for DataFrames instead —
        # the tempting shortcut — would leak `raw` in and miss `agg`, which has no result file
        # at all (a frameless DDL run writes none) and is invisible to anything document-derived.
        self._run("import pandas as pd\npd.DataFrame({'a': [1, 2, 3]})", output_name="sql_df")
        self._run("raw = pd.DataFrame({'zz': [1]})\nNone")
        envelope = self._run_duckdb("create table agg as select a from sql_df")

        by_name = {frame["name"]: frame for frame in envelope["frames"]}
        self.assertEqual(sorted(by_name), ["agg", "sql_df"])
        self.assertEqual(by_name["sql_df"]["kind"], "frame")
        self.assertEqual(by_name["sql_df"]["row_count"], 3)
        self.assertEqual(by_name["sql_df"]["columns"], [["a", "BIGINT"]])
        self.assertEqual(by_name["agg"]["kind"], "table")

    def test_snapshot_rides_a_failed_run(self):
        # A run that raises part-way can still have changed the catalog, so snapshotting only
        # successful runs would hide `scratch` until some later run happened to succeed.
        self._run_duckdb("create table scratch as select 1 as n")
        envelope = self._run("raise ValueError('boom')")

        self.assertEqual(envelope["status"], "error")
        self.assertEqual([frame["name"] for frame in envelope["frames"]], ["scratch"])

    def test_snapshot_drops_a_deleted_frame(self):
        # `del df` unregisters it, so it stops being SELECT-able and must stop being listed —
        # this is the phantom-frame case that sank deriving the list from the document.
        self._run("import pandas as pd\npd.DataFrame({'a': [1]})", output_name="doomed")
        self._run("del doomed")
        envelope = self._run("1 + 1")

        self.assertEqual([frame["name"] for frame in envelope["frames"]], [])

    def test_snapshot_keeps_same_named_objects_apart(self):
        # Keyed on the bare name, a registered frame and a same-named table in another schema
        # merge into one entry whose columns and row count match neither — a schema the user's
        # SQL will never see. Only one object is reachable from a bare `FROM`, and DuckDB
        # resolves the registration first, so that is the one to report.
        self._run("import pandas as pd\npd.DataFrame({'a': [1, 2, 3]})", output_name="sql_df")
        self.session.duck.execute("CREATE SCHEMA IF NOT EXISTS other")
        self.session.duck.execute("CREATE TABLE other.sql_df AS SELECT 99 AS totally_different")
        envelope = self._run("1 + 1")

        entries = [frame for frame in envelope["frames"] if frame["name"] == "sql_df"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["kind"], "frame")
        self.assertEqual(entries[0]["row_count"], 3)
        self.assertEqual(entries[0]["columns"], [["a", "BIGINT"]])

    def test_snapshot_is_omitted_when_the_catalog_cannot_be_read(self):
        # An empty list means "the kernel has nothing" and overwrites the stored snapshot; a
        # failed read knows nothing and must leave it alone. The two must not look alike.
        self._run("import pandas as pd\npd.DataFrame({'a': [1]})", output_name="kept")
        self.session.duck.close()
        envelope = self._run("2 + 2")

        self.assertNotIn("frames", envelope)

    def test_snapshot_stays_within_the_envelope_budget(self):
        # Column names and type strings are user-controlled and unbounded, so a count cap alone
        # can still push the envelope past the callback's byte limit — which drops the whole
        # result, costing the user their run over a sidebar list.
        wide = ", ".join(f"1 AS {'x' * 300}_{index}" for index in range(60))
        for table in range(30):
            self.session.duck.execute(f"CREATE TABLE wide_{table} AS SELECT {wide}")
        envelope = self._run("3 + 3")

        self.assertLessEqual(len(json.dumps(envelope["frames"])), 300_000)

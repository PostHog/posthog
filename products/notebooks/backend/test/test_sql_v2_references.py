from django.test import SimpleTestCase

from products.notebooks.backend.sql_v2_references import (
    SQLV2Ref,
    SQLV2ReferenceError,
    resolve_python_node_inputs,
    resolve_sql_node_run,
    resolve_sql_v2_references,
)


def hogql_ref(code: str | None) -> SQLV2Ref:
    return SQLV2Ref(kind="hogql", last_run_code=code)


LOCAL = SQLV2Ref(kind="local")


class TestResolvePythonNodeInputs(SimpleTestCase):
    def test_only_referenced_frames_are_materialized(self):
        # A python node reads frames as variables; materialize only the ones its code uses.
        inputs = resolve_python_node_inputs(
            "df1.head()", {"df1": hogql_ref("select id from events"), "df2": hogql_ref("select 1")}
        )
        self.assertEqual(len(inputs), 1)
        self.assertEqual(inputs[0]["name"], "df1")
        self.assertEqual(inputs[0]["kind"], "hogql")
        self.assertEqual(inputs[0]["query"], "select id from events")
        self.assertTrue(inputs[0]["query_hash"])

    def test_unused_refs_are_ignored(self):
        self.assertEqual(
            resolve_python_node_inputs("import pandas as pd\npd.DataFrame()", {"df1": hogql_ref("select 1")}), []
        )

    def test_query_hash_is_stable_for_the_same_query(self):
        # The executor reuses a frame file keyed by hash, so identical queries must hash identically.
        a = resolve_python_node_inputs("df1", {"df1": hogql_ref("select 1")})[0]["query_hash"]
        b = resolve_python_node_inputs("df1", {"df1": hogql_ref("select 1")})[0]["query_hash"]
        self.assertEqual(a, b)

    def test_referencing_a_never_run_node_raises(self):
        with self.assertRaises(SQLV2ReferenceError):
            resolve_python_node_inputs("df1.head()", {"df1": hogql_ref(None)})

    def test_used_local_upstream_becomes_a_local_input(self):
        # A python upstream carries no query — the kernel only asserts the frame exists.
        inputs = resolve_python_node_inputs(
            "new_events.describe()", {"new_events": LOCAL, "df1": hogql_ref("select 1")}
        )
        self.assertEqual(inputs, [{"name": "new_events", "kind": "local"}])


class TestResolveSQLNodeRun(SimpleTestCase):
    def test_all_hogql_refs_push_to_clickhouse(self):
        node_type, run_code, inputs = resolve_sql_node_run(
            "select * from df1", {"df1": hogql_ref("select id from events")}
        )
        self.assertEqual(node_type, "hogql")
        self.assertIn("WITH df1 AS (SELECT id FROM events)", run_code)
        self.assertEqual(inputs, [])

    def test_unreferenced_local_frame_does_not_reroute(self):
        # The local frame exists in the notebook but this query never touches it.
        node_type, run_code, inputs = resolve_sql_node_run(
            "select * from df1", {"df1": hogql_ref("select id from events"), "new_events": LOCAL}
        )
        self.assertEqual(node_type, "hogql")
        self.assertIn("WITH df1 AS", run_code)
        self.assertEqual(inputs, [])

    def test_referenced_local_frame_reroutes_to_duckdb_and_materializes_hogql_refs(self):
        # Journey 5 step 4: the join runs locally, forcing df2 into the sandbox.
        code = "select * from df2 join new_events on df2.id = new_events.id"
        node_type, run_code, inputs = resolve_sql_node_run(
            code, {"df2": hogql_ref("select id from persons"), "new_events": LOCAL}
        )
        self.assertEqual(node_type, "duckdb")
        self.assertEqual(run_code, code)  # DuckDB gets the SQL as written, not a CTE rewrite
        self.assertEqual([(spec["name"], spec["kind"]) for spec in inputs], [("df2", "hogql"), ("new_events", "local")])
        self.assertEqual(inputs[0]["query"], "select id from persons")
        self.assertTrue(inputs[0]["query_hash"])

    def test_local_only_query_reroutes_with_no_materialization(self):
        node_type, run_code, inputs = resolve_sql_node_run("select count() from new_events", {"new_events": LOCAL})
        self.assertEqual(node_type, "duckdb")
        self.assertEqual(inputs, [{"name": "new_events", "kind": "local"}])

    def test_duckdb_run_referencing_a_never_run_hogql_node_raises(self):
        with self.assertRaises(SQLV2ReferenceError):
            resolve_sql_node_run(
                "select * from df2 join new_events on true", {"df2": hogql_ref(None), "new_events": LOCAL}
            )

    def test_unparseable_hogql_naming_a_local_frame_still_routes_to_duckdb(self):
        # DuckDB-only syntax (QUALIFY isn't HogQL) must still run locally when it reads a local frame.
        code = "select * from new_events qualify row_number() over (partition by id) = 1"
        node_type, run_code, inputs = resolve_sql_node_run(code, {"new_events": LOCAL})
        self.assertEqual(node_type, "duckdb")
        self.assertEqual(run_code, code)
        self.assertEqual(inputs, [{"name": "new_events", "kind": "local"}])


class TestResolveSQLV2References(SimpleTestCase):
    def test_query_referencing_nothing_is_returned_verbatim(self):
        # Paging and the run row store this string as-is; rewriting a plain run would break both.
        self.assertEqual(resolve_sql_v2_references("select 1", {"df1": "select id from events"}), "select 1")

    def test_no_refs_is_returned_verbatim(self):
        self.assertEqual(resolve_sql_v2_references("select * from df1", {}), "select * from df1")

    def test_referenced_nodes_are_inlined_as_ctes(self):
        resolved = resolve_sql_v2_references(
            "select * from df1 join df2 on df1.id = df2.id",
            {"df1": "select id from events", "df2": "select id from persons"},
        )
        self.assertIn("WITH df1 AS (SELECT id FROM events)", resolved)
        self.assertIn("df2 AS (SELECT id FROM persons)", resolved)
        self.assertIn("df1 JOIN df2", resolved)

    def test_transitive_reference_is_ordered_before_its_user(self):
        # df2 reads df1, so df1's CTE must be printed first or ClickHouse can't resolve it.
        resolved = resolve_sql_v2_references(
            "select * from df2",
            {"df1": "select id from events", "df2": "select id from df1 where id > 0"},
        )
        self.assertLess(resolved.index("df1 AS"), resolved.index("df2 AS"))

    def test_unreferenced_definitions_are_not_inlined_or_parsed(self):
        # A malformed node nobody references must never fail an unrelated run.
        resolved = resolve_sql_v2_references(
            "select * from df1",
            {"df1": "select id from events", "broken": "select from where syntax("},
        )
        self.assertIn("df1 AS", resolved)
        self.assertNotIn("broken", resolved)

    def test_user_defined_cte_shadows_a_node_of_the_same_name(self):
        # `with df1 as (...)` is the user's own frame — don't replace it with the node's definition.
        resolved = resolve_sql_v2_references(
            "with df1 as (select 9 as n) select * from df1",
            {"df1": "select id from events"},
        )
        self.assertNotIn("from events", resolved.lower())

    def test_user_with_clause_is_preserved_when_merging_refs(self):
        resolved = resolve_sql_v2_references(
            "with mine as (select 1 as x) select * from mine join df1 on true",
            {"df1": "select id from events"},
        )
        self.assertIn("mine AS", resolved)
        self.assertIn("df1 AS", resolved)

    def test_union_query_with_a_trailing_line_comment_still_resolves(self):
        # The UNION wrap embeds the raw text in `select * from (…)`; without a newline before
        # the closing paren a trailing `--` comment swallows the wrapper and the parse crashes.
        resolved = resolve_sql_v2_references(
            "select * from df1 union all select id from events -- combined",
            {"df1": "select id from events"},
        )
        self.assertIn("WITH df1 AS", resolved)
        self.assertIn("UNION ALL", resolved)

    def test_top_level_union_referencing_a_node_is_wrapped_with_the_cte(self):
        # A SelectSetQuery can't carry a WITH, so it gets wrapped in a SELECT that can.
        resolved = resolve_sql_v2_references(
            "select * from df1 union all select id from events",
            {"df1": "select id from events"},
        )
        self.assertIn("WITH df1 AS", resolved)
        self.assertIn("UNION ALL", resolved)

    def test_reference_cycle_raises(self):
        with self.assertRaises(SQLV2ReferenceError):
            resolve_sql_v2_references(
                "select * from a",
                {"a": "select * from b", "b": "select * from a"},
            )

    def test_invalid_referenced_definition_raises(self):
        with self.assertRaises(SQLV2ReferenceError):
            resolve_sql_v2_references("select * from df1", {"df1": "select from where ("})

    def test_referencing_a_never_run_node_raises(self):
        # df1 is a known node (present in refs) but has no last-run definition to inline.
        with self.assertRaises(SQLV2ReferenceError):
            resolve_sql_v2_references("select * from df1", {"df1": None})

    def test_unreferenced_never_run_node_is_ignored(self):
        # A never-run node nobody references must not block the run.
        self.assertEqual(resolve_sql_v2_references("select 1", {"df1": None}), "select 1")

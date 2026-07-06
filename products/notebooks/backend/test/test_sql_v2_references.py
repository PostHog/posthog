from django.test import SimpleTestCase

from products.notebooks.backend.sql_v2_references import (
    SQLV2ReferenceError,
    resolve_python_node_inputs,
    resolve_sql_v2_references,
)


class TestResolvePythonNodeInputs(SimpleTestCase):
    def test_only_referenced_frames_are_materialized(self):
        # A python node reads frames as variables; materialize only the ones its code uses.
        inputs = resolve_python_node_inputs("df1.head()", {"df1": "select id from events", "df2": "select 1"})
        self.assertEqual(len(inputs), 1)
        self.assertEqual(inputs[0]["name"], "df1")
        self.assertEqual(inputs[0]["kind"], "hogql")
        self.assertEqual(inputs[0]["query"], "select id from events")
        self.assertTrue(inputs[0]["query_hash"])

    def test_unused_refs_are_ignored(self):
        self.assertEqual(resolve_python_node_inputs("import pandas as pd\npd.DataFrame()", {"df1": "select 1"}), [])

    def test_query_hash_is_stable_for_the_same_query(self):
        # The executor reuses a frame file keyed by hash, so identical queries must hash identically.
        a = resolve_python_node_inputs("df1", {"df1": "select 1"})[0]["query_hash"]
        b = resolve_python_node_inputs("df1", {"df1": "select 1"})[0]["query_hash"]
        self.assertEqual(a, b)

    def test_referencing_a_never_run_node_raises(self):
        with self.assertRaises(SQLV2ReferenceError):
            resolve_python_node_inputs("df1.head()", {"df1": None})


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

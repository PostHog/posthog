from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast

from products.notebooks.backend.sql_v2_references import (
    SQLV2Ref,
    SQLV2ReferenceError,
    resolve_python_node_inputs,
    resolve_sql_node_run,
    resolve_sql_v2_references,
)


def hogql_ref(code: str | None, node_id: str = "node-df1", run_id: str = "run-1") -> SQLV2Ref:
    # A never-run node (code None) has no run to key on, mirroring how the view builds refs.
    return SQLV2Ref(kind="hogql", node_id=node_id, run_id=None if code is None else run_id, last_run_code=code)


LOCAL = SQLV2Ref(kind="local")


class TestResolvePythonNodeInputs(SimpleTestCase):
    def test_only_referenced_frames_are_materialized(self):
        # A python node reads frames as variables; materialize only the ones its code uses.
        inputs = resolve_python_node_inputs(
            "df1.head()", {"df1": hogql_ref("select id from events"), "df2": hogql_ref("select 1", node_id="node-df2")}
        )
        self.assertEqual(len(inputs), 1)
        self.assertEqual(inputs[0]["name"], "df1")
        self.assertEqual(inputs[0]["kind"], "hogql")
        self.assertEqual(inputs[0]["query"], "select id from events")

    def test_unused_refs_are_ignored(self):
        self.assertEqual(
            resolve_python_node_inputs("import pandas as pd\npd.DataFrame()", {"df1": hogql_ref("select 1")}), []
        )

    def test_reassigned_ref_is_still_materialized(self):
        # Reassigning a ref (df1 = df1.assign(...)) must not drop it from the inputs — otherwise it
        # is never re-fetched and the node runs against the mutated frame from its previous run.
        inputs = resolve_python_node_inputs(
            "df1.columns = ['a']\ndf1 = df1.assign(x=1)", {"df1": hogql_ref("select 1")}
        )
        self.assertEqual([i["name"] for i in inputs], ["df1"])

    def test_frame_is_keyed_on_the_upstream_run_id(self):
        # The executor caches/evicts frames by (node_id, run_id), so both must reach the spec — a
        # new run of the same node must key a fresh frame rather than reuse the stale one.
        inputs = resolve_python_node_inputs("df1.head()", {"df1": hogql_ref("select 1", node_id="n1", run_id="r2")})
        self.assertEqual(inputs[0]["node_id"], "n1")
        self.assertEqual(inputs[0]["run_id"], "r2")

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
        plan = resolve_sql_node_run("select * from df1", {"df1": hogql_ref("select id from events")})
        self.assertEqual(plan.node_type, "hogql")
        self.assertIn("WITH df1 AS (SELECT id FROM events)", plan.code)
        self.assertEqual(plan.inputs, [])

    def test_unreferenced_local_frame_does_not_reroute(self):
        # The local frame exists in the notebook but this query never touches it.
        plan = resolve_sql_node_run(
            "select * from df1", {"df1": hogql_ref("select id from events"), "new_events": LOCAL}
        )
        self.assertEqual(plan.node_type, "hogql")
        self.assertIn("WITH df1 AS", plan.code)
        self.assertEqual(plan.inputs, [])

    def test_referenced_local_frame_reroutes_to_duckdb_and_materializes_hogql_refs(self):
        # Journey 5 step 4: the join runs locally, forcing df2 into the sandbox.
        code = "select * from df2 join new_events on df2.id = new_events.id"
        plan = resolve_sql_node_run(code, {"df2": hogql_ref("select id from persons"), "new_events": LOCAL})
        self.assertEqual(plan.node_type, "duckdb")
        self.assertEqual(plan.code, code)  # DuckDB gets the SQL as written, not a CTE rewrite
        self.assertEqual(
            [(spec["name"], spec["kind"]) for spec in plan.inputs], [("df2", "hogql"), ("new_events", "local")]
        )
        self.assertEqual(plan.inputs[0]["query"], "select id from persons")
        # DuckDB-rerouted runs key materialized frames the same way python nodes do.
        self.assertEqual(plan.inputs[0]["node_id"], "node-df1")
        self.assertEqual(plan.inputs[0]["run_id"], "run-1")

    def test_local_only_query_reroutes_with_no_materialization(self):
        plan = resolve_sql_node_run("select count() from new_events", {"new_events": LOCAL})
        self.assertEqual(plan.node_type, "duckdb")
        self.assertEqual(plan.inputs, [{"name": "new_events", "kind": "local"}])

    def test_duckdb_run_referencing_a_never_run_hogql_node_raises(self):
        with self.assertRaises(SQLV2ReferenceError):
            resolve_sql_node_run(
                "select * from df2 join new_events on true", {"df2": hogql_ref(None), "new_events": LOCAL}
            )

    def test_unparseable_hogql_naming_a_local_frame_still_routes_to_duckdb(self):
        # DuckDB-only syntax (PIVOT isn't HogQL; QUALIFY actually parses) must still run
        # locally when it names a local frame — this is the regex fallback's positive path.
        code = "pivot new_events on category"
        plan = resolve_sql_node_run(code, {"new_events": LOCAL})
        self.assertEqual(plan.node_type, "duckdb")
        self.assertEqual(plan.code, code)
        self.assertEqual(plan.inputs, [{"name": "new_events", "kind": "local"}])

    def test_frame_named_only_in_a_literal_or_comment_does_not_route_to_duckdb(self):
        # The fallback scanner must not see the frame name inside a string or comment —
        # that would reroute the query to DuckDB and materialize a frame it never reads.
        code = "pivot events on label in ('new_events') -- new_events"
        plan = resolve_sql_node_run(code, {"new_events": LOCAL})
        self.assertEqual(plan.node_type, "hogql")
        self.assertEqual(plan.code, code)
        self.assertEqual(plan.inputs, [])


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

    @parameterized.expand(
        [
            # The user's own WITH reads a node frame, so the injected CTE has to precede it.
            ("user_cte_reads_a_ref", "with mine as (select id from df1) select * from mine", "df1 AS", "mine AS"),
            # And the reverse: the node's definition reads a name the user's WITH shadows.
            ("ref_reads_a_shadowed_cte", "with df1 as (select 5 as id) select * from df2", "df1 AS", "df2 AS"),
            # A scalar CTE is read as a column, so this dependency appears in no FROM/JOIN at all.
            ("ref_reads_a_scalar_cte", "with 5 as cutoff select id from df3", "5 AS cutoff", "df3 AS"),
        ]
    )
    def test_ctes_are_merged_in_dependency_order(self, _name, code, first, second):
        # Whichever side a CTE comes from, it must be printed before the one that reads it —
        # appending the refs after the user's WITH leaves them unknown tables.
        resolved = resolve_sql_v2_references(
            code,
            {
                "df1": "select uuid as id from events",
                "df2": "select id from df1 where id > 0",
                "df3": "select uuid as id from events where 1 > cutoff",
            },
        )
        self.assertLess(resolved.index(first), resolved.index(second))

    @parameterized.expand(
        [
            ("subquery_in_from", "select id from (select id from df1)"),
            ("subquery_in_where", "select uuid from events where uuid in (select id from df1)"),
            ("scalar_subquery_in_select_list", "select (select count() from df1) as c"),
            ("union_inside_a_user_cte", "with u as (select id from df1 union all select 1 as id) select id from u"),
        ]
    )
    def test_refs_nested_below_the_top_level_are_still_inlined(self, _name, code):
        # Every other case here reads the ref from a top-level FROM/JOIN, so a collector that
        # stopped descending into subqueries would still pass them while silently dropping the
        # CTE — the query then fails in ClickHouse with an unknown table.
        resolved = resolve_sql_v2_references(code, {"df1": "select uuid as id from events"})
        self.assertIn("df1 AS (", resolved)

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

    def test_cycle_through_a_user_cte_raises(self):
        # The cycle check above only walks node names, so a cycle closed by the user's own CTE
        # reaches the merge instead. Naming a CTE after a table the node reads is an easy
        # collision to hit, and it must fail here as a 400 rather than as a ClickHouse error.
        with self.assertRaises(SQLV2ReferenceError):
            resolve_sql_v2_references(
                "with events as (select * from df1) select * from df1",
                {"df1": "select * from events"},
            )

    def test_columns_sharing_a_cte_name_are_not_a_cycle(self):
        # Ordering scans every identifier, not just table positions, so two CTEs selecting a
        # column named after each other look circular. They aren't, and must still resolve.
        resolved = resolve_sql_v2_references(
            "with a as (select b from df1), b as (select a from df1) select * from a",
            {"df1": "select uuid as a, uuid as b from events"},
        )
        self.assertIn("df1 AS (", resolved)

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


class TestResolvedQueryIsValidHogQL(BaseTest):
    # Every other assertion in this file matches a substring of the resolved SQL, which cannot see
    # a query that is well-formed but unresolvable: the CTE-ordering bug emitted a perfectly good
    # `df1 AS (…)` *after* the CTE reading it, so every substring check passed while ClickHouse
    # rejected the query. Resolving it for real is the only assertion that catches that class.
    @parameterized.expand(
        [
            ("user_cte_reads_a_ref", "with mine as (select id from df1) select id from mine"),
            ("ref_reads_a_shadowed_cte", "with df1 as (select 5 as id) select id from df2"),
            (
                "chained_user_ctes_over_a_ref",
                "with a as (select id from df1), b as (select id from a) select id from b",
            ),
            ("nested_subquery", "select id from (select id from df1)"),
            ("ref_reads_a_scalar_cte", "with 5 as cutoff select id from df3"),
        ]
    )
    def test_resolved_query_typechecks(self, _name, code):
        resolved = resolve_sql_v2_references(
            code,
            {
                "df1": "select uuid as id from events",
                "df2": "select id from df1 where id > 0",
                "df3": "select uuid as id from events where 1 > cutoff",
            },
        )
        context = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)
        prepare_and_print_ast(parse_select(resolved), context=context, dialect="clickhouse")

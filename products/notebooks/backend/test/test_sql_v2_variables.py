import time
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from products.notebooks.backend.sql_v2_references import SQLV2Ref, resolve_sql_node_run
from products.notebooks.backend.sql_v2_variables import (
    NotebookVariable,
    NotebookVariableError,
    build_notebook_variables,
    python_variable_bindings,
    reject_variables_in_raw_query,
    substitute_duckdb_variables,
    substitute_hogql_variables,
)

UTC = ZoneInfo("UTC")
COUNTRY = NotebookVariable(name="country", value="US")
DAYS = NotebookVariable(name="lookback_days", value=30)


class TestSubstituteHogqlVariables(SimpleTestCase):
    def test_binds_a_value_as_a_constant(self):
        printed = substitute_hogql_variables("select 1 where 'x' = {country}", [COUNTRY])
        self.assertIn("'US'", printed)
        self.assertNotIn("{country}", printed)

    def test_a_query_without_placeholders_is_returned_verbatim(self):
        # Byte-identical, so adding the feature cannot reformat anybody's existing query.
        code = "select   count()\nfrom events -- trailing comment"
        self.assertEqual(substitute_hogql_variables(code, [COUNTRY]), code)

    def test_a_string_value_stays_one_literal(self):
        # The value is a constant in the AST, never spliced text, so SQL syntax inside it is
        # data. Re-parsing the printed query is what proves it: an escape that leaked would
        # change the shape of the tree, not just the characters.
        injected = "US' or 1=1 --"
        printed = substitute_hogql_variables(
            "select 1 where 'x' = {country}", [NotebookVariable(name="country", value=injected)]
        )
        where = parse_select(printed).where  # type: ignore[union-attr]
        self.assertIsInstance(where, ast.Call)
        # Exactly two operands, the payload intact in the second — not an `or` the escape opened up.
        constants = [arg.value for arg in where.args if isinstance(arg, ast.Constant)]  # type: ignore[union-attr]
        self.assertEqual(constants, ["x", injected])

    @parameterized.expand(
        [
            # Injected by HogQL itself, and resolved much later than dispatch.
            ("filters", "select 1 from events where {filters}"),
            # An insight variable, which has its own resolver and its own storage.
            ("dotted_chain", "select 1 from events where properties.x = {variables.country}"),
        ]
    )
    def test_another_resolvers_placeholder_is_left_untouched(self, _name: str, code: str) -> None:
        self.assertEqual(substitute_hogql_variables(code, [COUNTRY]), code)

    @parameterized.expand(
        [
            ("close_match_is_suggested", "{contry}", [COUNTRY], "country"),
            ("nothing_declared_says_how_to_declare", "{country}", [], "Variables block"),
        ]
    )
    def test_an_undeclared_name_is_reported(
        self, _name: str, placeholder: str, variables: list[NotebookVariable], expected: str
    ) -> None:
        with self.assertRaises(NotebookVariableError) as error:
            substitute_hogql_variables(f"select 1 where 'x' = {placeholder}", variables)
        self.assertIn(expected, str(error.exception))


class TestSubstituteDuckdbVariables(SimpleTestCase):
    def test_a_placeholder_becomes_a_bound_parameter(self):
        # The value never enters the SQL, so nothing about it can be parsed as SQL.
        code, params = substitute_duckdb_variables("select * from t where c = {country}", [COUNTRY])
        self.assertEqual(code, "select * from t where c = $country")
        self.assertEqual(params, {"country": "US"})

    def test_only_the_names_the_query_uses_are_bound(self):
        # DuckDB rejects a parameter the query never references, so an unused declaration
        # must not be sent.
        code, params = substitute_duckdb_variables("select {country}", [COUNTRY, DAYS])
        self.assertEqual(code, "select $country")
        self.assertEqual(params, {"country": "US"})

    @parameterized.expand(
        [
            ("single_quoted", "select '{country}' as label"),
            ("double_quoted_identifier", 'select 1 as "{country}"'),
            # The region the escaping scanner missed: everything between the tags is literal,
            # so a value written here could have closed the string and run as SQL.
            ("dollar_quoted", "select $tag${country}$tag$"),
            ("dollar_quoted_bare", "select $${country}$$"),
            ("line_comment", "-- {country}\nselect 1"),
            ("block_comment", "/* {country} */ select 1"),
        ]
    )
    def test_a_placeholder_outside_executable_sql_is_left_alone(self, _name: str, code: str) -> None:
        rewritten, params = substitute_duckdb_variables(code, [COUNTRY])
        self.assertEqual(rewritten, code)
        self.assertEqual(params, {})

    def test_a_value_cannot_escape_a_dollar_quoted_string(self):
        # The reported injection: with textual escaping this produced
        # `select $tag$'$tag$ UNION ALL SELECT version() --'$tag$`, where the payload closed
        # the literal and ran. Now the placeholder is literal text and nothing is bound.
        code = "select $tag${country}$tag$"
        rewritten, params = substitute_duckdb_variables(
            code, [NotebookVariable(name="country", value="$tag$ UNION ALL SELECT version() --")]
        )
        self.assertEqual(rewritten, code)
        self.assertEqual(params, {})

    def test_a_query_without_placeholders_is_returned_verbatim(self):
        code = "select * from py_df"
        self.assertEqual(substitute_duckdb_variables(code, [COUNTRY]), (code, {}))

    @parameterized.expand(
        [
            # An unterminated literal swallows the rest of the input, exactly as a lexer reads
            # it. The query is malformed either way; what matters is that no value goes in.
            ("unterminated_dollar_quote", "select $tag$ {country}"),
            ("unterminated_string", "select ' {country}"),
            ("unterminated_block_comment", "select /* {country}"),
            # Backslash escapes apply inside E'…', so the quote here does not close the string.
            ("escaped_quote_in_e_string", "select E'\\' {country}"),
        ]
    )
    def test_an_unterminated_region_keeps_the_placeholder_literal(self, _name: str, code: str) -> None:
        rewritten, params = substitute_duckdb_variables(code, [COUNTRY])
        self.assertEqual(rewritten, code)
        self.assertEqual(params, {})

    def test_a_numbered_parameter_is_not_read_as_a_dollar_quote(self):
        # `$1$2` is two positional parameters; reading it as an opener would swallow the query.
        code = "select $1, $2, {country}"
        rewritten, params = substitute_duckdb_variables(code, [COUNTRY])
        self.assertEqual(rewritten, "select $1, $2, $country")
        self.assertEqual(params, {"country": "US"})

    def test_many_unmatched_dollar_openers_stay_linear(self):
        # Matching `$tag$…$tag$` with a backreference rescans the tail once per unmatched
        # opener, which a single 20 MB request turns into hours of CPU. The margin here is
        # three orders of magnitude: the linear scan does this in milliseconds.
        code = " ".join(f"$tag{index}$" for index in range(200_000)) + " {country}"
        started = time.monotonic()
        substitute_duckdb_variables(code, [COUNTRY])
        self.assertLess(time.monotonic() - started, 2.0)

    def test_an_undeclared_name_raises(self):
        with self.assertRaises(NotebookVariableError):
            substitute_duckdb_variables("select {nope}", [COUNTRY])


class TestBuildNotebookVariables(SimpleTestCase):
    @parameterized.expand(
        [
            ("string", "string", "US", "US"),
            ("number_from_string", "number", "30", 30),
            ("number_float", "number", "1.5", 1.5),
            ("number_invalid", "number", "abc", None),
            ("boolean_from_string", "boolean", "true", True),
            ("boolean_false", "boolean", "nope", False),
            ("absolute_date", "date", "2026-01-31", "2026-01-31"),
            ("unknown_type_reads_as_string", "wat", 5, "5"),
        ]
    )
    def test_coerces_by_type(self, _name: str, variable_type: str, value: object, expected: object) -> None:
        built = build_notebook_variables([{"name": "v", "type": variable_type, "value": value}], UTC)
        self.assertEqual(built[0].value, expected)

    def test_a_relative_date_resolves_to_a_datetime(self):
        built = build_notebook_variables([{"name": "since", "type": "date", "value": "-7d"}], UTC)
        self.assertIsNotNone(built[0].value)
        self.assertNotEqual(built[0].value, "-7d")

    def test_duplicates_keep_the_first_declaration(self):
        # Matches the editor, which flags the second one as invalid rather than shadowing.
        built = build_notebook_variables(
            [
                {"name": "country", "type": "string", "value": "US"},
                {"name": "country", "type": "string", "value": "DE"},
            ],
            UTC,
        )
        self.assertEqual([(variable.name, variable.value) for variable in built], [("country", "US")])

    def test_unnamed_and_reserved_declarations_are_dropped(self):
        built = build_notebook_variables(
            [
                {"name": "  ", "type": "string", "value": "x"},
                {"name": "filters", "type": "string", "value": "x"},
                {"name": "ok", "type": "string", "value": "x"},
            ],
            UTC,
        )
        self.assertEqual([variable.name for variable in built], ["ok"])


class TestPythonVariableBindings(SimpleTestCase):
    def test_scalars_pass_through_and_dates_become_iso_strings(self):
        built = build_notebook_variables(
            [
                {"name": "country", "type": "string", "value": "US"},
                {"name": "days", "type": "number", "value": 30},
                {"name": "since", "type": "date", "value": "-7d"},
            ],
            UTC,
        )
        bindings = python_variable_bindings(built)
        self.assertEqual(bindings["country"], "US")
        self.assertEqual(bindings["days"], 30)
        self.assertIsInstance(bindings["since"], str)


class TestResolveSqlNodeRunWithVariables(SimpleTestCase):
    def test_the_clickhouse_lane_binds_through_the_ast(self):
        plan = resolve_sql_node_run("select 1 where 'x' = {country}", {}, [COUNTRY])
        self.assertEqual(plan.node_type, "hogql")
        self.assertEqual(plan.inputs, [])
        self.assertIn("'US'", plan.code)

    def test_the_duckdb_lane_carries_parameters_without_reformatting(self):
        # A local ref reroutes to DuckDB, whose dialect the HogQL printer must not rewrite.
        # The value rides alongside as a bound parameter rather than inside the SQL.
        plan = resolve_sql_node_run(
            "select * from py_df where country = {country}", {"py_df": SQLV2Ref(kind="local")}, [COUNTRY]
        )
        self.assertEqual(plan.node_type, "duckdb")
        self.assertEqual(plan.code, "select * from py_df where country = $country")
        self.assertEqual(plan.variables, {"country": "US"})

    def test_a_variable_binds_in_a_query_that_also_inlines_a_reference(self):
        # Both rewrites have to survive each other: the CTE merge reprints the AST, which fails
        # on a placeholder that is still unresolved by then.
        plan = resolve_sql_node_run(
            "select * from df1 where days > {lookback_days}",
            {"df1": SQLV2Ref(kind="hogql", node_id="n1", run_id="r1", last_run_code="select 1 as days")},
            [DAYS],
        )
        self.assertEqual(plan.node_type, "hogql")
        self.assertIn("30", plan.code)
        self.assertIn("df1 AS (", plan.code)


class TestRejectVariablesInRawQuery(SimpleTestCase):
    def test_a_raw_query_reading_a_variable_is_refused(self):
        # Escaping differs by engine and by server setting — MySQL treats a backslash as an
        # escape, so quote doubling alone would let `\' OR 1=1 -- ` close the literal and run
        # as SQL. Refusing is what keeps a hand-rolled escape out of the raw lane.
        with self.assertRaises(NotebookVariableError) as error:
            reject_variables_in_raw_query("select * from t where c = {country}", [COUNTRY])
        self.assertIn("raw query", str(error.exception))
        self.assertIn("country", str(error.exception))

    @parameterized.expand(
        [
            # Raw SQL may use braces for its own purposes, so an unknown name is not ours to reject.
            ("an undeclared name", "select {not_a_variable}"),
            ("a name inside a string literal", "select '{country}' as label"),
            ("a name inside a comment", "-- {country}\nselect 1"),
            ("no braces at all", "select * from t"),
        ]
    )
    def test_leaves_a_query_alone(self, _name: str, code: str) -> None:
        reject_variables_in_raw_query(code, [COUNTRY])

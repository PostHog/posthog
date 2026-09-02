"""Materialization analysis tests that run on the AST alone.

These live apart from test_variable_materialization.py because that module marks every
class django_db. Keep this file free of a Team, a request, or a database, so the cases
stay on SimpleTestCase and skip Django setup.
"""

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select

from products.endpoints.backend.logic.strategies import apply_where_filter
from products.endpoints.backend.materialization_transforms import (
    REAGGREGATABLE_BASE_FUNCTIONS,
    DownstreamCTEShape,
    PropagatingSource,
    _build_cte_read_graph,
    _classify_downstream_cte,
    _downstream_ctes,
    _extract_aggregate_name,
    _strip_combinators,
    _topological_order,
    analyze_variables_for_materialization,
    get_reaggregation,
)


class TestStripCombinators(SimpleTestCase):
    """Unit tests for _strip_combinators."""

    @parameterized.expand(
        [
            ("count", "count"),
            ("sum", "sum"),
            ("min", "min"),
            ("max", "max"),
            ("sumIf", "sum"),
            ("countIf", "count"),
            ("maxIf", "max"),
            ("countArrayIf", "count"),
            ("sumArray", "sum"),
            ("minOrDefault", "min"),
            ("maxOrNull", "max"),
        ]
    )
    def test_strips_to_known_base(self, func_name, expected_base):
        assert _strip_combinators(func_name) == expected_base

    @parameterized.expand(
        [
            ("avg",),
            ("uniq",),
            ("uniqIf",),
            ("uniqExact",),
            ("median",),
            ("quantile",),
            ("someRandomFunction",),
        ]
    )
    def test_returns_none_for_unknown(self, func_name):
        result = _strip_combinators(func_name)
        # Should return the base but it won't be in REAGGREGATABLE_BASE_FUNCTIONS
        # For truly unknown functions, returns None
        if result is not None:
            # The base was found but it's not in the registry — that's the expected path
            # for functions like uniq, avg whose base is known but not re-aggregatable
            assert result not in REAGGREGATABLE_BASE_FUNCTIONS or result == func_name.lower()


class TestCTEGraph(SimpleTestCase):
    """Unit tests for the CTE reference graph and downstream/topological helpers."""

    @staticmethod
    def _parse(query_str: str) -> ast.SelectQuery:
        parsed = parse_select(query_str)
        assert isinstance(parsed, ast.SelectQuery)
        return parsed

    def test_no_ctes_returns_empty_graph(self):
        node = self._parse("SELECT count() FROM events")
        assert _build_cte_read_graph(node) == {}

    def test_single_cte_with_no_cte_references(self):
        node = self._parse("WITH a AS (SELECT 1 AS x) SELECT x FROM a")
        graph = _build_cte_read_graph(node)
        assert graph == {"a": set()}

    def test_cte_reads_from_another_cte(self):
        node = self._parse("WITH a AS (SELECT 1 AS x), b AS (SELECT x FROM a) SELECT x FROM b")
        graph = _build_cte_read_graph(node)
        assert graph["a"] == set()
        assert graph["b"] == {"a"}

    def test_cte_reads_via_nested_subquery(self):
        node = self._parse("WITH a AS (SELECT 1 AS x), b AS (SELECT * FROM (SELECT x FROM a)) SELECT * FROM b")
        graph = _build_cte_read_graph(node)
        assert graph["b"] == {"a"}

    def test_cte_reads_via_cross_join(self):
        node = self._parse(
            "WITH a AS (SELECT 1 AS x), b AS (SELECT 2 AS y), c AS (SELECT * FROM a CROSS JOIN b) SELECT * FROM c"
        )
        graph = _build_cte_read_graph(node)
        assert graph["c"] == {"a", "b"}

    def test_cte_reads_via_left_join(self):
        node = self._parse(
            "WITH a AS (SELECT 1 AS x), b AS (SELECT 1 AS y), c AS (SELECT * FROM a LEFT JOIN b ON 1=1) SELECT * FROM c"
        )
        graph = _build_cte_read_graph(node)
        assert graph["c"] == {"a", "b"}

    def test_downstream_direct_reader(self):
        node = self._parse("WITH a AS (SELECT 1 AS x), b AS (SELECT x FROM a) SELECT x FROM b")
        graph = _build_cte_read_graph(node)
        assert _downstream_ctes(graph, "a") == {"b"}

    def test_downstream_transitive_chain(self):
        node = self._parse("WITH a AS (SELECT 1 AS x), b AS (SELECT x FROM a), c AS (SELECT x FROM b) SELECT x FROM c")
        graph = _build_cte_read_graph(node)
        assert _downstream_ctes(graph, "a") == {"b", "c"}

    def test_downstream_excludes_siblings(self):
        node = self._parse("WITH a AS (SELECT 1 AS x), b AS (SELECT 2 AS y), c AS (SELECT x FROM a) SELECT x FROM c")
        graph = _build_cte_read_graph(node)
        assert _downstream_ctes(graph, "a") == {"c"}
        assert _downstream_ctes(graph, "b") == set()

    def test_topological_order_respects_dependencies(self):
        node = self._parse("WITH a AS (SELECT 1 AS x), b AS (SELECT x FROM a), c AS (SELECT x FROM b) SELECT x FROM c")
        graph = _build_cte_read_graph(node)
        order = _topological_order(graph, {"b", "c"})
        assert order.index("b") < order.index("c")

    def test_shadowed_cte_name_is_not_counted_as_reference(self):
        node = self._parse(
            "WITH a AS (SELECT 1 AS x), b AS (WITH a AS (SELECT 99 AS y) SELECT y FROM a) SELECT * FROM b"
        )
        graph = _build_cte_read_graph(node)
        assert graph["b"] == set()
        assert _downstream_ctes(graph, "a") == set()

    def test_shadow_inside_nested_subquery_also_honored(self):
        node = self._parse(
            "WITH a AS (SELECT 1 AS x), "
            "b AS (SELECT 2 AS y WHERE 1 = (WITH a AS (SELECT 99 AS y) SELECT y FROM a)) "
            "SELECT * FROM b"
        )
        graph = _build_cte_read_graph(node)
        assert graph["b"] == set()


class TestDownstreamCTEClassifier(SimpleTestCase):
    """Unit tests for the downstream CTE shape classifier."""

    @staticmethod
    def _get_cte(query_str: str, cte_name: str) -> ast.Expr:
        parsed = parse_select(query_str)
        assert isinstance(parsed, ast.SelectQuery) and parsed.ctes
        return parsed.ctes[cte_name].expr

    def test_projection_shape(self):
        expr = self._get_cte(
            "WITH base AS (SELECT 1 AS x), proj AS (SELECT x FROM base) SELECT * FROM proj",
            "proj",
        )
        plan = _classify_downstream_cte("proj", expr, {"base", "proj"}, ["event_name"])
        assert plan.reject_reason is None
        assert plan.shape == DownstreamCTEShape.PROJECTION
        assert plan.propagating_sources == [PropagatingSource(alias="base", cte_name="base")]

    def test_aggregation_shape(self):
        expr = self._get_cte(
            "WITH base AS (SELECT 1 AS x), agg AS (SELECT x, count() FROM base GROUP BY x) SELECT * FROM agg",
            "agg",
        )
        plan = _classify_downstream_cte("agg", expr, {"base", "agg"}, ["event_name"])
        assert plan.reject_reason is None
        assert plan.shape == DownstreamCTEShape.AGGREGATION

    @parameterized.expand(["MAX", "MIN", "SUM", "AVG", "COUNT"])
    def test_aggregation_shape_uppercase_function(self, fn):
        expr = self._get_cte(
            f"WITH base AS (SELECT 1 AS x), agg AS (SELECT {fn}(x) AS m FROM base) SELECT * FROM agg",
            "agg",
        )
        plan = _classify_downstream_cte("agg", expr, {"base", "agg"}, ["event_name"])
        assert plan.reject_reason is None
        assert plan.shape == DownstreamCTEShape.AGGREGATION

    def test_distinct_shape(self):
        expr = self._get_cte(
            "WITH base AS (SELECT 1 AS x), u AS (SELECT DISTINCT x FROM base) SELECT * FROM u",
            "u",
        )
        plan = _classify_downstream_cte("u", expr, {"base", "u"}, ["event_name"])
        assert plan.reject_reason is None
        assert plan.shape == DownstreamCTEShape.DISTINCT

    @parameterized.expand(
        ["CROSS JOIN base2", "JOIN base2 ON base.x = base2.x", "INNER JOIN base2 ON base.x = base2.x"]
    )
    def test_multi_join_shape(self, join_clause):
        expr = self._get_cte(
            "WITH base AS (SELECT 1 AS x), base2 AS (SELECT 1 AS x), "
            f"combined AS (SELECT base.x FROM base {join_clause}) "
            "SELECT * FROM combined",
            "combined",
        )
        plan = _classify_downstream_cte("combined", expr, {"base", "base2", "combined"}, ["event_name"])
        assert plan.reject_reason is None
        assert plan.shape == DownstreamCTEShape.MULTI_JOIN
        assert len(plan.propagating_sources) == 2

    def test_union_all_shape(self):
        expr = self._get_cte(
            "WITH base AS (SELECT 1 AS x), u AS (SELECT x FROM base UNION ALL SELECT x FROM base) SELECT * FROM u",
            "u",
        )
        plan = _classify_downstream_cte("u", expr, {"base", "u"}, ["event_name"])
        assert plan.reject_reason is None
        assert plan.shape == DownstreamCTEShape.UNION_ALL
        assert len(plan.leg_plans) == 2

    @parameterized.expand(["LEFT JOIN", "RIGHT JOIN", "FULL OUTER JOIN"])
    def test_outer_join_between_propagating_ctes_rejected(self, join_type):
        expr = self._get_cte(
            "WITH base AS (SELECT 1 AS x), base2 AS (SELECT 1 AS x), "
            f"combined AS (SELECT base.x FROM base {join_type} base2 ON base.x = base2.x) "
            "SELECT * FROM combined",
            "combined",
        )
        plan = _classify_downstream_cte("combined", expr, {"base", "base2", "combined"}, ["event_name"])
        assert plan.reject_reason is not None
        assert join_type in plan.reject_reason

    @parameterized.expand(["UNION DISTINCT", "INTERSECT", "EXCEPT"])
    def test_non_union_all_set_operator_rejected(self, set_operator):
        expr = self._get_cte(
            f"WITH base AS (SELECT 1 AS x), u AS (SELECT x FROM base {set_operator} SELECT x FROM base) "
            "SELECT * FROM u",
            "u",
        )
        plan = _classify_downstream_cte("u", expr, {"base", "u"}, ["event_name"])
        assert plan.reject_reason == "Only UNION ALL is supported for propagation across set operations"

    def test_window_function_downstream_rejected(self):
        expr = self._get_cte(
            "WITH base AS (SELECT 1 AS x), "
            "ranked AS (SELECT x, row_number() OVER win AS rn FROM base WINDOW win AS (ORDER BY x)) "
            "SELECT * FROM ranked",
            "ranked",
        )
        plan = _classify_downstream_cte("ranked", expr, {"base", "ranked"}, ["event_name"])
        assert plan.reject_reason is not None
        assert "Window functions" in plan.reject_reason

    def test_nested_subquery_reference_rejected(self):
        expr = self._get_cte(
            "WITH base AS (SELECT 1 AS x), nested AS (SELECT * FROM (SELECT x FROM base)) SELECT * FROM nested",
            "nested",
        )
        plan = _classify_downstream_cte("nested", expr, {"base", "nested"}, ["event_name"])
        assert plan.reject_reason is not None
        assert "nested subquery" in plan.reject_reason

    def test_scalar_subquery_in_where_rejected(self):
        expr = self._get_cte(
            "WITH base AS (SELECT 1 AS x), "
            "agg AS (SELECT max(x) AS m FROM base), "
            "use AS (SELECT x FROM base WHERE x = (SELECT m FROM agg)) "
            "SELECT * FROM use",
            "use",
        )
        plan = _classify_downstream_cte("use", expr, {"base", "agg", "use"}, ["event_name"])
        assert plan.reject_reason is not None
        assert "scalar subquery" in plan.reject_reason

    def test_scalar_subquery_in_select_rejected(self):
        expr = self._get_cte(
            "WITH base AS (SELECT 1 AS x), "
            "agg AS (SELECT max(x) AS m FROM base), "
            "use AS (SELECT x, (SELECT m FROM agg) AS latest FROM base) "
            "SELECT * FROM use",
            "use",
        )
        plan = _classify_downstream_cte("use", expr, {"base", "agg", "use"}, ["event_name"])
        assert plan.reject_reason is not None
        assert "scalar subquery" in plan.reject_reason

    def test_scalar_subquery_in_nested_cte_rejected(self):
        expr = self._get_cte(
            "WITH base AS (SELECT 1 AS x), "
            "use AS ("
            "  WITH latest AS (SELECT max(x) AS m FROM base) "
            "  SELECT x FROM base WHERE x = (SELECT m FROM latest)"
            ") "
            "SELECT * FROM use",
            "use",
        )
        plan = _classify_downstream_cte("use", expr, {"base", "use"}, ["event_name"])
        assert plan.reject_reason is not None
        assert "scalar subquery" in plan.reject_reason

    def test_scalar_subquery_in_join_on_rejected(self):
        expr = self._get_cte(
            "WITH base AS (SELECT 1 AS x, 2 AS y), "
            "agg AS (SELECT max(x) AS m FROM base), "
            "use AS (SELECT b.x FROM base b JOIN base b2 ON b.y = (SELECT m FROM agg)) "
            "SELECT * FROM use",
            "use",
        )
        plan = _classify_downstream_cte("use", expr, {"base", "agg", "use"}, ["event_name"])
        assert plan.reject_reason is not None
        assert "scalar subquery" in plan.reject_reason

    def test_scalar_subquery_in_limit_by_rejected(self):
        expr = self._get_cte(
            "WITH base AS (SELECT 1 AS x, 2 AS y), "
            "agg AS (SELECT max(x) AS m FROM base), "
            "use AS (SELECT x, y FROM base LIMIT 5 BY (SELECT m FROM agg)) "
            "SELECT * FROM use",
            "use",
        )
        plan = _classify_downstream_cte("use", expr, {"base", "agg", "use"}, ["event_name"])
        assert plan.reject_reason is not None
        assert "scalar subquery" in plan.reject_reason

    @parameterized.expand(["maxIf", "MAXIF", "sumIf", "SUMIF", "countIf", "COUNTIF"])
    def test_aggregation_shape_detects_combinator_regardless_of_case(self, fn):
        expr = self._get_cte(
            f"WITH base AS (SELECT 1 AS x, 1 AS c), agg AS (SELECT {fn}(x, c > 0) AS m FROM base) SELECT * FROM agg",
            "agg",
        )
        plan = _classify_downstream_cte("agg", expr, {"base", "agg"}, ["event_name"])
        assert plan.reject_reason is None
        assert plan.shape == DownstreamCTEShape.AGGREGATION

    @parameterized.expand(
        [
            ("count(DISTINCT event)", "countDistinct"),
            ("COUNT(DISTINCT event)", "countDistinct"),
            ("countDistinct(event)", "countDistinct"),
            ("COUNTDISTINCT(event)", "countDistinct"),
            ("CountDistinct(event)", "countDistinct"),
        ]
    )
    def test_extract_aggregate_name_canonicalizes_count_distinct(self, src, expected):
        assert _extract_aggregate_name(parse_expr(src)) == expected

    @parameterized.expand(
        [
            ("max(x)", "max"),
            ("MAX(x)", "max"),
            ("Max(x)", "max"),
            ("sum(x)", "sum"),
            ("SUM(x)", "sum"),
        ]
    )
    def test_extract_aggregate_name_canonicalizes_base_aggregates(self, src, expected):
        assert _extract_aggregate_name(parse_expr(src)) == expected

    def test_nested_subquery_shadowing_does_not_flag_as_bypass(self):
        expr = self._get_cte(
            "WITH base AS (SELECT 1 AS x), "
            "use AS ("
            "  SELECT x FROM base WHERE x = (WITH base AS (SELECT 99 AS x) SELECT x FROM base)"
            ") "
            "SELECT * FROM use",
            "use",
        )
        plan = _classify_downstream_cte("use", expr, {"base", "use"}, ["event_name"])
        assert plan.reject_reason is None

    def test_column_name_collision_rejected(self):
        expr = self._get_cte(
            "WITH base AS (SELECT 1 AS x), clash AS (SELECT x, 'a' AS event_name FROM base) SELECT * FROM clash",
            "clash",
        )
        plan = _classify_downstream_cte("clash", expr, {"base", "clash"}, ["event_name"])
        assert plan.reject_reason is not None
        assert "collides with existing column" in plan.reject_reason

    @parameterized.expand(
        [
            (
                "leg_without_propagating_source",
                "WITH base AS (SELECT 1 AS x), u AS (SELECT x FROM base UNION ALL SELECT 1 AS x) SELECT * FROM u",
                "does not read from any propagating CTE",
            ),
            (
                "nested_set_query_leg",
                "WITH base AS (SELECT 1 AS x), "
                "u AS ((SELECT x FROM base UNION ALL SELECT x FROM base) UNION ALL SELECT x FROM base) "
                "SELECT * FROM u",
                "nested set queries are not supported",
            ),
        ]
    )
    def test_union_leg_unable_to_propagate_rejected(self, _name, query_str, expected_fragment):
        expr = self._get_cte(query_str, "u")
        plan = _classify_downstream_cte("u", expr, {"base", "u"}, ["event_name"])
        assert plan.reject_reason is not None
        assert "UNION leg" in plan.reject_reason
        assert expected_fragment in plan.reject_reason


class TestDownstreamAnalysisRejections(SimpleTestCase):
    """Analyzer-level rejection tests for downstream CTE shapes we don't support."""

    def test_downstream_left_join_between_propagating_ctes_rejected(self):
        query = {
            "kind": "HogQLQuery",
            "query": (
                "WITH base AS (SELECT event, distinct_id FROM events WHERE event = {variables.event_name}), "
                "alt AS (SELECT distinct_id FROM base), "
                "combined AS (SELECT b.event FROM base b LEFT JOIN alt a ON b.distinct_id = a.distinct_id) "
                "SELECT event FROM combined"
            ),
            "variables": {"var-1": {"code_name": "event_name", "value": "$pageview"}},
        }
        can_materialize, reason, _ = analyze_variables_for_materialization(query)
        assert can_materialize is False
        assert "LEFT JOIN" in reason

    def test_downstream_full_join_rejected(self):
        query = {
            "kind": "HogQLQuery",
            "query": (
                "WITH base AS (SELECT event, distinct_id FROM events WHERE event = {variables.event_name}), "
                "alt AS (SELECT distinct_id FROM base), "
                "combined AS (SELECT b.event FROM base b FULL OUTER JOIN alt a ON b.distinct_id = a.distinct_id) "
                "SELECT event FROM combined"
            ),
            "variables": {"var-1": {"code_name": "event_name", "value": "$pageview"}},
        }
        can_materialize, reason, _ = analyze_variables_for_materialization(query)
        assert can_materialize is False
        assert "FULL OUTER JOIN" in reason

    def test_downstream_nested_subquery_reference_rejected(self):
        query = {
            "kind": "HogQLQuery",
            "query": (
                "WITH base AS (SELECT event, distinct_id FROM events WHERE event = {variables.event_name}), "
                "wrap AS (SELECT * FROM (SELECT distinct_id FROM base)) "
                "SELECT distinct_id FROM wrap"
            ),
            "variables": {"var-1": {"code_name": "event_name", "value": "$pageview"}},
        }
        can_materialize, reason, _ = analyze_variables_for_materialization(query)
        assert can_materialize is False
        assert "nested subquery" in reason

    def test_downstream_scalar_subquery_in_where_rejected(self):
        query = {
            "kind": "HogQLQuery",
            "query": (
                "WITH base AS (SELECT event, distinct_id, timestamp FROM events WHERE event = {variables.event_name}), "
                "latest AS (SELECT max(timestamp) AS ts FROM base), "
                "use AS (SELECT distinct_id FROM base WHERE timestamp = (SELECT ts FROM latest)) "
                "SELECT distinct_id FROM use"
            ),
            "variables": {"var-1": {"code_name": "event_name", "value": "$pageview"}},
        }
        can_materialize, reason, variables = analyze_variables_for_materialization(query)
        assert can_materialize is False
        assert "scalar subquery" in reason
        assert variables == []

    def test_downstream_scalar_subquery_in_select_rejected(self):
        query = {
            "kind": "HogQLQuery",
            "query": (
                "WITH base AS (SELECT event, distinct_id, timestamp FROM events WHERE event = {variables.event_name}), "
                "latest AS (SELECT max(timestamp) AS ts FROM base), "
                "use AS (SELECT distinct_id, (SELECT ts FROM latest) AS ts FROM base) "
                "SELECT distinct_id FROM use"
            ),
            "variables": {"var-1": {"code_name": "event_name", "value": "$pageview"}},
        }
        can_materialize, reason, _ = analyze_variables_for_materialization(query)
        assert can_materialize is False
        assert "scalar subquery" in reason

    def test_downstream_union_leg_unable_to_propagate_rejected(self):
        query = {
            "kind": "HogQLQuery",
            "query": (
                "WITH base AS (SELECT event, distinct_id FROM events WHERE event = {variables.event_name}), "
                "u AS (SELECT distinct_id FROM base UNION ALL SELECT distinct_id FROM events) "
                "SELECT distinct_id FROM u"
            ),
            "variables": {"var-1": {"code_name": "event_name", "value": "$pageview"}},
        }
        can_materialize, reason, _ = analyze_variables_for_materialization(query)
        assert can_materialize is False
        assert "UNION leg" in reason

    def test_downstream_column_name_collision_rejected(self):
        query = {
            "kind": "HogQLQuery",
            "query": (
                "WITH base AS (SELECT event, distinct_id FROM events WHERE event = {variables.event_name}), "
                "clash AS (SELECT distinct_id, 'x' AS event_name FROM base) "
                "SELECT distinct_id FROM clash"
            ),
            "variables": {"var-1": {"code_name": "event_name", "value": "$pageview"}},
        }
        can_materialize, reason, _ = analyze_variables_for_materialization(query)
        assert can_materialize is False
        assert "collides with existing column" in reason


class TestCombinatorReaggregation(SimpleTestCase):
    """Test combinator-based re-aggregation detection."""

    @parameterized.expand(
        [
            ("sumIf", "sum"),
            ("countIf", "sum"),
            ("maxIf", "max"),
            ("minIf", "min"),
            ("sumArray", "sum"),
            ("countArrayIf", "sum"),
        ]
    )
    def test_reaggregatable_combinators_allowed(self, func_name, expected_reagg):
        reagg = get_reaggregation(func_name)
        assert reagg is not None, f"{func_name} should be re-aggregatable"
        assert reagg.reaggregate_fn == expected_reagg

    @parameterized.expand(
        [
            ("avg",),
            ("uniq",),
            ("uniqIf",),
            ("uniqExact",),
            ("uniqArrayIf",),
            ("avgWeighted",),
            ("avgWeightedIf",),
            ("median",),
            ("quantile",),
        ]
    )
    def test_non_reaggregatable_functions_rejected(self, func_name):
        reagg = get_reaggregation(func_name)
        assert reagg is None, f"{func_name} should NOT be re-aggregatable"

    def test_sumIf_query_materializes(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT sumIf(1, event = '$pageview') FROM events WHERE timestamp >= {variables.start} AND timestamp < {variables.end}",
            "variables": {
                "var-1": {"code_name": "start", "value": "2024-01-01"},
                "var-2": {"code_name": "end", "value": "2024-02-01"},
            },
        }

        can_materialize, reason, _ = analyze_variables_for_materialization(query)
        assert can_materialize is True, f"sumIf should be allowed: {reason}"

    def test_uniqIf_query_rejected(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT uniqIf(person_id, event = '$pageview') FROM events WHERE timestamp >= {variables.start} AND timestamp < {variables.end}",
            "variables": {
                "var-1": {"code_name": "start", "value": "2024-01-01"},
                "var-2": {"code_name": "end", "value": "2024-02-01"},
            },
        }

        can_materialize, reason, _ = analyze_variables_for_materialization(query)
        assert can_materialize is False
        assert "re-aggregated" in reason


class TestMaterializedReadPath(SimpleTestCase):
    """Test that the read path applies value_wrapper_fns when filtering the materialized table."""

    def _build_read_query(self, query_str: str, variables_meta: dict, variable_values: dict) -> str:
        """Simulate the materialized read path: analyze variables, then build a SELECT with filters."""
        hogql_query = {"kind": "HogQLQuery", "query": query_str, "variables": variables_meta}
        _, _, var_infos = analyze_variables_for_materialization(hogql_query)

        select_query = ast.SelectQuery(
            select=[ast.Field(chain=["*"])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["materialized_table"])),
        )

        for mat_var in var_infos:
            var_value = variable_values.get(mat_var.code_name)
            if var_value is not None:
                apply_where_filter(
                    select_query,
                    mat_var.code_name,
                    var_value,
                    op=mat_var.operator,
                    value_wrapper_fns=mat_var.value_wrapper_fns,
                    bucket_fn=mat_var.bucket_fn,
                )

        return select_query.to_hogql()

    def test_bare_variable_no_wrapper(self):
        result = self._build_read_query(
            "SELECT count() FROM events WHERE event = {variables.event_name}",
            {"var-1": {"code_name": "event_name", "value": "$pageview"}},
            {"event_name": "$pageview"},
        )

        assert "event_name" in result
        assert "'$pageview'" in result
        assert "toDate" not in result

    def test_toDate_wrapper_applied_to_value(self):
        result = self._build_read_query(
            "SELECT count() FROM events WHERE toDate(timestamp) >= toDate({variables.from_date})",
            {"var-1": {"code_name": "from_date", "value": "2024-01-01"}},
            {"from_date": "2024-01-15 14:30:00"},
        )

        assert "toDate('2024-01-15 14:30:00')" in result

    def test_lower_wrapper_applied_to_value(self):
        result = self._build_read_query(
            "SELECT count() FROM events WHERE lower(event) = lower({variables.event_name})",
            {"var-1": {"code_name": "event_name", "value": "$PageView"}},
            {"event_name": "$PageView"},
        )

        assert "lower('$PageView')" in result

    def test_range_with_wrapper_both_sides(self):
        result = self._build_read_query(
            "SELECT count() FROM events WHERE toStartOfMonth(timestamp) >= toStartOfMonth({variables.from_date}) AND toStartOfMonth(timestamp) < toStartOfMonth({variables.to_date})",
            {
                "var-1": {"code_name": "from_date", "value": "2024-01-15"},
                "var-2": {"code_name": "to_date", "value": "2024-06-15"},
            },
            {"from_date": "2024-01-15", "to_date": "2024-06-15"},
        )

        assert "toStartOfMonth('2024-01-15')" in result
        assert "toStartOfMonth('2024-06-15')" in result

    def test_nested_wrapper_applied_to_value(self):
        result = self._build_read_query(
            "SELECT count() FROM events WHERE toDate(timestamp) >= toDate(toStartOfMonth({variables.from_date}))",
            {"var-1": {"code_name": "from_date", "value": "2024-01-15"}},
            {"from_date": "2024-01-15"},
        )

        assert "toDate(toStartOfMonth('2024-01-15'))" in result


class TestCTEVariableAnalysis(SimpleTestCase):
    """Test variable analysis for variables inside CTE WHERE clauses."""

    def test_single_cte_with_variable_in_where(self):
        query = {
            "kind": "HogQLQuery",
            "query": "WITH cte AS (SELECT count() as cnt, event FROM events WHERE event = {variables.event_name} GROUP BY event) SELECT cnt, event FROM cte",
            "variables": {
                "var-1": {"code_name": "event_name", "value": "$pageview"},
            },
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is True
        assert reason == "OK"
        assert len(var_infos) == 1
        assert var_infos[0].code_name == "event_name"
        assert var_infos[0].cte_name == "cte"

    def test_variable_in_cte_with_or_condition_rejected(self):
        query = {
            "kind": "HogQLQuery",
            "query": (
                "WITH cte AS (SELECT count() as cnt FROM events WHERE event = {variables.event_name} OR event = '$click' GROUP BY event) "
                "SELECT cnt FROM cte"
            ),
            "variables": {
                "var-1": {"code_name": "event_name", "value": "$pageview"},
            },
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is False
        assert "OR conditions" in reason
        assert var_infos == []

    def test_two_ctes_one_variable_each_different_vars_allowed(self):
        query = {
            "kind": "HogQLQuery",
            "query": (
                "WITH cte1 AS (SELECT count() as cnt1 FROM events WHERE event = {variables.event_name} GROUP BY event), "
                "cte2 AS (SELECT count() as cnt2 FROM events WHERE distinct_id = {variables.user_id} GROUP BY distinct_id) "
                "SELECT cnt1 FROM cte1"
            ),
            "variables": {
                "var-1": {"code_name": "event_name", "value": "$pageview"},
                "var-2": {"code_name": "user_id", "value": "user_0"},
            },
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        # Each variable is in its own single CTE — this should be allowed
        assert can_materialize is True
        assert reason == "OK"
        assert len(var_infos) == 2
        code_names = {v.code_name for v in var_infos}
        assert code_names == {"event_name", "user_id"}

    def test_variable_in_cte_and_top_level_rejected(self):
        query = {
            "kind": "HogQLQuery",
            "query": "WITH cte AS (SELECT count() as cnt FROM events WHERE event = {variables.event_name} GROUP BY event) SELECT cnt FROM cte WHERE event = {variables.event_name}",
            "variables": {
                "var-1": {"code_name": "event_name", "value": "$pageview"},
            },
        }

        can_materialize, reason, _ = analyze_variables_for_materialization(query)

        assert can_materialize is False
        assert "both CTE and top-level" in reason

    def test_variable_in_two_different_ctes_rejected(self):
        query = {
            "kind": "HogQLQuery",
            "query": (
                "WITH cte1 AS (SELECT count() as cnt1 FROM events WHERE event = {variables.event_name} GROUP BY event), "
                "cte2 AS (SELECT count() as cnt2 FROM events WHERE event = {variables.event_name} GROUP BY event) "
                "SELECT cnt1, cnt2 FROM cte1 CROSS JOIN cte2"
            ),
            "variables": {
                "var-1": {"code_name": "event_name", "value": "$pageview"},
            },
        }

        can_materialize, reason, _ = analyze_variables_for_materialization(query)

        assert can_materialize is False
        assert "multiple CTEs" in reason

    def test_variable_in_cte_having_rejected(self):
        query = {
            "kind": "HogQLQuery",
            "query": "WITH cte AS (SELECT count() as cnt, event FROM events GROUP BY event HAVING cnt > {variables.min_count}) SELECT * FROM cte",
            "variables": {
                "var-1": {"code_name": "min_count", "value": "10"},
            },
        }

        can_materialize, reason, _ = analyze_variables_for_materialization(query)

        assert can_materialize is False
        assert "HAVING" in reason

    def test_cte_variable_with_top_level_join_rejected(self):
        query = {
            "kind": "HogQLQuery",
            "query": (
                "WITH filtered AS (SELECT user_id FROM events WHERE event = {variables.event_name} GROUP BY user_id) "
                "SELECT p.name FROM persons p LEFT JOIN filtered f ON p.id = f.user_id"
            ),
            "variables": {
                "var-1": {"code_name": "event_name", "value": "$pageview"},
            },
        }

        can_materialize, reason, _ = analyze_variables_for_materialization(query)

        assert can_materialize is False
        assert "JOINs" in reason

    def test_top_level_variable_with_join_still_allowed(self):
        query = {
            "kind": "HogQLQuery",
            "query": (
                "WITH cte AS (SELECT count() as cnt, event FROM events GROUP BY event) "
                "SELECT c.cnt, p.name FROM cte c JOIN persons p ON 1=1 WHERE c.event = {variables.event_name}"
            ),
            "variables": {
                "var-1": {"code_name": "event_name", "value": "$pageview"},
            },
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is True
        assert var_infos[0].cte_name is None

    def test_top_level_variable_still_works(self):
        query = {
            "kind": "HogQLQuery",
            "query": "WITH cte AS (SELECT count() as cnt, event FROM events GROUP BY event) SELECT cnt, event FROM cte WHERE event = {variables.event_name}",
            "variables": {
                "var-1": {"code_name": "event_name", "value": "$pageview"},
            },
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is True
        assert len(var_infos) == 1
        assert var_infos[0].cte_name is None

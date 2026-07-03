from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.errors import SyntaxError as HogQLSyntaxError
from posthog.hogql.visitor import clear_locations

from products.logs.backend.column_expressions import canonical_key, column_to_expr, path_to_expr


class TestPathToExpr(SimpleTestCase):
    @parameterized.expand(
        [
            ("flat_attribute_key", "attributes", "http.url"),
            ("flat_resource_attribute_key", "resource_attributes", "service.name"),
        ]
    )
    def test_flat_map_key_lowers_to_field_chain(self, _name, source, path):
        # attributes / resource_attributes: the whole path is a single map key (dots included)
        assert path_to_expr(source, path) == ast.Field(chain=[source, path])

    def test_dotted_attribute_path_stays_a_single_flat_key(self):
        # source-driven: a dotted attribute path is NOT split into a nested dig
        assert path_to_expr("attributes", "a.b.c") == ast.Field(chain=["attributes", "a.b.c"])

    def test_body_nested_json_path_lowers_to_jsonextractstring(self):
        assert path_to_expr("body", "user.id") == ast.Call(
            name="JSONExtractString",
            args=[ast.Field(chain=["body"]), ast.Constant(value="user"), ast.Constant(value="id")],
        )

    def test_body_single_segment_path_lowers_to_jsonextractstring(self):
        assert path_to_expr("body", "message") == ast.Call(
            name="JSONExtractString",
            args=[ast.Field(chain=["body"]), ast.Constant(value="message")],
        )

    @parameterized.expand(
        [
            ("double_dot", "a..b"),
            ("leading_dot", ".a"),
            ("trailing_dot", "a."),
        ]
    )
    def test_body_path_with_empty_segment_is_rejected(self, _name, path):
        # an empty segment is a user typo, not a valid JSON key -> surface it instead of digging ''
        with self.assertRaises(ValueError):
            path_to_expr("body", path)

    def test_injection_in_attribute_key_is_kept_as_bound_string(self):
        malicious = "x'] AS y, (SELECT 1) --"
        expr = path_to_expr("attributes", malicious)
        # the malicious input survives verbatim as a chain member, never parsed as SQL
        assert isinstance(expr, ast.Field)
        assert expr.chain == ["attributes", malicious]

    def test_injection_in_body_path_is_kept_as_bound_constants(self):
        malicious = "') OR 1=1 --"
        expr = path_to_expr("body", malicious)
        # no dots -> one segment, carried as a bound Constant, not interpolated SQL
        assert isinstance(expr, ast.Call)
        assert expr.name == "JSONExtractString"
        assert expr.args[0] == ast.Field(chain=["body"])
        assert expr.args[1] == ast.Constant(value=malicious)


class TestColumnToExpr(SimpleTestCase):
    @parameterized.expand(
        [
            ("attributes_flat_key", "attributes.http.url", ast.Field(chain=["attributes", "http.url"])),
            (
                "resource_attributes_flat_key",
                "resource_attributes.service.name",
                ast.Field(chain=["resource_attributes", "service.name"]),
            ),
            (
                "body_json_dig",
                "body.user.id",
                ast.Call(
                    name="JSONExtractString",
                    args=[ast.Field(chain=["body"]), ast.Constant(value="user"), ast.Constant(value="id")],
                ),
            ),
        ]
    )
    def test_recognized_prefix_routes_to_shorthand(self, _name, text, expected):
        assert column_to_expr(text) == expected

    def test_bare_source_name_is_not_shorthand(self):
        # "attributes" with no path falls through to HogQL as a plain field
        assert clear_locations(column_to_expr("attributes")) == ast.Field(chain=["attributes"])

    def test_unrecognized_prefix_parses_as_hogql(self):
        # a top-level field with dots but no recognized source is HogQL field access, not shorthand
        expr = clear_locations(column_to_expr("upper(level)"))
        assert expr == ast.Call(name="upper", args=[ast.Field(chain=["level"])])

    def test_scalar_functions_and_map_access_are_allowed(self):
        # coalesce over map indexing exercises the validator's allow path on a compound expression
        expr = column_to_expr("coalesce(attributes['a'], attributes['b'])")
        assert isinstance(expr, ast.Call)
        assert expr.name == "coalesce"

    @parameterized.expand(
        [
            ("top_level_aggregate", "count()"),
            ("case_insensitive_aggregate", "COUNT()"),
            ("nested_aggregate", "upper(toString(sum(1)))"),
            ("subquery", "(SELECT 1)"),
            ("placeholder", "{cursor}"),
            # Row-multiplying functions would expand a per-row column into many rows — a low-friction DoS.
            ("array_join_row_multiplier", "arrayJoin(range(1000000000))"),
            ("array_join_case_insensitive", "ARRAYJOIN([1, 2, 3])"),
            ("nested_array_join", "toString(arrayJoin(range(10)))"),
            # Value-generating functions build a huge per-row value from a small constant argument without
            # multiplying rows — the row-multiplier check above misses them.
            ("range_generator", "range(1000000000)"),
            ("range_case_insensitive", "RANGE(10)"),
            ("nested_range_generator", "length(range(1000000000))"),
            ("repeat_generator", "repeat(body, 1000000000)"),
            ("arraywithconstant_generator", "arrayWithConstant(1000000000, 'x')"),
        ]
    )
    def test_non_scalar_expressions_are_rejected(self, _name, text):
        with self.assertRaises(ValueError):
            column_to_expr(text)

    def test_unparsable_input_raises_instead_of_passing_through(self):
        # tier 2 goes through parse_expr: junk is a syntax error, never interpolated SQL
        with self.assertRaises(HogQLSyntaxError):
            column_to_expr("level; DROP TABLE logs")


class TestCanonicalKey(SimpleTestCase):
    @parameterized.expand(
        [
            ("attributes_http_url", "attributes.http.url", "col_7284f0d699a5"),
            ("body_user_id", "body.user.id", "col_d26ac1a56e8b"),
            ("upper_level", "upper(level)", "col_ec05982ca9de"),
        ]
    )
    def test_canonical_key_is_stable(self, _name, text, expected):
        assert canonical_key(text) == expected

    def test_canonical_key_differs_by_expression(self):
        assert canonical_key("attributes.http.url") != canonical_key("attributes.http.method")

    def test_canonical_key_ignores_surrounding_whitespace(self):
        # column_to_expr strips input, so the alias must too — else identical columns miss the cache
        assert canonical_key(" upper(level) ") == canonical_key("upper(level)")

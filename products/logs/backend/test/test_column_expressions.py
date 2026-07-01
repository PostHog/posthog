from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql import ast

from products.logs.backend.column_expressions import canonical_key, path_to_expr


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


class TestCanonicalKey(SimpleTestCase):
    @parameterized.expand(
        [
            ("attributes", "http.url", "col_4d1ef362ef20"),
            ("body", "user.id", "col_b74ba7d37d48"),
            ("resource_attributes", "service.name", "col_acc699467fd2"),
        ]
    )
    def test_canonical_key_is_stable(self, source, path, expected):
        assert canonical_key(source, path) == expected

    def test_canonical_key_differs_by_source_and_path(self):
        assert canonical_key("attributes", "http.url") != canonical_key("body", "http.url")
        assert canonical_key("attributes", "http.url") != canonical_key("attributes", "http.method")

    def test_canonical_key_separator_prevents_collisions(self):
        # ("ab","c") and ("a","bc") must not collide despite naive concatenation
        assert canonical_key("ab", "c") != canonical_key("a", "bc")

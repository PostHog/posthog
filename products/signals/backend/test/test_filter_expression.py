from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.filter_expression import FilterExpression, FilterValidationError


class TestFilterExpression(SimpleTestCase):
    fields = {
        "project_name": "string",
        "priority": "integer",
        "label_names": "array<string>",
    }

    @parameterized.expand(
        [
            "false",
            "true",
            "priority IN (1, 2)",
            "priority IN (1)",
            "project_name NOT IN ('Core')",
            "priority = -1",
            "priority NOT IN (1, 2)",
            "project_name IS NULL",
            "project_name = 'Core' AND NOT has(label_names, 'internal')",
            "isNull(label_names)",
            "HAS(label_names, 'internal')",
            "empty(label_names)",
            "NOT notEmpty(label_names)",
            "EMPTY(label_names) OR priority = 1",
        ]
    )
    def test_boolean_contract(self, expression: str) -> None:
        self.assertIsNotNone(FilterExpression(expression, self.fields).predicate())

    @parameterized.expand(
        [
            "SELECT true",
            "(SELECT true)",
            "priority IN (SELECT team_id FROM events)",
            "events.team_id = 1",
            "project_name.foo = 'x'",
            "unknown = 1",
            "{priority} = 1",
            "sum(priority) > 0",
            "count() OVER () > 0",
            "arrayExists(x -> x = 'x', label_names)",
            "sleep(10) = 0",
            "priority + 1 > 2",
            "priority GLOBAL IN (1, 2)",
            "project_name =~ '.*'",
            "priority",
            "1",
            "'true'",
            "NULL",
            "priority AND true",
            "NOT priority",
            "priority = '1'",
            "has(label_names, 1)",
            "has(label_names, project_name)",
            "priority = 1.5",
            "project_name LIKE '%core%'",
            "project_name ILIKE '%core%'",
            "lower(project_name) = 'core'",
            "upper(project_name) = 'CORE'",
            "startsWith(project_name, 'co')",
            "endsWith(project_name, 're')",
            "length(label_names) > 0",
            "notEmpty(project_name)",
            "empty(priority)",
            "empty(['x'])",
            "empty(label_names, label_names)",
            "has(priority, 1)",
            "label_names = ['x']",
            "priority IN (project_name, priority)",
            "priority IN (1, '2')",
            "priority IN ('1')",
            "priority IN (priority)",
            "priority IN (NULL)",
            "true; SELECT true",
            "true AS accepted",
            "isNull(priority, priority)",
            "has(('a', 'b'), 'a')",
            "toDateTime('2026-01-02T00:00:00Z') IS NULL",
        ]
    )
    def test_rejects_unsafe_or_untyped_expression(self, expression: str) -> None:
        with self.assertRaises(FilterValidationError):
            FilterExpression(expression, self.fields)

    @parameterized.expand(
        [
            ("length", " " * 4097, "expression_limit"),
            ("depth", "NOT " * 22 + "true", "complexity_limit"),
            ("nodes", " OR ".join(["priority = 1"] * 90), "complexity_limit"),
            ("list", "priority IN (" + ",".join(str(i) for i in range(65)) + ")", "type"),
            ("string", "project_name = '" + "x" * 1025 + "'", "literal_limit"),
            ("integer", "priority = 9223372036854775808", "literal_limit"),
        ]
    )
    def test_complexity_limits(self, _name: str, expression: str, code: str) -> None:
        with self.assertRaises(FilterValidationError) as raised:
            FilterExpression(expression, self.fields)
        self.assertEqual(raised.exception.code, code)

    @parameterized.expand(["boolean", "number", "datetime", "array<integer>", "array<number>", "array<boolean>"])
    def test_rejects_deferred_field_types(self, field_type: str) -> None:
        with self.assertRaises(FilterValidationError) as raised:
            FilterExpression("", {"future_field": field_type})
        self.assertEqual(raised.exception.code, "unsupported_field_type")

    def test_blank_expression_has_no_predicate(self) -> None:
        self.assertIsNone(FilterExpression(" \n ", self.fields).predicate())

    @parameterized.expand(
        [
            ("unknown_field", "project_name = 'Core' AND unknown = 1", "unknown_field", 26, 33),
            ("unknown_field_after_non_ascii", "project_name = 'Cœur' AND unknown = 1", "unknown_field", 26, 33),
            ("type", "priority = 'high'", "type", 0, 17),
            ("boolean_required", "project_name", "boolean_required", 0, 12),
            ("syntax_trailing_token", "project_name = 'Core' )", "syntax", 22, 23),
            ("syntax_ends_early", "project_name = ", "syntax", 15, 15),
            ("syntax_after_non_ascii", "project_name = 'Cœur' )", "syntax", None, None),
            ("expression_limit", " " * 4097, "expression_limit", None, None),
        ]
    )
    def test_error_position(self, _name: str, expression: str, code: str, start: int | None, end: int | None) -> None:
        with self.assertRaises(FilterValidationError) as raised:
            FilterExpression(expression, self.fields)
        self.assertEqual((raised.exception.code, raised.exception.start, raised.exception.end), (code, start, end))

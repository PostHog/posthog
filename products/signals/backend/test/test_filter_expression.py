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
            "empty(label_names)",
            "notEmpty(project_name)",
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

    def test_blank_and_structured_errors(self) -> None:
        self.assertIsNone(FilterExpression(" \n ", self.fields).predicate())
        with self.assertRaises(FilterValidationError) as raised:
            FilterExpression("unknown = 1", self.fields)
        self.assertEqual(raised.exception.code, "unknown_field")
        self.assertIsNotNone(raised.exception.start)
        self.assertIsNotNone(raised.exception.end)

from datetime import date

from django.test import SimpleTestCase

from parameterized import parameterized

from products.docs.backend.facade.enums import DataShape
from products.docs.backend.logic import data_points
from products.docs.backend.logic.data_points import extract_query, is_read_query


class TestDataPointQueries(SimpleTestCase):
    @parameterized.expand(
        [
            ('<hogql label="teams">SELECT 1</hogql>', ("SELECT 1", "teams")),
            (
                '<hogql display="block" title="Signups">\nSELECT count() FROM events;\n</hogql>',
                ("SELECT count() FROM events", "Signups"),
            ),
            (
                "first <hogql>SELECT 1</hogql> then <hogql>WITH x AS (SELECT 2) SELECT * FROM x</hogql>",
                ("WITH x AS (SELECT 2) SELECT * FROM x", ""),
            ),
            ("<hogql>DELETE FROM events</hogql>", None),
            ("no tag here", None),
        ]
    )
    def test_extract_query_reads_the_last_read_only_tag(self, text, expected):
        assert extract_query(text) == expected

    @parameterized.expand(
        [
            ("SELECT 1;", True),
            ("  with a as (select 1) select 1", True),
            ("SELECT 1; SELECT 2", False),
            ("INSERT INTO x", False),
        ]
    )
    def test_is_read_query(self, query, expected):
        assert is_read_query(query) is expected


class TestClassify(SimpleTestCase):
    @parameterized.expand(
        [
            ([[42]], DataShape.NUMBER, "42"),
            ([[date(2026, 9, 1), 3], ["2026-09-02", 5.5]], DataShape.SERIES, "5.5"),
            ([[3, "2026-09-01"], [5, "2026-09-02"]], DataShape.SERIES, "5"),
            ([["$pageview", 3], ["$autocapture", 5]], DataShape.TABLE, None),
            ([[1, 2, 3]], DataShape.TABLE, None),
            ([[1], [2]], DataShape.TABLE, None),
        ]
    )
    def test_classify_reads_the_shape(self, rows, shape, value):
        run = data_points.classify(rows)
        assert (run.shape, run.value, run.error) == (shape, value, None)

    def test_classify_refuses_an_empty_result(self):
        assert data_points.classify([]).error == "The query came back with no rows."

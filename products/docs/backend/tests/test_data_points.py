from django.test import SimpleTestCase

from parameterized import parameterized

from products.docs.backend.logic.data_points import extract_query, extract_structured, is_read_query


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

    @parameterized.expand(
        [
            (
                '{"status": "ok", "query": "SELECT 1", "label": "one"}',
                {"status": "ok", "query": "SELECT 1", "label": "one", "note": ""},
            ),
            (
                '```json\n{"status": "none", "note": "no data"}\n```',
                {"status": "none", "query": "", "label": "", "note": "no data"},
            ),
            ("Sure, here it is: SELECT 1", None),
            ('{"status": "maybe"}', None),
        ]
    )
    def test_extract_structured_reads_the_schema_shaped_turn(self, text, expected):
        assert extract_structured(text) == expected

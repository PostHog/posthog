import re
from functools import cache
from pathlib import Path

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.functions.mapping import find_hogql_aggregation, find_hogql_function, find_hogql_posthog_function
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast

GUIDELINES = Path(__file__).parents[2] / "skills" / "querying-posthog-data" / "references" / "guidelines.md"
CODE_SPAN = re.compile(r"`([^`]+\))`")
BARE_CALL = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\(\)")
# The table's example arguments, so a span like `quantileIf(0.9)(x, cond)` resolves.
PLACEHOLDER_COLUMNS = "SELECT 1 AS x, 1 AS cond, now() AS timestamp, 1 AS bitmap"


def _function_table_rows() -> list[tuple[str, list[str], list[str]]]:
    section = GUIDELINES.read_text().split("##### Unsupported/changed functions", 1)[1].split("#####", 1)[0]
    rows = [line for line in section.splitlines() if " | " in line and not line.startswith("Don't use")]
    return [
        (left, CODE_SPAN.findall(left), CODE_SPAN.findall(right))
        for left, right in (row.split(" | ", 1) for row in rows)
    ]


@cache
def _database() -> Database:
    return Database()


def _prints(query: str) -> bool:
    context = HogQLContext(database=_database(), enable_select_queries=True, use_new_events_schema=False)
    try:
        prepare_and_print_ast(parse_select(query), context, "clickhouse")
    except BaseHogQLError:
        return False
    return True


def _works(span: str) -> bool:
    if bare := BARE_CALL.fullmatch(span):
        name = bare.group(1)
        return any(find(name) for find in (find_hogql_function, find_hogql_aggregation, find_hogql_posthog_function))
    return _prints(f"SELECT {span} FROM ({PLACEHOLDER_COLUMNS})")


# The rule examples in guidelines.md "Other rules". Aggregate aliases that shadow a column, `windowFunnel(timestamp)`
# and `arraySum` over raw JSON fail only inside ClickHouse, so only their fixes are checked here.
SYNTAX_RULE_EXAMPLES: list[tuple[str, bool]] = [
    *[(f"SELECT count() {keyword} FROM events", False) for keyword in ("first", "last", "day", "step", "name", "rows")],
    *[
        (f"SELECT count() AS {keyword} FROM events", True)
        for keyword in ("first", "last", "day", "step", "name", "rows")
    ],
    *[
        (f"SELECT count() AS {reserved} FROM events", False)
        for reserved in ("fn", "fun", "let", "try", "catch", "throw", "while", "null", "true", "false", "inf", "nan")
    ],
    ("SELECT count() AS `fn` FROM events", True),
    ("WITH toDate(timestamp) AS day SELECT day, count() AS c FROM events GROUP BY day", False),
    ("WITH 7 AS days SELECT days", True),
    (r"SELECT count() AS c FROM events WHERE match(event, '\d+')", False),
    (r"SELECT count() AS c FROM events WHERE match(event, '\\d+')", True),
    (r"SELECT count() AS c FROM events WHERE event LIKE '%\_%'", False),
    (r"SELECT count() AS c FROM events WHERE event LIKE '%\\_%'", True),
    ("""SELECT 'say "hi"' AS greeting""", True),
    ("SELECT count() AS c FROM system.tables", False),
    ("SELECT count() AS c FROM system.information_schema.tables", True),
    ("SELECT event, max(timestamp) AS last_seen FROM events GROUP BY event", True),
    (
        "SELECT windowFunnel(3600)(toUnixTimestamp(timestamp), event = 'a') AS level FROM events GROUP BY person_id",
        True,
    ),
    ("SELECT arraySum(arrayMap(x -> toFloatOrZero(x), JSONExtractArrayRaw('[1, 2]'))) AS total", True),
]


class TestQueryingGuidelines(SimpleTestCase):
    def test_table_is_parsed(self) -> None:
        self.assertGreater(len(_function_table_rows()), 10)

    @parameterized.expand(_function_table_rows)
    def test_row_matches_hogql(self, _row: str, avoid: list[str], use_instead: list[str]) -> None:
        self.assertTrue(avoid and use_instead)
        self.assertEqual([span for span in avoid if _works(span)], [])
        self.assertEqual([span for span in use_instead if not _works(span)], [])

    @parameterized.expand(SYNTAX_RULE_EXAMPLES)
    def test_rule_example_matches_hogql(self, query: str, works: bool) -> None:
        self.assertEqual(_prints(query), works)

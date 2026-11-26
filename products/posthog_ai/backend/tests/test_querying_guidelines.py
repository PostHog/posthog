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


def _works(span: str) -> bool:
    if bare := BARE_CALL.fullmatch(span):
        name = bare.group(1)
        return any(find(name) for find in (find_hogql_function, find_hogql_aggregation, find_hogql_posthog_function))
    context = HogQLContext(database=_database(), enable_select_queries=True, use_new_events_schema=False)
    try:
        prepare_and_print_ast(parse_select(f"SELECT {span} FROM ({PLACEHOLDER_COLUMNS})"), context, "clickhouse")
    except BaseHogQLError:
        return False
    return True


class TestQueryingGuidelinesFunctionTable(SimpleTestCase):
    def test_table_is_parsed(self) -> None:
        self.assertGreater(len(_function_table_rows()), 10)

    @parameterized.expand(_function_table_rows)
    def test_row_matches_hogql(self, _row: str, avoid: list[str], use_instead: list[str]) -> None:
        self.assertTrue(avoid and use_instead)
        self.assertEqual([span for span in avoid if _works(span)], [])
        self.assertEqual([span for span in use_instead if not _works(span)], [])

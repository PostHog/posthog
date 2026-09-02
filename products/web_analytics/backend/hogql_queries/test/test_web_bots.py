import re
from typing import Any, Optional

from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)

from parameterized import parameterized

from posthog.schema import DateRange, WebBotsBreakdown, WebBotsTableQuery

from products.web_analytics.backend.hogql_queries.bot_definitions import BOT_DEFINITIONS
from products.web_analytics.backend.hogql_queries.web_bots import WebBotsTableQueryRunner

GOOGLEBOT_UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
HUMAN_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

# ClickHouse string literals escape with backslashes, so an apostrophe in a bot pattern
# or label arrives as \' rather than ''. See posthog/hogql/escape_sql.py.
_STRING = re.compile(r"'(?:[^'\\]|\\.)*'")
_LITERAL_ARRAY = re.compile(rf"\[{_STRING.pattern}(?:, {_STRING.pattern}){{19,}}\]")
_IP_GROUP_MATCH = re.compile(r"\bin\(tupleElement\(IPv6CIDRToRange\(")
_ADJACENT_IP_GROUPS = re.compile(r"/\* bot ip range \*/(?:, /\* bot ip range \*/)+")

# Both the pattern list and each label list run one entry longer than the table, because
# HogQL appends the empty user agent sentinel. Keying the collapse on that length leaves an
# unrelated array, such as a property filter holding many values, visible in the snapshot.
_BOT_ARRAY_LENGTH = len(BOT_DEFINITIONS) + 1


def _end_of_call(query: str, call_start: int) -> int:
    depth = 0
    for index in range(query.index("(", call_start), len(query)):
        if query[index] == "(":
            depth += 1
        elif query[index] == ")":
            depth -= 1
            if depth == 0:
                return index + 1
    raise ValueError("unbalanced parentheses in captured query")


def _collapse_array(array: re.Match[str]) -> str:
    length = len(_STRING.findall(array.group(0)))
    if length != _BOT_ARRAY_LENGTH:
        return array.group(0)
    return f"[/* {length} bot literals */]"


# The bot gate expands into every query: the user agent patterns and labels from
# BOT_DEFINITIONS, plus one IPv6 range check per prefix group in BOT_IP_DEFINITIONS,
# repeated for each column that classifies traffic. Left verbatim they bury the query
# shape this snapshot exists to protect, and any change to the tables rewrites the
# snapshot. The tables keep their own coverage in test_bot_definitions.py, and the
# expression built from them in test_traffic_type_snapshot.ambr.
def _collapse_bot_tables(query: str) -> str:
    parts: list[str] = []
    position = 0
    while (match := _IP_GROUP_MATCH.search(query, position)) is not None:
        parts.append(query[position : match.start()])
        parts.append("/* bot ip range */")
        position = _end_of_call(query, match.start())
    parts.append(query[position:])
    collapsed = _ADJACENT_IP_GROUPS.sub("/* bot ip ranges */", "".join(parts))
    return _LITERAL_ARRAY.sub(_collapse_array, collapsed)


@snapshot_clickhouse_queries
class TestWebBotsTableQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def assertQueryMatchesSnapshot(
        self, query: str, params: Optional[dict[str, Any]] = None, replace_all_numbers: bool = False
    ) -> None:
        super().assertQueryMatchesSnapshot(_collapse_bot_tables(query), params, replace_all_numbers)

    def _create_pageview(self, distinct_id: str, user_agent: str, pathname: str) -> None:
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id,
            timestamp="2026-01-10T12:00:00Z",
            properties={
                "$raw_user_agent": user_agent,
                "$ip": "203.0.113.7",
                "$pathname": pathname,
                "$session_id": "s1",
            },
        )

    def _run(self, breakdown_by: WebBotsBreakdown) -> list[list]:
        query = WebBotsTableQuery(
            breakdownBy=breakdown_by,
            dateRange=DateRange(date_from="2026-01-01", date_to="2026-01-31"),
            properties=[],
        )
        runner = WebBotsTableQueryRunner(team=self.team, query=query)
        return runner.calculate().results

    @parameterized.expand(
        [
            # If the runner drops the $virt_is_bot/$virt_bot_name gate, human
            # traffic leaks into the bot tables; if the breakdown dispatch is
            # inverted, the Crawler tile shows paths. Both surface as the wrong
            # first column or row count here.
            (WebBotsBreakdown.CRAWLER, "Googlebot"),
            (WebBotsBreakdown.PATH, "/pricing"),
        ]
    )
    def test_only_bot_traffic_grouped_by_breakdown(
        self, breakdown_by: WebBotsBreakdown, expected_first_value: str
    ) -> None:
        with freeze_time("2026-01-10T11:00:00Z"):
            _create_person(team_id=self.team.pk, distinct_ids=["bot"], properties={})
            _create_person(team_id=self.team.pk, distinct_ids=["human"], properties={})
        self._create_pageview("bot", GOOGLEBOT_UA, "/pricing")
        self._create_pageview("bot", GOOGLEBOT_UA, "/pricing")
        self._create_pageview("human", HUMAN_UA, "/pricing")

        with freeze_time("2026-01-15T00:00:00Z"):
            results = self._run(breakdown_by)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], expected_first_value)
        requests_column = 2
        self.assertEqual(results[0][requests_column], 2)  # human pageview excluded

    def test_date_range_excludes_outside_events(self) -> None:
        with freeze_time("2026-01-10T11:00:00Z"):
            _create_person(team_id=self.team.pk, distinct_ids=["bot"], properties={})
        self._create_pageview("bot", GOOGLEBOT_UA, "/pricing")

        with freeze_time("2026-03-15T00:00:00Z"):
            query = WebBotsTableQuery(
                breakdownBy=WebBotsBreakdown.CRAWLER,
                dateRange=DateRange(date_from="2026-03-01", date_to="2026-03-31"),
                properties=[],
            )
            results = WebBotsTableQueryRunner(team=self.team, query=query).calculate().results

        self.assertEqual(results, [])

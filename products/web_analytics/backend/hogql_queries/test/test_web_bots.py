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

from products.web_analytics.backend.hogql_queries.web_bots import WebBotsTableQueryRunner

GOOGLEBOT_UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
HUMAN_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

_STRING = r"'(?:[^']|'')*'"
_BOT_LITERAL_ARRAY = re.compile(rf"\[{_STRING}(?:, {_STRING}){{19,}}\]")
_IP_GROUP_MATCH = re.compile(r"\bin\(tupleElement\(IPv6CIDRToRange\(")
_ADJACENT_IP_GROUPS = re.compile(r"/\* bot ip range \*/(?:, /\* bot ip range \*/)+")


def _end_of_call(query: str, call_start: int) -> int:
    """Index just past the closing paren of the call that starts at `call_start`."""
    depth = 0
    for index in range(query.index("(", call_start), len(query)):
        if query[index] == "(":
            depth += 1
        elif query[index] == ")":
            depth -= 1
            if depth == 0:
                return index + 1
    raise ValueError("unbalanced parentheses in captured query")


def _collapse_bot_tables(query: str) -> str:
    """Replace the inlined bot definition tables with markers.

    The bot gate expands into every query: the user agent patterns and labels from
    BOT_DEFINITIONS, plus one IPv6 range check per prefix group in BOT_IP_DEFINITIONS,
    repeated for each column that classifies traffic. Left verbatim they bury the query
    shape this snapshot exists to protect, and any change to the tables rewrites the
    snapshot. The tables themselves are covered by test_bot_definitions.py, and the
    expression built from them by test_traffic_type_snapshot.ambr.
    """
    parts: list[str] = []
    position = 0
    while (match := _IP_GROUP_MATCH.search(query, position)) is not None:
        parts.append(query[position : match.start()])
        parts.append("/* bot ip range */")
        position = _end_of_call(query, match.start())
    parts.append(query[position:])
    collapsed = _ADJACENT_IP_GROUPS.sub("/* bot ip ranges */", "".join(parts))
    return _BOT_LITERAL_ARRAY.sub(lambda array: f"[/* {array.group(0).count(', ') + 1} bot literals */]", collapsed)


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

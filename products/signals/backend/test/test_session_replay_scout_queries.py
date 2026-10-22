from datetime import UTC, datetime, timedelta
from pathlib import Path

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.models.utils import uuid7
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.test.persons import create_person

SKILL_PATH = Path(__file__).resolve().parents[2] / "skills" / "signals-scout-session-replay" / "SKILL.md"
URL = "https://example.com/checkout/123?step=2"


def _skill_query(heading: str) -> str:
    section = SKILL_PATH.read_text().split(heading, 1)[1]
    return section.split("```sql\n", 1)[1].split("\n```", 1)[0]


class TestBrokenExperienceCohortQuery(ClickhouseTestMixin, BaseTest):
    def _session(self, distinct_id: str, *, with_events: bool = True) -> None:
        session_id = str(uuid7())
        started_at = datetime.now(UTC) - timedelta(hours=1)
        produce_replay_summary(
            team_id=self.team.pk,
            session_id=session_id,
            distinct_id=distinct_id,
            first_timestamp=started_at,
            last_timestamp=started_at + timedelta(minutes=5),
            first_url=URL,
            ensure_analytics_event_in_session=False,
        )
        sync_execute(
            "INSERT INTO writable_session_replay_features "
            "(session_id, team_id, distinct_id, min_first_timestamp, max_last_timestamp, event_count, "
            "console_error_after_click_count) "
            "SELECT %(session_id)s, %(team_id)s, %(distinct_id)s, now64(6) - INTERVAL 1 HOUR, now64(6), 10, 2",
            {"session_id": session_id, "team_id": self.team.pk, "distinct_id": distinct_id},
        )
        if with_events:
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=distinct_id,
                properties={"$session_id": session_id},
                timestamp=started_at + timedelta(minutes=1),
            )

    def test_one_person_with_several_distinct_ids_counts_once(self) -> None:
        repeat_ids = ["anon-1", "device-2", "user-3"]
        create_person(team=self.team, distinct_ids=repeat_ids)
        for index in range(7):
            self._session(repeat_ids[index % len(repeat_ids)])
        for distinct_id in ["other-1", "other-2", "other-3"]:
            create_person(team=self.team, distinct_ids=[distinct_id])
            self._session(distinct_id)
        self._session("no-events", with_events=False)
        flush_persons_and_events()

        response = execute_hogql_query(_skill_query("#### Broken-experience cohort"), team=self.team)

        assert response.columns is not None
        rows = [dict(zip(response.columns, row)) for row in response.results]
        assert [
            (row["url"], row["sessions"], row["mapped_sessions"], row["persons"], row["errors_after_click"])
            for row in rows
        ] == [("https://example.com/checkout/:id", 11, 10, 4, 22)]

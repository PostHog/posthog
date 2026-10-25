import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    run_clickhouse_statement_in_parallel,
)

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.models.app_metrics2.sql import TRUNCATE_APP_METRICS2_TABLE_SQL
from posthog.test.fixtures import create_app_metric2

RECIPES = Path(__file__).resolve().parent.parent / "references" / "recipes.md"
RECIPE_HEADING = re.compile(r"^### (.+)$", re.MULTILINE)
SQL_FENCE = re.compile(r"```sql\n(.*?)\n```", re.DOTALL)

WORKFLOW_ID = "01a00000-0000-0000-0000-000000000001"
OTHER_WORKFLOW_ID = "01a00000-0000-0000-0000-000000000002"
STEP_ID = "action_function_email_welcome"
OTHER_STEP_ID = "action_function_email_reminder"
RUN_ID = "01a00000-0000-0000-0000-0000000000aa"
OTHER_RUN_ID = "01a00000-0000-0000-0000-0000000000bb"
OUTCOME_EVENT = "insight created"
NOW = datetime.now(UTC).replace(microsecond=0)
WINDOW_START = NOW - timedelta(days=30)
WINDOW_END = NOW - timedelta(days=1)


def _recipes() -> dict[str, str]:
    sections = RECIPE_HEADING.split(RECIPES.read_text(encoding="utf-8"))[1:]
    recipes = {}
    for name, body in zip(sections[::2], sections[1::2]):
        (query,) = SQL_FENCE.findall(body)
        recipes[name] = query
    return recipes


def _placeholders() -> dict[str, ast.Expr]:
    return {
        "workflow_id": ast.Constant(value=WORKFLOW_ID),
        "step_id": ast.Constant(value=STEP_ID),
        "window_start": ast.Constant(value=WINDOW_START),
        "window_end": ast.Constant(value=WINDOW_END),
        "outcome_event": ast.Constant(value=OUTCOME_EVENT),
        "outcome_days": ast.Constant(value=7),
        "person_id": ast.Constant(value="00000000-0000-0000-0000-000000000000"),
        "run_id": ast.Constant(value=RUN_ID),
    }


class TestEmailPerformanceRecipes(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        run_clickhouse_statement_in_parallel([TRUNCATE_APP_METRICS2_TABLE_SQL])

    def _run(self, recipe: str) -> list[dict[str, Any]]:
        response = execute_hogql_query(query=_recipes()[recipe], team=self.team, placeholders=_placeholders())
        assert response.columns is not None
        return [dict(zip(response.columns, row)) for row in response.results]

    def _person(self, name: str) -> None:
        _create_person(team=self.team, distinct_ids=[name])

    def _email_event(
        self, name: str, event: str, at: datetime, step: str = STEP_ID, properties: dict[str, Any] | None = None
    ) -> None:
        _create_event(
            team=self.team,
            distinct_id=name,
            event=f"$workflows_email_{event}",
            timestamp=at,
            properties={"$workflow_id": WORKFLOW_ID, "$workflow_action_id": step, **(properties or {})},
        )

    def _sent(self, name: str, at: datetime, tracked: bool = True, step: str = STEP_ID) -> None:
        self._email_event(name, "sent", at, step=step, properties={"$email_tracking_enabled": tracked})

    def _product_event(self, name: str, at: datetime) -> None:
        _create_event(team=self.team, distinct_id=name, event=OUTCOME_EVENT, timestamp=at)

    @parameterized.expand(sorted(_recipes()))
    def test_recipe_runs_as_written(self, recipe: str) -> None:
        self._run(recipe)

    def test_step_engagement_separates_tracked_sends_and_counts_people_once(self) -> None:
        self._person("ada")
        self._person("bo")
        sent_at = WINDOW_START + timedelta(days=2)
        self._sent("ada", sent_at)
        self._sent("ada", sent_at + timedelta(days=1))
        self._sent("bo", sent_at, tracked=False)
        self._email_event("ada", "opened", sent_at + timedelta(hours=1))
        self._email_event("ada", "opened", sent_at + timedelta(hours=5))
        self._email_event("ada", "bounced", sent_at + timedelta(days=1, hours=1), properties={"$bounce_type": "soft"})
        self._email_event("bo", "bounced", sent_at + timedelta(hours=1), properties={"$bounce_type": "hard"})
        self._sent("bo", sent_at, step=OTHER_STEP_ID)

        rows = {row["step"]: row for row in self._run("Step engagement")}

        assert {
            key: rows[STEP_ID][key]
            for key in (
                "sent",
                "tracked_sent",
                "people_sent",
                "people_tracked",
                "opens",
                "openers",
                "bounces",
                "hard_bounces",
            )
        } == {
            "sent": 3,
            "tracked_sent": 2,
            "people_sent": 2,
            "people_tracked": 1,
            "opens": 2,
            "openers": 1,
            "bounces": 2,
            "hard_bounces": 1,
        }
        assert rows[OTHER_STEP_ID]["sent"] == 1

    def _counter(
        self, app_source_id: str, instance_id: str, metric_name: str, count: int, app_source: str = "hog_flow_version"
    ) -> None:
        create_app_metric2(
            team_id=self.team.pk,
            app_source=app_source,
            app_source_id=app_source_id,
            instance_id=instance_id,
            metric_kind="email",
            metric_name=metric_name,
            count=count,
            timestamp=WINDOW_START + timedelta(days=3),
        )

    def test_run_counters_read_one_run_with_its_conversions(self) -> None:
        self._counter(RUN_ID, STEP_ID, "email_sent", 5, app_source="hog_flow")
        self._counter(RUN_ID, STEP_ID, "email_opened", 2, app_source="hog_flow")
        self._counter(RUN_ID, WORKFLOW_ID, "conversion", 1, app_source="hog_flow")
        self._counter(RUN_ID, OTHER_STEP_ID, "email_sent", 4, app_source="hog_flow")
        self._counter(OTHER_RUN_ID, STEP_ID, "email_sent", 7, app_source="hog_flow")
        self._counter(f"{WORKFLOW_ID}/1", STEP_ID, "email_sent", 5)

        rows = self._run("Run counters")

        assert rows == [
            {"metric_name": "conversion", "total": 1},
            {"metric_name": "email_opened", "total": 2},
            {"metric_name": "email_sent", "total": 5},
        ]

    def test_counters_by_version_split_versions_of_one_workflow(self) -> None:
        self._counter(f"{WORKFLOW_ID}/2", STEP_ID, "email_sent", 3)
        self._counter(f"{WORKFLOW_ID}/2", STEP_ID, "email_untracked", 1)
        self._counter(f"{WORKFLOW_ID}/10", STEP_ID, "email_sent", 4)
        self._counter(RUN_ID, STEP_ID, "email_sent", 8, app_source="hog_flow")
        self._counter(f"{WORKFLOW_ID}/2", OTHER_STEP_ID, "email_sent", 4)
        self._counter(f"{OTHER_WORKFLOW_ID}/2", STEP_ID, "email_sent", 6)

        rows = self._run("Counters by version")

        assert rows == [
            {"version": "2", "metric_name": "email_sent", "total": 3},
            {"version": "2", "metric_name": "email_untracked", "total": 1},
            {"version": "10", "metric_name": "email_sent", "total": 4},
        ]

    def test_clicked_links_add_up_each_position_from_the_redacted_counter(self) -> None:
        clicks = "email_link_clicked_by_link"
        self._counter(f"{WORKFLOW_ID}/1", f"{STEP_ID}|0|https://example.com/pricing", clicks, 2)
        self._counter(f"{WORKFLOW_ID}/2", f"{STEP_ID}|0|https://example.com/pricing", clicks, 1)
        self._counter(f"{WORKFLOW_ID}/2", f"{STEP_ID}|1|https://example.com/a|b", clicks, 1)
        self._counter(f"{WORKFLOW_ID}/2", f"{STEP_ID}|2|https://example.com/invite/ada", clicks, 1)
        self._counter(f"{WORKFLOW_ID}/2", f"{STEP_ID}|2|https://example.com/invite/bo", clicks, 1)
        self._counter(WORKFLOW_ID, f"{STEP_ID}|0|https://example.com/pricing", clicks, 3, app_source="hog_flow")
        self._counter(f"{WORKFLOW_ID}/2", f"{OTHER_STEP_ID}|0|https://example.com/other", clicks, 4)
        self._counter(f"{OTHER_WORKFLOW_ID}/1", f"{STEP_ID}|0|https://example.com/pricing", clicks, 6)

        rows = self._run("Clicked links")

        assert rows == [
            {"link_index": "0", "clicks": 3, "urls": 1, "link": "https://example.com/pricing"},
            {"link_index": "2", "clicks": 2, "urls": 2, "link": ""},
            {"link_index": "1", "clicks": 1, "urls": 1, "link": "https://example.com/a|b"},
        ]

    def test_outcome_counts_each_recipient_once_within_their_own_window(self) -> None:
        sent_at = WINDOW_START + timedelta(days=5)
        for name in ("acted_next_day", "acted_before_send", "acted_too_late", "sent_twice"):
            self._person(name)
            self._sent(name, sent_at)
        self._product_event("acted_next_day", sent_at + timedelta(days=1))
        self._product_event("acted_before_send", sent_at - timedelta(hours=1))
        self._product_event("acted_too_late", sent_at + timedelta(days=8))
        self._sent("sent_twice", sent_at + timedelta(days=5))
        self._product_event("sent_twice", sent_at + timedelta(days=8))
        self._person("never_sent")
        self._product_event("never_sent", sent_at + timedelta(days=1))
        self._person("sent_yesterday")
        self._sent("sent_yesterday", WINDOW_END - timedelta(hours=2))

        (row,) = self._run("Product outcome after the first send")

        assert row == {"recipients": 4, "reached_outcome": 1, "recipients_still_in_window": 1}

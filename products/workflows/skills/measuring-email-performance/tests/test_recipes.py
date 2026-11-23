import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    NonAtomicBaseTest,
    _create_event,
    _create_person,
    run_clickhouse_statement_in_parallel,
)

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.models.app_metrics2.sql import TRUNCATE_APP_METRICS2_TABLE_SQL
from posthog.test.fixtures import create_app_metric2

from products.workflows.backend.facade.testing import create_workflow_for_test

RECIPES = Path(__file__).resolve().parent.parent / "references" / "recipes.md"
RECIPE_HEADING = re.compile(r"^### (.+)$", re.MULTILINE)
SQL_FENCE = re.compile(r"```sql\n(.*?)\n```", re.DOTALL)

WORKFLOW_ID = "01a00000-0000-0000-0000-000000000001"
OTHER_WORKFLOW_ID = "01a00000-0000-0000-0000-000000000002"
STEP_ID = "action_function_email_welcome"
OTHER_STEP_ID = "action_function_email_reminder"
RUN_ID = "01a00000-0000-0000-0000-0000000000aa"
SECOND_RUN_ID = "01a00000-0000-0000-0000-0000000000ab"
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
        assert query.rstrip().endswith("LIMIT 500"), f"{name} must end with LIMIT 500"
        recipes[name] = query
    return recipes


def _placeholders(
    workflow_id: str = WORKFLOW_ID, person_id: str = "00000000-0000-0000-0000-000000000000"
) -> dict[str, ast.Expr]:
    return {
        "workflow_id": ast.Constant(value=workflow_id),
        "step_id": ast.Constant(value=STEP_ID),
        "window_start": ast.Constant(value=WINDOW_START),
        "window_end": ast.Constant(value=WINDOW_END),
        "outcome_event": ast.Constant(value=OUTCOME_EVENT),
        "outcome_days": ast.Constant(value=7),
        "person_id": ast.Constant(value=person_id),
        "run_ids": ast.Tuple(exprs=[ast.Constant(value=RUN_ID), ast.Constant(value=SECOND_RUN_ID)]),
    }


class TestEmailPerformanceRecipes(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        run_clickhouse_statement_in_parallel([TRUNCATE_APP_METRICS2_TABLE_SQL])

    def _run(self, recipe: str, **placeholders: str) -> list[dict[str, Any]]:
        response = execute_hogql_query(
            query=_recipes()[recipe], team=self.team, user=self.user, placeholders=_placeholders(**placeholders)
        )
        assert response.columns is not None
        return [dict(zip(response.columns, row)) for row in response.results]

    def _person(self, name: str) -> str:
        return str(_create_person(team=self.team, distinct_ids=[name]).uuid)

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

    def test_run_counters_split_the_chosen_runs_with_their_conversions(self) -> None:
        self._counter(RUN_ID, STEP_ID, "email_sent", 5, app_source="hog_flow")
        self._counter(RUN_ID, STEP_ID, "email_opened", 2, app_source="hog_flow")
        self._counter(RUN_ID, WORKFLOW_ID, "conversion", 1, app_source="hog_flow")
        self._counter(RUN_ID, OTHER_STEP_ID, "email_sent", 4, app_source="hog_flow")
        self._counter(SECOND_RUN_ID, STEP_ID, "email_sent", 3, app_source="hog_flow")
        self._counter(OTHER_RUN_ID, STEP_ID, "email_sent", 7, app_source="hog_flow")
        self._counter(f"{WORKFLOW_ID}/1", STEP_ID, "email_sent", 5)

        rows = self._run("Run counters")

        assert rows == [
            {"run_id": RUN_ID, "metric_name": "conversion", "total": 1},
            {"run_id": RUN_ID, "metric_name": "email_opened", "total": 2},
            {"run_id": RUN_ID, "metric_name": "email_sent", "total": 5},
            {"run_id": SECOND_RUN_ID, "metric_name": "email_sent", "total": 3},
        ]

    def test_engagement_by_version_splits_one_steps_callbacks_and_keeps_unattributed_last(self) -> None:
        for name in ("ada", "bo", "cy"):
            self._person(name)
        at = WINDOW_START + timedelta(days=2)
        v2, v10 = {"$workflow_version": 2}, {"$workflow_version": 10}
        self._email_event("ada", "delivered", at, properties=v2)
        self._email_event("ada", "opened", at + timedelta(hours=1), properties=v2)
        self._email_event("ada", "opened", at + timedelta(hours=2), properties=v2)
        self._email_event("ada", "link_clicked", at + timedelta(hours=3), properties=v2)
        self._email_event("bo", "opened", at, properties=v10)
        self._email_event("bo", "bounced", at, properties=v10)
        self._email_event("cy", "opened", at)
        self._email_event("ada", "opened", at, step=OTHER_STEP_ID, properties=v2)
        self._email_event("bo", "opened", at, properties={**v2, "$workflow_id": OTHER_WORKFLOW_ID})

        rows = self._run("Engagement by version")

        empty = {
            "delivered": 0,
            "opens": 0,
            "openers": 0,
            "clicks": 0,
            "clickers": 0,
            "bounces": 0,
            "spam_complaints": 0,
        }
        assert rows == [
            {**empty, "version": "2", "delivered": 1, "opens": 2, "openers": 1, "clicks": 1, "clickers": 1},
            {**empty, "version": "10", "opens": 1, "openers": 1, "bounces": 1},
            {**empty, "version": None, "opens": 1, "openers": 1},
        ]

    def test_clicked_links_count_each_position_per_version_without_urls(self) -> None:
        clicks = "email_link_clicked_by_link"
        self._counter(f"{WORKFLOW_ID}/1", f"{STEP_ID}|0|https://example.com/pricing", clicks, 2)
        self._counter(f"{WORKFLOW_ID}/2", f"{STEP_ID}|0|https://example.com/pricing", clicks, 1)
        self._counter(f"{WORKFLOW_ID}/2", f"{STEP_ID}|1|https://example.com/a|b", clicks, 1)
        self._counter(f"{WORKFLOW_ID}/2", f"{STEP_ID}|2|https://example.com/invite/ada", clicks, 1)
        self._counter(f"{WORKFLOW_ID}/2", f"{STEP_ID}|2|https://example.com/invite/bo", clicks, 1)
        self._counter(f"{WORKFLOW_ID}/2", f"{STEP_ID}||https://example.com/unnumbered", clicks, 1)
        self._counter(WORKFLOW_ID, f"{STEP_ID}|0|https://example.com/pricing", clicks, 3, app_source="hog_flow")
        self._counter(f"{WORKFLOW_ID}/2", f"{OTHER_STEP_ID}|0|https://example.com/other", clicks, 4)
        self._counter(f"{OTHER_WORKFLOW_ID}/1", f"{STEP_ID}|0|https://example.com/pricing", clicks, 6)

        rows = self._run("Clicked links")

        assert rows == [
            {"version": "1", "link_index": "0", "clicks": 2},
            {"version": "2", "link_index": "0", "clicks": 1},
            {"version": "2", "link_index": "1", "clicks": 1},
            {"version": "2", "link_index": "2", "clicks": 2},
            {"version": "2", "link_index": "", "clicks": 1},
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

        (row,) = self._run("Product outcome after the first send")

        assert row == {"recipients": 4, "reached_outcome": 1}

    def test_person_history_lists_one_persons_email_and_outcome_events_in_order(self) -> None:
        ada = self._person("ada")
        self._person("bo")
        at = WINDOW_START + timedelta(days=2)
        self._sent("ada", at)
        self._email_event("ada", "link_clicked", at + timedelta(hours=2), properties={"$link_index": 1})
        self._email_event("ada", "opened", at + timedelta(hours=1))
        self._product_event("ada", at + timedelta(hours=3))
        _create_event(team=self.team, distinct_id="ada", event="$pageview", timestamp=at + timedelta(hours=4))
        self._email_event("ada", "opened", WINDOW_START - timedelta(days=1))
        self._email_event("bo", "opened", at)

        rows = self._run("One person's email history", person_id=ada)

        assert [(row["event"], row["step"], row["link_index"]) for row in rows] == [
            ("$workflows_email_sent", STEP_ID, None),
            ("$workflows_email_opened", STEP_ID, None),
            ("$workflows_email_link_clicked", STEP_ID, "1"),
            (OUTCOME_EVENT, None, None),
        ]


class TestEmailStepsRecipe(ClickhouseTestMixin, NonAtomicBaseTest):
    def test_email_steps_lists_only_the_email_steps_of_one_workflow(self) -> None:
        def email(step_id: str, name: str) -> dict[str, Any]:
            return {"id": step_id, "name": name, "type": "function_email"}

        workflow = create_workflow_for_test(
            team_id=self.team.pk,
            actions=[
                {"id": "trigger_node", "name": "Trigger", "type": "trigger"},
                email(STEP_ID, "Welcome"),
                {"id": "delay_node", "name": "Wait a day", "type": "delay"},
                email(OTHER_STEP_ID, "Reminder"),
            ],
        )
        create_workflow_for_test(team_id=self.team.pk, actions=[email("action_function_email_other", "Newsletter")])

        response = execute_hogql_query(
            query=_recipes()["Email steps"],
            team=self.team,
            user=self.user,
            placeholders=_placeholders(workflow_id=workflow.id),
        )

        assert response.results == [(STEP_ID, "Welcome"), (OTHER_STEP_ID, "Reminder")]

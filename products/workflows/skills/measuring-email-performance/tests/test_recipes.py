import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

RECIPES = Path(__file__).resolve().parent.parent / "references" / "recipes.md"
RECIPE_SECTION = re.compile(r"^### (.+?)\n.*?```sql\n(.*?)\n```", re.DOTALL | re.MULTILINE)

WORKFLOW_ID = "01a00000-0000-0000-0000-000000000001"
STEP_ID = "action_function_email_welcome"
OTHER_STEP_ID = "action_function_email_reminder"
OUTCOME_EVENT = "insight created"
NOW = datetime.now(UTC).replace(microsecond=0)
WINDOW_START = NOW - timedelta(days=30)
WINDOW_END = NOW - timedelta(days=1)


def _recipes() -> dict[str, str]:
    return dict(RECIPE_SECTION.findall(RECIPES.read_text(encoding="utf-8")))


def _placeholders(person_id: str = "00000000-0000-0000-0000-000000000000") -> dict[str, ast.Expr]:
    return {
        "workflow_id": ast.Constant(value=WORKFLOW_ID),
        "step_id": ast.Constant(value=STEP_ID),
        "window_start": ast.Constant(value=WINDOW_START),
        "window_end": ast.Constant(value=WINDOW_END),
        "outcome_event": ast.Constant(value=OUTCOME_EVENT),
        "outcome_days": ast.Constant(value=7),
        "person_id": ast.Constant(value=person_id),
    }


class TestEmailPerformanceRecipes(ClickhouseTestMixin, APIBaseTest):
    def _run(self, recipe: str, **placeholder_overrides: Any) -> list[dict[str, Any]]:
        response = execute_hogql_query(
            query=_recipes()[recipe], team=self.team, placeholders=_placeholders(**placeholder_overrides)
        )
        assert response.columns is not None
        return [dict(zip(response.columns, row)) for row in response.results]

    def _person(self, name: str) -> str:
        return str(_create_person(team=self.team, distinct_ids=[name]).uuid)

    def _email_event(self, name: str, event: str, at: datetime, step: str = STEP_ID, **properties: Any) -> None:
        _create_event(
            team=self.team,
            distinct_id=name,
            event=f"$workflows_email_{event}",
            timestamp=at,
            properties={"$workflow_id": WORKFLOW_ID, "$workflow_action_id": step, **properties},
        )

    def _sent(self, name: str, at: datetime, tracked: bool = True) -> None:
        self._email_event(name, "sent", at, **{"$email_tracking_enabled": tracked})

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
        self._sent("bo", sent_at, tracked=False)
        self._email_event("ada", "opened", sent_at + timedelta(hours=1))
        self._email_event("ada", "opened", sent_at + timedelta(hours=5))
        self._sent("bo", sent_at, tracked=True)
        self._email_event("bo", "sent", sent_at, step=OTHER_STEP_ID, **{"$email_tracking_enabled": True})

        rows = {row["step"]: row for row in self._run("Step engagement")}

        assert rows[STEP_ID]["sent"] == 3
        assert rows[STEP_ID]["tracked_sent"] == 2
        assert rows[STEP_ID]["opens"] == 2
        assert rows[STEP_ID]["openers"] == 1
        assert rows[OTHER_STEP_ID]["sent"] == 1

    def test_clicked_links_never_expose_query_strings(self) -> None:
        self._person("ada")
        clicked_at = WINDOW_START + timedelta(days=3)
        for url in ("https://example.com/pricing?token=secret-1", "https://example.com/pricing?token=secret-2"):
            self._email_event("ada", "link_clicked", clicked_at, **{"$link_url": url, "$link_index": 0})

        rows = self._run("Clicked links")

        assert rows == [
            {"link_index": "0", "link_domain": "example.com", "link_path": "/pricing", "clicks": 2, "clickers": 1}
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

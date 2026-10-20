from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest

from posthog.models import User

from products.tasks.backend.facade.user_task_summaries import list_user_task_summaries
from products.tasks.backend.models import Task, TaskRun

NOW = datetime(2026, 10, 19, tzinfo=UTC)


class TestListUserTaskSummaries(BaseTest):
    def _task(self, title: str, *, origin: str = "slack", user: User | None = None, days_ago: int = 1) -> Task:
        return Task.objects.create(
            team=self.team,
            created_by=user or self.user,
            title=title,
            description="",
            origin_product=origin,
            created_at=NOW - timedelta(days=days_ago),
        )

    def _run(self, task: Task, state: dict, *, days_ago: int) -> None:
        TaskRun.objects.create(task=task, team=self.team, state=state, created_at=NOW - timedelta(days=days_ago))

    def test_reads_the_latest_run_of_the_person_own_tasks(self) -> None:
        asked = self._task("why did signups drop", days_ago=3)
        self._run(asked, {"task_summary": "Goal: old answer.", "task_tags": ["old"]}, days_ago=3)
        self._run(asked, {"prior_run_summary": "Goal: find the signup drop.", "task_tags": []}, days_ago=2)
        self._task("scout run", origin="signals_scout")
        self._task("someone else's task", user=User.objects.create(email="other@example.com"))
        self._task("too old", days_ago=40)

        summaries = list_user_task_summaries(
            team_ids=[self.team.id],
            user_id=self.user.id,
            start=NOW - timedelta(days=28),
            end=NOW,
            origin_products=["slack", "posthog_ai", "user_created"],
            limit=10,
        )

        assert [(s.title, s.summary, s.tags) for s in summaries] == [
            ("why did signups drop", "Goal: find the signup drop.", ()),
        ]

from datetime import timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin

from django.utils import timezone

from parameterized import parameterized

from posthog.test.fixtures import create_app_metric2

from products.workflows.backend.facade.api import list_workflow_activity
from products.workflows.backend.facade.contracts import WorkflowActivityPage
from products.workflows.backend.metrics import HOG_FLOW_VERSION_APP_SOURCE
from products.workflows.backend.models import HogFlow

EMAIL_ACTION_ID = "email_step"


class TestListWorkflowActivity(ClickhouseTestMixin, BaseTest):
    def _flow(self, name: str, *, status: str = "active", origin_product: str | None = None, email: bool = False):
        actions = [{"id": "trigger_node", "type": "trigger", "config": {"type": "event"}}]
        if email:
            actions.append({"id": EMAIL_ACTION_ID, "type": "function_email", "config": {}})
        actions.append({"id": "exit_node", "type": "exit", "config": {}})
        return HogFlow.objects.create(
            team=self.team,
            name=name,
            status=status,
            origin_product=origin_product,
            trigger={"type": "event"},
            actions=actions,
        )

    def _metric(self, flow: HogFlow, metric_name: str, *, instance_id: str = "", count: int = 1, days_ago: int = 1):
        create_app_metric2(
            team_id=self.team.pk,
            app_source=HOG_FLOW_VERSION_APP_SOURCE,
            app_source_id=f"{flow.id}/1",
            instance_id=instance_id,
            metric_kind="other",
            metric_name=metric_name,
            count=count,
            timestamp=timezone.now() - timedelta(days=days_ago),
        )

    def _list(
        self, *, status: str | None = None, workflow_type: str | None = None, limit: int = 10
    ) -> WorkflowActivityPage:
        now = timezone.now()
        return list_workflow_activity(
            team_id=self.team.pk,
            access_control=None,
            status=status,
            workflow_type=workflow_type,
            limit=limit,
            after=now - timedelta(days=7),
            before=now,
        )

    def test_counts_runs_at_run_level_and_sums_email_steps_within_window(self) -> None:
        flow = self._flow("Welcome", email=True)
        self._metric(flow, "triggered", count=5)
        self._metric(flow, "succeeded", count=3)
        self._metric(flow, "failed", count=1)
        # A step-level row must not count as a run.
        self._metric(flow, "succeeded", instance_id=EMAIL_ACTION_ID, count=7)
        self._metric(flow, "email_sent", instance_id=EMAIL_ACTION_ID, count=3)
        self._metric(flow, "email_opened", instance_id=EMAIL_ACTION_ID, count=2)
        # Outside the window.
        self._metric(flow, "triggered", count=50, days_ago=10)

        page = self._list()

        assert page.has_more is False
        assert len(page.rows) == 1
        row = page.rows[0]
        assert (row.started, row.completed, row.failed) == (5, 3, 1)
        assert (row.email_sent, row.email_delivered, row.email_opened, row.email_bounced) == (3, 0, 2, 0)
        assert row.has_email_step is True
        assert row.workflow_type == "messaging"
        assert row.trigger_type == "event"

    @parameterized.expand(
        [
            ("status", "draft", None, {"Draft automation"}),
            ("messaging", None, "messaging", {"Welcome"}),
            ("automation", None, "automation", {"Draft automation"}),
            ("broadcast", None, "broadcast", {"Launch"}),
        ]
    )
    def test_filters_by_status_and_type(
        self, _name: str, status: str | None, workflow_type: str | None, expected: set[str]
    ) -> None:
        self._flow("Welcome", email=True)
        self._flow("Draft automation", status="draft")
        self._flow("Launch", origin_product=HogFlow.OriginProduct.BROADCASTS, email=True)

        page = self._list(status=status, workflow_type=workflow_type)

        assert {row.name for row in page.rows} == expected

    def test_has_more_past_limit_and_newest_first(self) -> None:
        older = self._flow("Older")
        newer = self._flow("Newer")

        page = self._list(limit=1)

        assert [row.id for row in page.rows] == [str(newer.id)]
        assert page.has_more is True
        assert older.updated_at < newer.updated_at

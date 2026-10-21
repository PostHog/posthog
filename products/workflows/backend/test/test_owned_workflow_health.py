from datetime import timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.test.fixtures import create_app_metric2

from products.workflows.backend.facade.api import list_owned_workflow_health
from products.workflows.backend.facade.contracts import (
    DataSuggestion,
    DataSuggestionsResult,
    DataSuggestionsStatus,
    OwnedWorkflowHealth,
)
from products.workflows.backend.facade.data_suggestions import count_waiting_data_suggestions
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.workflow_proposal import WorkflowProposal

SERVICE = "products.workflows.backend.services.data_suggestions.service"


class TestOwnedWorkflowHealth(ClickhouseTestMixin, BaseTest):
    def _flow(self, name: str, **fields: object) -> HogFlow:
        return HogFlow.objects.create(
            **{"team": self.team, "name": name, "status": HogFlow.State.ACTIVE, "created_by": self.user, **fields}
        )

    def _runs(self, flow: HogFlow, metric_name: str, count: int, days_ago: int = 1) -> None:
        create_app_metric2(
            team_id=self.team.pk,
            app_source="hog_flow",
            app_source_id=str(flow.id),
            metric_kind="success" if metric_name == "succeeded" else "failure",
            metric_name=metric_name,
            count=count,
            timestamp=timezone.now() - timedelta(days=days_ago),
        )

    def _proposal(self, flow: HogFlow, status: str) -> None:
        WorkflowProposal.objects.for_team(self.team.pk).create(
            team=self.team,
            hog_flow=flow,
            title="Shorten the subject",
            rationale="Opens are low.",
            content={"exit_condition": "exit_only_at_end"},
            base_version=1,
            status=status,
        )

    def test_lists_your_live_workflows_with_last_weeks_runs_and_pending_suggestions(self) -> None:
        live = self._flow("Onboarding drip", email_sending_paused_at=timezone.now())
        self._flow("Draft", status=HogFlow.State.DRAFT)
        self._flow("Archived", status=HogFlow.State.ARCHIVED)
        self._flow("Loop", origin_product="loops")
        self._flow("Not yours", created_by=self._create_user("other@example.com"))
        self._runs(live, "succeeded", 30)
        self._runs(live, "failed", 12)
        self._runs(live, "failed", 50, days_ago=10)
        self._proposal(live, WorkflowProposal.Status.SUGGESTED)
        self._proposal(live, WorkflowProposal.Status.SUGGESTED)
        self._proposal(live, WorkflowProposal.Status.REJECTED)

        assert list_owned_workflow_health(team=self.team, user=self.user, limit=20) == [
            OwnedWorkflowHealth(
                workflow_id=live.id,
                name="Onboarding drip",
                succeeded=30,
                failed=12,
                email_sending_paused=True,
                pending_suggestions=2,
            )
        ]

    @parameterized.expand(
        [
            ("ideas wait on the empty page", None, "ready", 3),
            ("a workflow replaces the empty page", HogFlow.State.DRAFT, "ready", 0),
            ("only archived workflows keep the empty page", HogFlow.State.ARCHIVED, "ready", 3),
            ("still generating", None, "generating", 0),
        ]
    )
    def test_counts_ideas_only_where_the_empty_page_shows_them(
        self, _name: str, existing: str | None, status: DataSuggestionsStatus, expected: int
    ) -> None:
        if existing:
            self._flow("Existing", status=existing)
        idea = DataSuggestion(
            id="idea",
            name="Welcome new users",
            description="",
            reason="",
            trigger_event="signed_up",
            weekly_count=10,
            stage="signup",
            step_outline=("email",),
        )
        suggestions = DataSuggestionsResult(status=status, suggestions=(idea,) * 3 if status == "ready" else ())

        with patch(f"{SERVICE}.get_data_suggestions", return_value=suggestions):
            assert count_waiting_data_suggestions(team=self.team) == expected

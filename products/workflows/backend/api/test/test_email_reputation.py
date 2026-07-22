from datetime import datetime, timedelta

from posthog.test.base import APIBaseTest

from django.utils import timezone

from rest_framework import status

from posthog.models import Team

from products.workflows.backend.models import EmailReputationSnapshot, HogFlow
from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig

RUN_2 = timezone.now().replace(microsecond=0) - timedelta(days=1)
RUN_1 = RUN_2 - timedelta(days=1)
STALE_RUN = RUN_2 - timedelta(days=30)


class TestEmailReputationAPI(APIBaseTest):
    def _create_flow(self, name: str) -> HogFlow:
        return HogFlow.objects.create(
            team=self.team,
            name=name,
            status="active",
            trigger={"type": "event"},
            edges=[],
            actions=[],
            billable_action_types=["function_email"],
        )

    def _create_snapshot(self, hog_flow: HogFlow | None, evaluated_at: datetime, **kwargs) -> EmailReputationSnapshot:
        snapshot = EmailReputationSnapshot(
            team=self.team,
            hog_flow=hog_flow,
            scope=EmailReputationSnapshot.Scope.WORKFLOW if hog_flow else EmailReputationSnapshot.Scope.TEAM,
            evaluated_at=evaluated_at,
            **kwargs,
        )
        snapshot.save()
        return snapshot

    def test_reputation_endpoint_returns_empty_shape_before_first_evaluation(self):
        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/reputation")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "reputation": None,
            "workflows": [],
            "email_sending_suspended": False,
            "email_sending_suspended_at": None,
        }

    def test_reputation_endpoint_reports_email_sending_suspension(self):
        suspended_at = timezone.now().replace(microsecond=0)
        TeamWorkflowsConfig.objects.update_or_create(
            team=self.team,
            defaults={
                "email_sending_suspended_at": suspended_at,
                "email_sending_suspension_reason": "critical bounce rate",
            },
        )

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/reputation")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["email_sending_suspended"] is True
        assert data["email_sending_suspended_at"] == suspended_at.isoformat().replace("+00:00", "Z")

    def test_reputation_endpoint_returns_latest_history_and_worst_first_workflows(self):
        ok_flow = self._create_flow("Fine workflow")
        bad_flow = self._create_flow("Toxic workflow")
        stale_flow = self._create_flow("Long-dead workflow")

        # Two daily team runs: latest must win regardless of insertion order
        self._create_snapshot(None, RUN_2, state="warning", bounce_rate=0.03)
        self._create_snapshot(None, RUN_1, state="healthy", bounce_rate=0.01)

        # Per-workflow: only the latest run's snapshot per flow, sorted worst first
        self._create_snapshot(ok_flow, RUN_1, state="critical", bounce_rate=0.09)
        self._create_snapshot(ok_flow, RUN_2, state="healthy", bounce_rate=0.005)
        self._create_snapshot(bad_flow, RUN_2, state="critical", bounce_rate=0.08)
        # A workflow whose last snapshot predates the recency cutoff drops off the breakdown
        self._create_snapshot(stale_flow, STALE_RUN, state="critical", bounce_rate=0.5)

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/reputation")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert data["reputation"]["state"] == "warning"
        assert data["reputation"]["scope"] == "team"

        assert [(row["hog_flow_name"], row["state"]) for row in data["workflows"]] == [
            ("Toxic workflow", "critical"),
            ("Fine workflow", "healthy"),
        ]
        assert data["workflows"][0]["hog_flow_id"] == str(bad_flow.id)

        # Each workflow entry carries its own per-run history, oldest first
        assert [row["state"] for row in data["workflows"][1]["history"]] == ["critical", "healthy"]
        assert [row["state"] for row in data["workflows"][0]["history"]] == ["critical"]

    def test_reputation_endpoint_never_returns_other_teams_snapshots(self):
        other_team = Team.objects.create(organization=self.organization, name="other team")
        other_flow = HogFlow.objects.create(
            team=other_team,
            name="Other team workflow",
            status="active",
            trigger={"type": "event"},
            edges=[],
            actions=[],
            billable_action_types=["function_email"],
        )
        EmailReputationSnapshot(
            team=other_team,
            hog_flow=None,
            scope=EmailReputationSnapshot.Scope.TEAM,
            state="critical",
            bounce_rate=0.5,
            evaluated_at=RUN_2,
        ).save()
        EmailReputationSnapshot(
            team=other_team,
            hog_flow=other_flow,
            scope=EmailReputationSnapshot.Scope.WORKFLOW,
            state="critical",
            bounce_rate=0.5,
            evaluated_at=RUN_2,
        ).save()

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/reputation")
        assert response.status_code == status.HTTP_200_OK
        # Nothing from the other team leaks: no aggregate, no workflow rows
        assert response.json() == {
            "reputation": None,
            "workflows": [],
            "email_sending_suspended": False,
            "email_sending_suspended_at": None,
        }

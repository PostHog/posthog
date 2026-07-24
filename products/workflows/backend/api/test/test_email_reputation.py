from datetime import datetime, timedelta

from posthog.test.base import APIBaseTest

from django.utils import timezone

from rest_framework import status

from posthog.models import Team

from products.workflows.backend.models import EmailReputationSnapshot, HogFlow

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
        assert response.json() == {"reputation": None, "workflows": []}

    def test_reputation_endpoint_search_filters_before_the_cap(self):
        # A healthy workflow pushed past the worst-50 cap must still be findable by name
        needle = self._create_flow("Quarterly newsletter")
        self._create_snapshot(needle, RUN_2, state="healthy", bounce_rate=0.001)
        for i in range(55):
            noisy = self._create_flow(f"Blast {i}")
            self._create_snapshot(noisy, RUN_2, state="critical", bounce_rate=0.2)

        unfiltered = self.client.get(f"/api/projects/{self.team.id}/hog_flows/reputation").json()
        assert all(row["hog_flow_name"] != "Quarterly newsletter" for row in unfiltered["workflows"])

        searched = self.client.get(f"/api/projects/{self.team.id}/hog_flows/reputation?search=newsLETTER").json()
        assert [row["hog_flow_name"] for row in searched["workflows"]] == ["Quarterly newsletter"]
        # The team aggregate is unaffected by workflow search
        assert searched["reputation"] is None

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
        assert response.json() == {"reputation": None, "workflows": []}

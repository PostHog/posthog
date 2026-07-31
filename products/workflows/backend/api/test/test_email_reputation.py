from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.utils import timezone

from rest_framework import status

from posthog.models import Team

from products.workflows.backend.models import HogFlow, HogFlowBatchJob
from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig


class TestEmailReputationAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        # Totals are cached per team and the team persists across this class's tests — clear so
        # one test's mocked totals can't leak into the next.
        cache.clear()

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

    def _get_reputation(self, totals_by_source: dict, query: str = "") -> dict:
        with patch(
            "products.workflows.backend.api.hog_flow.fetch_app_metric_totals_by_source",
            return_value=totals_by_source,
        ):
            response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/reputation{query}")
        assert response.status_code == status.HTTP_200_OK
        return response.json()

    def test_reputation_endpoint_returns_empty_shape_when_nothing_was_sent(self):
        assert self._get_reputation({}) == {
            "reputation": None,
            "workflows": [],
            "email_sending_suspended": False,
            "email_sending_suspended_at": None,
            "email_sending_suspension_reason": "",
        }

    # Creating a HogFlowBatchJob fires a post_save signal that dispatches to the plugin server —
    # patched out like every other batch-job test, or CI fails on the outbound HTTP attempt.
    @patch(
        "products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job.create_batch_hog_flow_job_invocation"
    )
    def test_reputation_endpoint_computes_rates_and_folds_batch_jobs_into_workflows(self, _mock_dispatch):
        flow = self._create_flow("Newsletter")
        batch_job = HogFlowBatchJob.objects.create(
            team=self.team, hog_flow=flow, variables={}, filters={}, status="completed"
        )
        other_flow = self._create_flow("Onboarding drip")

        data = self._get_reputation(
            {
                # Event-triggered sends recorded under the workflow id...
                str(flow.id): {"email_sent": 600, "email_bounced_hard": 30},
                # ...batch sends under the batch job id — folded into the same workflow row
                str(batch_job.id): {"email_sent": 400, "email_bounced_hard": 20, "email_blocked": 1},
                str(other_flow.id): {"email_sent": 1000},
                # A source resolving to no workflow (deleted flow) counts only toward the team aggregate
                "00000000-0000-0000-0000-00000000dead": {"email_sent": 500, "email_bounced_hard": 100},
                # Non-UUID sources can't be workflows and also count team-level only
                "not-a-uuid": {"email_sent": 100},
            }
        )

        assert data["reputation"] == {
            "bounce_rate": 150 / 2600,
            "complaint_rate": 1 / 2600,
            "emails_sent": 2600,
        }
        # Worst first: the folded Newsletter row (complaints beat bounces) before the clean flow
        assert [(row["hog_flow_name"], row["emails_sent"]) for row in data["workflows"]] == [
            ("Newsletter", 1000),
            ("Onboarding drip", 1000),
        ]
        assert data["workflows"][0]["bounce_rate"] == 50 / 1000
        assert data["workflows"][0]["complaint_rate"] == 1 / 1000
        assert data["workflows"][0]["hog_flow_id"] == str(flow.id)

    def test_reputation_endpoint_clamps_rates_when_trailing_feedback_exceeds_window_sends(self):
        # Bounces/complaints are recorded at webhook time: a workflow that mostly stopped sending
        # can have more feedback in the window than sends. The rate clamps at 100%.
        flow = self._create_flow("Dormant blast")

        data = self._get_reputation(
            {str(flow.id): {"email_sent": 100, "email_bounced_hard": 500, "email_blocked": 150}}
        )

        assert data["workflows"][0]["bounce_rate"] == 1.0
        assert data["workflows"][0]["complaint_rate"] == 1.0
        assert data["reputation"]["bounce_rate"] == 1.0

    def test_reputation_endpoint_serializes_unnamed_workflows_with_empty_name(self):
        unnamed = HogFlow.objects.create(
            team=self.team,
            name=None,
            status="active",
            trigger={"type": "event"},
            edges=[],
            actions=[],
            billable_action_types=["function_email"],
        )

        data = self._get_reputation({str(unnamed.id): {"email_sent": 10}})
        assert [(row["hog_flow_id"], row["hog_flow_name"]) for row in data["workflows"]] == [(str(unnamed.id), "")]

    def test_reputation_endpoint_search_filters_before_the_cap(self):
        needle = self._create_flow("Quarterly newsletter")
        totals = {str(needle.id): {"email_sent": 100}}
        for i in range(55):
            noisy = self._create_flow(f"Blast {i}")
            totals[str(noisy.id)] = {"email_sent": 1000, "email_bounced_hard": 200}

        unfiltered = self._get_reputation(totals)
        assert len(unfiltered["workflows"]) == 50
        assert all(row["hog_flow_name"] != "Quarterly newsletter" for row in unfiltered["workflows"])

        searched = self._get_reputation(totals, query="?search=newsLETTER")
        assert [row["hog_flow_name"] for row in searched["workflows"]] == ["Quarterly newsletter"]

    def test_reputation_endpoint_never_resolves_other_teams_workflows(self):
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

        # A cross-team app_source_id must not leak the other team's workflow name; its counts
        # still land in this team's aggregate because the metrics query is team-scoped upstream.
        data = self._get_reputation({str(other_flow.id): {"email_sent": 200, "email_bounced_hard": 10}})
        assert data["workflows"] == []
        assert data["reputation"]["emails_sent"] == 200

    def test_reputation_endpoint_reports_email_sending_suspension(self):
        suspended_at = timezone.now().replace(microsecond=0)
        TeamWorkflowsConfig.objects.update_or_create(
            team=self.team,
            defaults={
                "email_sending_suspended_at": suspended_at,
                "email_sending_suspension_reason": "critical bounce rate",
            },
        )

        data = self._get_reputation({})
        assert data["email_sending_suspended"] is True
        assert data["email_sending_suspended_at"] == suspended_at.isoformat().replace("+00:00", "Z")
        assert data["email_sending_suspension_reason"] == "critical bounce rate"

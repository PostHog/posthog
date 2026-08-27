import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import Team
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.access_control.backend.models.access_control import AccessControl
from products.workflows.backend.models import HogFlow, HogFlowBatchJob
from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig


class TestEmailReputationAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        # Totals and the AWS tenant lookup are cached per team and the team persists across
        # this class's tests — clear so one test's mocked data can't leak into the next.
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

    def _get_reputation(
        self, totals_by_source: dict, query: str = "", aws_tenant: dict | None | Exception = None
    ) -> dict:
        provider = MagicMock()
        if isinstance(aws_tenant, Exception):
            provider.get_tenant_reputation.side_effect = aws_tenant
        else:
            provider.get_tenant_reputation.return_value = aws_tenant
        with (
            patch(
                "products.workflows.backend.api.hog_flow.fetch_app_metric_totals_by_source",
                return_value=totals_by_source,
            ),
            patch("products.workflows.backend.api.hog_flow.SESProvider", return_value=provider),
        ):
            response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/reputation{query}")
        assert response.status_code == status.HTTP_200_OK
        return response.json()

    def test_reputation_endpoint_returns_empty_shape_when_nothing_was_sent(self):
        assert self._get_reputation({}) == {
            "aws": None,
            "reputation": None,
            "workflows": [],
            "email_sending_suspended": False,
            "email_sending_suspended_at": None,
            "email_sending_suspension_reason": "",
        }

    @parameterized.expand(
        [
            ("no_findings", "ENABLED", None, "healthy"),
            ("low_impact", "ENABLED", "LOW", "warning"),
            ("high_impact", "ENABLED", "HIGH", "critical"),
            ("reinstated_low", "REINSTATED", "LOW", "warning"),
            ("paused", "DISABLED", "HIGH", "suspended"),
        ]
    )
    def test_reputation_endpoint_maps_aws_tenant_state_to_health(
        self, _name: str, sending_status: str, impact: str | None, expected_health: str
    ):
        data = self._get_reputation(
            {},
            aws_tenant={"sending_status": sending_status, "reputation_impact": impact, "findings": []},
        )
        assert data["aws"]["health"] == expected_health
        assert data["aws"]["sending_status"] == sending_status

    def test_reputation_endpoint_passes_through_aws_findings(self):
        data = self._get_reputation(
            {},
            aws_tenant={
                "sending_status": "ENABLED",
                "reputation_impact": "LOW",
                "findings": [
                    {
                        "finding_type": "BOUNCE",
                        "impact": "LOW",
                        "description": "Your bounce rate is elevated. Clean your recipient lists.",
                        "last_updated_at": None,
                    }
                ],
            },
        )
        assert data["aws"]["findings"] == [
            {
                "finding_type": "BOUNCE",
                "impact": "LOW",
                "description": "Your bounce rate is elevated. Clean your recipient lists.",
                "last_updated_at": None,
            }
        ]

    def test_reputation_endpoint_survives_aws_being_unreachable(self):
        data = self._get_reputation({}, aws_tenant=Exception("SES timeout"))
        assert data["aws"] is None
        assert data["workflows"] == []

    def test_reputation_endpoint_does_not_redial_aws_after_a_failure(self):
        provider = MagicMock()
        provider.get_tenant_reputation.side_effect = Exception("SES timeout")
        with (
            patch("products.workflows.backend.api.hog_flow.fetch_app_metric_totals_by_source", return_value={}),
            patch("products.workflows.backend.api.hog_flow.SESProvider", return_value=provider),
        ):
            url = f"/api/projects/{self.team.id}/hog_flows/reputation"
            first = self.client.get(url)
            second = self.client.get(url)

        assert first.json()["aws"] is None
        assert second.json()["aws"] is None
        assert provider.get_tenant_reputation.call_count == 1

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


@pytest.mark.ee
class TestEmailReputationAccessControl(APIBaseTest):
    """
    The AWS tenant verdict and the project-wide rates aggregate both pool ALL workflows' email,
    so members holding only object-level grants must get neither — just their own workflow rows.
    """

    def test_object_level_only_member_gets_rows_but_no_project_wide_state(self):
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        member = User.objects.create_and_join(self.organization, "obj-only@posthog.com", "testtest")
        membership = OrganizationMembership.objects.get(user=member, organization=self.organization)
        flow = HogFlow.objects.create(
            team=self.team,
            name="Granted workflow",
            status="active",
            trigger={"type": "event"},
            edges=[],
            actions=[],
            billable_action_types=["function_email"],
        )
        # Project-wide default of `none`; the member's only access is the one object grant.
        AccessControl.objects.create(team=self.team, resource="hog_flow", resource_id=None, access_level="none")
        AccessControl.objects.create(
            team=self.team,
            resource="hog_flow",
            resource_id=str(flow.id),
            access_level="viewer",
            organization_member=membership,
        )
        self.client.force_login(member)

        provider = MagicMock()
        provider.get_tenant_reputation.return_value = {
            "sending_status": "DISABLED",
            "reputation_impact": "HIGH",
            "findings": [],
        }
        with (
            patch(
                "products.workflows.backend.api.hog_flow.fetch_app_metric_totals_by_source",
                return_value={str(flow.id): {"email_sent": 100, "email_bounced_hard": 5}},
            ),
            patch("products.workflows.backend.api.hog_flow.SESProvider", return_value=provider),
        ):
            response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/reputation")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["aws"] is None
        assert data["reputation"] is None
        assert [row["hog_flow_id"] for row in data["workflows"]] == [str(flow.id)]

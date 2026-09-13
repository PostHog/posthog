import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import Team
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.access_control.backend.models.access_control import AccessControl
from products.workflows.backend.models import HogFlow, HogFlowBatchJob
from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig
from products.workflows.backend.providers.ses import IspDailyPoint, IspSendingMetrics


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
        self,
        totals_by_source: dict,
        query: str = "",
        aws_tenant: dict | None | Exception = None,
        isp_metrics: list | Exception | None = None,
        isp_flag_enabled: bool = True,
    ) -> dict:
        provider = MagicMock()
        if isinstance(aws_tenant, Exception):
            provider.get_tenant_reputation.side_effect = aws_tenant
        else:
            provider.get_tenant_reputation.return_value = aws_tenant
        if isinstance(isp_metrics, Exception):
            provider.get_identity_isp_metrics.side_effect = isp_metrics
        else:
            provider.get_identity_isp_metrics.return_value = isp_metrics or []
        with (
            patch(
                "products.workflows.backend.api.hog_flow.fetch_app_metric_totals_by_source",
                return_value=totals_by_source,
            ),
            patch("products.workflows.backend.api.hog_flow.SESProvider", return_value=provider),
            patch(
                "products.workflows.backend.api.hog_flow._isp_breakdown_enabled",
                return_value=isp_flag_enabled,
            ),
        ):
            response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/reputation{query}")
        assert response.status_code == status.HTTP_200_OK
        return response.json()

    def test_reputation_endpoint_returns_empty_shape_when_nothing_was_sent(self):
        data = self._get_reputation({})
        # The allowance values come from the tier tables, which are deployment configuration, so
        # assert the fresh-team invariants rather than the numbers.
        allowance = data.pop("sending_allowance")
        assert allowance["tier"] == 0
        assert allowance["enforced"] is False
        assert allowance["emails_sent_last_hour"] == 0
        assert allowance["emails_sent_last_day"] == 0
        assert data == {
            "aws": None,
            "reputation": None,
            "workflows": [],
            "isps": [],
            "isp_shared_domains": [],
            "isp_withheld_domains": [],
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

    def _verify_sending_domain(self, domain: str = "mail.example.com") -> None:
        Integration.objects.create(
            team=self.team,
            kind="email",
            integration_id=domain,
            config={"domain": domain, "provider": "ses", "verified": True},
        )

    def test_reputation_endpoint_returns_the_per_provider_breakdown(self):
        self._verify_sending_domain()

        body = self._get_reputation(
            {},
            isp_metrics=[
                IspSendingMetrics(
                    isp="Gmail",
                    emails_sent=900,
                    delivery_rate=0.97,
                    bounce_rate=0.01,
                    complaint_rate=None,
                    daily=(IspDailyPoint(date="2026-08-01", emails_sent=900, delivery_rate=0.97, bounce_rate=0.01),),
                ),
                IspSendingMetrics(
                    isp="Yahoo",
                    emails_sent=100,
                    delivery_rate=0.99,
                    bounce_rate=0.0,
                    complaint_rate=0.002,
                    daily=(),
                ),
            ],
        )

        assert body["isps"] == [
            {
                "isp": "Gmail",
                "emails_sent": 900,
                "delivery_rate": 0.97,
                "bounce_rate": 0.01,
                # Null rather than 0 — Gmail runs no feedback loop, so a complaint rate would be
                # a number we can't actually measure.
                "complaint_rate": None,
                "unavailable": [],
                "daily": [
                    {
                        "date": "2026-08-01",
                        "emails_sent": 900,
                        "delivery_rate": 0.97,
                        "bounce_rate": 0.01,
                    }
                ],
            },
            {
                "isp": "Yahoo",
                "emails_sent": 100,
                "delivery_rate": 0.99,
                "bounce_rate": 0.0,
                "complaint_rate": 0.002,
                "unavailable": [],
                "daily": [],
            },
        ]

    @parameterized.expand(
        [
            ("sibling verified on the same domain", True, ["mail.example.com"]),
            ("sibling not verified yet", False, []),
        ]
    )
    def test_reputation_endpoint_names_domains_a_sibling_project_also_sends_from(
        self, _name: str, sibling_verified: bool, expected: list[str]
    ):
        self._verify_sending_domain()
        sibling = Team.objects.create(organization=self.organization, name="Sibling")
        Integration.objects.create(
            team=sibling,
            kind="email",
            integration_id="mail.example.com",
            config={"domain": "mail.example.com", "provider": "ses", "verified": sibling_verified},
        )

        body = self._get_reputation({}, isp_metrics=[])

        assert body["isp_shared_domains"] == expected

    def test_reputation_endpoint_omits_domains_only_this_project_sends_from(self):
        self._verify_sending_domain()
        self._verify_sending_domain("solo.example.com")
        sibling = Team.objects.create(organization=self.organization, name="Sibling")
        Integration.objects.create(
            team=sibling,
            kind="email",
            integration_id="mail.example.com",
            config={"domain": "mail.example.com", "provider": "ses", "verified": True},
        )

        body = self._get_reputation({}, isp_metrics=[])

        assert body["isp_shared_domains"] == ["mail.example.com"]

    @parameterized.expand(
        [
            ("sibling project hidden from the caller", "none", [], ["mail.example.com"]),
            ("sibling project the caller can open", "member", ["mail.example.com"], []),
        ]
    )
    def test_reputation_endpoint_withholds_a_domain_a_hidden_project_also_sends_from(
        self, _name: str, sibling_access: str, expected_shared: list[str], expected_withheld: list[str]
    ):
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()
        self._verify_sending_domain()
        sibling = Team.objects.create(organization=self.organization, name="Sibling")
        Integration.objects.create(
            team=sibling,
            kind="email",
            integration_id="mail.example.com",
            config={"domain": "mail.example.com", "provider": "ses", "verified": True},
        )
        AccessControl.objects.create(
            team=sibling, resource="project", resource_id=str(sibling.id), access_level=sibling_access
        )
        member = User.objects.create_and_join(self.organization, f"sibling-{sibling_access}@posthog.com", "testtest")
        self.client.force_login(member)

        body = self._get_reputation(
            {},
            isp_metrics=[
                IspSendingMetrics(
                    isp="Gmail",
                    emails_sent=900,
                    delivery_rate=0.97,
                    bounce_rate=0.01,
                    complaint_rate=None,
                    daily=(),
                )
            ],
        )

        assert body["isp_shared_domains"] == expected_shared
        assert body["isp_withheld_domains"] == expected_withheld
        # A withheld domain is never queried, so the provider rows go with it.
        assert [row["isp"] for row in body["isps"]] == ([] if expected_withheld else ["Gmail"])

    def test_reputation_endpoint_still_loads_when_the_provider_breakdown_fails(self):
        # The breakdown is an addition to the rates display; SES being unreachable must not take
        # the whole reputation page down with it.
        self._verify_sending_domain()

        body = self._get_reputation(
            {"src": {"email_sent": 100, "email_bounced_hard": 1}},
            isp_metrics=Exception("SES timeout"),
        )

        assert body["isps"] == []
        assert body["reputation"]["emails_sent"] == 100

    def test_reputation_endpoint_shows_no_breakdown_while_another_request_is_refreshing_it(self):
        # One refresh is 150 metric queries over 15 sequential SES calls, and the endpoint reloads on
        # every search keystroke, so a cold key must admit one request rather than all of them.
        self._verify_sending_domain()
        provider = MagicMock()
        provider.get_tenant_reputation.return_value = None
        with (
            patch("products.workflows.backend.api.hog_flow.fetch_app_metric_totals_by_source", return_value={}),
            patch("products.workflows.backend.api.hog_flow.SESProvider", return_value=provider),
            patch("products.workflows.backend.api.hog_flow._isp_breakdown_enabled", return_value=True),
            patch("products.workflows.backend.api.hog_flow.cache.add", return_value=False),
        ):
            response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/reputation")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["isps"] == []
        assert provider.get_identity_isp_metrics.call_count == 0

    def test_reputation_endpoint_withholds_the_breakdown_without_the_feature_flag(self):
        self._verify_sending_domain()

        body = self._get_reputation(
            {"src": {"email_sent": 100, "email_bounced_hard": 1}},
            isp_metrics=[
                IspSendingMetrics(
                    isp="Gmail",
                    emails_sent=90,
                    delivery_rate=0.99,
                    bounce_rate=0.01,
                    complaint_rate=None,
                    daily=(),
                )
            ],
            isp_flag_enabled=False,
        )

        assert body["isps"] == []
        assert body["reputation"]["emails_sent"] == 100


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
        provider.get_identity_isp_metrics.return_value = [
            IspSendingMetrics(
                isp="Gmail",
                emails_sent=100,
                delivery_rate=0.9,
                bounce_rate=0.05,
                complaint_rate=None,
                daily=(),
            )
        ]
        with (
            patch(
                "products.workflows.backend.api.hog_flow.fetch_app_metric_totals_by_source",
                return_value={str(flow.id): {"email_sent": 100, "email_bounced_hard": 5}},
            ),
            patch("products.workflows.backend.api.hog_flow.SESProvider", return_value=provider),
            # Enabled, so what the assertion below tests is the access-control gate, not the flag.
            patch("products.workflows.backend.api.hog_flow._isp_breakdown_enabled", return_value=True),
        ):
            response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/reputation")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["aws"] is None
        assert data["reputation"] is None
        assert data["isps"] == []
        assert [row["hog_flow_id"] for row in data["workflows"]] == [str(flow.id)]

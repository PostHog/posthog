import uuid

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.conf import settings

from rest_framework import status
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership
from posthog.models.scoping import team_scope
from posthog.models.team import Team
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle
from posthog.slo.types import SloOperation

from products.product_analytics.backend.models.insight import Insight
from products.pulse.backend.api.brief import ProductBriefViewSet
from products.pulse.backend.models import BriefConfig, ProductBrief

from ee.models.rbac.access_control import AccessControl


def _temporal_client() -> MagicMock:
    client = MagicMock()
    client.start_workflow = AsyncMock()
    return client


@patch("posthoganalytics.feature_enabled", return_value=True)
@patch("products.pulse.backend.api.brief.sync_connect")
class TestPulseAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

    def test_generate_requires_flag(self, mock_connect: MagicMock, mock_flag: MagicMock) -> None:
        mock_flag.return_value = False
        response = self.client.post(f"/api/projects/{self.team.id}/pulse/briefs/generate/")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_connect.assert_not_called()

    def test_generate_requires_ai_consent(self, mock_connect: MagicMock, _mock_flag: MagicMock) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()
        response = self.client.post(f"/api/projects/{self.team.id}/pulse/briefs/generate/")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        # The frontend matches this code to show the consent banner — it is part of the API contract.
        assert response.json()["code"] == "ai_consent_required"
        mock_connect.assert_not_called()

    def test_generate_creates_brief_and_starts_workflow(self, mock_connect: MagicMock, _mock_flag: MagicMock) -> None:
        client = _temporal_client()
        mock_connect.return_value = client
        response = self.client.post(
            f"/api/projects/{self.team.id}/pulse/briefs/generate/",
            {"period": {"period_type": "last_n_days", "days": 14}},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        brief = ProductBrief.objects.for_team(self.team.pk).get(id=response.json()["id"])
        assert brief.status == ProductBrief.Status.GENERATING
        assert brief.trigger == ProductBrief.Trigger.ON_DEMAND
        assert brief.period == {"type": "last_n_days", "days": 14}
        client.start_workflow.assert_called_once()
        assert client.start_workflow.call_args.kwargs["task_queue"] == settings.ANALYTICS_PLATFORM_TASK_QUEUE
        assert client.start_workflow.call_args.kwargs["execution_timeout"] is not None
        # The workflow input carries an SLO config so the interceptor emits started/completed metrics.
        workflow_input = client.start_workflow.call_args.args[1]
        assert workflow_input.slo is not None
        assert workflow_input.slo.operation == SloOperation.PULSE_BRIEF_GENERATION
        assert workflow_input.slo.resource_id == str(brief.id)
        assert client.start_workflow.call_args.kwargs["id"] == f"pulse-brief-{self.team.id}-default"

    def test_generate_scopes_workflow_to_config(self, mock_connect: MagicMock, _mock_flag: MagicMock) -> None:
        client = _temporal_client()
        mock_connect.return_value = client
        with team_scope(self.team.pk, canonical=True):
            config = BriefConfig.objects.create(team=self.team, created_by=self.user, name="Configured")

        response = self.client.post(
            f"/api/projects/{self.team.id}/pulse/briefs/generate/", {"config_id": str(config.id)}
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert client.start_workflow.call_args.kwargs["id"] == f"pulse-brief-{self.team.id}-{config.id}"

    def test_generate_uses_ai_throttles(self, _mock_connect: MagicMock, _mock_flag: MagicMock) -> None:
        view = ProductBriefViewSet()
        view.action = "generate"
        assert [type(throttle) for throttle in view.get_throttles()] == [
            AIBurstRateThrottle,
            AISustainedRateThrottle,
        ]

    def test_generate_token_requires_source_read_scopes(self, mock_connect: MagicMock, _mock_flag: MagicMock) -> None:
        api_key = self.create_personal_api_key_with_scopes(["project:write"])

        response = self.client.post(
            f"/api/projects/{self.team.id}/pulse/briefs/generate/",
            headers={"authorization": f"Bearer {api_key}"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["detail"] == "API key missing required scope 'annotation:read'"
        mock_connect.assert_not_called()

    def test_generate_token_with_source_read_scopes_is_allowed(
        self, mock_connect: MagicMock, _mock_flag: MagicMock
    ) -> None:
        mock_connect.return_value = _temporal_client()
        api_key = self.create_personal_api_key_with_scopes(
            ["project:write", "annotation:read", "subscription:read", "alert:read", "insight:read"]
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/pulse/briefs/generate/",
            headers={"authorization": f"Bearer {api_key}"},
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()

    def test_retrieve_token_requires_source_read_scopes(self, _mock_connect: MagicMock, _mock_flag: MagicMock) -> None:
        with team_scope(self.team.pk, canonical=True):
            brief = ProductBrief.objects.create(
                team=self.team,
                created_by=self.user,
                trigger=ProductBrief.Trigger.ON_DEMAND,
            )
        api_key = self.create_personal_api_key_with_scopes(["project:read"])

        response = self.client.get(
            f"/api/projects/{self.team.id}/pulse/briefs/{brief.id}/",
            headers={"authorization": f"Bearer {api_key}"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["detail"] == "API key missing required scope 'annotation:read'"

    @patch("products.pulse.backend.api.brief.report_user_action")
    def test_generate_while_running_returns_409_without_orphan_brief(
        self, mock_report: MagicMock, mock_connect: MagicMock, _mock_flag: MagicMock
    ) -> None:
        client = _temporal_client()
        client.start_workflow.side_effect = WorkflowAlreadyStartedError("pulse-brief-x", "pulse-generate-brief")
        mock_connect.return_value = client
        response = self.client.post(f"/api/projects/{self.team.id}/pulse/briefs/generate/")
        assert response.status_code == status.HTTP_409_CONFLICT
        assert not ProductBrief.objects.for_team(self.team.pk).exists()
        # Contention is a distinct analytics signal from a successful generate.
        assert "pulse brief generation contended" in [call.args[1] for call in mock_report.call_args_list]

    def test_generate_dispatch_failure_returns_500_with_brief_id_and_status(
        self, mock_connect: MagicMock, _mock_flag: MagicMock
    ) -> None:
        client = _temporal_client()
        client.start_workflow.side_effect = RuntimeError("temporal down")
        mock_connect.return_value = client
        response = self.client.post(f"/api/projects/{self.team.id}/pulse/briefs/generate/")
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        brief = ProductBrief.objects.for_team(self.team.pk).get()
        assert brief.status == ProductBrief.Status.FAILED
        assert "temporal down" in (brief.error or "")
        # The failed row's id+status is returned so the frontend can surface/deep-link it.
        assert response.json()["brief"] == {"id": str(brief.id), "status": ProductBrief.Status.FAILED.value}

    def test_generate_with_unknown_config_returns_400(self, mock_connect: MagicMock, _mock_flag: MagicMock) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        with team_scope(other_team.pk, canonical=True):
            foreign_config = BriefConfig.objects.create(team=other_team, name="foreign")
        for config_id in [str(foreign_config.id), str(uuid.uuid4())]:
            response = self.client.post(
                f"/api/projects/{self.team.id}/pulse/briefs/generate/", {"config_id": config_id}
            )
            assert response.status_code == status.HTTP_400_BAD_REQUEST, config_id
            assert "Brief config not found." in str(response.json())
        assert not ProductBrief.objects.for_team(self.team.pk).exists()
        mock_connect.assert_not_called()

    def test_briefs_are_team_scoped(self, _mock_connect: MagicMock, _mock_flag: MagicMock) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        with team_scope(other_team.pk, canonical=True):
            other_brief = ProductBrief.objects.create(team=other_team, trigger=ProductBrief.Trigger.ON_DEMAND)
        response = self.client.get(f"/api/projects/{self.team.id}/pulse/briefs/")
        assert response.status_code == status.HTTP_200_OK
        assert str(other_brief.id) not in [row["id"] for row in response.json()["results"]]

    def test_configs_and_briefs_are_creator_scoped(self, _mock_connect: MagicMock, _mock_flag: MagicMock) -> None:
        other_user = self._create_user("other@posthog.com")
        with team_scope(self.team.pk, canonical=True):
            other_config = BriefConfig.objects.create(team=self.team, created_by=other_user, name="private")
            other_brief = ProductBrief.objects.create(
                team=self.team,
                created_by=other_user,
                config=other_config,
                trigger=ProductBrief.Trigger.ON_DEMAND,
            )

        configs = self.client.get(f"/api/projects/{self.team.id}/pulse/brief_configs/").json()["results"]
        briefs = self.client.get(f"/api/projects/{self.team.id}/pulse/briefs/").json()["results"]

        assert str(other_config.id) not in [row["id"] for row in configs]
        assert str(other_brief.id) not in [row["id"] for row in briefs]

    def test_project_member_can_mutate_and_generate(self, mock_connect: MagicMock, _mock_flag: MagicMock) -> None:
        mock_connect.return_value = _temporal_client()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            access_level="member",
        )

        list_response = self.client.get(f"/api/projects/{self.team.id}/pulse/brief_configs/")
        create_response = self.client.post(f"/api/projects/{self.team.id}/pulse/brief_configs/", {"name": "allowed"})
        generate_response = self.client.post(f"/api/projects/{self.team.id}/pulse/briefs/generate/")

        assert list_response.status_code == status.HTTP_200_OK
        assert create_response.status_code == status.HTTP_201_CREATED
        assert generate_response.status_code == status.HTTP_201_CREATED
        mock_connect.assert_called_once()

    def test_config_crud_roundtrip(self, _mock_connect: MagicMock, _mock_flag: MagicMock) -> None:
        insight = Insight.objects.create(team=self.team, name="Pageviews")
        create_response = self.client.post(
            f"/api/projects/{self.team.id}/pulse/brief_configs/",
            {
                "name": "Feature flags focus",
                "focus_prompt": "flags team",
                "anchors": {"insights": [insight.short_id]},
            },
        )
        assert create_response.status_code == status.HTTP_201_CREATED, create_response.json()
        config_id = create_response.json()["id"]

        list_response = self.client.get(f"/api/projects/{self.team.id}/pulse/brief_configs/")
        assert list_response.status_code == status.HTTP_200_OK
        assert [row["id"] for row in list_response.json()["results"]] == [config_id]

        patch_response = self.client.patch(
            f"/api/projects/{self.team.id}/pulse/brief_configs/{config_id}/", {"name": "Renamed"}
        )
        assert patch_response.status_code == status.HTTP_200_OK
        assert patch_response.json()["name"] == "Renamed"

        with team_scope(self.team.pk, canonical=True):
            brief = ProductBrief.objects.create(
                team=self.team, config_id=config_id, trigger=ProductBrief.Trigger.ON_DEMAND
            )

        delete_response = self.client.delete(f"/api/projects/{self.team.id}/pulse/brief_configs/{config_id}/")
        assert delete_response.status_code == status.HTTP_204_NO_CONTENT
        assert self.client.get(f"/api/projects/{self.team.id}/pulse/brief_configs/").json()["results"] == []
        # Soft delete: brief history keeps its config pointer and the row is recoverable.
        brief.refresh_from_db()
        assert str(brief.config_id) == config_id
        restore_response = self.client.patch(
            f"/api/projects/{self.team.id}/pulse/brief_configs/{config_id}/", {"deleted": False}
        )
        assert restore_response.status_code == status.HTTP_200_OK
        assert [
            row["id"] for row in self.client.get(f"/api/projects/{self.team.id}/pulse/brief_configs/").json()["results"]
        ] == [config_id]

    def test_generate_with_soft_deleted_config_returns_400(
        self, mock_connect: MagicMock, _mock_flag: MagicMock
    ) -> None:
        with team_scope(self.team.pk, canonical=True):
            config = BriefConfig.objects.create(team=self.team, name="gone", deleted=True)
        response = self.client.post(
            f"/api/projects/{self.team.id}/pulse/briefs/generate/", {"config_id": str(config.id)}
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Brief config not found." in str(response.json())
        mock_connect.assert_not_called()

    def test_config_rejects_unavailable_anchor(self, _mock_connect: MagicMock, _mock_flag: MagicMock) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/pulse/brief_configs/",
            {"name": "Restricted", "anchors": {"insights": ["missing"]}},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "anchored insights are unavailable" in str(response.json())

    def test_generate_revalidates_config_anchors(self, mock_connect: MagicMock, _mock_flag: MagicMock) -> None:
        with team_scope(self.team.pk, canonical=True):
            config = BriefConfig.objects.create(
                team=self.team,
                created_by=self.user,
                name="Stale access",
                anchors={"insights": ["missing"]},
            )

        response = self.client.post(
            f"/api/projects/{self.team.id}/pulse/briefs/generate/", {"config_id": str(config.id)}
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "anchored insights are unavailable" in str(response.json())
        mock_connect.assert_not_called()

    def test_config_focus_prompt_length_capped(self, _mock_connect: MagicMock, _mock_flag: MagicMock) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/pulse/brief_configs/",
            {"name": "too long", "focus_prompt": "x" * 2001},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "focus_prompt"

    def test_config_settings_round_trip_and_range_validated(
        self, _mock_connect: MagicMock, _mock_flag: MagicMock
    ) -> None:
        # Valid knobs persist; an out-of-range knob is rejected at the serializer (wiring guard).
        response = self.client.post(
            f"/api/projects/{self.team.id}/pulse/brief_configs/",
            {"name": "Tuned", "settings": {"confidence_threshold": 0.8}},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["settings"]["confidence_threshold"] == 0.8

        bad = self.client.post(
            f"/api/projects/{self.team.id}/pulse/brief_configs/",
            {"name": "Bad", "settings": {"confidence_threshold": 5.0}},
            format="json",
        )
        assert bad.status_code == status.HTTP_400_BAD_REQUEST

    def test_generate_rejects_last_n_days_without_days(self, mock_connect: MagicMock, _mock_flag: MagicMock) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/pulse/briefs/generate/",
            {"period": {"period_type": "last_n_days"}},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_connect.assert_not_called()

import uuid

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.conf import settings

from rest_framework import status
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.models.scoping import team_scope
from posthog.models.team import Team

from products.pulse.backend.models import BriefConfig, ProductBrief


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
        response = self.client.post(f"/api/projects/{self.team.id}/pulse/briefs/generate/", {"period_days": 14})
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        brief = ProductBrief.objects.for_team(self.team.pk).get(id=response.json()["id"])
        assert brief.status == ProductBrief.Status.GENERATING
        assert brief.trigger == ProductBrief.Trigger.ON_DEMAND
        assert brief.period_days == 14
        client.start_workflow.assert_called_once()
        assert client.start_workflow.call_args.kwargs["task_queue"] == settings.ANALYTICS_PLATFORM_TASK_QUEUE
        assert client.start_workflow.call_args.kwargs["execution_timeout"] is not None

    def test_generate_while_running_returns_409_without_orphan_brief(
        self, mock_connect: MagicMock, _mock_flag: MagicMock
    ) -> None:
        client = _temporal_client()
        client.start_workflow.side_effect = WorkflowAlreadyStartedError("pulse-brief-x", "pulse-generate-brief")
        mock_connect.return_value = client
        response = self.client.post(f"/api/projects/{self.team.id}/pulse/briefs/generate/")
        assert response.status_code == status.HTTP_409_CONFLICT
        assert not ProductBrief.objects.for_team(self.team.pk).exists()

    def test_generate_dispatch_failure_marks_brief_failed(self, mock_connect: MagicMock, _mock_flag: MagicMock) -> None:
        client = _temporal_client()
        client.start_workflow.side_effect = RuntimeError("temporal down")
        mock_connect.return_value = client
        response = self.client.post(f"/api/projects/{self.team.id}/pulse/briefs/generate/")
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        brief = ProductBrief.objects.for_team(self.team.pk).get()
        assert brief.status == ProductBrief.Status.FAILED
        assert "temporal down" in (brief.error or "")

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
            other_brief = ProductBrief.objects.create(
                team=other_team, trigger=ProductBrief.Trigger.ON_DEMAND, period_days=7
            )
        response = self.client.get(f"/api/projects/{self.team.id}/pulse/briefs/")
        assert response.status_code == status.HTTP_200_OK
        assert str(other_brief.id) not in [row["id"] for row in response.json()["results"]]

    def test_config_crud_roundtrip(self, _mock_connect: MagicMock, _mock_flag: MagicMock) -> None:
        create_response = self.client.post(
            f"/api/projects/{self.team.id}/pulse/brief_configs/",
            {"name": "Feature flags focus", "focus_prompt": "flags team", "anchors": {"insights": ["abc123"]}},
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
                team=self.team, config_id=config_id, trigger=ProductBrief.Trigger.ON_DEMAND, period_days=7
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

    def test_config_focus_prompt_length_capped(self, _mock_connect: MagicMock, _mock_flag: MagicMock) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/pulse/brief_configs/",
            {"name": "too long", "focus_prompt": "x" * 2001},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "focus_prompt"

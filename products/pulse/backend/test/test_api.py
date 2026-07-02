from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.conf import settings

from rest_framework import status

from posthog.models.scoping import team_scope
from posthog.models.team import Team

from products.pulse.backend.models import ProductBrief


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

        delete_response = self.client.delete(f"/api/projects/{self.team.id}/pulse/brief_configs/{config_id}/")
        assert delete_response.status_code == status.HTTP_204_NO_CONTENT
        assert self.client.get(f"/api/projects/{self.team.id}/pulse/brief_configs/").json()["results"] == []

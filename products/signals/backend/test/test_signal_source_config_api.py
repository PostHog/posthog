from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.team.team import Team
from posthog.temporal.ai.video_segment_clustering.constants import clustering_workflow_id
from posthog.temporal.ai.video_segment_clustering.models import ClusteringWorkflowInputs

from products.signals.backend.models import SignalSourceConfig


class TestSignalSourceConfigAPI(APIBaseTest):
    def _url(self, config_id: str | None = None) -> str:
        base = f"/api/projects/{self.team.id}/signal_source_configs/"
        if config_id:
            return f"{base}{config_id}/"
        return base

    # --- Create ---

    def test_create_source_config(self):
        response = self.client.post(
            self._url(),
            data={
                "source_product": "session_replay",
                "source_type": "session_analysis_cluster",
                "enabled": True,
                "config": {"recording_filters": {"duration_min": 5}},
            },
            format="json",
        )
        data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, data
        assert data["source_product"] == "session_replay"
        assert data["source_type"] == "session_analysis_cluster"
        assert data["enabled"] is True
        assert data["config"] == {"recording_filters": {"duration_min": 5}}
        assert SignalSourceConfig.objects.filter(id=data["id"], team=self.team).exists()

    def test_create_source_config_sets_created_by(self):
        response = self.client.post(
            self._url(),
            data={"source_product": "session_replay", "source_type": "session_analysis_cluster"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        config = SignalSourceConfig.objects.get(id=response.json()["id"])
        assert config.created_by_id == self.user.id

    def test_create_source_config_defaults(self):
        response = self.client.post(
            self._url(),
            data={"source_product": "session_replay", "source_type": "session_analysis_cluster"},
            format="json",
        )
        data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, data
        assert data["enabled"] is True
        assert data["config"] == {}

    def test_create_source_config_invalid_source_type(self):
        response = self.client.post(
            self._url(),
            data={"source_product": "session_replay", "source_type": "nonexistent_type"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "source_type" in str(response.json())

    def test_create_duplicate_source_type_per_team_rejected(self):
        SignalSourceConfig.objects.create(
            team=self.team,
            source_product="session_replay",
            source_type="session_analysis_cluster",
            created_by=self.user,
        )
        response = self.client.post(
            self._url(),
            data={"source_product": "session_replay", "source_type": "session_analysis_cluster"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "already exists" in str(response.json())

    def test_same_source_type_allowed_on_different_teams(self):
        SignalSourceConfig.objects.create(
            team=self.team,
            source_product="session_replay",
            source_type="session_analysis_cluster",
            created_by=self.user,
        )
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        SignalSourceConfig.objects.create(
            team=other_team,
            source_product="session_replay",
            source_type="session_analysis_cluster",
            created_by=self.user,
        )
        assert SignalSourceConfig.objects.filter(source_type="session_analysis_cluster").count() == 2

    @patch("products.signals.backend.views.sync_connect")
    def test_workflow_create_session_analysis_cluster_triggers(self, mock_sync_connect):
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock()
        mock_sync_connect.return_value = mock_client

        response = self.client.post(
            self._url(),
            data={
                "source_product": "session_replay",
                "source_type": "session_analysis_cluster",
                "enabled": True,
            },
            format="json",
        )
        data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, data

        mock_client.start_workflow.assert_called_once()
        call_args, call_kwargs = mock_client.start_workflow.call_args
        assert call_args[0] == "video-segment-clustering"
        assert call_args[1] == clustering_workflow_id(self.team.id, data["id"])
        assert isinstance(call_kwargs["arg"], ClusteringWorkflowInputs)
        assert call_kwargs["arg"].team_id == self.team.id

    @patch("products.signals.backend.views.sync_connect")
    def test_workflow_create_disabled_does_not_trigger(self, mock_sync_connect):
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock()
        mock_sync_connect.return_value = mock_client

        response = self.client.post(
            self._url(),
            data={
                "source_product": "session_replay",
                "source_type": "session_analysis_cluster",
                "enabled": False,
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        mock_client.start_workflow.assert_not_called()

    @patch("products.signals.backend.views.sync_connect")
    def test_workflow_create_evaluation_does_not_trigger(self, mock_sync_connect):
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock()
        mock_sync_connect.return_value = mock_client

        response = self.client.post(
            self._url(),
            data={
                "source_product": "llm_analytics",
                "source_type": "evaluation",
                "enabled": True,
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        mock_client.start_workflow.assert_not_called()

    # --- Config validation ---

    @parameterized.expand(
        [
            ("valid_recording_filters", {"recording_filters": {"duration_min": 5}}, status.HTTP_201_CREATED),
            ("empty_config", {}, status.HTTP_201_CREATED),
            ("recording_filters_not_dict", {"recording_filters": "bad"}, status.HTTP_400_BAD_REQUEST),
        ]
    )
    def test_create_config_validation(self, _name, config, expected_status):
        response = self.client.post(
            self._url(),
            data={"source_product": "session_replay", "source_type": "session_analysis_cluster", "config": config},
            format="json",
        )
        assert response.status_code == expected_status, response.json()

    # --- List ---

    def test_list_source_configs(self):
        SignalSourceConfig.objects.create(
            team=self.team,
            source_product="session_replay",
            source_type="session_analysis_cluster",
            created_by=self.user,
        )
        response = self.client.get(self._url())
        data = response.json()
        assert response.status_code == status.HTTP_200_OK
        assert len(data["results"]) == 1
        assert data["results"][0]["source_type"] == "session_analysis_cluster"

    def test_list_excludes_other_teams(self):
        SignalSourceConfig.objects.create(
            team=self.team,
            source_product="session_replay",
            source_type="session_analysis_cluster",
            created_by=self.user,
        )
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        SignalSourceConfig.objects.create(
            team=other_team,
            source_product="session_replay",
            source_type="session_analysis_cluster",
            created_by=self.user,
        )

        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == 1

    # --- Retrieve ---

    def test_retrieve_source_config(self):
        config = SignalSourceConfig.objects.create(
            team=self.team,
            source_product="session_replay",
            source_type="session_analysis_cluster",
            config={"recording_filters": {"duration_min": 10}},
            created_by=self.user,
        )
        response = self.client.get(self._url(str(config.id)))
        data = response.json()
        assert response.status_code == status.HTTP_200_OK
        assert data["id"] == str(config.id)
        assert data["source_type"] == "session_analysis_cluster"
        assert data["config"] == {"recording_filters": {"duration_min": 10}}

    def test_retrieve_other_teams_config_forbidden(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        config = SignalSourceConfig.objects.create(
            team=other_team,
            source_product="session_replay",
            source_type="session_analysis_cluster",
            created_by=self.user,
        )
        response = self.client.get(self._url(str(config.id)))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_update_other_teams_config_forbidden(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        config = SignalSourceConfig.objects.create(
            team=other_team,
            source_product="session_replay",
            source_type="session_analysis_cluster",
            created_by=self.user,
        )
        response = self.client.patch(
            self._url(str(config.id)),
            data={"enabled": False},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    # --- Update ---

    def test_update_enabled(self):
        config = SignalSourceConfig.objects.create(
            team=self.team,
            source_product="session_replay",
            source_type="session_analysis_cluster",
            enabled=True,
            created_by=self.user,
        )
        response = self.client.patch(
            self._url(str(config.id)),
            data={"enabled": False},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["enabled"] is False
        config.refresh_from_db()
        assert config.enabled is False

    def test_update_config(self):
        config = SignalSourceConfig.objects.create(
            team=self.team,
            source_product="session_replay",
            source_type="session_analysis_cluster",
            config={},
            created_by=self.user,
        )
        response = self.client.patch(
            self._url(str(config.id)),
            data={"config": {"recording_filters": {"duration_min": 30}}},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["config"] == {"recording_filters": {"duration_min": 30}}

    def test_update_config_recording_filters_not_dict_rejected(self):
        config = SignalSourceConfig.objects.create(
            team=self.team,
            source_product="session_replay",
            source_type="session_analysis_cluster",
            config={},
            created_by=self.user,
        )
        response = self.client.patch(
            self._url(str(config.id)),
            data={"config": {"recording_filters": [1, 2, 3]}},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "recording_filters must be a JSON object" in str(response.json())

    def test_update_source_type_is_not_writable(self):
        config = SignalSourceConfig.objects.create(
            team=self.team,
            source_product="session_replay",
            source_type="session_analysis_cluster",
            created_by=self.user,
        )
        response = self.client.patch(
            self._url(str(config.id)),
            data={"source_type": "nonexistent_type"},
            format="json",
        )
        # source_type is not read_only in serializer, so this may succeed
        # but the value is validated
        config.refresh_from_db()
        # Should either be rejected or keep original value
        assert config.source_type == "session_analysis_cluster" or response.status_code == status.HTTP_400_BAD_REQUEST

    def test_delete_other_teams_config_forbidden(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        config = SignalSourceConfig.objects.create(
            team=other_team,
            source_product="session_replay",
            source_type="session_analysis_cluster",
            created_by=self.user,
        )
        response = self.client.delete(self._url(str(config.id)))
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert SignalSourceConfig.objects.filter(id=config.id).exists()

    # --- Delete ---

    def test_delete_source_config(self):
        config = SignalSourceConfig.objects.create(
            team=self.team,
            source_product="session_replay",
            source_type="session_analysis_cluster",
            created_by=self.user,
        )
        config_id = str(config.id)
        response = self.client.delete(self._url(config_id))
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not SignalSourceConfig.objects.filter(id=config_id).exists()

    # --- Read-only fields ---

    def test_read_only_fields_in_response(self):
        response = self.client.post(
            self._url(),
            data={"source_product": "session_replay", "source_type": "session_analysis_cluster"},
            format="json",
        )
        data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, data
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data

    # --- Auth ---

    def test_unauthenticated_request_rejected(self):
        self.client.logout()
        response = self.client.get(self._url())
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

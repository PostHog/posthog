from datetime import timedelta
from uuid import UUID, uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone as django_timezone

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import PersonalAPIKey
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.personal_api_key import hash_key_value
from posthog.models.scoping import team_scope
from posthog.temporal.oauth import ARRAY_APP_CLIENT_ID_DEV

from products.tasks.backend.models import (
    Channel,
    ChannelContextGeneration,
    ChannelFeedMessage,
    ChannelStar,
    Task,
    TaskRun,
)


class ChannelExtrasBaseTest(APIBaseTest):
    def setUp(self):
        super().setUp()
        with team_scope(self.team.id):
            self.channel = Channel.objects.create(team=self.team, name="general", created_by=self.user)
        self.base = f"/api/projects/{self.team.id}/task_channels/{self.channel.id}"


class TestChannelRetrieve(ChannelExtrasBaseTest):
    def test_retrieve(self):
        response = self.client.get(f"{self.base}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "general"

    def test_foreign_personal_channel_is_hidden(self):
        other = self._create_user("other@posthog.com")
        with team_scope(self.team.id):
            personal = Channel.objects.create(
                team=self.team, name="me", channel_type=Channel.ChannelType.PERSONAL, created_by=other
            )
        response = self.client.get(f"/api/projects/{self.team.id}/task_channels/{personal.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestChannelInstructions(ChannelExtrasBaseTest):
    def _sandbox_client(self, task_id: UUID) -> APIClient:
        application = OAuthApplication.objects.create(
            name="Loop sandbox",
            client_id=ARRAY_APP_CLIENT_ID_DEV,
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            algorithm="RS256",
            redirect_uris="https://example.com/callback",
            organization=self.organization,
            user=self.user,
        )
        access_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=application,
            token="pha_loop_sandbox",
            expires=django_timezone.now() + timedelta(hours=1),
            scope="task:read task:write",
            scoped_teams=[self.team.id],
            sandbox_task_id=task_id,
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token.token}")
        return client

    def test_loop_sandbox_can_publish_only_to_its_configured_context(self):
        with team_scope(self.team.id):
            other_channel = Channel.objects.create(team=self.team, name="other", created_by=self.user)
            task = Task.objects.create(
                team=self.team,
                created_by=self.user,
                title="Maintain context",
                origin_product=Task.OriginProduct.LOOP,
            )
            TaskRun.objects.create(
                task=task,
                team=self.team,
                state={
                    "config_snapshot": {
                        "context_target": {
                            "channel_id": str(self.channel.id),
                            "outputs": {"update_context": True},
                        }
                    }
                },
            )

        client = self._sandbox_client(task.id)
        denied = client.put(
            f"/api/projects/{self.team.id}/task_channels/{other_channel.id}/instructions/",
            {"content": "wrong target", "base_version": 0},
            format="json",
        )
        allowed = client.put(
            f"{self.base}/instructions/", {"content": "configured target", "base_version": 0}, format="json"
        )

        assert denied.status_code == status.HTTP_403_FORBIDDEN
        assert allowed.status_code == status.HTTP_200_OK

    def test_unpublished_reads_as_blank_version_zero(self):
        response = self.client.get(f"{self.base}/instructions/")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["content"] == ""
        assert body["version"] == 0

    def test_publish_read_and_conflict(self):
        response = self.client.put(
            f"{self.base}/instructions/", {"content": "# Context", "base_version": 0}, format="json"
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["version"] == 1

        response = self.client.get(f"{self.base}/instructions/")
        assert response.json()["content"] == "# Context"

        # Publishing against a stale base conflicts.
        response = self.client.put(
            f"{self.base}/instructions/", {"content": "clobber", "base_version": 0}, format="json"
        )
        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()["current_version"] == 1

        # An unguarded publish appends version 2.
        response = self.client.patch(f"{self.base}/instructions/", {"content": "v2"}, format="json")
        assert response.json()["version"] == 2

        versions = self.client.get(f"{self.base}/instructions/versions/").json()["results"]
        assert [v["version"] for v in versions] == [2, 1]

    def test_delete_resets_to_blank(self):
        self.client.put(f"{self.base}/instructions/", {"content": "x"}, format="json")
        response = self.client.delete(f"{self.base}/instructions/")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert self.client.get(f"{self.base}/instructions/").json()["version"] == 0

    def test_publish_race_surfaces_conflict_not_500(self):
        # Simulate the lost-update race: a version row exists, but the guarded
        # select_for_update sees no is_latest row (a concurrent publisher cleared
        # it / a delete landed), so the publisher computes the same next version
        # and the (channel, version) uniqueness fires. The API must answer 409,
        # not leak a 500 from the unhandled IntegrityError.
        from products.tasks.backend.models import ChannelInstructions

        self.client.put(f"{self.base}/instructions/", {"content": "v1"}, format="json")
        ChannelInstructions.objects.unscoped().filter(channel_id=self.channel.id).update(is_latest=False)

        response = self.client.patch(f"{self.base}/instructions/", {"content": "v2"}, format="json")
        assert response.status_code == status.HTTP_409_CONFLICT
        assert "current_version" in response.json()


class TestChannelSetup(ChannelExtrasBaseTest):
    GOAL_BODY = {
        "kind": "goal",
        "goal": {"statement": "Increase the weekly activation rate", "target": "20%", "deadline": "2026-12-01"},
    }

    @patch("products.cdp.backend.facade.api.is_hog_function_template_available", return_value=True)
    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_goal_setup_starts_a_task_in_the_channel(self, _mock_workflow, _template):
        with team_scope(self.team.id):
            self.channel.repositories = ["posthog/posthog"]
            self.channel.save(update_fields=["repositories"])

        response = self.client.post(f"{self.base}/setup/", self.GOAL_BODY, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        task = Task.objects.get(id=response.json()["task_id"])
        assert task.channel_id == self.channel.id
        assert task.origin_product == Task.OriginProduct.SPACE_SETUP
        assert task.created_by_id == self.user.id
        assert "Increase the weekly activation rate" in task.description
        assert "posthog/posthog" in task.description
        assert f"team_id: {self.team.id}" in task.description
        run = TaskRun.objects.get(task=task)
        assert run.state["model"] == "gpt-5.6-sol"
        assert run.state["reasoning_effort"] == "high"
        scopes = run.state["pending_dispatch"]["posthog_mcp_scopes"]
        assert "canvas:write" in scopes
        assert "hog_flow:write" in scopes
        assert "context_layer_internal:write" in scopes
        assert "organization:write" not in scopes
        assert "feature_flag:write" not in scopes
        assert ChannelContextGeneration.objects.unscoped().get(channel=self.channel).task_id == task.id
        feed = ChannelFeedMessage.objects.unscoped().get(channel=self.channel, event="space_setup_started")
        assert feed.payload["kind"] == "goal"
        assert feed.payload["task_id"] == str(task.id)

    @parameterized.expand([("not_started",), ("queued",), ("in_progress",)])
    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_active_setup_is_not_duplicated_after_context_publication(self, run_status, _workflow):
        task = Task.objects.create(
            team=self.team, channel=self.channel, title="Setup", origin_product=Task.OriginProduct.SPACE_SETUP
        )
        TaskRun.objects.create(team=self.team, task=task, status=run_status)

        response = self.client.post(
            f"{self.base}/setup/", {"kind": "feature", "feature": {"name": "Checklist"}}, format="json"
        )

        assert response.status_code == status.HTTP_409_CONFLICT, response.json()
        assert Task.objects.filter(channel=self.channel).count() == 1

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_feed_database_error_does_not_roll_back_setup(self, _workflow):
        create = ChannelFeedMessage.objects.create

        def invalid_feed(**kwargs):
            return create(**{**kwargs, "event": None})

        with patch.object(ChannelFeedMessage.objects, "create", side_effect=invalid_feed):
            response = self.client.post(
                f"{self.base}/setup/", {"kind": "feature", "feature": {"name": "Checklist"}}, format="json"
            )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert TaskRun.objects.filter(task_id=response.json()["task_id"]).exists()
        assert ChannelContextGeneration.objects.unscoped().get(channel=self.channel).task_id == UUID(
            response.json()["task_id"]
        )

    def test_task_only_key_cannot_start_setup(self):
        raw_key = "test_space_setup_key"
        PersonalAPIKey.objects.create(
            user=self.user, label="Setup", secure_value=hash_key_value(raw_key), scopes=["task:write"]
        )
        self.client.logout()
        response = self.client.post(
            f"{self.base}/setup/",
            {"kind": "feature", "feature": {"name": "Checklist"}},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {raw_key}",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        assert not Task.objects.filter(channel=self.channel).exists()

    @patch("products.cdp.backend.facade.api.is_hog_function_template_available", return_value=False)
    def test_goal_setup_without_the_task_template_does_not_start(self, _template):
        response = self.client.post(f"{self.base}/setup/", self.GOAL_BODY, format="json")

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert not Task.objects.filter(channel=self.channel).exists()
        assert not ChannelContextGeneration.objects.unscoped().filter(channel=self.channel).exists()

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_setup_of_a_hidden_channel_is_not_found(self, mock_workflow):
        other = self._create_user("other@posthog.com")
        with team_scope(self.team.id):
            personal = Channel.objects.create(
                team=self.team, name="me", channel_type=Channel.ChannelType.PERSONAL, created_by=other
            )

        response = self.client.post(
            f"/api/projects/{self.team.id}/task_channels/{personal.id}/setup/", self.GOAL_BODY, format="json"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_workflow.assert_not_called()
        assert not Task.objects.filter(channel=personal).exists()

    def test_setup_without_the_matching_payload_is_rejected(self):
        response = self.client.post(f"{self.base}/setup/", {"kind": "goal"}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "goal"
        assert not Task.objects.filter(channel=self.channel).exists()


class TestChannelContextGeneration(ChannelExtrasBaseTest):
    def test_get_and_set(self):
        response = self.client.get(f"{self.base}/context_generation/")
        assert response.json()["task_id"] is None

        response = self.client.put(f"{self.base}/context_generation/", {"task_id": str(uuid4())}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST  # unknown task

        response = self.client.put(f"{self.base}/context_generation/", {"task_id": None}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["task_id"] is None

    def test_publishing_instructions_clears_marker(self):
        from products.tasks.backend.models import ChannelContextGeneration

        with team_scope(self.team.id):
            ChannelContextGeneration.objects.create(team=self.team, channel=self.channel, task_id=uuid4())
        self.client.put(f"{self.base}/instructions/", {"content": "done"}, format="json")
        assert self.client.get(f"{self.base}/context_generation/").json()["task_id"] is None


class TestChannelStars(ChannelExtrasBaseTest):
    def test_star_round_trip_reflected_in_list(self):
        response = self.client.post(f"{self.base}/star/", {"starred": True}, format="json")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert ChannelStar.objects.unscoped().filter(channel=self.channel, user=self.user).exists()

        channels = self.client.get(f"/api/projects/{self.team.id}/task_channels/").json()
        starred = {c["name"]: c["starred"] for c in channels}
        assert starred["general"] is True

        response = self.client.post(f"{self.base}/star/", {"starred": False}, format="json")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not ChannelStar.objects.unscoped().filter(channel=self.channel, user=self.user).exists()

    @parameterized.expand(
        [
            ("star_omitted", {}, True),
            ("star_on", {"star": True}, True),
            ("star_off", {"star": False}, False),
        ]
    )
    def test_creating_a_channel_stars_it_for_its_creator(self, _name, body, expected_starred):
        response = self.client.post(
            f"/api/projects/{self.team.id}/task_channels/", {"name": "growth", **body}, format="json"
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["starred"] is expected_starred
        assert (
            ChannelStar.objects.unscoped().filter(channel_id=response.json()["id"], user=self.user).exists()
            is expected_starred
        )

    def test_resolving_an_existing_channel_leaves_stars_alone(self):
        response = self.client.post(f"/api/projects/{self.team.id}/task_channels/", {"name": "general"}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["id"] == str(self.channel.id)
        assert response.json()["starred"] is False
        assert not ChannelStar.objects.unscoped().filter(channel=self.channel, user=self.user).exists()

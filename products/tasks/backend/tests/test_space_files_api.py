from datetime import timedelta
from uuid import UUID

from posthog.test.base import APIBaseTest

from django.utils import timezone as django_timezone

from rest_framework import status
from rest_framework.test import APIClient

from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.scoping import team_scope
from posthog.temporal.oauth import ARRAY_APP_CLIENT_ID_DEV

from products.tasks.backend.models import Channel, ChannelMembership, SpaceFile, Task


class TestSpaceFilesAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        with team_scope(self.team.id):
            self.channel = Channel.objects.create(team=self.team, name="general", created_by=self.user)
        self.base = f"/api/projects/{self.team.id}/space_files/"

    def _create_file(self, name: str = "notes.md", content: str = "") -> dict:
        response = self.client.post(
            self.base,
            {"channel_id": str(self.channel.id), "name": name, "content": content},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.content
        return response.json()

    def _sandbox_client(self, task_id: UUID) -> APIClient:
        application = OAuthApplication.objects.create(
            name="Task sandbox",
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
            token=f"pha_space_file_{task_id}",
            expires=django_timezone.now() + timedelta(hours=1),
            scope="task:read task:write",
            scoped_teams=[self.team.id],
            sandbox_task_id=task_id,
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token.token}")
        return client

    def test_create_list_get_and_update(self) -> None:
        created = self._create_file(content="# Notes")
        assert created["content"] == "# Notes"
        assert created["version"] == 1

        listed = self.client.get(self.base)
        assert listed.status_code == status.HTTP_200_OK
        assert listed.json()["results"] == [
            {
                "id": created["id"],
                "channel_id": str(self.channel.id),
                "name": "notes.md",
                "version": 1,
                "created_at": created["created_at"],
                "updated_at": created["updated_at"],
            }
        ]

        detail = self.client.get(f"{self.base}{created['id']}/")
        assert detail.status_code == status.HTTP_200_OK
        assert detail.json()["content"] == "# Notes"

        for incomplete_update in ({"content": "# Revised"}, {"base_version": 1}):
            response = self.client.patch(f"{self.base}{created['id']}/", incomplete_update, format="json")
            assert response.status_code == status.HTTP_400_BAD_REQUEST

        updated = self.client.patch(
            f"{self.base}{created['id']}/",
            {"content": "# Revised", "base_version": 1},
            format="json",
        )
        assert updated.status_code == status.HTTP_200_OK
        assert updated.json()["version"] == 2
        assert updated.json()["content"] == "# Revised"

    def test_stale_update_returns_current_version_without_overwriting_content(self) -> None:
        created = self._create_file(content="original")
        first_update = self.client.patch(
            f"{self.base}{created['id']}/",
            {"content": "current", "base_version": 1},
            format="json",
        )
        assert first_update.status_code == status.HTTP_200_OK

        stale_update = self.client.patch(
            f"{self.base}{created['id']}/",
            {"content": "stale", "base_version": 1},
            format="json",
        )
        assert stale_update.status_code == status.HTTP_409_CONFLICT
        assert stale_update.json()["current_version"] == 2

        with team_scope(self.team.id):
            stored = SpaceFile.objects.get(id=created["id"])
        assert stored.content == "current"
        assert stored.version == 2

    def test_rejects_non_markdown_names_and_oversized_utf8_content(self) -> None:
        for name in ("nested/notes.md", "notes\tcopy.md"):
            invalid_name = self.client.post(
                self.base,
                {"channel_id": str(self.channel.id), "name": name},
                format="json",
            )
            assert invalid_name.status_code == status.HTTP_400_BAD_REQUEST

        oversized_content = self.client.post(
            self.base,
            {"channel_id": str(self.channel.id), "name": "notes.md", "content": "€" * 33_334},
            format="json",
        )
        assert oversized_content.status_code == status.HTTP_400_BAD_REQUEST

    def test_name_is_unique_case_insensitively_per_space(self) -> None:
        self._create_file(name="Notes.md")
        duplicate = self.client.post(
            self.base,
            {"channel_id": str(self.channel.id), "name": "notes.md"},
            format="json",
        )
        assert duplicate.status_code == status.HTTP_400_BAD_REQUEST

    def test_private_space_files_are_hidden_from_non_members(self) -> None:
        owner = self._create_user("owner@example.com")
        self.organization.members.add(owner)
        with team_scope(self.team.id):
            private_channel = Channel.objects.create(
                team=self.team,
                name="private",
                channel_type=Channel.ChannelType.PRIVATE,
                created_by=owner,
            )
            ChannelMembership.objects.create(team=self.team, channel=private_channel, user=owner)
            space_file = SpaceFile.objects.create(
                team=self.team,
                channel=private_channel,
                name="private.md",
                content="private",
            )

        assert self.client.get(self.base).json()["results"] == []
        assert self.client.get(f"{self.base}{space_file.id}/").status_code == status.HTTP_404_NOT_FOUND

    def test_sandbox_token_is_limited_to_its_tasks_space(self) -> None:
        with team_scope(self.team.id):
            other_channel = Channel.objects.create(team=self.team, name="other", created_by=self.user)
            task = Task.objects.create(
                team=self.team,
                channel=self.channel,
                created_by=self.user,
                title="Update space files",
                origin_product=Task.OriginProduct.USER_CREATED,
            )
            own_file = SpaceFile.objects.create(team=self.team, channel=self.channel, name="own.md", content="own")
            other_file = SpaceFile.objects.create(
                team=self.team,
                channel=other_channel,
                name="other.md",
                content="other",
            )

        client = self._sandbox_client(task.id)
        listed = client.get(self.base)
        assert listed.status_code == status.HTTP_200_OK
        assert [item["id"] for item in listed.json()["results"]] == [str(own_file.id)]
        assert client.get(f"{self.base}{other_file.id}/").status_code == status.HTTP_404_NOT_FOUND

        denied_update = client.patch(
            f"{self.base}{other_file.id}/",
            {"content": "changed", "base_version": 1},
            format="json",
        )
        assert denied_update.status_code == status.HTTP_404_NOT_FOUND
        with team_scope(self.team.id):
            other_file.refresh_from_db()
        assert other_file.content == "other"

    def test_unfiled_task_sandbox_token_cannot_access_space_files(self) -> None:
        with team_scope(self.team.id):
            task = Task.objects.create(
                team=self.team,
                created_by=self.user,
                title="Unfiled task",
                origin_product=Task.OriginProduct.USER_CREATED,
            )

        assert self._sandbox_client(task.id).get(self.base).status_code == status.HTTP_403_FORBIDDEN

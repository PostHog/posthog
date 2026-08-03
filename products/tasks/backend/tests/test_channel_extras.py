from uuid import uuid4

from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models.scoping import team_scope

from products.tasks.backend.models import Channel, ChannelStar


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

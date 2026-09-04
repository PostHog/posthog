import json
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.api.test.test_sharing import mock_exporter_template
from posthog.models import SharingConfiguration
from posthog.models.activity_logging.activity_log import Detail, log_activity
from posthog.models.scoping import team_scope
from posthog.models.user import User

from products.tasks.backend import activity_visibility
from products.tasks.backend.models import Channel, SharedTaskArtifact, Task, TaskRun

EXPORTED_DATA_OPEN = '<script id="posthog-exported-data" type="application/json">'

STORAGE: dict[str, bytes] = {
    "artifacts/report-v1.md": b"# Draft\n",
    "artifacts/report-v2.md": b"# Final\n",
    "artifacts/report-v3.md": b"# Revised\n",
    "artifacts/chart.png": b"\x89PNG fake",
    "artifacts/page.html": b"<script>alert(1)</script>",
}


def _entry(artifact_id: str, name: str, storage_path: str, content_type: str, uploaded_at: str) -> dict[str, Any]:
    return {
        "id": artifact_id,
        "name": name,
        "type": "output",
        "storage_path": storage_path,
        "content_type": content_type,
        "size": len(STORAGE[storage_path]),
        "uploaded_at": uploaded_at,
    }


class TestTaskArtifactSharing(APIBaseTest):
    def setUp(self):
        super().setUp()
        read_bytes = patch("posthog.storage.object_storage.read_bytes", side_effect=lambda key, **_: STORAGE.get(key))
        read_bytes.start()
        self.addCleanup(read_bytes.stop)
        with team_scope(self.team.id):
            self.channel = Channel.objects.create(team=self.team, name="general", created_by=self.user)
        self.task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            channel=self.channel,
            title="Write the report",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        self.older_run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            artifacts=[
                _entry("art-1", "report.md", "artifacts/report-v1.md", "text/markdown", "2026-01-01T00:00:00+00:00"),
                _entry("img-1", "chart.png", "artifacts/chart.png", "image/png", "2026-01-01T00:00:00+00:00"),
                _entry("html-1", "page.html", "artifacts/page.html", "text/html", "2026-01-01T00:00:00+00:00"),
            ],
        )
        self.newer_run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            artifacts=[
                _entry("art-2", "report.md", "artifacts/report-v2.md", "text/markdown", "2026-02-01T00:00:00+00:00")
            ],
        )

    def _sharing_url(self, artifact_id: str, task: Task | None = None) -> str:
        return f"/api/projects/{self.team.id}/tasks/{(task or self.task).id}/artifacts/{artifact_id}/sharing"

    def _enable_sharing(self, artifact_id: str) -> str:
        response = self.client.patch(self._sharing_url(artifact_id), {"enabled": True})
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()["access_token"]

    def _shared_payload(self, access_token: str) -> dict[str, Any]:
        @mock_exporter_template
        def fetch(test: "TestTaskArtifactSharing") -> dict[str, Any]:
            response = test.client.get(f"/shared/{access_token}")
            assert response.status_code == status.HTTP_200_OK, response.content
            body = response.content.decode()
            start = body.index(EXPORTED_DATA_OPEN) + len(EXPORTED_DATA_OPEN)
            return json.loads(body[start : body.index("</script>", start)])

        return fetch(self)

    def test_reading_sharing_state_never_creates_the_anchor(self):
        response = self.client.get(self._sharing_url("art-1"))

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["enabled"] is False
        assert response.json()["shared_artifact_id"] is None
        assert not SharedTaskArtifact.objects.for_team(self.team.id).exists()

    def test_sharing_pins_the_newest_upload_and_every_version_reads_the_same_share(self):
        access_token = self._enable_sharing("art-1")

        with team_scope(self.team.id):
            anchor = SharedTaskArtifact.objects.get(task=self.task, name="report.md")
            assert anchor.artifact_id == "art-2"
            assert SharingConfiguration.objects.get(access_token=access_token).task_artifact_id == anchor.id
        state = self.client.get(self._sharing_url("art-2")).json()
        assert state["access_token"] == access_token
        assert (state["shared_artifact_id"], state["latest_artifact_id"]) == ("art-2", "art-2")
        self.client.logout()
        payload = self._shared_payload(access_token)

        assert payload["task_artifact"]["kind"] == "markdown"
        assert payload["task_artifact"]["markdown"] == "# Final\n"
        assert payload["task_artifact"]["file_url"] == f"/shared/{access_token}.md"

    def test_a_later_upload_stays_private_until_its_changes_are_published(self):
        access_token = self._enable_sharing("art-1")
        self.newer_run.artifacts.append(
            _entry("art-3", "report.md", "artifacts/report-v3.md", "text/markdown", "2026-03-01T00:00:00+00:00")
        )
        self.newer_run.save(update_fields=["artifacts"])

        state = self.client.get(self._sharing_url("art-3")).json()
        assert (state["shared_artifact_id"], state["latest_artifact_id"]) == ("art-2", "art-3")
        assert self._shared_payload(access_token)["task_artifact"]["markdown"] == "# Final\n"

        published = self.client.patch(self._sharing_url("art-3"), {"enabled": True})

        assert published.status_code == status.HTTP_200_OK, published.json()
        assert published.json()["shared_artifact_id"] == "art-3"
        assert self._shared_payload(access_token)["task_artifact"]["markdown"] == "# Revised\n"

    def test_publishing_drops_the_expiry_tag_of_whichever_upload_is_served(self):
        with patch("posthog.storage.object_storage.tag") as tag:
            self._enable_sharing("art-1")
            first_share = [call.args for call in tag.call_args_list]
            # Re-enabling with nothing new to publish leaves the pin, so nothing is retagged.
            self._enable_sharing("art-1")
            unchanged = [call.args for call in tag.call_args_list]
            self.newer_run.artifacts.append(
                _entry("art-3", "report.md", "artifacts/report-v3.md", "text/markdown", "2026-03-01T00:00:00+00:00")
            )
            self.newer_run.save(update_fields=["artifacts"])
            self._enable_sharing("art-3")
            published = [call.args for call in tag.call_args_list]

        team = {"team_id": str(self.team.id)}
        assert first_share == [("artifacts/report-v2.md", team)]
        assert unchanged == first_share
        assert published == [("artifacts/report-v2.md", team), ("artifacts/report-v3.md", team)]

    def test_image_streams_inline_with_nosniff(self):
        access_token = self._enable_sharing("img-1")
        self.client.logout()

        response = self.client.get(f"/shared/{access_token}.png")

        assert response.status_code == status.HTTP_200_OK
        assert response["Content-Type"] == "image/png"
        assert response["X-Content-Type-Options"] == "nosniff"
        assert response["Content-Disposition"].startswith("inline")
        assert response.content == STORAGE["artifacts/chart.png"]

    def test_html_is_download_only(self):
        access_token = self._enable_sharing("html-1")
        self.client.logout()

        payload = self._shared_payload(access_token)
        response = self.client.get(f"/shared/{access_token}.html")

        assert payload["task_artifact"]["kind"] == "html"
        assert payload["task_artifact"]["markdown"] is None
        assert response.status_code == status.HTTP_200_OK
        assert response["Content-Type"] == "application/octet-stream"
        assert response["Content-Disposition"].startswith("attachment")

    @parameterized.expand([("task deleted",), ("upload dismissed",)])
    def test_public_page_404s_once_the_file_is_gone(self, case: str):
        access_token = self._enable_sharing("art-1")
        if case == "task deleted":
            self.task.deleted = True
            self.task.save()
        else:
            self.newer_run.artifacts[0]["dismissed_at"] = "2026-03-01T00:00:00+00:00"
            self.newer_run.save(update_fields=["artifacts"])
        self.client.logout()

        assert self.client.get(f"/shared/{access_token}").status_code == status.HTTP_404_NOT_FOUND
        assert self.client.get(f"/shared/{access_token}.md").status_code == status.HTTP_404_NOT_FOUND

    @parameterized.expand([("unknown artifact", "missing"), ("reference entry without a file", "ref-1")])
    def test_unknown_artifact_ids_are_not_found(self, _name: str, artifact_id: str):
        self.older_run.artifacts.append({"id": "ref-1", "name": "Insight", "type": "reference"})
        self.older_run.save(update_fields=["artifacts"])

        response = self.client.patch(self._sharing_url(artifact_id), {"enabled": True})

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_someone_elses_personal_task_cannot_be_shared(self):
        owner = User.objects.create_and_join(self.organization, "owner@example.com", None)
        with team_scope(self.team.id):
            personal = Channel.objects.create(
                team=self.team, name="me", channel_type=Channel.ChannelType.PERSONAL, created_by=owner
            )
        task = Task.objects.create(
            team=self.team,
            created_by=owner,
            channel=personal,
            title="Private",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        TaskRun.objects.create(
            task=task,
            team=self.team,
            artifacts=[
                _entry("secret", "report.md", "artifacts/report-v1.md", "text/markdown", "2026-01-01T00:00:00+00:00")
            ],
        )

        response = self.client.patch(self._sharing_url("secret", task), {"enabled": True})

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert not SharedTaskArtifact.objects.for_team(self.team.id).exists()

    def test_a_teammate_can_read_the_sharing_state_but_not_publish_the_file(self):
        teammate = User.objects.create_and_join(self.organization, "teammate@example.com", None)
        client = APIClient()
        client.force_login(teammate)

        read = client.get(self._sharing_url("art-1"))
        write = client.patch(self._sharing_url("art-1"), {"enabled": True}, format="json")

        assert read.status_code == status.HTTP_200_OK, read.json()
        assert read.json()["enabled"] is False
        assert write.status_code == status.HTTP_403_FORBIDDEN, write.json()
        assert not SharedTaskArtifact.objects.for_team(self.team.id).exists()


class TestTaskActivityVisibility(APIBaseTest):
    """A task in someone's personal space is theirs alone, so the `Task`-scoped rows an
    artifact share writes must not reach another member through the activity feed."""

    def _personal_task(self, owner: User, title: str) -> Task:
        with team_scope(self.team.id):
            channel = Channel.objects.create(
                team=self.team, name=title, channel_type=Channel.ChannelType.PERSONAL, created_by=owner
            )
        return Task.objects.create(
            team=self.team,
            created_by=owner,
            channel=channel,
            title=title,
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
        )

    def test_hidden_ids_cover_another_members_personal_task_only(self):
        other = User.objects.create_and_join(self.organization, "teammate-activity@example.com", None)
        theirs = self._personal_task(other, "Theirs")
        mine = self._personal_task(self.user, "Mine")

        hidden = activity_visibility.hidden_task_ids(self.team.id, self.user)
        hidden_for_org = activity_visibility.hidden_task_ids_for_org(self.organization.id, self.user)

        assert str(theirs.id) in hidden
        assert str(mine.id) not in hidden
        assert str(theirs.id) in hidden_for_org
        assert str(mine.id) not in hidden_for_org

    def test_team_activity_feed_hides_another_members_personal_task(self):
        other = User.objects.create_and_join(self.organization, "teammate-feed@example.com", None)
        theirs = self._personal_task(other, "Theirs")
        mine = self._personal_task(self.user, "Mine")
        for task in (theirs, mine):
            log_activity(
                organization_id=self.organization.id,
                team_id=self.team.id,
                user=None,
                was_impersonated=False,
                item_id=str(task.id),
                scope="Task",
                activity="share_login_failed",
                detail=Detail(name="report.md"),
                force_save=True,
            )

        response = self.client.get(f"/api/projects/{self.team.id}/advanced_activity_logs/")

        assert response.status_code == status.HTTP_200_OK
        visible = {row["item_id"] for row in response.json()["results"] if row["scope"] == "Task"}
        assert str(mine.id) in visible
        assert str(theirs.id) not in visible

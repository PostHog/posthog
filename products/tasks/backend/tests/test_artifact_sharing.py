import json
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.api.test.test_sharing import mock_exporter_template
from posthog.models import SharingConfiguration
from posthog.models.scoping import team_scope
from posthog.models.user import User

from products.tasks.backend.models import Channel, SharedTaskArtifact, Task, TaskRun

EXPORTED_DATA_OPEN = '<script id="posthog-exported-data" type="application/json">'

STORAGE: dict[str, bytes] = {
    "artifacts/report-v1.md": b"# Draft\n",
    "artifacts/report-v2.md": b"# Final\n",
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
        assert not SharedTaskArtifact.objects.for_team(self.team.id).exists()

    def test_a_share_serves_the_upload_that_was_shared_not_a_newer_one(self):
        access_token = self._enable_sharing("art-1")

        with team_scope(self.team.id):
            anchor = SharedTaskArtifact.objects.get(run=self.older_run, artifact_id="art-1")
            assert anchor.task_id == self.task.id
            assert SharingConfiguration.objects.get(access_token=access_token).task_artifact_id == anchor.id
        self.client.logout()
        payload = self._shared_payload(access_token)

        assert payload["task_artifact"]["kind"] == "markdown"
        assert payload["task_artifact"]["markdown"] == "# Draft\n"
        assert payload["task_artifact"]["file_url"] == f"/shared/{access_token}.md"

    def test_each_upload_has_its_own_share(self):
        first = self._enable_sharing("art-1")

        assert self.client.get(self._sharing_url("art-2")).json()["enabled"] is False
        second = self._enable_sharing("art-2")

        assert first != second
        assert SharedTaskArtifact.objects.for_team(self.team.id).count() == 2
        self.client.logout()
        assert self._shared_payload(second)["task_artifact"]["markdown"] == "# Final\n"

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
            self.older_run.artifacts[0]["dismissed_at"] = "2026-03-01T00:00:00+00:00"
            self.older_run.save(update_fields=["artifacts"])
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

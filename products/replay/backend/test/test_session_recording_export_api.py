from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models import Team

from products.replay.backend.models.exported_recording import ExportedRecording

VIEWSET = "products.replay.backend.api.session_recording_export"


class TestSessionRecordingExportAPI(APIBaseTest):
    def _url(self, export_id: str | None = None) -> str:
        base = f"/api/projects/{self.team.id}/session_recording_exports/"
        return f"{base}{export_id}/" if export_id else base

    def _make_staff(self) -> None:
        self.user.is_staff = True
        self.user.save()

    def _export(self, team: Team | None = None, session_id: str = "session-1") -> ExportedRecording:
        return ExportedRecording.objects.create(
            team=team or self.team,
            session_id=session_id,
            reason="because",
            created_by=self.user,
        )

    def test_staff_create_triggers_export(self) -> None:
        self._make_staff()

        def fake_trigger(*, team: Team, session_id: str, reason: str, **_: object) -> ExportedRecording:
            return self._export(team=team, session_id=session_id)

        with patch(f"{VIEWSET}.trigger_recording_export", side_effect=fake_trigger) as mock_trigger:
            response = self.client.post(
                self._url(),
                {"session_id": "session-abc", "reason": "investigating a bug"},
            )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert ExportedRecording.objects.filter(team=self.team).count() == 1
        mock_trigger.assert_called_once()
        kwargs = mock_trigger.call_args.kwargs
        assert kwargs["team"] == self.team
        assert kwargs["session_id"] == "session-abc"
        assert kwargs["reason"] == "investigating a bug"
        assert kwargs["user"] == self.user
        assert kwargs["was_impersonated"] is False

    @parameterized.expand(["create", "list", "retrieve"])
    def test_non_staff_is_forbidden(self, action: str) -> None:
        export = self._export()

        if action == "create":
            response = self.client.post(self._url(), {"session_id": "s", "reason": "r"})
        elif action == "list":
            response = self.client.get(self._url())
        else:
            response = self.client.get(self._url(str(export.id)))

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_staff_can_list_and_retrieve(self) -> None:
        self._make_staff()
        export = self._export(session_id="session-xyz")

        list_response = self.client.get(self._url())
        assert list_response.status_code == status.HTTP_200_OK
        results = list_response.json()["results"]
        assert len(results) == 1
        assert results[0]["session_id"] == "session-xyz"
        assert results[0]["status"] == ExportedRecording.Status.PENDING
        assert results[0]["created_by"]["id"] == self.user.id

        detail_response = self.client.get(self._url(str(export.id)))
        assert detail_response.status_code == status.HTTP_200_OK
        assert detail_response.json()["id"] == str(export.id)

    def test_team_isolation(self) -> None:
        self._make_staff()
        other_team = Team.objects.create(organization=self.organization)
        other_export = self._export(team=other_team, session_id="other-team-session")

        list_response = self.client.get(self._url())
        assert list_response.status_code == status.HTTP_200_OK
        assert list_response.json()["results"] == []

        detail_response = self.client.get(self._url(str(other_export.id)))
        assert detail_response.status_code == status.HTTP_404_NOT_FOUND

    @parameterized.expand([("session_id", {"reason": "r"}), ("reason", {"session_id": "s"})])
    def test_missing_required_field_is_rejected(self, _name: str, body: dict[str, str]) -> None:
        self._make_staff()

        response = self.client.post(self._url(), body)

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_workflow_start_failure_surfaces_error(self) -> None:
        self._make_staff()

        with patch(f"{VIEWSET}.trigger_recording_export", side_effect=RuntimeError("temporal down")):
            response = self.client.post(
                self._url(),
                {"session_id": "session-abc", "reason": "investigating a bug"},
            )

        assert response.status_code == status.HTTP_502_BAD_GATEWAY

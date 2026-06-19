from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from products.replay.backend.models.exported_recording import ExportedRecording
from products.replay.backend.services.export_recording import trigger_recording_export

SERVICE = "products.replay.backend.services.export_recording"


class TestTriggerRecordingExport(BaseTest):
    def _run(self, *, was_impersonated: bool = False) -> tuple[ExportedRecording, MagicMock, MagicMock]:
        mock_temporal = MagicMock()
        mock_temporal.start_workflow = AsyncMock(return_value=None)

        with (
            patch(f"{SERVICE}.sync_connect", return_value=mock_temporal),
            patch(f"{SERVICE}.log_activity") as mock_log_activity,
        ):
            record = trigger_recording_export(
                team=self.team,
                session_id="session-123",
                reason="debugging a customer issue",
                user=self.user,
                was_impersonated=was_impersonated,
            )
        return record, mock_temporal.start_workflow, mock_log_activity

    def test_creates_exported_recording_row(self) -> None:
        record, _, _ = self._run()

        persisted = ExportedRecording.objects.get(id=record.id)
        assert persisted.team == self.team
        assert persisted.session_id == "session-123"
        assert persisted.reason == "debugging a customer issue"
        assert persisted.created_by == self.user
        assert persisted.status == ExportedRecording.Status.PENDING

    def test_starts_export_workflow_for_the_new_record(self) -> None:
        record, start_workflow, _ = self._run()

        start_workflow.assert_called_once()
        args, kwargs = start_workflow.call_args
        assert args[0] == "export-recording"
        assert args[1].exported_recording_id == record.id
        assert kwargs["id"].startswith(f"export-recording-{record.id}-")

    def test_forwards_was_impersonated_to_activity_log(self) -> None:
        _, _, mock_log_activity = self._run(was_impersonated=True)

        mock_log_activity.assert_called_once()
        assert mock_log_activity.call_args.kwargs["was_impersonated"] is True
        assert mock_log_activity.call_args.kwargs["scope"] == "Replay"
        assert mock_log_activity.call_args.kwargs["activity"] == "exported"

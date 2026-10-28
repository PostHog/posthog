from posthog.test.base import BaseTest

from posthog.models import Team

from products.error_tracking.backend.management.commands.drop_error_tracking_stack_frame_code_variables import Command
from products.error_tracking.backend.models import ErrorTrackingStackFrame


def frame_contents(raw_id: str, code_variables: dict[str, str] | None = None) -> dict[str, object]:
    contents: dict[str, object] = {"raw_id": raw_id, "mangled_name": "handle_request", "lang": "python"}
    if code_variables is not None:
        contents["code_variables"] = code_variables
    return contents


class TestDropErrorTrackingStackFrameCodeVariables(BaseTest):
    def test_drop_removes_code_variables_from_the_team_frames_in_batches(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        code_variables = {"api_key": "fake-api-key-for-tests"}
        first_frame = ErrorTrackingStackFrame.objects.create(
            team=self.team, raw_id="frame-a", contents=frame_contents("frame-a", code_variables), resolved=True
        )
        second_frame = ErrorTrackingStackFrame.objects.create(
            team=self.team, raw_id="frame-b", contents=frame_contents("frame-b", code_variables), resolved=True
        )
        clean_frame = ErrorTrackingStackFrame.objects.create(
            team=self.team, raw_id="frame-c", contents=frame_contents("frame-c"), resolved=True
        )
        other_team_frame = ErrorTrackingStackFrame.objects.create(
            team=other_team, raw_id="frame-a", contents=frame_contents("frame-a", code_variables), resolved=True
        )

        Command().handle(team_id=self.team.id, live_run=False, batch_size=1, start_after_raw_id=None)

        first_frame.refresh_from_db()
        second_frame.refresh_from_db()
        assert first_frame.contents == frame_contents("frame-a", code_variables)
        assert second_frame.contents == frame_contents("frame-b", code_variables)

        Command().handle(team_id=self.team.id, live_run=True, batch_size=1, start_after_raw_id=None)

        first_frame.refresh_from_db()
        second_frame.refresh_from_db()
        clean_frame.refresh_from_db()
        other_team_frame.refresh_from_db()
        assert first_frame.contents == frame_contents("frame-a")
        assert second_frame.contents == frame_contents("frame-b")
        assert clean_frame.contents == frame_contents("frame-c")
        assert other_team_frame.contents == frame_contents("frame-a", code_variables)

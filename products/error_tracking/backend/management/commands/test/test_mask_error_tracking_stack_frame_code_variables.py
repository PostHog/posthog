from posthog.test.base import BaseTest

from posthog.models import Team

from products.error_tracking.backend.logic.code_variables_masking import REDACTED
from products.error_tracking.backend.management.commands.mask_error_tracking_stack_frame_code_variables import Command
from products.error_tracking.backend.models import ErrorTrackingStackFrame

UNMASKED = {"url": "postgresql://app:fake-pass-for-tests@db.example.com/app", "retries": 3}
MASKED = {"url": f"postgresql://{REDACTED}@db.example.com/app", "retries": 3}


def frame_contents(raw_id: str, code_variables: dict[str, object] | None = None) -> dict[str, object]:
    contents: dict[str, object] = {"raw_id": raw_id, "mangled_name": "handle_request", "lang": "python"}
    if code_variables is not None:
        contents["code_variables"] = code_variables
    return contents


class TestMaskErrorTrackingStackFrameCodeVariables(BaseTest):
    def test_masks_every_team_except_the_excluded_ones(self) -> None:
        second_team = Team.objects.create(organization=self.organization, name="Second team")
        excluded_team = Team.objects.create(organization=self.organization, name="Excluded team")
        frames = {
            "first": ErrorTrackingStackFrame.objects.create(
                team=self.team, raw_id="frame-a", contents=frame_contents("frame-a", UNMASKED), resolved=True
            ),
            "second": ErrorTrackingStackFrame.objects.create(
                team=second_team, raw_id="frame-a", contents=frame_contents("frame-a", UNMASKED), resolved=True
            ),
            "clean": ErrorTrackingStackFrame.objects.create(
                team=self.team, raw_id="frame-b", contents=frame_contents("frame-b"), resolved=True
            ),
            "excluded": ErrorTrackingStackFrame.objects.create(
                team=excluded_team, raw_id="frame-a", contents=frame_contents("frame-a", UNMASKED), resolved=True
            ),
        }

        def run(*, live_run: bool) -> None:
            Command().handle(
                live_run=live_run,
                batch_size=1,
                exclude_team_ids=str(excluded_team.id),
                start_at_team_id=None,
                start_after_raw_id=None,
            )

        run(live_run=False)

        for frame in frames.values():
            frame.refresh_from_db()
        assert frames["first"].contents == frame_contents("frame-a", UNMASKED)

        run(live_run=True)

        for frame in frames.values():
            frame.refresh_from_db()
        assert frames["first"].contents == frame_contents("frame-a", MASKED)
        assert frames["second"].contents == frame_contents("frame-a", MASKED)
        assert frames["clean"].contents == frame_contents("frame-b")
        assert frames["excluded"].contents == frame_contents("frame-a", UNMASKED)

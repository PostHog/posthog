from posthog.test.base import BaseTest
from unittest.mock import patch

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
    def frame(
        self, team: Team, raw_id: str, code_variables: dict[str, object] | None, part: int = 0
    ) -> ErrorTrackingStackFrame:
        return ErrorTrackingStackFrame.objects.create(
            team=team, raw_id=raw_id, part=part, contents=frame_contents(raw_id, code_variables), resolved=True
        )

    def test_masks_only_the_listed_teams(self) -> None:
        second_team = Team.objects.create(organization=self.organization, name="Second team")
        unlisted_team = Team.objects.create(organization=self.organization, name="Unlisted team")
        frames = {
            "first": self.frame(self.team, "frame-a", UNMASKED),
            "first_part_1": self.frame(self.team, "frame-a", UNMASKED, part=1),
            "second": self.frame(second_team, "frame-a", UNMASKED),
            "clean": self.frame(self.team, "frame-b", None),
            "unlisted": self.frame(unlisted_team, "frame-a", UNMASKED),
        }

        def run(*, live_run: bool) -> None:
            with patch(f"{Command.__module__}.FRAMES_PER_READ", 1):
                Command().handle(
                    team_ids=f"{self.team.id},{second_team.id}",
                    live_run=live_run,
                    batch_size=1,
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
        assert frames["first_part_1"].contents == frame_contents("frame-a", MASKED)
        assert frames["second"].contents == frame_contents("frame-a", MASKED)
        assert frames["clean"].contents == frame_contents("frame-b")
        assert frames["unlisted"].contents == frame_contents("frame-a", UNMASKED)

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


def run_command(
    *,
    live_run: bool = True,
    team_ids: str = "",
    exclude_team_ids: str = "",
    start_at_team_id: int | None = None,
    start_after_raw_id: str | None = None,
) -> None:
    Command().handle(
        live_run=live_run,
        batch_size=1,
        team_ids=team_ids,
        exclude_team_ids=exclude_team_ids,
        start_at_team_id=start_at_team_id,
        start_after_raw_id=start_after_raw_id,
    )


class TestMaskErrorTrackingStackFrameCodeVariables(BaseTest):
    def frame(self, team: Team, raw_id: str, code_variables: dict[str, object] | None) -> ErrorTrackingStackFrame:
        return ErrorTrackingStackFrame.objects.create(
            team=team, raw_id=raw_id, contents=frame_contents(raw_id, code_variables), resolved=True
        )

    def test_masks_every_team_except_the_excluded_ones(self) -> None:
        second_team = Team.objects.create(organization=self.organization, name="Second team")
        excluded_team = Team.objects.create(organization=self.organization, name="Excluded team")
        frames = {
            "first": self.frame(self.team, "frame-a", UNMASKED),
            "second": self.frame(second_team, "frame-a", UNMASKED),
            "clean": self.frame(self.team, "frame-b", None),
            "excluded": self.frame(excluded_team, "frame-a", UNMASKED),
        }

        run_command(live_run=False, exclude_team_ids=str(excluded_team.id))

        for frame in frames.values():
            frame.refresh_from_db()
        assert frames["first"].contents == frame_contents("frame-a", UNMASKED)

        run_command(exclude_team_ids=str(excluded_team.id))

        for frame in frames.values():
            frame.refresh_from_db()
        assert frames["first"].contents == frame_contents("frame-a", MASKED)
        assert frames["second"].contents == frame_contents("frame-a", MASKED)
        assert frames["clean"].contents == frame_contents("frame-b")
        assert frames["excluded"].contents == frame_contents("frame-a", UNMASKED)

    def test_masks_only_the_listed_teams(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        listed = self.frame(self.team, "frame-a", UNMASKED)
        unlisted = self.frame(other_team, "frame-a", UNMASKED)

        run_command(team_ids=str(self.team.id))

        listed.refresh_from_db()
        unlisted.refresh_from_db()
        assert listed.contents == frame_contents("frame-a", MASKED)
        assert unlisted.contents == frame_contents("frame-a", UNMASKED)

    def test_resume_cursor_applies_only_to_the_start_team(self) -> None:
        # The start team holds no frames, so the walk moves on to the next team, which the cursor must not skip.
        next_team = Team.objects.create(organization=self.organization, name="Next team")
        frame = self.frame(next_team, "frame-a", UNMASKED)

        run_command(start_at_team_id=self.team.id, start_after_raw_id="frame-z")

        frame.refresh_from_db()
        assert frame.contents == frame_contents("frame-a", MASKED)

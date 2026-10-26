from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from products.replay_vision.backend.media_small_copies import (
    backfill_small_copies,
    media_missing_small_copies,
    teams_missing_small_copies,
)


class Command(BaseCommand):
    help = "Add the small copy list views load to Replay Vision frames rendered before small copies existed"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, action="append", help="Only this team; repeat for more")
        parser.add_argument("--limit", type=int, help="At most this many frames per team")
        parser.add_argument(
            "--dry-run", action="store_true", help="Count the frames without a small copy, write nothing"
        )

    def handle(self, *args: Any, **options: Any) -> None:
        for team_id in options["team_id"] or teams_missing_small_copies():
            if options["dry_run"]:
                count = media_missing_small_copies(team_id, options["limit"]).count()
                self.stdout.write(f"Team {team_id}: {count} frames need a small copy.")
                continue
            result = backfill_small_copies(team_id, options["limit"])
            self.stdout.write(
                f"Team {team_id}: added {result.created} of {result.candidates} small copies, {result.failed} failed."
            )

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from products.replay_vision.backend.media_small_backfill import SmallCopyBackfill, teams_missing_small_copies


class Command(BaseCommand):
    help = "Add the small copy list views load to Replay Vision frames rendered before small copies existed"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, action="append", help="Only this team; repeat for more")
        parser.add_argument("--limit", type=int, help="At most this many frames per team")
        parser.add_argument(
            "--dry-run", action="store_true", help="Count the frames without a small copy, write nothing"
        )

    def handle(self, *args: Any, **options: Any) -> None:
        team_ids = options["team_id"] or teams_missing_small_copies()
        dry_run = bool(options["dry_run"])
        for team_id in team_ids:
            result = SmallCopyBackfill(team_id, limit=options["limit"]).run(dry_run=dry_run)
            if dry_run:
                self.stdout.write(f"Team {team_id}: {result.candidates} frames need a small copy.")
            else:
                self.stdout.write(
                    f"Team {team_id}: added {result.created} of {result.candidates} small copies, {result.failed} failed."
                )

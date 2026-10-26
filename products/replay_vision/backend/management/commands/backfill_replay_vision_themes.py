from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone

from products.replay_vision.backend.watch_rank_backfill import teams_with_observations
from products.replay_vision.backend.watch_themes import THEME_ACTIVE_WINDOW
from products.replay_vision.backend.watch_themes_backfill import backfill_team_themes


class Command(BaseCommand):
    help = "Group recent ranked Replay Vision observations into named search themes"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, action="append", help="Only this team; repeat for more")
        parser.add_argument("--days", type=int, default=THEME_ACTIVE_WINDOW.days, help="How far back to read, in days")
        parser.add_argument("--dry-run", action="store_true", help="Count what would be grouped, write nothing")

    def handle(self, *args: Any, **options: Any) -> None:
        since = timezone.now() - timedelta(days=options["days"])
        team_ids = options["team_id"] or teams_with_observations(since)
        for team_id in team_ids:
            try:
                result = backfill_team_themes(team_id, since, dry_run=bool(options["dry_run"]))
            except Exception as e:
                # One team without AI data processing, or a slow query, must not stop the rest.
                self.stderr.write(f"Team {team_id}: skipped ({e.__class__.__name__}: {e})")
                continue
            self.stdout.write(
                f"Team {team_id}: {result.observations} issue observations, "
                f"{result.assigned} grouped, {result.named} themes named."
            )

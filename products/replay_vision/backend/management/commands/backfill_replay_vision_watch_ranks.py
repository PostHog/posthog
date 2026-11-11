from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone

from products.replay_vision.backend.watch_rank_backfill import (
    WATCH_RANK_BACKFILL_DAYS,
    backfill_team_watch_ranks,
    teams_with_observations,
)


class Command(BaseCommand):
    help = "Rank recent Replay Vision observations for the highlight feed from the embeddings search already stored"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, action="append", help="Only this team; repeat for more")
        parser.add_argument("--days", type=int, default=WATCH_RANK_BACKFILL_DAYS, help="How far back to rank, in days")
        parser.add_argument("--dry-run", action="store_true", help="Count what would be ranked, write nothing")

    def handle(self, *args: Any, **options: Any) -> None:
        since = timezone.now() - timedelta(days=options["days"])
        team_ids = options["team_id"] or teams_with_observations(since)
        verb = "Would rank" if options["dry_run"] else "Ranked"
        for team_id in team_ids:
            try:
                result = backfill_team_watch_ranks(team_id, since, dry_run=bool(options["dry_run"]))
            except Exception as e:
                # One team without AI data processing, or a slow query, must not stop the rest.
                self.stderr.write(f"Team {team_id}: skipped ({e.__class__.__name__}: {e})")
                continue
            self.stdout.write(
                f"Team {team_id}: {verb} {result.ranked} of {result.observations} observations, "
                f"{result.without_embedding} had no stored embedding."
            )

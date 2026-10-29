from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone

from products.replay_vision.backend.cluster_membership import backfill_team_memberships
from products.replay_vision.backend.rank_days import backfill_team_rank_days
from products.replay_vision.backend.watch_rank import ANCHOR_VERSION
from products.replay_vision.backend.watch_rank_backfill import teams_with_observations
from products.replay_vision.backend.watch_semantics import SEMANTIC_RETENTION


class Command(BaseCommand):
    help = "Count each scanner's ranked rows per day, and copy feed group and search theme ids from each ranked observation's rank onto the row, with day counts"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, action="append", help="Only this team; repeat for more")
        parser.add_argument("--days", type=int, default=SEMANTIC_RETENTION.days, help="How far back to read, in days")
        parser.add_argument("--dry-run", action="store_true", help="Count the rows it would copy, write nothing")

    def handle(self, *args: Any, **options: Any) -> None:
        since = timezone.now() - timedelta(days=options["days"])
        dry_run = bool(options["dry_run"])
        for team_id in options["team_id"] or teams_with_observations(since):
            rank_days = backfill_team_rank_days(team_id, since, ANCHOR_VERSION, dry_run=dry_run)
            result = backfill_team_memberships(team_id, since, dry_run=dry_run)
            self.stdout.write(
                f"Team {team_id}: {rank_days.days} rank days, {result.observations} rows read, {result.recorded} recorded."
            )

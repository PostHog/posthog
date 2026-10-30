from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone

from products.replay_vision.backend.highlight_builds import build_highlight_feed
from products.replay_vision.backend.models.replay_highlight_feed import HighlightWindow
from products.replay_vision.backend.observation_ranks import copy_team_ranks
from products.replay_vision.backend.watch_rank import ANCHOR_VERSION
from products.replay_vision.backend.watch_rank_backfill import teams_with_observations


class Command(BaseCommand):
    help = "Copy Replay Vision observations' ranks into rank rows, then build each team's highlight feed from them"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, action="append", help="Only this team; repeat for more")
        parser.add_argument(
            "--days", type=int, default=max(HighlightWindow.values), help="How far back to copy, in days"
        )
        parser.add_argument("--dry-run", action="store_true", help="Count the ranks it would copy, write nothing")

    def handle(self, *args: Any, **options: Any) -> None:
        since = timezone.now() - timedelta(days=options["days"])
        dry_run = bool(options["dry_run"])
        for team_id in options["team_id"] or teams_with_observations(since):
            try:
                copied = copy_team_ranks(team_id, ANCHOR_VERSION, since, dry_run=dry_run)
                if not dry_run:
                    build_highlight_feed(team_id, ANCHOR_VERSION)
            except Exception as e:
                # One team's slow query must not stop the rest.
                self.stderr.write(f"Team {team_id}: skipped ({e.__class__.__name__}: {e})")
                continue
            self.stdout.write(f"Team {team_id}: {'would copy' if dry_run else 'copied'} {copied} ranks.")

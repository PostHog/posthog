"""Seed the activity summary queue state of the enrolled teams, in batches of teams.

Run it once before the tick reads the queue, and again after a large enrollment change. Without it,
the queue holds only the rows that the cursors read after their first tick.
"""

import json

from django.core.management.base import BaseCommand
from django.utils import timezone

from products.signals.backend.activity_summary.config import parse_config, read_config
from products.signals.backend.activity_summary.queue import FEED_LAG, enrolled_team_ids, move_cursors_to, seed_queue


class Command(BaseCommand):
    help = "Seed the activity summary queue state from the rows after each pair's watermark, then move the cursors."

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=50, help="Teams per batch.")
        parser.add_argument(
            "--config",
            type=json.loads,
            default=None,
            help="A flag payload as JSON, in place of the `activity-summary` flag, e.g. "
            '\'{"enabled": true, "enroll_all_approved": true}\'.',
        )

    def handle(self, *args, **options):
        config = parse_config(options["config"]) if options["config"] is not None else read_config()
        if not config.enabled:
            self.stdout.write("The config is not enabled, so no team is enrolled.")
            return
        batch_size = max(1, options["batch_size"])
        end = timezone.now() - FEED_LAG
        team_ids = enrolled_team_ids(config)
        pairs = 0
        for index in range(0, len(team_ids), batch_size):
            batch = team_ids[index : index + batch_size]
            pairs += seed_queue(config, batch, end)
            self.stdout.write(f"seeded {index + len(batch)}/{len(team_ids)} teams, {pairs} pairs")
        move_cursors_to(config, end)
        self.stdout.write(f"done: {len(team_ids)} teams, {pairs} pairs, cursors at {end.isoformat()}")

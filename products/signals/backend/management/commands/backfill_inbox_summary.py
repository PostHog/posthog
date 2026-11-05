from argparse import ArgumentParser
from typing import cast
from uuid import UUID

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from products.signals.backend.inbox_summary import INBOX_SUMMARY_PERIOD, generated_pull_requests
from products.signals.backend.tasks import refresh_pull_request_participants
from products.tasks.backend.facade import api as tasks_facade


class Command(BaseCommand):
    help = "Queue a bounded batch of missing inbox participant snapshots. Safe to rerun."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--after", type=UUID, help="Resume after this pull request UUID.")
        parser.add_argument(
            "--run-after", type=UUID, help="Resume verified URL normalization after this task run UUID."
        )
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args: object, **options: object) -> None:
        team_id = cast(int, options["team_id"])
        if not options["dry_run"]:
            next_run = tasks_facade.normalize_verified_pull_request_urls_batch(
                team_id=team_id, after=cast(UUID | None, options["run_after"])
            )
            if next_run is not None:
                self.stdout.write(f"Normalized verified pull request URLs. Resume with --run-after {next_run}")
                return
        rows = (
            generated_pull_requests(team_id)
            .filter(
                Q(merged_at__gte=timezone.now() - INBOX_SUMMARY_PERIOD) | Q(merged_at__isnull=True),
                state="merged",
            )
            .filter(Q(participants_synced_at__isnull=True) | Q(participant_logins__isnull=True))
            .order_by("id")
        )
        if options["after"]:
            rows = rows.filter(id__gt=options["after"])
        batch = list(rows[: max(1, min(cast(int, options["limit"]), 1000))])
        for pr in batch:
            if not options["dry_run"]:
                refresh_pull_request_participants.delay(team_id=team_id, repository=pr.repository, pr_number=pr.number)
        self.stdout.write(f"{'Would queue' if options['dry_run'] else 'Queued'} {len(batch)} pull requests")
        if batch:
            self.stdout.write(f"Resume with --after {batch[-1].id}")

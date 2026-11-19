from typing import Any

from django.core.management.base import BaseCommand

from products.messaging.backend.services.suppression import add_global_hard_bounces
from products.workflows.backend.facade.api import list_ses_bounce_suppressions


class Command(BaseCommand):
    help = (
        "Copy the bounce entries of the SES account-level suppression list to the global hard-bounce list. "
        "Run this before turning off SES suppression, so no known bad address loses its block. Idempotent."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Count the addresses without writing them")

    def handle(self, *args: Any, **options: Any) -> None:
        dry_run = options.get("dry_run", False)
        total = 0
        for page in list_ses_bounce_suppressions():
            total += len(page)
            if not dry_run:
                add_global_hard_bounces(page)
        prefix = "[DRY-RUN] Would import" if dry_run else "Imported"
        self.stdout.write(f"{prefix} {total} address(es) from the SES suppression list")

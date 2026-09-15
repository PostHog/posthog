from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from products.skills.backend.api.skill_services import DIGEST_BACKFILL_BATCH_SIZE, backfill_skill_digests


class Command(BaseCommand):
    help = "Stamp SHA-256 digests and byte sizes on skill rows written before digests existed."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DIGEST_BACKFILL_BATCH_SIZE,
            help="Rows written per batch (default: %(default)s).",
        )
        parser.add_argument(
            "--recompute",
            action="store_true",
            help="Re-stamp rows that already carry a digest.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        counts = backfill_skill_digests(batch_size=options["batch_size"], recompute=options["recompute"])
        self.stdout.write(f"skills={counts.skills} files={counts.files}")

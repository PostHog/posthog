import time
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from posthog.settings import EE_AVAILABLE

from products.event_definitions.backend.logic.definition_metadata import (
    copy_definition_metadata,
    next_enterprise_definition_ids,
)


class Command(BaseCommand):
    help = (
        "Copy the ee definition rows to the team-scoped metadata tables, in batches by id. "
        "It is safe to run again: a rerun changes only the rows that drifted, so its count is a parity check. "
        "--start-after resumes a stopped run."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--kind", choices=["event", "property"], required=True)
        parser.add_argument("--batch-size", type=int, default=200)
        parser.add_argument("--sleep-seconds", type=float, default=1.0, help="Pause between batches")
        parser.add_argument("--start-after", default=None, help="Resume after this definition id")
        parser.add_argument("--max-batches", type=int, default=None, help="Stop after this many batches")

    def handle(self, *args: Any, **options: Any) -> None:
        if not EE_AVAILABLE:
            raise CommandError("the ee definition tables exist only when ee is available")
        if options["batch_size"] < 1:
            raise CommandError("--batch-size must be at least 1")

        kind = options["kind"]
        after: str | None = options["start_after"]
        batches = changed = 0
        while options["max_batches"] is None or batches < options["max_batches"]:
            ids = next_enterprise_definition_ids(kind, after=after, limit=options["batch_size"])
            if not ids:
                break
            changed += copy_definition_metadata(kind, ids)
            batches += 1
            after = ids[-1]
            self.stdout.write(f"batch {batches}: {changed} rows changed, last id {after}")
            time.sleep(options["sleep_seconds"])

        self.stdout.write(f"done: {batches} batches, {changed} rows changed, last id {after}")

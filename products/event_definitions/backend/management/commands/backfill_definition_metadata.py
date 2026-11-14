import time
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from posthog.settings import EE_AVAILABLE
from posthog.temporal.common.db_errors import is_transient_db_error

from products.event_definitions.backend.logic.definition_metadata import (
    DefinitionKind,
    copy_definition_metadata,
    next_enterprise_definition_ids,
)

# A batch that fails with a transient error (a deadlock with an edit, a failover) runs again
MAX_BATCH_ATTEMPTS = 3


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
            changed += self._copy_batch(kind, ids, sleep_seconds=options["sleep_seconds"])
            batches += 1
            after = ids[-1]
            self.stdout.write(f"batch {batches}: {changed} rows changed, last id {after}")
            time.sleep(options["sleep_seconds"])

        self.stdout.write(f"done: {batches} batches, {changed} rows changed, last id {after}")

    def _copy_batch(self, kind: DefinitionKind, ids: list[str], *, sleep_seconds: float) -> int:
        for attempt in range(1, MAX_BATCH_ATTEMPTS + 1):
            try:
                return copy_definition_metadata(kind, ids)
            except Exception as error:
                if attempt == MAX_BATCH_ATTEMPTS or not is_transient_db_error(error):
                    raise
                self.stdout.write(f"batch after {ids[0]} failed ({error}), attempt {attempt} of {MAX_BATCH_ATTEMPTS}")
                # Django keeps a connection that a failover closed, so drop it and let the retry reconnect.
                # Closing it inside a transaction would break that transaction, as in tests.
                if not connection.in_atomic_block:
                    connection.close_if_unusable_or_obsolete()
                time.sleep(sleep_seconds)
        raise AssertionError("unreachable")

"""Fill `last_checked_at` on schemas whose last successful run predates the column.

Until a schema runs again, `system.source_schemas.last_checked_at` falls back to `last_synced_at`, which a
run that found no new rows leaves behind. Only `sync_type_config["last_full_run_at"]` records such a run, and
the system table cannot read that config without exposing it, so this copies the later of the two stamps in.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db.models import Case, DateTimeField, Value, When

from products.warehouse_sources.backend.facade.models import ExternalDataSchema

BATCH_SIZE = 1000


class Command(BaseCommand):
    help = (
        "Set last_checked_at from the legacy run stamps on schemas that have none. "
        "Previews by default; pass --live-run to write."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, default=None, help="Only fill schemas of this team.")
        parser.add_argument(
            "--live-run", action="store_true", help="Write the stamps. Without this the command only reports."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        schemas = ExternalDataSchema.objects.filter(deleted=False, last_checked_at__isnull=True).only(
            "id", "last_checked_at", "last_synced_at", "sync_type_config"
        )
        if options["team_id"] is not None:
            schemas = schemas.filter(team_id=options["team_id"])

        filled = 0
        batch: dict[Any, Any] = {}
        # Streamed, so memory stays flat across every schema of the installation.
        for schema in schemas.order_by("pk").iterator(chunk_size=BATCH_SIZE):
            stamp = schema.last_run_at
            if stamp is None:
                continue
            batch[schema.pk] = stamp
            if len(batch) >= BATCH_SIZE:
                filled += self._write(batch, live_run=options["live_run"])
                batch = {}
        if batch:
            filled += self._write(batch, live_run=options["live_run"])

        verb = "Filled" if options["live_run"] else "Would fill"
        self.stdout.write(f"{verb} last_checked_at on {filled} schema(s).")

    def _write(self, stamps: dict[Any, Any], *, live_run: bool) -> int:
        if not live_run:
            return len(stamps)
        # Re-checks the null, so a run that stamps the schema meanwhile keeps its newer value.
        return ExternalDataSchema.objects.filter(pk__in=stamps, last_checked_at__isnull=True).update(
            last_checked_at=Case(
                *(When(pk=pk, then=Value(stamp)) for pk, stamp in stamps.items()),
                output_field=DateTimeField(),
            )
        )

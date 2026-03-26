from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.clickhouse.client import sync_execute

DEFAULT_EVAL_SOURCE = "signals-grouping"

TABLES = [
    "sharded_events",
    "sharded_events_recent",
]

COUNT_SQL = """
SELECT count()
FROM {table}
WHERE event = '$ai_evaluation'
  AND JSONExtractString(properties, '$ai_eval_source') = %(eval_source)s
"""

DELETE_SQL = """
ALTER TABLE {table} DELETE
WHERE event = '$ai_evaluation'
  AND JSONExtractString(properties, '$ai_eval_source') = %(eval_source)s
"""


class Command(BaseCommand):
    help = "Delete eval pipeline data ($ai_evaluation events) from ClickHouse, filtered by $ai_eval_source tag. DEBUG only."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            type=str,
            default=DEFAULT_EVAL_SOURCE,
            help=f"Value of $ai_eval_source to filter on (default: {DEFAULT_EVAL_SOURCE})",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Skip confirmation prompt",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show counts without deleting",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command can only be run with DEBUG=True")

        eval_source = options["source"]
        params = {"eval_source": eval_source}

        total = 0
        for table in TABLES:
            rows = sync_execute(COUNT_SQL.format(table=table), params)
            count = rows[0][0] if rows else 0
            total += count
            self.stdout.write(f"  {table}: {count} events")

        if total == 0:
            self.stdout.write(self.style.SUCCESS(f"No eval events to delete (source={eval_source})."))
            return

        if options["dry_run"]:
            self.stdout.write(f"Dry run: {total} events would be deleted (source={eval_source}).")
            return

        if not options["yes"]:
            self.stdout.write(
                self.style.WARNING(f"This will DELETE {total} eval events (source={eval_source}) from ClickHouse.")
            )
            confirm = input("Type 'yes' to confirm: ")
            if confirm != "yes":
                self.stdout.write("Aborted.")
                return

        for table in TABLES:
            self.stdout.write(f"Deleting from {table}...")
            sync_execute(
                DELETE_SQL.format(table=table),
                params,
                settings={"mutations_sync": 1},
            )
            self.stdout.write("  done.")

        # Verify
        remaining = 0
        for table in TABLES:
            rows = sync_execute(COUNT_SQL.format(table=table), params)
            remaining += rows[0][0] if rows else 0

        if remaining == 0:
            self.stdout.write(self.style.SUCCESS(f"Deleted {total} eval events from {len(TABLES)} tables."))
        else:
            self.stdout.write(
                self.style.WARNING(f"Deleted but {remaining} events still remain (mutations may be pending).")
            )

from datetime import UTC, datetime

from django.core.management.base import BaseCommand

from products.warehouse_sources.backend.facade.contracts import SchemaReenableTarget
from products.warehouse_sources.backend.facade.staff import reenable_schemas_for_staff
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema


class Command(BaseCommand):
    help = "Re-enable schemas that were auto-disabled by a specific non-retryable error substring"

    def add_arguments(self, parser):
        parser.add_argument(
            "error",
            type=str,
            help="Error substring to match against latest_error (case-insensitive)",
        )
        parser.add_argument(
            "--live-run",
            action="store_true",
            help="Actually re-enable schemas. Without this flag the command only lists matches (dry-run).",
        )
        parser.add_argument(
            "--source-type",
            type=str,
            default=None,
            help="Optionally filter by source type (e.g. Postgres, MySQL)",
        )
        parser.add_argument(
            "--disabled-after",
            type=str,
            default=None,
            help="Only include schemas updated after this ISO8601 datetime (e.g. 2026-04-16T17:00:00Z)",
        )
        parser.add_argument(
            "--disabled-before",
            type=str,
            default=None,
            help="Only include schemas updated before this ISO8601 datetime (e.g. 2026-04-17T00:00:00Z)",
        )

    def handle(self, *args, **options):
        error_substring = options["error"]
        live_run = options["live_run"]
        source_type = options["source_type"]
        disabled_after = options["disabled_after"]
        disabled_before = options["disabled_before"]

        schemas = ExternalDataSchema.objects.select_related("source").filter(
            should_sync=False,
            deleted=False,
            latest_error__icontains=error_substring,
        )

        if source_type:
            schemas = schemas.filter(source__source_type=source_type)

        if disabled_after:
            dt = datetime.fromisoformat(disabled_after)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            schemas = schemas.filter(updated_at__gte=dt)

        if disabled_before:
            dt = datetime.fromisoformat(disabled_before)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            schemas = schemas.filter(updated_at__lte=dt)

        schema_list = list(schemas)

        if not schema_list:
            self.stdout.write(self.style.WARNING(f"No disabled schemas found matching error: {error_substring}"))
            return

        self.stdout.write(f"Found {len(schema_list)} disabled schema(s) matching '{error_substring}':\n")

        for schema in schema_list:
            self.stdout.write(
                f"  schema={schema.id} team={schema.team_id} source={schema.source_id} "
                f"name={schema.name} source_type={schema.source.source_type}"
            )

        if not live_run:
            self.stdout.write(
                self.style.WARNING(
                    f"\nDry run — {len(schema_list)} schema(s) would be re-enabled. Pass --live-run to execute."
                )
            )
            return

        result = reenable_schemas_for_staff(
            [
                SchemaReenableTarget(
                    schema_id=schema.id, team_id=schema.team_id, auto_disabled_at=schema.auto_disabled_at
                )
                for schema in schema_list
            ]
        )

        for schema_id in result.failed:
            self.stdout.write(self.style.ERROR(f"  failed: schema={schema_id}"))
        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Re-enabled: {len(result.reenabled)}, Failed: {len(result.failed)}, "
                f"Skipped (changed since listed): {len(result.skipped)}"
            )
        )

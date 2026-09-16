from typing import Any

from django.core.management.base import BaseCommand, CommandError

import structlog

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType, IncrementalField

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = (
        "Move schemas stuck on a full refresh onto the cursor their connector declares. "
        "The cursor is seeded from the rows already synced, so the next run reads only what "
        "changed rather than re-importing the whole table."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--source-type", type=str, required=True, help="Source type, for example Zendesk")
        parser.add_argument("--schema-name", type=str, required=True, help="Schema name, for example tickets")
        parser.add_argument("--team-id", type=int, default=None, help="Limit to one team")
        parser.add_argument(
            "--allow-reimport",
            action="store_true",
            help=(
                "Also switch schemas whose synced rows give no cursor value to start from. "
                "Those read their whole history once more before the cursor takes over."
            ),
        )
        parser.add_argument(
            "--live-run",
            action="store_true",
            help="Apply the change. Without this flag the command only lists what it would do.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        source_type = options["source_type"]
        schema_name = options["schema_name"]
        live_run = options["live_run"]
        allow_reimport = options["allow_reimport"]

        try:
            source = SourceRegistry.get_source(ExternalDataSourceType(source_type))
        except ValueError:
            raise CommandError(f"Unknown source type: {source_type}")

        # Discovery on any other source opens a connection to the customer's system, once per row.
        if not source.lists_tables_without_credentials:
            raise CommandError(
                f"{source_type} resolves its cursor over a live connection, so this command can't read it"
            )

        schemas = ExternalDataSchema.objects.select_related("source", "table").filter(
            deleted=False,
            should_sync=True,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
            name=schema_name,
            source__source_type=source_type,
            source__deleted=False,
        )
        if options["team_id"] is not None:
            schemas = schemas.filter(team_id=options["team_id"])

        schema_list = list(schemas)
        if not schema_list:
            self.stdout.write(self.style.WARNING(f"No full-refresh {source_type} {schema_name} schemas found"))
            return

        switched = 0
        skipped = 0
        for schema in schema_list:
            declared = self._declared_cursor(schema, schema_name)
            if declared is None:
                self.stdout.write(f"  skip schema={schema.id} team={schema.team_id}: connector declares no cursor")
                skipped += 1
                continue

            last_value = schema.table.get_max_value_for_column(declared["field"]) if schema.table else None
            if last_value is None and not allow_reimport:
                self.stdout.write(
                    f"  skip schema={schema.id} team={schema.team_id}: no value to start the cursor from, "
                    f"switching would re-read the whole history (pass --allow-reimport to accept that)"
                )
                skipped += 1
                continue

            self.stdout.write(
                f"  schema={schema.id} team={schema.team_id} cursor={declared['field']} starting at {last_value}"
            )
            if not live_run:
                continue

            schema.sync_type = ExternalDataSchema.SyncType.INCREMENTAL
            schema.sync_type_config["incremental_field"] = declared["field"]
            schema.sync_type_config["incremental_field_type"] = str(declared["field_type"])
            # Reads `incremental_field_type` back out of the config, so it has to be set first.
            schema.update_incremental_field_value(last_value, save=False)
            schema.save(update_fields=["sync_type", "sync_type_config"])
            switched += 1
            logger.info(
                "Switched schema to its declared cursor",
                schema_id=str(schema.id),
                team_id=schema.team_id,
                source_type=source_type,
                incremental_field=declared["field"],
            )

        if not live_run:
            self.stdout.write(
                self.style.WARNING(
                    f"\nDry run over {len(schema_list)} schema(s), {skipped} not eligible. Pass --live-run to apply."
                )
            )
            return

        self.stdout.write(self.style.SUCCESS(f"\nDone. Switched: {switched}, skipped: {skipped}"))

    def _declared_cursor(self, schema: ExternalDataSchema, schema_name: str) -> IncrementalField | None:
        source = SourceRegistry.get_source(ExternalDataSourceType(schema.source.source_type))
        config = source.parse_config(schema.source.job_inputs or {})
        source_schemas = source.get_schemas(config, schema.team_id, names=[schema_name])
        if not source_schemas:
            return None
        return source.declared_incremental_field_for_schema(source_schemas[0])

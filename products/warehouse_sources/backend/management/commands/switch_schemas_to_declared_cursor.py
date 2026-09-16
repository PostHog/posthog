from typing import Any

from django.core.management.base import BaseCommand, CommandError

import structlog

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.types import ExternalDataSourceType

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
        failed = 0
        for schema in schema_list:
            try:
                matched = self._matched_schema(schema, schema_name)
                declared = source.declared_incremental_field_for_schema(matched) if matched is not None else None
                if matched is None or declared is None:
                    self.stdout.write(f"  skip schema={schema.id} team={schema.team_id}: connector declares no cursor")
                    skipped += 1
                    continue

                # Which write mode the cursor feeds, as `build_default_sync_settings` picks it for a
                # new connection. A table the connector can only append to has no key to merge on,
                # so merging it raises `MissingPrimaryKeysException` on every run once the table
                # exists.
                if matched.supports_incremental:
                    sync_type = ExternalDataSchema.SyncType.INCREMENTAL
                elif matched.supports_append:
                    sync_type = ExternalDataSchema.SyncType.APPEND
                else:
                    self.stdout.write(
                        f"  skip schema={schema.id} team={schema.team_id}: connector declares a cursor for this "
                        f"table but supports neither incremental nor append"
                    )
                    skipped += 1
                    continue

                # The warehouse holds the column snake_cased, while the connector declares the
                # vendor's own spelling (`processedAt`). The config keeps the declared name, which
                # every data-side reader normalizes for itself.
                cursor_column = NamingConvention.normalize_identifier(declared["field"])
                last_value = schema.table.get_max_value_for_column(cursor_column) if schema.table else None
                if last_value is None and not allow_reimport:
                    self.stdout.write(
                        f"  skip schema={schema.id} team={schema.team_id}: no value to start the cursor from, "
                        f"switching would re-read the whole history (pass --allow-reimport to accept that)"
                    )
                    skipped += 1
                    continue

                self.stdout.write(
                    f"  schema={schema.id} team={schema.team_id} sync_type={sync_type} "
                    f"cursor={declared['field']} starting at {last_value}"
                )
                if not live_run:
                    continue

                schema.sync_type = sync_type
                schema.sync_type_config["incremental_field"] = declared["field"]
                schema.sync_type_config["incremental_field_type"] = str(declared["field_type"])
                if (
                    sync_type == ExternalDataSchema.SyncType.INCREMENTAL
                    and matched.default_incremental_lookback_seconds is not None
                    and schema.sync_type_config.get("incremental_field_lookback_seconds") is None
                ):
                    # These tables get their recent rows restated upstream, so without the
                    # connector's re-read window the cursor advances past a revision and no later
                    # run sees it. A value already on the schema is the operator's, so it wins.
                    schema.sync_type_config["incremental_field_lookback_seconds"] = (
                        matched.default_incremental_lookback_seconds
                    )
                # Reads `incremental_field_type` back out of the config, so it has to be set first.
                schema.update_incremental_field_value(last_value, save=False)
                schema.save(update_fields=["sync_type", "sync_type_config"])
                switched += 1
                logger.info(
                    "Switched schema to its declared cursor",
                    schema_id=str(schema.id),
                    team_id=schema.team_id,
                    source_type=source_type,
                    sync_type=str(sync_type),
                    incremental_field=declared["field"],
                )
            except Exception:
                # A row whose stored credentials no longer parse must not strand the schemas after
                # it: the selection has no order, so a re-run can stop at a different point again.
                failed += 1
                self.stdout.write(self.style.ERROR(f"  fail schema={schema.id} team={schema.team_id}"))
                logger.exception("Failed to switch schema", schema_id=str(schema.id), team_id=schema.team_id)

        if not live_run:
            self.stdout.write(
                self.style.WARNING(
                    f"\nDry run over {len(schema_list)} schema(s), {skipped} not eligible, {failed} failed. "
                    f"Pass --live-run to apply."
                )
            )
            return

        self.stdout.write(self.style.SUCCESS(f"\nDone. Switched: {switched}, skipped: {skipped}, failed: {failed}"))

    def _matched_schema(self, schema: ExternalDataSchema, schema_name: str) -> SourceSchema | None:
        source = SourceRegistry.get_source(ExternalDataSourceType(schema.source.source_type))
        config = source.parse_config(schema.source.job_inputs or {})
        # Cursors vary by vendor API version, so discovery reads the pin the sync runs on. A
        # schema-level override (user-managed) wins over the source pin, as the pipeline does.
        api_version = source.resolve_api_version(schema.api_version or schema.source.api_version)
        source_schemas = source.get_schemas(config, schema.team_id, names=[schema_name], api_version=api_version)
        return source_schemas[0] if source_schemas else None

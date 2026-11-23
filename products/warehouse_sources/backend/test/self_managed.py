from typing import Any
from uuid import UUID, uuid4

from products.access_control.backend.facade.api import replace_object_access_rules
from products.access_control.backend.facade.contracts import ObjectAccessRuleInput
from products.warehouse_sources.backend.facade.contracts import UploadReadSettings
from products.warehouse_sources.backend.file_upload_sources import create_source_for_upload, upload_schema_metadata
from products.warehouse_sources.backend.logic.source_inputs import SourceInputsStore
from products.warehouse_sources.backend.models.external_data_destination import (
    ExternalDataSourceDestination,
    get_or_create_warehouse_destination,
)
from products.warehouse_sources.backend.models.external_data_schema import (
    SCHEMA_PINNED_METADATA_KEY,
    SCHEMA_SELF_MANAGED_TABLE_METADATA_KEY,
    ExternalDataSchema,
    SelfManagedTableRef,
)
from products.warehouse_sources.backend.models.external_data_source import MIGRATION_MARKER_KEY, ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.self_managed_access import SOURCE_RESOURCE, TeamAccessRules
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.config import CsvOptions
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.csv_types import (
    csv_column_types_from_columns,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.discovery import (
    TableDefinition,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.globs import (
    glob_listing_prefix,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.self_managed import (
    needs_preserved_column_names,
    parse_self_managed_url,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.file_upload.source import UploadedFileFormat
from products.warehouse_sources.backend.types import ExternalDataSourceType

_UPLOAD_FORMATS: dict[str, UploadedFileFormat] = {"CSVWithNames": "csv", "JSONEachRow": "json", "Parquet": "parquet"}


def link_self_managed_table(table: DataWarehouseTable) -> ExternalDataSchema:
    # The rows the self-managed table migration wrote for a table: a source of its own with the access rules the
    # adoption check expects, and a turned-off schema that names the table. The table itself doesn't change.
    plan = TeamAccessRules(table.team_id).plan_for(str(table.id))
    if isinstance(plan, str):
        raise ValueError(f"the migration would have skipped this table: {plan}")
    hosted = table.hosted_upload
    if hosted is not None:
        file_format = _UPLOAD_FORMATS[table.format]
        source = create_source_for_upload(
            table, {"upload_id": "", "filename": "", "file_format": file_format, "schema_name": table.name}
        )
        columns = table.columns or {}
        read_settings = UploadReadSettings(columns=columns, allow_double_quotes=table.csv_allow_double_quotes)
        metadata = upload_schema_metadata(
            table.name, hosted.filename, file_format, read_settings, needs_preserved_column_names(columns)
        )
        marker: dict[str, Any] = {"group_key": f"upload/{table.pk}"}
    else:
        source, metadata, marker = _bucket_source(table)
    if plan.rules:
        replace_object_access_rules(
            team_id=table.team_id,
            resource=SOURCE_RESOURCE,
            resource_id=str(source.pk),
            rules=[
                ObjectAccessRuleInput(
                    access_level=rule.access_level,
                    organization_member_id=UUID(rule.organization_member_id) if rule.organization_member_id else None,
                    role_id=UUID(rule.role_id) if rule.role_id else None,
                )
                for rule in plan.rules
            ],
        )
    source.connection_metadata = {MIGRATION_MARKER_KEY: marker}
    source.save(update_fields=["connection_metadata"])
    ref = SelfManagedTableRef(table_id=str(table.id), url_pattern=table.url_pattern, format=table.format)
    return ExternalDataSchema.objects.create(
        name=table.name,
        team_id=table.team_id,
        source=source,
        should_sync=False,
        sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        sync_type_config={
            "schema_metadata": {
                **metadata,
                SCHEMA_PINNED_METADATA_KEY: True,
                SCHEMA_SELF_MANAGED_TABLE_METADATA_KEY: ref.to_metadata(),
            }
        },
    )


def _bucket_source(table: DataWarehouseTable) -> tuple[ExternalDataSource, dict[str, Any], dict[str, Any]]:
    location = parse_self_managed_url(table.url_pattern)
    credential = table.team_credential
    if location.service != "s3" or location.region is None or credential is None:
        raise ValueError("only a table with a credential and an S3 URL that names its region is supported")
    s3 = SourceRegistry.get_source(ExternalDataSourceType.AMAZONS3)
    inputs = s3.serialize_config(
        s3.parse_config(
            {
                "url_pattern": f"https://s3.{location.region}.amazonaws.com/{location.bucket}/",
                "access_key_id": credential.access_key,
                "secret_access_key": credential.access_secret,
                "file_format": "infer",
                "csv_allow_double_quotes": "true",
            }
        )
    )
    source = SourceInputsStore.create(
        source_id=str(uuid4()),
        connection_id=str(uuid4()),
        destination_id=str(uuid4()),
        team_id=table.team_id,
        status=ExternalDataSource.Status.RUNNING,
        source_type=s3.source_type,
        api_version=s3.default_version,
        inputs=inputs,
        description=f"Self-managed tables in {location.bucket}",
        access_method=ExternalDataSource.AccessMethod.WAREHOUSE,
    )
    ExternalDataSourceDestination.objects.for_team(table.team_id).create(
        team_id=table.team_id, source_id=source.pk, destination=get_or_create_warehouse_destination(table.team_id)
    )
    columns = table.columns or {}
    metadata = TableDefinition(
        name=table.name,
        kind="files",
        path=glob_listing_prefix(location.key),
        scope="glob",
        file_format="csv",
        csv=CsvOptions(
            allow_double_quotes=table.csv_allow_double_quotes is not False,
            column_types=csv_column_types_from_columns(columns),
            null_marker=True,
            delimiter=",",
        ),
        pattern=location.key,
        source_format="csv",
        preserve_column_names=needs_preserved_column_names(columns),
    ).schema_metadata()
    marker = {"group_key": location.group_key, "credential_id": str(credential.pk)}
    return source, metadata, marker

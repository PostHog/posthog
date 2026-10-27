"""Move self-managed warehouse tables into the object storage sources, without a copy.

A self-managed table is read in place from a customer bucket. Each one gets an object storage source
for its bucket and a turned-off schema that reads exactly the table's files. The schema does not link
to the table: it names the table in its pinned `schema_metadata` (see `SelfManagedTableRef`), and the
table stays as it is, read from the customer bucket and not billed. When the user turns syncing on,
the first sync is a normal billable sync, and its last step points the existing table row at the copy
in PostHog storage (see `find_replaced_self_managed_table` and `DataWarehouseTable.adopt_into_source`),
so the row id and the name stay and existing queries keep working.

A table made from an uploaded file is read in place from PostHog's own bucket. It gets a file upload
source of its own, with a turned-off schema that names it the same way. That source syncs only when a
file is uploaded, and it reads no file until then, so the table keeps reading its current file, in either
upload folder, and nothing is copied. The next upload for the table points the source at the new file
and starts a normal billable sync, which adopts the table. The old file is deleted after that sync,
when nothing else reads it (see `file_upload_sources.replace_file_upload`).

The state of each table comes from the rows themselves: a migration source carries a marker in its
`connection_metadata`, and its schemas name their tables. Running the migration again therefore
continues where it stopped.
"""

import re
import uuid
import dataclasses
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from enum import StrEnum
from typing import Any, Literal, cast

from django.conf import settings
from django.db import transaction
from django.db.models import CharField, Q, Value
from django.db.models.functions import Cast, Concat

import boto3
import structlog
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from posthog.dataclasses import frozen
from posthog.models.team import Team

from products.access_control.backend.facade.api import object_ids_with_rules, resource_has_rules
from products.data_warehouse.backend.facade.api import delete_external_data_schedule
from products.warehouse_sources.backend.facade.contracts import UploadReadSettings
from products.warehouse_sources.backend.file_upload_sources import (
    create_source_for_upload,
    file_upload_source,
    pending_upload_job_inputs,
    upload_schema_metadata,
)
from products.warehouse_sources.backend.file_uploads import (
    FILE_UPLOADS_FOLDER,
    LEGACY_UPLOADS_FOLDER,
    TABLE_FORMAT_TO_FILE_FORMAT,
    HostedUpload,
)
from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.external_data_destination import (
    ExternalDataSourceDestination,
    get_or_create_warehouse_destination,
)
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import (
    SCHEMA_PINNED_METADATA_KEY,
    SCHEMA_SELF_MANAGED_TABLE_METADATA_KEY,
    ExternalDataSchema,
    SelfManagedTableRef,
    self_managed_table_ref,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.presentation.views.external_data_source.helpers import (
    source_feature_flag_missing,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.csv_types import (
    UnsupportedCsvColumnError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.self_managed import (
    SelfManagedCredential,
    SelfManagedLocation,
    StorageService,
    UnmappableTableError,
    needs_preserved_column_names,
    parse_self_managed_url,
    refuse_columns_an_import_changes,
    table_definition_for,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.settings import (
    CONNECT_TIMEOUT_SECONDS,
    MAX_REQUEST_ATTEMPTS,
    READ_TIMEOUT_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.source_base import (
    ObjectStorageSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.file_upload.source import (
    FileUploadSource,
    UploadedFileFormat,
    read_format,
)
from products.warehouse_sources.backend.types import ExternalDataJobStatus, ExternalDataSourceType

logger = structlog.get_logger(__name__)

# The `connection_metadata` key of a source the migration created.
MIGRATION_MARKER_KEY = "self_managed_migration"
DEFAULT_ABANDON_REASON = "Left self-managed by an operator."
_DELETED_REASON = "its migration schema or source was deleted"

# Resolves the region of an S3 bucket whose URL names none, or returns None when it can't.
BucketRegionResolver = Callable[[str, SelfManagedCredential], str | None]


class TableMigrationState(StrEnum):
    # Not linked to a source yet.
    PENDING = "pending"
    # Has a migration schema, and the table still reads its own bucket until a sync replaces it.
    AWAITING_SYNC = "awaiting_sync"
    MIGRATED = "migrated"
    ABANDONED = "abandoned"
    SKIPPED = "skipped"


MigrationAction = Literal["none", "would_link", "linked", "link_failed", "limit_reached"]
AbandonAction = Literal["would_abandon", "abandoned", "refused"]


@frozen
class TableMigrationStatus:
    table_id: str
    team_id: int
    name: str
    state: TableMigrationState
    reason: str | None = None
    source_id: str | None = None
    schema_id: str | None = None


@frozen
class TableMigrationOutcome:
    status: TableMigrationStatus
    action: MigrationAction = "none"
    error: str | None = None


@frozen
class AbandonOutcome:
    table_id: str
    action: AbandonAction
    reason: str | None = None


@frozen
class MigrationOptions:
    team_id: int | None = None
    table_ids: tuple[str, ...] = ()
    live_run: bool = False
    # How many tables one run may link. None links every one it can.
    limit: int | None = None


@frozen
class _TablePlan:
    """How one self-managed table maps onto an import source."""

    source: ObjectStorageSource[Any] | FileUploadSource
    schema_metadata: dict[str, Any]
    job_inputs: dict[str, Any] = dataclasses.field(repr=False)
    # Tables with the same group key and credential share one source.
    group_key: str
    description: str
    # An uploaded table has no credential, and gets a source of its own.
    shares_source: bool = True
    # The bucket a shared source reads, which names its table prefix when one is needed.
    bucket: str = ""


@frozen
class _Evaluation:
    table: DataWarehouseTable
    status: TableMigrationStatus
    plan: _TablePlan | None = None
    # The live migration schema of the table.
    schema: ExternalDataSchema | None = None
    job: ExternalDataJob | None = None


def resolve_s3_bucket_region(bucket: str, credential: SelfManagedCredential) -> str | None:
    """Ask S3 for the bucket's region with the table's own key.

    S3 names the region in the `x-amz-bucket-region` header of a HEAD request, also when it
    answers with a redirect or a 403, so a key that may only read objects still finds it.
    """
    if not credential.access_key.strip() or not credential.access_secret.strip():
        return None
    client = boto3.client(
        "s3",
        region_name="us-east-1",
        aws_access_key_id=credential.access_key.strip(),
        aws_secret_access_key=credential.access_secret.strip(),
        config=BotoConfig(
            connect_timeout=CONNECT_TIMEOUT_SECONDS,
            read_timeout=READ_TIMEOUT_SECONDS,
            retries={"max_attempts": MAX_REQUEST_ATTEMPTS, "mode": "standard"},
        ),
    )
    response: Mapping[str, Any]
    try:
        response = client.head_bucket(Bucket=bucket)
    except ClientError as e:
        response = e.response
    except BotoCoreError:
        return None
    headers = response.get("ResponseMetadata", {}).get("HTTPHeaders", {})
    region = headers.get("x-amz-bucket-region")
    return region if isinstance(region, str) and region else None


def _object_storage_sources() -> dict[StorageService, ObjectStorageSource[Any]]:
    return {
        source.self_managed_service: source
        for source in SourceRegistry.get_all_sources().values()
        if isinstance(source, ObjectStorageSource)
    }


def _credential_of(table: DataWarehouseTable) -> SelfManagedCredential | None:
    credential = table.credential
    if credential is None:
        return None
    return SelfManagedCredential(access_key=credential.access_key or "", access_secret=credential.access_secret or "")


class _Planner:
    """Maps tables onto sources, caching the per-team flag check and the per-bucket region lookup."""

    def __init__(self, resolve_region: BucketRegionResolver) -> None:
        self._resolve_region = resolve_region
        self._sources = _object_storage_sources()
        self._upload_source = file_upload_source()
        self._flag_missing: dict[tuple[int, str], bool] = {}
        self._regions: dict[tuple[str, str], str | None] = {}
        self._tables_with_rules: dict[int, set[str]] = {}
        self._teams_with_source_rules: dict[int, bool] = {}

    def plan(self, table: DataWarehouseTable) -> _TablePlan | str:
        """The plan for a table, or the reason the table can't be migrated."""
        credential = _credential_of(table)
        hosted = table.hosted_upload if credential is None else None
        if credential is None and hosted is None:
            return "the table has no credential"
        if self._has_access_rules(table):
            # The new source would get default access, and a member the table's rules shut out
            # could read the same files through a schema of that source.
            return "the table has its own access rules, which the source PostHog would create can't carry"
        if self._has_source_rules(table):
            # A table in a source falls back to the rules for sources, which never reached a
            # self-managed table, so moving it could take access away from members who have it.
            # Rules for the whole warehouse don't reach the new source, so a member they shut out
            # could read the table's files through it.
            return "the project has access rules for sources or for the warehouse, which the move would change"
        if hosted is not None:
            return self._plan_upload(table, hosted)
        assert credential is not None
        try:
            location = parse_self_managed_url(table.url_pattern)
            source = self._sources.get(location.service)
            if source is None:
                return f"no import source reads '{location.service}' storage"
            if self._team_lacks_flag(table.team, source):
                return f"the team doesn't have the '{source.requires_team_feature_flag}' feature flag"
            if location.service == "s3" and location.region is None:
                region = self._region(table, location, credential)
                if region is None:
                    return "the URL doesn't name the bucket's region, and S3 didn't return it"
                location = dataclasses.replace(location, region=region)
            definition = table_definition_for(
                table.name, location, table.format, table.columns, table.csv_allow_double_quotes
            )
            job_inputs = source.job_inputs_for_self_managed(location, credential)
        except UnmappableTableError as e:
            return str(e)
        return _TablePlan(
            source=source,
            schema_metadata=definition.schema_metadata(),
            job_inputs=job_inputs,
            group_key=location.group_key,
            description=f"Self-managed tables in {location.bucket}",
            bucket=location.bucket,
        )

    def _plan_upload(self, table: DataWarehouseTable, hosted: HostedUpload) -> _TablePlan | str:
        """A table that reads a file the team uploaded gets a file upload source of its own."""
        source = self._upload_source
        if self._team_lacks_flag(table.team, source):
            return f"the team doesn't have the '{source.requires_team_feature_flag}' feature flag"
        file_format = TABLE_FORMAT_TO_FILE_FORMAT.get(table.format)
        if file_format is None:
            return f"an uploaded '{table.format}' file has no import equivalent"
        upload_format = cast(UploadedFileFormat, file_format)
        columns = table.columns or {}
        read_settings = UploadReadSettings(columns=columns, allow_double_quotes=table.csv_allow_double_quotes)
        try:
            # Adopting the table must keep the columns its queries read: their names, and their types.
            refuse_columns_an_import_changes(columns, read_format(upload_format))
            schema_metadata = upload_schema_metadata(
                table.name,
                hosted.filename,
                upload_format,
                read_settings,
                needs_preserved_column_names(columns.keys()),
            )
        except (UnmappableTableError, UnsupportedCsvColumnError) as e:
            return str(e)
        return _TablePlan(
            source=source,
            schema_metadata=schema_metadata,
            job_inputs=pending_upload_job_inputs(upload_format, table.name),
            group_key=f"upload/{table.pk}",
            description=f"Uploaded file for {table.name}"[:400],
            shares_source=False,
        )

    def _has_access_rules(self, table: DataWarehouseTable) -> bool:
        if table.team_id not in self._tables_with_rules:
            self._tables_with_rules[table.team_id] = object_ids_with_rules(
                team_id=table.team_id, resource="warehouse_table"
            )
        return str(table.id) in self._tables_with_rules[table.team_id]

    def _has_source_rules(self, table: DataWarehouseTable) -> bool:
        if table.team_id not in self._teams_with_source_rules:
            self._teams_with_source_rules[table.team_id] = resource_has_rules(
                team_id=table.team_id, resource="external_data_source"
            ) or resource_has_rules(team_id=table.team_id, resource="warehouse_objects")
        return self._teams_with_source_rules[table.team_id]

    def _team_lacks_flag(self, team: Team, source: ObjectStorageSource[Any] | FileUploadSource) -> bool:
        key = (team.pk, str(source.source_type))
        if key not in self._flag_missing:
            self._flag_missing[key] = source_feature_flag_missing(source, team)
        return self._flag_missing[key]

    def _region(
        self, table: DataWarehouseTable, location: SelfManagedLocation, credential: SelfManagedCredential
    ) -> str | None:
        key = (str(table.credential_id), location.bucket)
        if key not in self._regions:
            try:
                self._regions[key] = self._resolve_region(location.bucket, credential)
            except Exception:
                logger.warning("Could not resolve the S3 bucket region", table_id=str(table.id), exc_info=True)
                self._regions[key] = None
        return self._regions[key]


def _migration_schemas(team_id: int | None, table_ids: Iterable[str]) -> dict[str, list[ExternalDataSchema]]:
    """Every schema, deleted or not, that the migration made for a table, by table id, oldest first."""
    queryset = (
        ExternalDataSchema.objects.filter(
            source__connection_metadata__has_key=MIGRATION_MARKER_KEY,
            sync_type_config__schema_metadata__has_key=SCHEMA_SELF_MANAGED_TABLE_METADATA_KEY,
        )
        .select_related("source")
        .order_by("created_at", "id")
    )
    if team_id is not None:
        queryset = queryset.filter(team_id=team_id)
    ids = list(table_ids)
    if ids:
        queryset = queryset.filter(sync_type_config__schema_metadata__self_managed_table__table_id__in=ids)
    by_table: dict[str, list[ExternalDataSchema]] = defaultdict(list)
    for schema in queryset:
        ref = self_managed_table_ref(schema)
        if ref is not None:
            by_table[ref.table_id].append(schema)
    return by_table


def _is_live(schema: ExternalDataSchema) -> bool:
    return not schema.deleted and not schema.source.deleted


def _uploaded_table_filter() -> Q:
    """Credential-less tables that read a file in PostHog's bucket, in either upload folder.

    Narrowed to the table's own team folder of each upload folder, so tables PostHog writes to the
    bucket itself (materialized views) stay out. `DataWarehouseTable.hosted_upload` then checks the
    exact key.
    """
    domain = settings.DATAWAREHOUSE_BUCKET_DOMAIN
    if not domain or not settings.DATAWAREHOUSE_BUCKET:
        return Q(pk__in=[])

    def team_folder(folder: str) -> Concat:
        return Concat(
            Value(f"https://{domain}/{folder}/team_"),
            Cast("team_id", CharField()),
            Value("/"),
            output_field=CharField(),
        )

    in_upload_folder = Q(url_pattern__startswith=team_folder(FILE_UPLOADS_FOLDER)) | Q(
        url_pattern__startswith=team_folder(LEGACY_UPLOADS_FOLDER)
    )
    return Q(external_data_source__isnull=True, credential__isnull=True) & in_upload_folder


def _select_tables(
    team_id: int | None, table_ids: Iterable[str], migration_schemas: Mapping[str, list[ExternalDataSchema]]
) -> list[DataWarehouseTable]:
    """Self-managed tables, plus every table the migration made a schema for, oldest first.

    A table that another source's schema already links to is left out: a table made from an upload
    while the team had the flag waits for the first sync of its own file upload source.
    """
    queryset = (
        DataWarehouseTable.raw_objects.exclude(deleted=True)
        .filter(
            Q(external_data_source__isnull=True, credential__isnull=False)
            | _uploaded_table_filter()
            | Q(id__in=list(migration_schemas))
        )
        .select_related("credential", "team")
        .order_by("created_at", "id")
    )
    if team_id is not None:
        queryset = queryset.filter(team_id=team_id)
    ids = list(table_ids)
    if ids:
        queryset = queryset.filter(id__in=ids)
    tables = list(queryset)
    imported_elsewhere = set(
        ExternalDataSchema.objects.filter(
            table_id__in=[table.id for table in tables if table.external_data_source_id is None], deleted=False
        )
        .exclude(source__deleted=True)
        .exclude(source__connection_metadata__has_key=MIGRATION_MARKER_KEY)
        .values_list("table_id", flat=True)
    )
    return [table for table in tables if table.id not in imported_elsewhere]


def _latest_jobs(schemas: Iterable[ExternalDataSchema]) -> dict[str, ExternalDataJob]:
    schema_ids = [schema.id for schema in schemas]
    if not schema_ids:
        return {}
    jobs = ExternalDataJob.objects.filter(schema_id__in=schema_ids).order_by("schema_id", "-created_at")
    latest: dict[str, ExternalDataJob] = {}
    for job in jobs:
        latest.setdefault(str(job.schema_id), job)
    return latest


def _idle_reason(schema: ExternalDataSchema) -> str:
    if schema.should_sync:
        return "syncing is on; waiting for the first sync"
    if SourceRegistry.get_source(ExternalDataSourceType(schema.source.source_type)).syncs_on_demand:
        return "waiting for the next upload of the file"
    return "syncing is off"


def _awaiting_reason(table: DataWarehouseTable, schema: ExternalDataSchema, job: ExternalDataJob | None) -> str:
    ref = self_managed_table_ref(schema)
    if schema.table_id is not None:
        return "the table changed after the migration, so its schema syncs a separate table"
    if ref is None or (table.url_pattern, table.format) != (ref.url_pattern, ref.format):
        return "the table changed after the migration, so a sync makes a separate table"
    if job is None:
        return _idle_reason(schema)
    if job.status == ExternalDataJobStatus.RUNNING:
        return "the first sync is running"
    detail = job.latest_error or f"the last sync ended with status {job.status}"
    return f"{detail}; the table still reads its own bucket"


def _evaluate(
    table: DataWarehouseTable,
    schemas: list[ExternalDataSchema],
    jobs: Mapping[str, ExternalDataJob],
    planner: _Planner,
) -> _Evaluation:
    live = next((schema for schema in schemas if _is_live(schema)), None)
    job = jobs.get(str(live.id)) if live is not None else None

    def status(state: TableMigrationState, reason: str | None = None) -> TableMigrationStatus:
        named = live or (schemas[-1] if schemas else None)
        return TableMigrationStatus(
            table_id=str(table.id),
            team_id=table.team_id,
            name=table.name,
            state=state,
            reason=reason,
            source_id=str(named.source_id) if named is not None else None,
            schema_id=str(named.id) if named is not None else None,
        )

    if table.external_data_source_id is not None:
        return _Evaluation(table=table, status=status(TableMigrationState.MIGRATED), schema=live, job=job)
    if live is not None:
        reason = _awaiting_reason(table, live, job)
        return _Evaluation(table=table, status=status(TableMigrationState.AWAITING_SYNC, reason), schema=live, job=job)
    if schemas:
        refs = [ref for ref in (self_managed_table_ref(schema) for schema in schemas) if ref is not None]
        reason = next((ref.abandon_reason for ref in reversed(refs) if ref.abandon_reason), _DELETED_REASON)
        return _Evaluation(table=table, status=status(TableMigrationState.ABANDONED, reason))

    planned = planner.plan(table)
    if isinstance(planned, _TablePlan):
        return _Evaluation(table=table, status=status(TableMigrationState.PENDING, "not linked yet"), plan=planned)
    return _Evaluation(table=table, status=status(TableMigrationState.SKIPPED, planned))


def evaluate_tables(
    team_id: int | None = None,
    table_ids: Iterable[str] = (),
    resolve_region: BucketRegionResolver = resolve_s3_bucket_region,
) -> list[TableMigrationStatus]:
    return [evaluation.status for evaluation in _evaluate_all(team_id, table_ids, _Planner(resolve_region))]


def _evaluate_all(team_id: int | None, table_ids: Iterable[str], planner: _Planner) -> list[_Evaluation]:
    ids = list(table_ids)
    schemas = _migration_schemas(team_id, ids)
    tables = _select_tables(team_id, ids, schemas)
    jobs = _latest_jobs(schema for table_schemas in schemas.values() for schema in table_schemas if _is_live(schema))
    return [_evaluate(table, schemas.get(str(table.id), []), jobs, planner) for table in tables]


def _free_prefix(team_id: int, plan: _TablePlan) -> str | None:
    """A table prefix no other source of the type uses, so the new source's table names can't clash.

    Like a source a user creates, the first source of a type needs none.
    """
    sources = ExternalDataSource.objects.filter(team_id=team_id, source_type=plan.source.source_type).exclude(
        deleted=True
    )
    taken = {(prefix or "").strip() for prefix in sources.values_list("prefix", flat=True)}
    if "" not in taken:
        return None
    base = re.sub(r"[^A-Za-z0-9_]", "_", plan.bucket).strip("_").lower() or "bucket"
    if not base[0].isalpha():
        base = f"bucket_{base}"
    candidate, suffix = base, 2
    while candidate in taken or ExternalDataSource.is_system_managed_prefix(candidate):
        candidate, suffix = f"{base}_{suffix}", suffix + 1
    return candidate


def _find_or_create_source(table: DataWarehouseTable, plan: _TablePlan) -> ExternalDataSource:
    """The group's source for the table's team, credential and bucket. Runs under the group lock."""
    if not plan.shares_source:
        return create_source_for_upload(
            table, plan.job_inputs, connection_metadata={MIGRATION_MARKER_KEY: {"group_key": plan.group_key}}
        )
    existing = (
        ExternalDataSource.objects.filter(
            team_id=table.team_id,
            source_type=plan.source.source_type,
            connection_metadata__self_managed_migration__group_key=plan.group_key,
            connection_metadata__self_managed_migration__credential_id=str(table.credential_id),
        )
        .exclude(deleted=True)
        .order_by("created_at")
        .first()
    )
    if existing is not None:
        return existing
    source = ExternalDataSource.objects.create(
        prefix=_free_prefix(table.team_id, plan),
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        destination_id=str(uuid.uuid4()),
        team_id=table.team_id,
        status=ExternalDataSource.Status.RUNNING,
        source_type=plan.source.source_type,
        api_version=plan.source.default_version,
        job_inputs=plan.job_inputs,
        description=plan.description,
        access_method=ExternalDataSource.AccessMethod.WAREHOUSE,
        connection_metadata={
            MIGRATION_MARKER_KEY: {
                "group_key": plan.group_key,
                "credential_id": str(table.credential_id),
            }
        },
    )
    ExternalDataSourceDestination.objects.for_team(table.team_id).create(
        team_id=table.team_id, source_id=source.pk, destination=get_or_create_warehouse_destination(table.team_id)
    )
    return source


def _credential_id(table: DataWarehouseTable) -> uuid.UUID:
    if table.credential_id is None:
        raise ValueError(f"Table {table.id} has no credential to migrate with")
    return table.credential_id


def _ensure_schema(table: DataWarehouseTable, plan: _TablePlan) -> ExternalDataSchema:
    """The table's migration schema, created with its source when there is none yet.

    The credential row is the group lock: every table of one source shares it, and nothing else
    locks it, so two runs can't create two sources or two schemas for the same table. An uploaded
    table has no credential and a source of its own, so its own row is the lock.
    """
    with transaction.atomic():
        if plan.shares_source:
            DataWarehouseCredential.objects.select_for_update().get(team_id=table.team_id, pk=_credential_id(table))
        else:
            DataWarehouseTable.raw_objects.select_for_update().get(team_id=table.team_id, pk=table.pk)
        schemas = _migration_schemas(table.team_id, [str(table.id)]).get(str(table.id), [])
        live = next((schema for schema in schemas if _is_live(schema)), None)
        if live is not None:
            return live
        if schemas:
            raise UnmappableTableError("the table's migration was abandoned")
        source = _find_or_create_source(table, plan)
        if (
            ExternalDataSchema.objects.filter(team_id=table.team_id, source_id=source.pk, name=table.name)
            .exclude(deleted=True)
            .exists()
        ):
            raise UnmappableTableError(f"another table in this bucket already uses the name '{table.name}'")
        ref = SelfManagedTableRef(table_id=str(table.id), url_pattern=table.url_pattern, format=table.format)
        return ExternalDataSchema.objects.create(
            name=table.name,
            team_id=table.team_id,
            source=source,
            should_sync=False,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
            sync_type_config={
                "schema_metadata": {
                    **plan.schema_metadata,
                    SCHEMA_PINNED_METADATA_KEY: True,
                    SCHEMA_SELF_MANAGED_TABLE_METADATA_KEY: ref.to_metadata(),
                }
            },
        )


def migrate_self_managed_tables(
    options: MigrationOptions, resolve_region: BucketRegionResolver = resolve_s3_bucket_region
) -> list[TableMigrationOutcome]:
    """Plan, and on a live run create, the source and the turned-off schema of every selected table.

    Nothing syncs and no table changes. A dry run reads the same rows and reports the same
    decisions, but writes nothing.
    """
    planner = _Planner(resolve_region)
    outcomes: list[TableMigrationOutcome] = []
    linked = 0
    for evaluation in _evaluate_all(options.team_id, options.table_ids, planner):
        if evaluation.plan is None or evaluation.status.state != TableMigrationState.PENDING:
            outcomes.append(TableMigrationOutcome(status=evaluation.status))
            continue
        if options.limit is not None and linked >= options.limit:
            outcomes.append(TableMigrationOutcome(status=evaluation.status, action="limit_reached"))
            continue
        linked += 1
        if not options.live_run:
            outcomes.append(TableMigrationOutcome(status=evaluation.status, action="would_link"))
            continue
        outcomes.append(_link(evaluation.table, evaluation.plan, evaluation.status))
    return outcomes


def _link(table: DataWarehouseTable, plan: _TablePlan, status: TableMigrationStatus) -> TableMigrationOutcome:
    try:
        schema = _ensure_schema(table, plan)
    except UnmappableTableError as e:
        return TableMigrationOutcome(status=status, action="link_failed", error=str(e))
    except Exception as e:
        # A database error on one table must not stop the batch or hide its outcomes.
        logger.warning("Could not link a self-managed table", table_id=str(table.id), exc_info=True)
        return TableMigrationOutcome(status=status, action="link_failed", error=f"{type(e).__name__}: {e}")
    logger.info(
        "Linked a self-managed table to an object storage source",
        table_id=str(table.id),
        team_id=table.team_id,
        schema_id=str(schema.id),
    )
    return TableMigrationOutcome(
        status=dataclasses.replace(
            status,
            state=TableMigrationState.AWAITING_SYNC,
            reason=_idle_reason(schema),
            schema_id=str(schema.id),
            source_id=str(schema.source_id),
        ),
        action="linked",
    )


def _abandon_refusal(evaluation: _Evaluation) -> str | None:
    state = evaluation.status.state
    if state == TableMigrationState.MIGRATED:
        return "the table is already migrated"
    if state == TableMigrationState.ABANDONED:
        return "the table's migration is already abandoned"
    if state == TableMigrationState.SKIPPED:
        return f"the table can't be migrated, so there is nothing to abandon ({evaluation.status.reason})"
    schema = evaluation.schema
    if schema is None:
        return None
    if schema.table_id is not None:
        return "the table's schema syncs a separate table"
    if schema.should_sync:
        return "the user turned syncing on for the table's schema"
    if evaluation.job is not None and evaluation.job.status == ExternalDataJobStatus.RUNNING:
        return "the table's first sync is running"
    return None


def abandon_tables(
    table_ids: Iterable[str],
    reason: str = DEFAULT_ABANDON_REASON,
    team_id: int | None = None,
    live_run: bool = False,
    resolve_region: BucketRegionResolver = resolve_s3_bucket_region,
) -> list[AbandonOutcome]:
    """Leave tables self-managed for good, and remove the schema the migration made for them.

    The schema stays as a deleted row that names the table and the reason, so later runs leave the
    table alone. A table with no schema yet gets one first, for that record. A table's source goes
    too when the table was the last one it held. The table itself never changes.
    """
    ids = list(table_ids)
    evaluations = {
        evaluation.status.table_id: evaluation for evaluation in _evaluate_all(team_id, ids, _Planner(resolve_region))
    }
    outcomes: list[AbandonOutcome] = []
    for table_id in ids:
        evaluation = evaluations.get(table_id)
        if evaluation is None:
            outcomes.append(AbandonOutcome(table_id=table_id, action="refused", reason="no such self-managed table"))
            continue
        refusal = _abandon_refusal(evaluation)
        if refusal is not None:
            outcomes.append(AbandonOutcome(table_id=table_id, action="refused", reason=refusal))
        elif not live_run:
            outcomes.append(AbandonOutcome(table_id=table_id, action="would_abandon"))
        else:
            try:
                _abandon(evaluation, reason)
            except UnmappableTableError as e:
                outcomes.append(AbandonOutcome(table_id=table_id, action="refused", reason=str(e)))
                continue
            outcomes.append(AbandonOutcome(table_id=table_id, action="abandoned", reason=reason))
    return outcomes


def _abandon(evaluation: _Evaluation, reason: str) -> None:
    table = evaluation.table
    removed_source_id: str | None = None
    with transaction.atomic():
        if evaluation.schema is not None:
            schema = evaluation.schema
        else:
            assert evaluation.plan is not None
            schema = _ensure_schema(table, evaluation.plan)
        ref = self_managed_table_ref(schema)
        assert ref is not None
        metadata = (schema.sync_type_config or {})["schema_metadata"]
        metadata[SCHEMA_SELF_MANAGED_TABLE_METADATA_KEY] = dataclasses.replace(ref, abandon_reason=reason).to_metadata()
        schema.save(update_fields=["sync_type_config", "updated_at"])
        schema.soft_delete()
        source = schema.source
        if (
            not ExternalDataSchema.objects.filter(team_id=table.team_id, source_id=source.pk)
            .exclude(deleted=True)
            .exists()
        ):
            source.soft_delete()
            removed_source_id = str(source.pk)
    if evaluation.schema is not None:
        # A schedule exists only when the user turned syncing on before, so it is paused now.
        try:
            delete_external_data_schedule(str(schema.id))
        except Exception:
            # The schema is deleted, so its schedule can't start a sync.
            logger.warning(
                "Could not delete the schedule of an abandoned migration schema",
                table_id=str(table.id),
                schema_id=str(schema.id),
                exc_info=True,
            )
    logger.info(
        "Abandoned a self-managed table migration",
        table_id=str(table.id),
        team_id=table.team_id,
        removed_source_id=removed_source_id,
    )


def describe_status(status: TableMigrationStatus) -> str:
    reason = f" ({status.reason})" if status.reason else ""
    return f"table={status.table_id} team={status.team_id} name={status.name} state={status.state}{reason}"

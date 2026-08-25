from __future__ import annotations

import json
import asyncio
import datetime as dt
from datetime import timedelta
from uuid import UUID

from django.db import close_old_connections, transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

import psycopg
import temporalio.activity
import temporalio.workflow
from structlog.contextvars import bind_contextvars
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.errors import unwrap_temporal_cause
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
from posthog.temporal.common.logger import get_logger

from products.data_modeling.backend.facade import api as data_modeling
from products.managed_warehouse.backend.common import (
    default_bucket_region,
    ducklake_data_modeling_schema_team_id,
    get_duckgres_config_for_org,
    get_org_config,
    validate_duckgres_identifier,
)
from products.managed_warehouse.backend.facade.team_state import resolve_events_persons_tables
from products.managed_warehouse.backend.models import ManagedWarehousePublishedTable
from products.managed_warehouse.backend.publish import (
    build_publish_copy_sql,
    build_publish_nonempty_probe_sql,
    delete_stale_publish_versions,
    is_publishable_table,
    publish_folder,
    publish_s3_uri,
    publish_url_pattern,
    sum_publish_version_size_bytes,
)
from products.managed_warehouse.backend.storage import setup_duckgres_session
from products.warehouse_sources.backend.facade import api as warehouse_sources
from products.warehouse_sources.backend.facade.constants import S3_DELETE_TIME_BUFFER

LOGGER = get_logger(__name__)


def build_publish_table_workflow_id(publication_id: UUID | str) -> str:
    return f"duckgres-publish-{publication_id}"


def _publication_queryset(team_id: int, publication_id: str) -> QuerySet[ManagedWarehousePublishedTable]:
    return ManagedWarehousePublishedTable.objects.for_team(team_id).filter(
        Q(saved_query_id=publication_id) | Q(id=publication_id)
    )


@frozen
class PublishTableInputs:
    team_id: int
    publication_id: str


@frozen
class PublishCopyResult:
    folder_version: str
    row_count: int
    bucket: str
    bucket_region: str


@frozen
class PublishRegisterInputs:
    team_id: int
    publication_id: str
    folder_version: str
    row_count: int
    bucket: str
    bucket_region: str


@frozen
class PrunePublishedSnapshotInputs:
    team_id: int
    publication_id: str
    # A version whose COPY completed but which may not be registered as live yet —
    # kept alongside the live version so a half-finished register never strands the
    # table on a deleted folder.
    completed_version: str | None = None
    # The version the table pointed at before this publish. Kept for one prune
    # cycle so readers that resolved the old url_pattern just before the repoint
    # don't lose their files mid-query.
    superseded_version: str | None = None
    skip_delete_buffer: bool = False


@frozen
class PublishMarkFailedInputs:
    team_id: int
    publication_id: str
    error: str


@temporalio.activity.defn
def publish_table_copy_activity(inputs: PublishTableInputs) -> PublishCopyResult:
    """Run COPY TO parquet on the org's duckgres worker, into a fresh version folder."""
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind(publication_id=inputs.publication_id)
    close_old_connections()
    publication = _publication_queryset(inputs.team_id, inputs.publication_id).get(deleted=False)
    source_team_id = ducklake_data_modeling_schema_team_id(publication.source_schema_name)
    if source_team_id is None:
        raise ApplicationError("Choose a modeled table from this project.", non_retryable=True)
    source_team = Team.objects.only("id", "parent_team_id").filter(id=source_team_id).first()
    source_project_id = source_team.parent_team_id or source_team.id if source_team is not None else None
    if source_project_id != publication.team_id:
        raise ApplicationError("Choose a modeled table from this project.", non_retryable=True)
    try:
        validate_duckgres_identifier(publication.source_schema_name)
        validate_duckgres_identifier(publication.source_table_name)
    except ValueError as error:
        raise ApplicationError(str(error), non_retryable=True) from error
    managed_tables = resolve_events_persons_tables(source_team_id)
    if not is_publishable_table(
        publication.source_schema_name,
        publication.source_table_name,
        reserved_table_names=frozenset({managed_tables.events_table, managed_tables.persons_table}),
    ):
        raise ApplicationError("Choose a publishable modeled table from this project.", non_retryable=True)

    if publication.saved_query_id is not None:
        workflow_run_id = temporalio.activity.info().workflow_run_id
        publication.active_job_id = data_modeling.start_managed_warehouse_saved_query_publish(
            inputs.team_id,
            publication.saved_query_id,
            build_publish_table_workflow_id(publication.id),
            workflow_run_id,
        )
    publication.status = ManagedWarehousePublishedTable.Status.PUBLISHING
    publication.save(update_fields=["active_job_id", "status", "updated_at"])

    team = Team.objects.only("organization_id").get(id=inputs.team_id)
    organization_id = str(team.organization_id)
    config = get_duckgres_config_for_org(organization_id)
    # Published snapshots live in the org's own managed-warehouse bucket, so the
    # worker's ambient credentials cover the write — no injected secret.
    storage = get_org_config(organization_id)
    bucket = storage.get("DUCKLAKE_BUCKET") or ""
    if not bucket:
        raise ValueError(f"No managed warehouse bucket recorded for organization {organization_id}")
    bucket_region = storage.get("DUCKLAKE_BUCKET_REGION") or default_bucket_region()

    version = dt.datetime.now(dt.UTC).strftime("%Y%m%d%H%M%S")
    folder = publish_folder(inputs.team_id, publication.id.hex)
    destination = publish_s3_uri(bucket, folder, version)

    with HeartbeaterSync(details=("duckgres_publish", inputs.publication_id), logger=logger):
        with psycopg.connect(
            host=config["DUCKGRES_HOST"],
            port=config["DUCKGRES_PORT"],
            dbname=config["DUCKGRES_DATABASE"],
            user=config["DUCKGRES_USERNAME"],
            password=config["DUCKGRES_PASSWORD"],
            autocommit=True,
            connect_timeout=30,
            keepalives=1,
            keepalives_idle=60,
            keepalives_interval=15,
            keepalives_count=4,
        ) as conn:
            setup_duckgres_session(conn, extensions=("httpfs",))
            probe = conn.execute(
                build_publish_nonempty_probe_sql(publication.source_schema_name, publication.source_table_name)
            )
            if probe.fetchone() is None:
                raise ApplicationError("Empty modeled tables cannot be published yet.", non_retryable=True)
            cursor = conn.execute(
                build_publish_copy_sql(publication.source_schema_name, publication.source_table_name, destination)
            )
            row = cursor.fetchone()
            row_count = int(row[0]) if row else 0
            if row_count == 0:
                raise ApplicationError("Empty modeled tables cannot be published yet.", non_retryable=True)

    return PublishCopyResult(folder_version=version, row_count=row_count, bucket=bucket, bucket_region=bucket_region)


@temporalio.activity.defn
def publish_table_register_activity(inputs: PublishRegisterInputs) -> str | None:
    """Point the DataWarehouseTable at the freshly published version folder.

    Describes the new snapshot before anything commits, so readers never see new
    files through stale columns and a failed describe leaves no trace. Returns the
    version the table pointed at before this publish, so the caller can keep it
    alive for one more prune cycle.
    """
    close_old_connections()
    publication = _publication_queryset(inputs.team_id, inputs.publication_id).get(deleted=False)
    saved_query = (
        data_modeling.get_managed_warehouse_saved_query(inputs.team_id, publication.saved_query_id)
        if publication.saved_query_id is not None
        else None
    )
    folder = publish_folder(inputs.team_id, publication.id.hex)
    url_pattern = publish_url_pattern(inputs.bucket, inputs.bucket_region, folder, inputs.folder_version)

    registration = warehouse_sources.prepare_published_table_registration(
        team_id=inputs.team_id,
        table_id=saved_query.table_id if saved_query is not None else publication.table_id,
        name=saved_query.name if saved_query is not None else publication.name,
        url_pattern=url_pattern,
    )
    size_in_s3_mib = sum_publish_version_size_bytes(inputs.bucket, folder, inputs.folder_version) / (1024 * 1024)

    with transaction.atomic():
        publication = (
            _publication_queryset(inputs.team_id, inputs.publication_id).select_for_update().get(deleted=False)
        )
        superseded_version = publication.folder_version
        table = warehouse_sources.save_published_table_registration(
            registration,
            row_count=inputs.row_count,
            size_in_s3_mib=size_in_s3_mib,
        )

        if publication.saved_query_id is not None:
            data_modeling.complete_managed_warehouse_saved_query_publish(
                team_id=inputs.team_id,
                saved_query_id=publication.saved_query_id,
                table_id=table.id,
                job_id=publication.active_job_id,
            )

        publication.table_id = table.id
        publication.status = ManagedWarehousePublishedTable.Status.COMPLETED
        publication.folder_version = inputs.folder_version
        publication.row_count = inputs.row_count
        publication.last_published_at = timezone.now()
        publication.last_error = None
        publication.active_job_id = None
        publication.save(
            update_fields=[
                "table_id",
                "status",
                "folder_version",
                "row_count",
                "last_published_at",
                "last_error",
                "active_job_id",
                "updated_at",
            ]
        )

    return superseded_version


@temporalio.activity.defn
def prune_published_snapshot_activity(inputs: PrunePublishedSnapshotInputs) -> None:
    """Delete snapshot files the publication no longer needs.

    Keeps the live version (publication.folder_version) plus any just-completed
    version; deletes everything when the publication is deleted or has never
    published successfully. Resolves the bucket itself so it also runs standalone
    from the delete API path, where no copy result exists.
    """
    close_old_connections()
    publication = _publication_queryset(inputs.team_id, inputs.publication_id).first()
    if publication is None:
        return

    team = Team.objects.only("organization_id").get(id=inputs.team_id)
    storage = get_org_config(str(team.organization_id))
    bucket = storage.get("DUCKLAKE_BUCKET") or ""
    if not bucket:
        raise ValueError(f"No managed warehouse bucket recorded for organization {team.organization_id}")

    keep_versions: set[str] = set()
    min_age_seconds = 0
    if not publication.deleted:
        keep_versions = {
            version
            for version in (publication.folder_version, inputs.completed_version, inputs.superseded_version)
            if version is not None
        }
        min_age_seconds = 0 if inputs.skip_delete_buffer else S3_DELETE_TIME_BUFFER
    delete_stale_publish_versions(
        bucket,
        publish_folder(inputs.team_id, publication.id.hex),
        keep_versions,
        min_age_seconds=min_age_seconds,
    )


@temporalio.activity.defn
def publish_table_mark_failed_activity(inputs: PublishMarkFailedInputs) -> None:
    close_old_connections()
    publication = _publication_queryset(inputs.team_id, inputs.publication_id).first()
    if publication is None:
        return
    if publication.saved_query_id is not None:
        data_modeling.fail_managed_warehouse_saved_query_publish(
            team_id=inputs.team_id,
            saved_query_id=publication.saved_query_id,
            error=inputs.error[:512],
            job_id=publication.active_job_id,
        )
    _publication_queryset(inputs.team_id, inputs.publication_id).update(
        status=ManagedWarehousePublishedTable.Status.FAILED,
        last_error=inputs.error[:512],
        active_job_id=None,
        updated_at=timezone.now(),
    )


async def _prune_published_snapshot_best_effort(inputs: PrunePublishedSnapshotInputs, warning_message: str) -> None:
    try:
        await temporalio.workflow.execute_activity(
            prune_published_snapshot_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
    except Exception:
        temporalio.workflow.logger.warning(warning_message)


def _workflow_error_message(error: BaseException) -> str:
    return str(unwrap_temporal_cause(error) or error)[:512]


@temporalio.workflow.defn(name="duckgres-publish-table")
class DuckgresPublishTableWorkflow(PostHogWorkflow):
    # TODO: Reap publications left in PUBLISHING when Temporal terminates or cancels a workflow.
    @staticmethod
    def parse_inputs(inputs: list[str]) -> PublishTableInputs:
        loaded = json.loads(inputs[0])
        return PublishTableInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: PublishTableInputs) -> None:
        copy_result: PublishCopyResult | None = None
        try:
            copy_result = await temporalio.workflow.execute_activity(
                publish_table_copy_activity,
                inputs,
                start_to_close_timeout=timedelta(hours=2),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=30)),
            )
            superseded_version = await temporalio.workflow.execute_activity(
                publish_table_register_activity,
                PublishRegisterInputs(
                    team_id=inputs.team_id,
                    publication_id=inputs.publication_id,
                    folder_version=copy_result.folder_version,
                    row_count=copy_result.row_count,
                    bucket=copy_result.bucket,
                    bucket_region=copy_result.bucket_region,
                ),
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=10)),
            )
            await _prune_published_snapshot_best_effort(
                PrunePublishedSnapshotInputs(
                    team_id=inputs.team_id,
                    publication_id=inputs.publication_id,
                    completed_version=copy_result.folder_version,
                    superseded_version=superseded_version,
                ),
                "Publish cleanup failed; stale version folders remain",
            )
        except Exception as error:
            # Prune whatever the failed run wrote: partial COPY folders always, the
            # whole folder if the publication was deleted mid-publish.
            await _prune_published_snapshot_best_effort(
                PrunePublishedSnapshotInputs(
                    team_id=inputs.team_id,
                    publication_id=inputs.publication_id,
                    skip_delete_buffer=True,
                ),
                "Publish failure prune failed; stale files may remain",
            )
            await temporalio.workflow.execute_activity(
                publish_table_mark_failed_activity,
                PublishMarkFailedInputs(
                    team_id=inputs.team_id,
                    publication_id=inputs.publication_id,
                    error=_workflow_error_message(error),
                ),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            raise


@temporalio.workflow.defn(name="duckgres-prune-published-snapshot")
class DuckgresPrunePublishedSnapshotWorkflow(PostHogWorkflow):
    """Standalone snapshot prune, scheduled when a publication is deleted via the API."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> PrunePublishedSnapshotInputs:
        loaded = json.loads(inputs[0])
        return PrunePublishedSnapshotInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: PrunePublishedSnapshotInputs) -> None:
        # Give queries that resolved the table's url_pattern just before the
        # publication was deleted time to finish before their files disappear.
        await asyncio.sleep(S3_DELETE_TIME_BUFFER)
        await temporalio.workflow.execute_activity(
            prune_published_snapshot_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=10)),
        )

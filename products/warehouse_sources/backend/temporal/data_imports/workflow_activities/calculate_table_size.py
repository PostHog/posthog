import dataclasses

from django.conf import settings
from django.db import DatabaseError, close_old_connections

from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.temporal.common.logger import get_logger

from products.data_warehouse.backend.facade.api import get_size_of_folder
from products.warehouse_sources.backend.models import DataWarehouseTable
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.util import retry_internal_db_operation

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class CalculateTableSizeActivityInputs:
    team_id: int
    schema_id: str
    job_id: str


def _delta_table_uri(schema: ExternalDataSchema, table: DataWarehouseTable) -> str:
    """Where the table's Delta log lives.

    The query folder is named `<delta folder leaf>__query[...]`, so the leaf comes from the pointer
    when there is one: a `cdc_only` schema's table is its `_cdc` companion, whose Delta folder is not
    the schema's own.
    """
    if table.queryable_folder:
        leaf = table.queryable_folder.rsplit("__query", 1)[0]
    else:
        leaf = schema.normalized_s3_folder_name
    return f"{settings.BUCKET_URL}/{schema.folder_path()}/{leaf}"


def _live_delta_size_mib(delta_uri: str) -> float | None:
    """Total size of the files the Delta log lists as live, in MiB.

    The query folder holds a copy of exactly those files, so this is the number an S3 listing of
    that folder gives, without paging through every object. None when no Delta log exists there,
    so the caller can fall back to listing.
    """
    import pyarrow as pa  # noqa: PLC0415 — keeps the heavy pyarrow dep off this activity module's import path
    import deltalake  # noqa: PLC0415 — keeps the heavy deltalake dep off this activity module's import path
    import pyarrow.compute as pc  # noqa: PLC0415 — keeps the heavy pyarrow dep off this activity module's import path
    import deltalake.exceptions  # noqa: PLC0415 — keeps the heavy deltalake dep off this activity module's import path

    from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import (  # noqa: PLC0415 — keeps the heavy deltalake dep off this activity module's import path
        delta_storage_options,
    )

    try:
        delta_table = deltalake.DeltaTable(delta_uri, storage_options=delta_storage_options())
    except deltalake.exceptions.TableNotFoundError:
        return None

    # deltalake>=1.x returns an arro3 RecordBatch; pa.table() normalizes it through the Arrow C interface.
    add_actions = pa.table(delta_table.get_add_actions(flatten=True))
    total_bytes = pc.sum(add_actions.column("size_bytes")).as_py() or 0
    return total_bytes / (1024 * 1024)


# The individual queries carry `retry_internal_db_operation` rather than the whole activity
# carrying `with_internal_db_retries`, because retrying the whole body would repeat the size
# measurement below, which for the S3 listing fallback can take minutes and still has to finish
# inside the activity's timeout.
@activity.defn
def calculate_table_size_activity(inputs: CalculateTableSizeActivityInputs) -> None:
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()
    close_old_connections()

    logger.debug("Calculating table size in S3")

    try:
        schema = retry_internal_db_operation(lambda: ExternalDataSchema.objects.get(id=inputs.schema_id))
    except ExternalDataSchema.DoesNotExist:
        logger.debug(f"Schema doesnt exist, exiting early. Schema id = {inputs.schema_id}")
        return

    try:
        job = retry_internal_db_operation(lambda: ExternalDataJob.objects.get(id=inputs.job_id))
    except ExternalDataJob.DoesNotExist:
        logger.debug(f"Job doesnt exist, exiting early. Job id = {inputs.job_id}")
        return

    table: DataWarehouseTable | None = schema.table

    if not table:
        logger.debug("Table doesnt exist on schema, exiting early")
        return

    existing_size = table.size_in_s3_mib or 0

    logger.debug(f"Existing size in MiB = {existing_size:.2f}")

    folder_name = schema.folder_path()

    if table.queryable_folder:
        s3_folder = f"{settings.BUCKET_URL}/{folder_name}/{table.queryable_folder}"
    else:
        if table.format == DataWarehouseTable.TableFormat.DeltaS3Wrapper:
            s3_folder = f"{settings.BUCKET_URL}/{folder_name}/{schema.normalized_name}__query"
        else:
            s3_folder = f"{settings.BUCKET_URL}/{folder_name}/{schema.normalized_name}"

    try:
        total_mib: float | None = None
        if table.format == DataWarehouseTable.TableFormat.DeltaS3Wrapper:
            total_mib = _live_delta_size_mib(_delta_table_uri(schema, table))
        if total_mib is None:
            total_mib = get_size_of_folder(s3_folder)
    except OSError as e:
        from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.errors import (  # noqa: PLC0415 — keeps the heavy deltalake dep off this activity module's import path
            TransientObjectStoreError,
            is_transient_object_store_error,
        )

        if not is_transient_object_store_error(e):
            raise
        # Covers this worker's own fd pressure (EMFILE/ENFILE, e.g. botocore loading a data file
        # while building the S3 client) and known-transient S3/object-store blips (IMDS/STS hiccups,
        # dropped connections) hit opening the Delta log (_live_delta_size_mib) or listing the query
        # folder (get_size_of_folder) — see is_transient_object_store_error. A retry recovers on its
        # own, so it shouldn't page anyone.
        logger.warning("Transient object-store error calculating table size in S3", exc_info=e)
        raise TransientObjectStoreError(str(e)) from e

    logger.debug(f"Total size in MiB = {total_mib:.2f}")

    table_size_delta = total_mib - existing_size
    logger.debug(f"Table size delta in MiB = {table_size_delta:.2f}")

    job.storage_delta_mib = table_size_delta
    try:
        retry_internal_db_operation(lambda: job.save(update_fields=["storage_delta_mib", "updated_at"]))
    except DatabaseError:
        # get_size_of_folder() (an S3 listing) can run long enough for the job's team to be
        # deleted meanwhile, cascading away this row before the UPDATE lands. Not a defect —
        # exit the same way the DoesNotExist checks above do.
        if not ExternalDataJob.objects.filter(id=job.id).exists():
            logger.debug(f"Job was deleted while calculating table size, exiting early. Job id = {job.id}")
            return
        raise

    table.size_in_s3_mib = total_mib
    try:
        # Scoped to the field this activity actually changes: an unscoped save() compares this
        # possibly-stale in-memory url_pattern (table was loaded before the potentially long
        # get_size_of_folder() call above) against the row's current DB value, and a credential-less
        # table with no other change in flight trips the url_pattern guard on that false mismatch.
        retry_internal_db_operation(lambda: table.save(update_fields=["size_in_s3_mib", "updated_at"]))
    except DatabaseError:
        if not DataWarehouseTable.objects.filter(id=table.id).exists():
            logger.debug(f"Table was deleted while calculating table size, exiting early. Table id = {table.id}")
            return
        raise

    logger.debug("Table model updated")

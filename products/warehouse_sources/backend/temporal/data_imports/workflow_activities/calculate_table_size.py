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

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class CalculateTableSizeActivityInputs:
    team_id: int
    schema_id: str
    job_id: str


@activity.defn
def calculate_table_size_activity(inputs: CalculateTableSizeActivityInputs) -> None:
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()
    close_old_connections()

    logger.debug("Calculating table size in S3")

    try:
        schema = ExternalDataSchema.objects.get(id=inputs.schema_id)
    except ExternalDataSchema.DoesNotExist:
        logger.debug(f"Schema doesnt exist, exiting early. Schema id = {inputs.schema_id}")
        return

    try:
        job = ExternalDataJob.objects.get(id=inputs.job_id)
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

    total_mib = get_size_of_folder(s3_folder)

    logger.debug(f"Total size in MiB = {total_mib:.2f}")

    table_size_delta = total_mib - existing_size
    logger.debug(f"Table size delta in MiB = {table_size_delta:.2f}")

    job.storage_delta_mib = table_size_delta
    try:
        job.save(update_fields=["storage_delta_mib", "updated_at"])
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
        table.save(update_fields=["size_in_s3_mib", "updated_at"])
    except DatabaseError:
        if not DataWarehouseTable.objects.filter(id=table.id).exists():
            logger.debug(f"Table was deleted while calculating table size, exiting early. Table id = {table.id}")
            return
        raise

    logger.debug("Table model updated")

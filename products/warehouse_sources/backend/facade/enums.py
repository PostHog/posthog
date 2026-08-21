"""Enumerations the warehouse_sources models use.

Consumers that only need a status, a sync type or a creation source read it from here and do not
need the model class. The models keep each one as a class attribute (``ExternalDataSchema.Status``)
so ``choices=`` and existing call sites are unchanged.
"""

from django.db import models


class DataWarehouseTableFormat(models.TextChoices):
    CSV = "CSV", "CSV"
    CSVWithNames = "CSVWithNames", "CSVWithNames"
    Parquet = "Parquet", "Parquet"
    JSON = "JSONEachRow", "JSON"
    Delta = "Delta", "Delta"
    DeltaS3Wrapper = "DeltaS3Wrapper", "DeltaS3Wrapper"


class DataWarehouseTableCreatedVia(models.TextChoices):
    # The first five mirror `ExternalDataSource.CreatedVia` value-for-value, so table and source
    # attribution can be counted together. The last three have no source equivalent — they cover
    # the tables PostHog creates itself, which a request surface would otherwise misattribute to
    # whoever happened to trigger the run.
    WEB = "web", "web"
    API = "api", "api"
    MCP = "mcp", "mcp"
    WIZARD = "wizard", "wizard"
    SELF_DRIVING = "self_driving", "self_driving"
    SOURCE = "source", "source"
    MATERIALIZED_VIEW = "materialized_view", "materialized_view"
    DEMO = "demo", "demo"


class ExternalDataJobStatus(models.TextChoices):
    RUNNING = "Running", "Running"
    FAILED = "Failed", "Failed"
    COMPLETED = "Completed", "Completed"
    BILLING_LIMIT_REACHED = "BillingLimitReached", "BillingLimitReached"
    BILLING_LIMIT_TOO_LOW = "BillingLimitTooLow", "BillingLimitTooLow"


class ExternalDataJobPipelineVersion(models.TextChoices):
    V1 = "v1-dlt-sync", "v1-dlt-sync"
    V2 = "v2-non-dlt", "v2-non-dlt"
    V3 = "v3-kafka-s3", "v3-kafka-s3"


class ExternalDataSourceAccessMethod(models.TextChoices):
    WAREHOUSE = "warehouse", "warehouse"
    DIRECT = "direct", "direct"


class ExternalDataSourceCreatedVia(models.TextChoices):
    WEB = "web", "web"
    API = "api", "api"
    MCP = "mcp", "mcp"
    WIZARD = "wizard", "wizard"
    SELF_DRIVING = "self_driving", "self_driving"


class ExternalDataSourceStatus(models.TextChoices):
    RUNNING = "Running", "Running"
    PAUSED = "Paused", "Paused"
    ERROR = "Error", "Error"
    COMPLETED = "Completed", "Completed"
    CANCELLED = "Cancelled", "Cancelled"


class ExternalDataSourceSyncFrequency(models.TextChoices):
    DAILY = "day", "Daily"
    WEEKLY = "week", "Weekly"
    MONTHLY = "month", "Monthly"
    # TODO provide flexible schedule definition


class ExternalDataSchemaStatus(models.TextChoices):
    RUNNING = "Running", "Running"
    PAUSED = "Paused", "Paused"
    FAILED = "Failed", "Failed"
    COMPLETED = "Completed", "Completed"
    BILLING_LIMIT_REACHED = "BillingLimitReached", "BillingLimitReached"
    BILLING_LIMIT_TOO_LOW = "BillingLimitTooLow", "BillingLimitTooLow"


class ExternalDataSchemaSyncType(models.TextChoices):
    FULL_REFRESH = "full_refresh", "full_refresh"
    INCREMENTAL = "incremental", "incremental"
    APPEND = "append", "append"
    WEBHOOK = "webhook", "webhook"
    CDC = "cdc", "cdc"
    XMIN = "xmin", "xmin"


class ExternalDataSchemaSyncFrequency(models.TextChoices):
    DAILY = "day", "Daily"
    WEEKLY = "week", "Weekly"
    MONTHLY = "month", "Monthly"


class WarehouseColumnAnnotationDescriptionSource(models.TextChoices):
    CANONICAL = "canonical", "Canonical"
    AI_GENERATED = "ai_generated", "AI generated"
    USER_EDITED = "user_edited", "User edited"

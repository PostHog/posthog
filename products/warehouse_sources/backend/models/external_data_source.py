from uuid import UUID

from django.db import models
from django.utils import timezone

import structlog

from posthog.helpers.encrypted_fields import EncryptedJSONField
from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.utils import CreatedMetaFields, DeletedMetaFields, UpdatedMetaFields, UUIDTModel, sane_repr
from posthog.sync import database_sync_to_async

from products.warehouse_sources.backend.types import DIRECT_ENGINE_BY_SOURCE_TYPE, ExternalDataSourceType

logger = structlog.get_logger(__name__)


class ExternalDataSourceManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().select_related("revenue_analytics_config")


class ExternalDataSource(ModelActivityMixin, CreatedMetaFields, UpdatedMetaFields, UUIDTModel, DeletedMetaFields):
    class AccessMethod(models.TextChoices):
        WAREHOUSE = "warehouse", "warehouse"
        DIRECT = "direct", "direct"

    class CreatedVia(models.TextChoices):
        WEB = "web", "web"
        API = "api", "api"
        MCP = "mcp", "mcp"

    class Status(models.TextChoices):
        RUNNING = "Running", "Running"
        PAUSED = "Paused", "Paused"
        ERROR = "Error", "Error"
        COMPLETED = "Completed", "Completed"
        CANCELLED = "Cancelled", "Cancelled"

    # Deprecated, use `ExternalDataSchema.SyncFrequency`
    class SyncFrequency(models.TextChoices):
        DAILY = "day", "Daily"
        WEEKLY = "week", "Weekly"
        MONTHLY = "month", "Monthly"
        # TODO provide flexible schedule definition

    source_id = models.CharField(max_length=400)
    connection_id = models.CharField(max_length=400)
    destination_id = models.CharField(max_length=400, null=True, blank=True)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)

    # Deprecated, use `ExternalDataSchema.sync_frequency_interval`
    sync_frequency = models.CharField(max_length=128, choices=SyncFrequency, default=SyncFrequency.DAILY, blank=True)

    # `status` is deprecated in favour of external_data_schema.status
    status = models.CharField(max_length=400)
    source_type = models.CharField(max_length=128, choices=ExternalDataSourceType)
    job_inputs = EncryptedJSONField(null=True, blank=True)
    connection_metadata = models.JSONField(default=dict, blank=True, null=True)
    are_tables_created = models.BooleanField(default=False)
    prefix = models.CharField(max_length=100, null=True, blank=True)
    description = models.CharField(max_length=400, null=True, blank=True)
    # How this source was created — e.g. web UI, direct API call, or MCP tool. Required for new rows
    # via the serializer; NULL on historical rows created before this field existed.
    created_via = models.CharField(max_length=20, choices=CreatedVia, null=True, blank=True)
    access_method = models.CharField(max_length=32, choices=AccessMethod, default=AccessMethod.WAREHOUSE)
    # Lets a synced (warehouse) source also be live-queryable via direct connection; ignored for pure direct sources.
    # Off by default — a user opts a synced source in explicitly before it becomes live-queryable.
    direct_query_enabled = models.BooleanField(default=False)

    # DEPRECATED: Check inside `revenue_analytics_config` instead
    revenue_analytics_enabled = models.BooleanField(default=False, blank=True, null=True)

    objects = ExternalDataSourceManager()

    __repr__ = sane_repr("id", "source_id", "connection_id", "destination_id", "team_id")

    class Meta:
        db_table = "posthog_externaldatasource"

    @property
    def is_direct_query(self) -> bool:
        return self.access_method == self.AccessMethod.DIRECT

    @property
    def is_direct_postgres(self) -> bool:
        return self.is_direct_query and self.source_type == ExternalDataSourceType.POSTGRES

    @property
    def is_direct_mysql(self) -> bool:
        return self.is_direct_query and self.source_type == ExternalDataSourceType.MYSQL

    @property
    def is_direct_snowflake(self) -> bool:
        return self.is_direct_query and self.source_type == ExternalDataSourceType.SNOWFLAKE

    @property
    def direct_engine(self) -> str | None:
        """The direct-SQL engine for this source's type, or None if no engine maps to it.

        This keys off ``source_type`` only and ignores ``access_method``/toggles — a non-None
        result means "an engine exists for this type", not "this source is queryable". Whether a
        source may actually be queried live is decided by ``is_direct_capable`` and the adapters.
        """
        return DIRECT_ENGINE_BY_SOURCE_TYPE.get(self.source_type)

    @property
    def supports_scheduled_sync(self) -> bool:
        return not self.is_direct_query

    @property
    def revenue_analytics_config_safe(self):
        """
        Safely access revenue_analytics_config with automatic creation fallback.
        Use this instead of direct access when you need to guarantee the config exists.
        """
        from products.data_warehouse.backend.facade.models import ExternalDataSourceRevenueAnalyticsConfig

        try:
            return self.revenue_analytics_config
        except ExternalDataSourceRevenueAnalyticsConfig.DoesNotExist:
            config, _ = ExternalDataSourceRevenueAnalyticsConfig.objects.get_or_create(
                external_data_source=self,
                defaults={
                    "enabled": self.source_type == ExternalDataSourceType.STRIPE,
                },
            )
            return config

    def soft_delete(self):
        self.deleted = True
        self.deleted_at = timezone.now()
        self.save()

        # Lazy import to avoid circular: SourceRegistry → helpers.py → this module.
        from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry

        SourceRegistry.get_source(ExternalDataSourceType(self.source_type)).cleanup_cdc_resources_on_deletion(self)

    def reload_schemas(self):
        # temporalio at module scope would put the Temporal client on the django.setup() path —
        # this is a models module; the service import below pulls it anyway, but only at call time
        import temporalio.service  # noqa: PLC0415

        from products.data_warehouse.backend.facade.api import (
            sync_external_data_job_workflow,
            trigger_external_data_workflow,
        )
        from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

        if not self.supports_scheduled_sync:
            return

        for schema in (
            ExternalDataSchema.objects.filter(team_id=self.team.pk, source_id=self.id, should_sync=True)
            .exclude(deleted=True)
            .all()
        ):
            try:
                trigger_external_data_workflow(schema)
            except temporalio.service.RPCError as e:
                if e.status == temporalio.service.RPCStatusCode.NOT_FOUND:
                    sync_external_data_job_workflow(schema, create=True, should_sync=True)

            except Exception as e:
                logger.exception(f"Could not trigger external data job for schema {schema.name}", exc_info=e)


@database_sync_to_async
def get_external_data_source(source_id: UUID) -> ExternalDataSource:
    return ExternalDataSource.objects.get(pk=source_id)


def get_direct_external_data_source_for_connection(
    team_id: int, connection_id: str | None
) -> ExternalDataSource | None:
    if not connection_id:
        return None

    try:
        source_uuid = UUID(connection_id)
    except ValueError:
        return None

    # Function-local: capability imports this module (circular); also keeps direct-SQL drivers off django.setup().
    from posthog.hogql.direct_sql.capability import is_direct_capable  # noqa: PLC0415

    source = (
        ExternalDataSource.objects.filter(
            team_id=team_id,
            id=source_uuid,
        )
        .exclude(deleted=True)
        .first()
    )
    if source is None or not is_direct_capable(source):
        return None
    return source

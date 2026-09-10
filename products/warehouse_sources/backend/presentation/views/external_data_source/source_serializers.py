"""Serializers for external data source API requests and responses."""

from __future__ import annotations

import dataclasses
from typing import Any, cast

from django.db import transaction
from django.db.models import Q

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers, status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response

from posthog.exceptions_capture import capture_exception
from posthog.permissions import TeamMemberAdminManagementPermission

from products.access_control.backend.presentation.access_control import UserAccessControlSerializerMixin
from products.data_warehouse.backend.facade.api import (
    apply_on_schema_clear as apply_sql_warehouse_schema_clear_migration,
    detect_schema_clear_transition as detect_sql_schema_clear_transition,
    get_direct_query_engine,
    get_namespaced_resource_adapter,
)
from products.data_warehouse.backend.facade.models import ExternalDataSourceRevenueAnalyticsConfig
from products.warehouse_sources.backend.facade.models import (
    ExternalDataJob,
    ExternalDataSchema,
    ExternalDataSource,
    PendingSourceCredential,
    sync_old_schemas_with_new_schemas,
)
from products.warehouse_sources.backend.facade.source_management import (
    PREVIEW_DEFAULT_ROWS,
    PREVIEW_MAX_ROWS,
    Config,
    CustomSource,
    MySQLSource,
    PostgresSource,
    SourceRegistry,
    SourceSchema,
    WebhookSource,
)
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType
from products.warehouse_sources.backend.presentation.views.external_data_schema import (
    ExternalDataSchemaListSerializer,
    ExternalDataSchemaSerializer,
    RowFiltersField,
    SimpleExternalDataSchemaSerializer,
    source_supports_column_selection,
)
from products.warehouse_sources.backend.presentation.views.source_api_versions import (
    ExternalDataSourceApiVersionDeprecationSerializer,
    api_version_deprecation_payload,
)

from . import helpers


class ExternalDataSourceRevenueAnalyticsConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExternalDataSourceRevenueAnalyticsConfig
        fields = ["enabled", "include_invoiceless_charges"]


class ExternalDataSourceConnectionMetadataSerializer(serializers.Serializer):
    database = serializers.CharField(
        read_only=True,
        required=False,
        allow_null=True,
        help_text="Database name discovered for a direct connection.",
    )
    version = serializers.CharField(
        read_only=True,
        required=False,
        allow_null=True,
        help_text="Database version string reported by the direct connection.",
    )
    engine = serializers.ChoiceField(
        read_only=True,
        required=False,
        allow_null=True,
        choices=helpers.DIRECT_CONNECTION_ENGINE_CHOICES,
        help_text="Backend engine detected for the direct connection.",
    )
    function_source = serializers.CharField(
        read_only=True,
        required=False,
        allow_null=True,
        help_text="System catalog or function source used to discover supported functions.",
    )
    available_functions = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
        required=False,
        help_text="Functions discovered as available on the direct connection.",
    )


class ExternalDataSourceConnectionOptionSerializer(serializers.ModelSerializer):
    engine = serializers.ChoiceField(
        source="connection_metadata.engine",
        read_only=True,
        allow_null=True,
        choices=helpers.DIRECT_CONNECTION_ENGINE_CHOICES,
        help_text="Backend engine detected for the direct connection.",
    )
    source_type = serializers.ChoiceField(
        choices=ExternalDataSourceType.choices,
        read_only=True,
        help_text="The source type (e.g. 'Postgres', 'MySQL', 'Snowflake').",
    )
    access_method = serializers.ChoiceField(
        choices=ExternalDataSource.AccessMethod.choices,
        read_only=True,
        help_text="'direct' for pure live-query sources; 'warehouse' for synced sources with direct query enabled.",
    )
    supports_hogql = serializers.SerializerMethodField(
        help_text="Whether HogQL queries compile for this connection. When false, only raw SQL (sendRawQuery) works.",
    )
    is_builtin_managed_warehouse = serializers.SerializerMethodField(
        help_text="Whether this option is the built-in PostHog managed warehouse connection.",
    )
    description = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="User-set description of the source, shown as its display name in the connection picker when set.",
    )

    @extend_schema_field(serializers.BooleanField())
    def get_supports_hogql(self, source: ExternalDataSource) -> bool:
        # Function-local: keeps the direct-SQL driver imports off the django.setup() path.
        from posthog.hogql.direct_sql.capability import direct_supports_hogql  # noqa: PLC0415

        return direct_supports_hogql(source)

    @extend_schema_field(serializers.BooleanField())
    def get_is_builtin_managed_warehouse(self, source: ExternalDataSource) -> bool:
        return source.pk == self.context.get("builtin_managed_warehouse_source_id")

    class Meta:
        model = ExternalDataSource
        fields = [
            "id",
            "prefix",
            "engine",
            "source_type",
            "access_method",
            "supports_hogql",
            "is_builtin_managed_warehouse",
            "description",
        ]
        read_only_fields = fields


class DirectConnectionSourceOptionSerializer(serializers.Serializer):
    """A source type that can be added as a direct (live-query) connection, with display metadata."""

    source_type = serializers.ChoiceField(
        choices=ExternalDataSourceType.choices,
        read_only=True,
        help_text="The source type to start a direct-connection setup for (e.g. 'Postgres', 'ClickHouse').",
    )
    label = serializers.CharField(  # type: ignore[assignment]  # field name intentionally shadows Field.label
        read_only=True,
        help_text="Human-readable name to show in the picker (falls back to the source type).",
    )
    icon_path = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Path to the source's icon asset, or null when the source ships no icon.",
    )


class ExternalDataSourceBulkUpdateSchemaSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Schema identifier to update.")
    should_sync = serializers.BooleanField(required=False, help_text="Whether the schema should be queryable/synced.")
    sync_type = serializers.ChoiceField(
        required=False,
        allow_null=True,
        choices=ExternalDataSchema.SyncType.choices,
        help_text="Requested sync mode for the schema (incremental, full_refresh, append, cdc, or xmin).",
    )
    incremental_field = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Incremental cursor field for incremental or append syncs.",
    )
    incremental_field_type = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Type of the incremental cursor field.",
    )
    sync_frequency = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Human-readable sync frequency value.",
    )
    sync_time_of_day = serializers.TimeField(
        required=False,
        allow_null=True,
        help_text="UTC anchor time for scheduled syncs.",
    )
    primary_key_columns = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_null=True,
        help_text="Column names for primary key deduplication.",
    )
    cdc_table_mode = serializers.ChoiceField(
        required=False,
        allow_null=True,
        choices=["consolidated", "cdc_only", "both"],
        help_text="How CDC-backed tables should be exposed.",
    )
    enabled_columns = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_null=True,
        allow_empty=True,
        help_text="Columns to sync. Null means sync all columns.",
    )
    row_filters = RowFiltersField(
        required=False,
        allow_null=True,
        help_text="Row-filter predicates ANDed onto the source query. Null/empty means sync all rows.",
    )
    apply_sync_defaults = serializers.BooleanField(
        required=False,
        help_text=(
            "When true and the schema has no sync method configured yet (and this update does not set "
            "one), discover the table on the source and fill in default sync settings: incremental sync "
            "with an auto-selected tracking column where supported, otherwise append, otherwise full "
            "refresh. Ignored for schemas that already have a sync method."
        ),
    )


class ExternalDataSourceBulkUpdateSchemasSerializer(serializers.Serializer):
    schemas = ExternalDataSourceBulkUpdateSchemaSerializer(
        many=True,
        allow_empty=False,
        help_text="Schema updates to apply in a single batch.",
    )


def _validation_error_message(error: ValidationError) -> str:
    # DRF normalizes ValidationError.detail to a list or dict (never a bare string).
    detail = error.detail
    if isinstance(detail, dict):
        return " ".join(f"{field}: {value}" for field, value in detail.items())
    return " ".join(str(item) for item in detail)


class BulkSchemaSaveError(APIException):
    default_code = "bulk_schema_save_failed"

    def __init__(self, failures: dict[str, tuple[str, str]], *, only_validation_errors: bool) -> None:
        # Pure input problems are the caller's to fix (400). A database/infra error is ours and is
        # retryable (503); treat a mix as a server problem so it surfaces as retryable.
        self.status_code = (
            status.HTTP_400_BAD_REQUEST if only_validation_errors else status.HTTP_503_SERVICE_UNAVAILABLE
        )
        reasons = "; ".join(f"{name} ({reason})" for name, reason in failures.values())
        super().__init__(
            detail=(
                f"These schemas in the batch could not be saved: {reasons}. "
                "Any other schemas in the batch were saved successfully — retry the ones listed here."
            )
        )


class ExternalDataJobSerializers(serializers.ModelSerializer):
    schema = serializers.SerializerMethodField(read_only=True)
    status = serializers.SerializerMethodField(read_only=True)
    cdc_write_mode = serializers.SerializerMethodField(
        read_only=True,
        help_text=(
            "For CDC syncs with `cdc_table_mode='both'`, distinguishes the two ExternalDataJob "
            "rows produced per sync: `incremental_merge` (consolidated table) vs `scd2_append` "
            "(cdc-only history table). `null` for non-CDC syncs. Read from `schema_snapshot`."
        ),
    )
    billable = serializers.BooleanField(
        read_only=True,
        allow_null=True,
        help_text=(
            "Whether the rows synced by this job count toward billing. `false` for system-initiated "
            "runs the customer isn't charged for (e.g. rebuilding a table after an internal issue). "
            "`null` on legacy rows and means billable."
        ),
    )
    destination_ids = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
        help_text=(
            "Destinations this run delivered to, snapshotted when it started. Empty on runs that "
            "predate destinations, which wrote to the PostHog warehouse alone. `rows_synced` counts "
            "the rows read from the source once, not once per destination."
        ),
    )

    class Meta:
        model = ExternalDataJob
        fields = [
            "id",
            "created_at",
            "created_by",
            "finished_at",
            "status",
            "schema",
            "rows_synced",
            "latest_error",
            "workflow_run_id",
            "cdc_write_mode",
            "billable",
            "destination_ids",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "created_by",
            "finished_at",
            "status",
            "schema",
            "rows_synced",
            "latest_error",
            "workflow_run_id",
            "cdc_write_mode",
            "billable",
            "destination_ids",
        ]

    def get_cdc_write_mode(self, instance: ExternalDataJob) -> str | None:
        return (instance.schema_snapshot or {}).get("cdc_write_mode")

    def get_status(self, instance: ExternalDataJob):
        if instance.status == ExternalDataJob.Status.BILLING_LIMIT_REACHED:
            return "Billing limits"

        if instance.status == ExternalDataJob.Status.BILLING_LIMIT_TOO_LOW:
            return "Billing limit too low"

        return instance.status

    def get_schema(self, instance: ExternalDataJob):
        return SimpleExternalDataSchemaSerializer(
            instance.schema, many=False, read_only=True, context=self.context
        ).data


class ExternalDataSourceSerializers(UserAccessControlSerializerMixin, serializers.ModelSerializer):
    account_id = serializers.CharField(write_only=True)
    client_secret = serializers.CharField(write_only=True)
    last_run_at = serializers.SerializerMethodField(read_only=True)
    created_by = serializers.SerializerMethodField(read_only=True)
    latest_error = serializers.SerializerMethodField(read_only=True)
    status = serializers.SerializerMethodField(read_only=True)
    schemas = serializers.SerializerMethodField(read_only=True)
    engine = serializers.ChoiceField(
        source="connection_metadata.engine",
        read_only=True,
        allow_null=True,
        required=False,
        choices=helpers.DIRECT_CONNECTION_ENGINE_CHOICES,
        help_text="Backend engine detected for the direct connection.",
    )
    revenue_analytics_config = ExternalDataSourceRevenueAnalyticsConfigSerializer(
        source="revenue_analytics_config_safe", read_only=True
    )
    access_method = serializers.ChoiceField(choices=ExternalDataSource.AccessMethod.choices, read_only=True)
    supports_webhooks = serializers.SerializerMethodField(read_only=True)
    supports_column_selection = serializers.SerializerMethodField(
        read_only=True,
        help_text="Whether this source supports per-column sync selection via `enabled_columns`.",
    )
    # Optional on both create and update. On create, missing values default to `api`
    # in the viewset to preserve backward compatibility with direct API callers that
    # predate this field; the in-app UI and MCP tool always send it explicitly.
    # `update` strips it to make the field write-once.
    # `allow_null=True` because historical rows (created before migration 0049) have
    # `created_via=NULL`, and the settings page spreads the GET payload back into PATCH.
    created_via = serializers.ChoiceField(
        choices=ExternalDataSource.CreatedVia.choices,
        required=False,
        allow_null=True,
        help_text=(
            "How this source was created. Defaults to `api` on create when omitted. "
            "`web` for the in-app UI, `api` for direct API callers, `mcp` for agent/MCP tool calls, "
            "`wizard` for the setup wizard and `self_driving` for the PostHog Desktop app "
            "(both derived server-side from the caller's user agent). "
            "Ignored on update."
        ),
    )
    direct_query_enabled = serializers.BooleanField(
        required=False,
        help_text=(
            "Whether this synced source is also live-queryable via direct connection. "
            "Defaults to false for new sources; ignored for pure direct-query sources."
        ),
    )
    auto_sync_new_schemas = serializers.BooleanField(
        required=False,
        help_text=(
            "Automatically enable syncing for schemas discovered on this source after creation, "
            "on both the scheduled discovery pass and manual schema refreshes. Defaults to false. "
            "Not supported for direct-query sources."
        ),
    )
    auto_sync_schema_patterns = serializers.ListField(
        child=serializers.CharField(
            max_length=250,
            allow_blank=False,
            help_text="An fnmatch-style glob pattern, e.g. `raw_*`.",
        ),
        required=False,
        allow_null=True,
        max_length=100,
        help_text=(
            "Optional fnmatch-style globs (`*` and `?` wildcards) restricting which newly discovered "
            "schema names auto-sync, matched case-insensitively against both the qualified and bare "
            "table name. Null or empty means every new schema qualifies. Only used when "
            "`auto_sync_new_schemas` is true."
        ),
    )
    api_version = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text=(
            "Vendor API version this source is pinned to (an opaque vendor label, e.g. a Stripe "
            "date version). Null resolves to the source type's default version at sync time."
        ),
    )
    api_version_deprecation = serializers.SerializerMethodField(
        read_only=True,
        help_text=(
            "Set when the vendor has deprecated the API version this source is pinned to; "
            "null otherwise. Drives the in-product deprecation warning."
        ),
    )

    class Meta:
        model = ExternalDataSource
        fields = [
            "id",
            "created_at",
            "created_by",
            "created_via",
            "status",
            "client_secret",
            "account_id",
            "source_type",
            "latest_error",
            "prefix",
            "description",
            "access_method",
            "direct_query_enabled",
            "auto_sync_new_schemas",
            "auto_sync_schema_patterns",
            "engine",
            "last_run_at",
            "schemas",
            "job_inputs",
            "revenue_analytics_config",
            "user_access_level",
            "supports_webhooks",
            "supports_column_selection",
            "api_version",
            "api_version_deprecation",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
            "status",
            "source_type",
            "latest_error",
            "last_run_at",
            "schemas",
            "engine",
            "revenue_analytics_config",
            "user_access_level",
            "access_method",
            "supports_webhooks",
            "supports_column_selection",
            "api_version",
            "api_version_deprecation",
        ]

    def to_representation(self, instance):
        representation = super().to_representation(instance)

        job_inputs = representation.get("job_inputs", {})
        if not isinstance(job_inputs, dict):
            return representation

        # Derive allowed keys dynamically from source config field definitions
        try:
            source_type_model = ExternalDataSourceType(instance.source_type)
            source = SourceRegistry.get_source(source_type_model)
            split = helpers.get_nonsensitive_and_sensitive_field_names(source.get_source_config.fields)
            # CDC fields aren't form fields but are non-secret operational config the UI needs.
            nonsensitive = split.nonsensitive | helpers._CDC_EXPOSED_JOB_INPUT_KEYS
        except (ValueError, KeyError):
            representation["job_inputs"] = {}
            return representation

        # Normalize SSH tunnel legacy format before stripping
        if "ssh_tunnel" in job_inputs and isinstance(job_inputs["ssh_tunnel"], dict):
            tunnel = job_inputs["ssh_tunnel"]
            # Normalize 'auth_type' (legacy from migration 0807) -> 'auth'
            if "auth_type" in tunnel and "auth" not in tunnel:
                tunnel["auth"] = tunnel.pop("auth_type")
            if isinstance(tunnel.get("auth"), dict):
                auth = tunnel["auth"]
                # Normalize 'type' (legacy) -> 'selection'
                if "type" in auth and "selection" not in auth:
                    auth["selection"] = auth.pop("type")
            # Backfill require_tls default for sources created before the toggle existed
            if "require_tls" not in tunnel:
                tunnel["require_tls"] = {"enabled": True}

        stripped = helpers.strip_sensitive_from_dict(job_inputs, nonsensitive, split.sensitive)
        declared = helpers.get_declared_field_names(source.get_source_config.fields)
        representation["job_inputs"] = helpers.restore_declared_field_names(stripped, declared.hyphenated)
        return representation

    def get_last_run_at(self, instance: ExternalDataSource) -> str | None:
        latest_completed_run = instance.ordered_jobs[0] if instance.ordered_jobs else None  # type: ignore

        return latest_completed_run.created_at.isoformat() if latest_completed_run else None

    def get_created_by(self, instance: ExternalDataSource) -> str | None:
        return instance.created_by.email if instance.created_by else None

    def get_supports_webhooks(self, instance: ExternalDataSource) -> bool:
        try:
            source = SourceRegistry.get_source(ExternalDataSourceType(instance.source_type))
            return isinstance(source, WebhookSource)
        except Exception as e:
            capture_exception(e)
            return False

    def get_supports_column_selection(self, instance: ExternalDataSource) -> bool:
        return source_supports_column_selection(instance.source_type)

    @extend_schema_field(ExternalDataSourceApiVersionDeprecationSerializer(allow_null=True))
    def get_api_version_deprecation(self, instance: ExternalDataSource) -> dict[str, Any] | None:
        return api_version_deprecation_payload(instance.source_type, instance.api_version)

    def _prefetched_schemas(self, instance: ExternalDataSource) -> list[ExternalDataSchema] | None:
        prefetched = getattr(instance, "_prefetched_objects_cache", {}).get("schemas")
        if prefetched is None:
            return None
        return [schema for schema in prefetched if not schema.deleted]

    def _active_schemas(self, instance: ExternalDataSource) -> list[ExternalDataSchema]:
        """Schemas that are syncing or carry an error — derived in Python from the single `schemas`
        prefetch rather than a second DB scan of the same (potentially huge) table."""
        prefetched = self._prefetched_schemas(instance)
        if prefetched is not None:
            return [schema for schema in prefetched if schema.should_sync or schema.latest_error is not None]
        return list(instance.schemas.exclude(deleted=True).filter(Q(should_sync=True) | Q(latest_error__isnull=False)))

    def get_status(self, instance: ExternalDataSource) -> str:
        active_schemas: list[ExternalDataSchema] = self._active_schemas(instance)
        # Negative statuses should ignore schemas the user has disabled — those can linger in
        # active_schemas via the latest_error prefetch but shouldn't drag the source into a failed state.
        syncing_schemas = [schema for schema in active_schemas if schema.should_sync]
        any_failures = any(schema.status == ExternalDataSchema.Status.FAILED for schema in syncing_schemas)
        any_billing_limits_reached = any(
            schema.status == ExternalDataSchema.Status.BILLING_LIMIT_REACHED for schema in syncing_schemas
        )
        any_billing_limits_too_low = any(
            schema.status == ExternalDataSchema.Status.BILLING_LIMIT_TOO_LOW for schema in syncing_schemas
        )
        any_paused = any(schema.status == ExternalDataSchema.Status.PAUSED for schema in active_schemas)
        any_running = any(schema.status == ExternalDataSchema.Status.RUNNING for schema in active_schemas)
        any_completed = any(schema.status == ExternalDataSchema.Status.COMPLETED for schema in active_schemas)

        if any_failures:
            return ExternalDataSchema.Status.FAILED
        elif any_billing_limits_reached:
            return "Billing limits"
        elif any_billing_limits_too_low:
            return "Billing limits too low"
        elif any_paused:
            return ExternalDataSchema.Status.PAUSED
        elif any_running:
            return ExternalDataSchema.Status.RUNNING
        elif any_completed:
            return ExternalDataSchema.Status.COMPLETED
        else:
            # Fallback during migration phase of going from source -> schema as the source of truth for syncs
            return instance.status

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_latest_error(self, instance: ExternalDataSource):
        prefetched_schemas = self._prefetched_schemas(instance)
        if prefetched_schemas is not None:
            schema_with_error = next(
                (schema for schema in prefetched_schemas if schema.latest_error is not None),
                None,
            )
        else:
            schema_with_error = instance.schemas.filter(latest_error__isnull=False).first()
        return schema_with_error.latest_error if schema_with_error else None

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_schemas(self, instance: ExternalDataSource):
        prefetched_schemas = getattr(instance, "_prefetched_objects_cache", {}).get("schemas")
        if prefetched_schemas is not None:
            schemas = [schema for schema in prefetched_schemas if not schema.deleted]
        else:
            schemas = list(instance.schemas.exclude(deleted=True).order_by("name"))
        # The source list embeds every schema of every source; large projects have tens of thousands.
        # The list UI only reads a handful of per-schema fields, so serialize the trimmed shape there
        # and reserve the full serializer for single-source reads.
        if self.context.get("schemas_list_only"):
            return ExternalDataSchemaListSerializer(schemas, many=True, read_only=True, context=self.context).data
        return ExternalDataSchemaSerializer(schemas, many=True, read_only=True, context=self.context).data

    def update(self, instance: ExternalDataSource, validated_data: Any) -> Any:
        request = self.context.get("request")
        requested_access_method = request.data.get("access_method") if request is not None else None
        if requested_access_method is not None and requested_access_method != instance.access_method:
            raise ValidationError("Access method cannot be changed. Create a new source instead.")

        validated_data.pop("access_method", None)
        # created_via is set at creation time and cannot be mutated afterwards
        validated_data.pop("created_via", None)

        if validated_data.get("auto_sync_new_schemas") and instance.is_direct_query:
            raise ValidationError(
                "Auto-syncing new schemas is not supported for direct query sources, "
                "because their schemas resolve at query time."
            )

        incoming_prefix = validated_data.get("prefix", instance.prefix)

        if instance.is_direct_query:
            # For direct query sources the prefix acts as the user-facing source name.
            normalized_prefix = incoming_prefix.strip() if isinstance(incoming_prefix, str) else ""
            if not normalized_prefix:
                raise ValidationError("Name is required for direct query sources")
            if ExternalDataSource.is_system_managed_prefix(normalized_prefix):
                raise ValidationError(helpers.RESERVED_SOURCE_NAME_MESSAGE)
            validated_data["prefix"] = normalized_prefix
        else:
            validated_data["prefix"] = instance.prefix

        existing_job_inputs = instance.job_inputs or {}
        job_inputs_were_submitted = "job_inputs" in validated_data
        incoming_job_inputs = validated_data.get("job_inputs", {})

        source_type_model = ExternalDataSourceType(instance.source_type)
        source = SourceRegistry.get_source(source_type_model)
        sensitive_fields = helpers.get_sensitive_field_names(source.get_source_config.fields)
        declared_field_names = helpers.get_declared_field_names(source.get_source_config.fields)
        discovered_schemas: list[SourceSchema] | None = None

        new_job_inputs = {**existing_job_inputs, **incoming_job_inputs}

        # CDC resource ownership changes must go through the CDC-specific endpoints.
        for key in helpers._CDC_EXPOSED_JOB_INPUT_KEYS:
            if key in existing_job_inputs:
                new_job_inputs[key] = existing_job_inputs[key]
            else:
                new_job_inputs.pop(key, None)

        # Server-managed job_inputs (Custom's OAuth2 row pointer, GitHub's legacy `repository`
        # marker): pin each to the stored value so an editor can't repoint the source at a different
        # row/marker (and through it, different credentials). Re-entered auth_oauth2_* secrets flow
        # into the pinned row during credential validation. The source declares which fields these
        # are — the API never names the source type.
        for field in source.server_managed_job_input_fields(incoming_job_inputs, existing_job_inputs):
            if existing_job_inputs.get(field):
                new_job_inputs[field] = existing_job_inputs[field]
            else:
                new_job_inputs.pop(field, None)

        # If the connection target changed, require credentials to be re-entered. Covers
        # both the generic `host` field and source-specific URL fields like ServiceNow's
        # `instance_url`, so a stored credential can't be redirected to a new host.
        connection_host_changed = any(
            field in incoming_job_inputs and incoming_job_inputs[field] != existing_job_inputs.get(field)
            for field in helpers._CONNECTION_TARGET_FIELDS
        )

        # Some sources keep their connection target in a differently named field (e.g. Okta's
        # `okta_domain`, Freshdesk's `subdomain`). Changing one would send the preserved credential
        # to a new host — the same exfiltration risk as a `host` change — so require re-entry too.
        connection_host_changed = connection_host_changed or any(
            field in incoming_job_inputs and incoming_job_inputs[field] != existing_job_inputs.get(field)
            for field in source.connection_host_fields
        )

        # If the SSH tunnel's connection target changed, also require credentials. Without this an
        # editor could swap in a tunnel that routes the backend's auth to an attacker-controlled
        # server, exfiltrating the stored database credentials (VERIA-311).
        ssh_tunnel_changed = "ssh_tunnel" in incoming_job_inputs and helpers.ssh_tunnel_connection_changed(
            existing_job_inputs.get("ssh_tunnel"),
            incoming_job_inputs.get("ssh_tunnel"),
        )

        # Some sources keep their connection target somewhere other than a named field — Custom's
        # lives inside its manifest. An edit that introduces a new request host would send the
        # preserved credential somewhere it wasn't going before, the same exfiltration risk, so
        # require re-entry too. The source decides; the API never names the source type.
        job_inputs_host_added = source.job_inputs_add_connection_host(incoming_job_inputs, existing_job_inputs)

        # Some sources keep their secrets in a bound row, not job_inputs (Custom's
        # CustomOAuth2Integration) — the generic preserved-credentials check can't see those, yet a
        # host change would still redirect the row's injected token. The source reports whether such
        # row-backed secrets are preserved (not re-entered) on this update.
        preserved_row_backed_credentials = source.has_preserved_row_backed_credentials(instance, incoming_job_inputs)

        if connection_host_changed or ssh_tunnel_changed or job_inputs_host_added:
            gate_sensitive_fields = sensitive_fields - helpers._CREATION_ONLY_SECRET_FIELDS
            preserved_credentials = helpers.has_preserved_credentials(
                existing_job_inputs,
                incoming_job_inputs,
                gate_sensitive_fields,
                nested_containers=(*helpers._NESTED_AUTH_CONTAINERS, *declared_field_names.switch_groups),
            )
            if preserved_credentials or preserved_row_backed_credentials:
                if ssh_tunnel_changed:
                    raise ValidationError("Changing the SSH tunnel requires re-entering your database credentials.")
                if job_inputs_host_added:
                    raise ValidationError("Changing the manifest's request host requires re-entering your credentials.")
                raise ValidationError("Changing the connection host requires re-entering your credentials.")

        # Preserve sensitive credentials not explicitly provided (API response omits them for security)
        for key in sensitive_fields:
            if existing_job_inputs.get(key) and not incoming_job_inputs.get(key):
                new_job_inputs[key] = existing_job_inputs[key]

        # SSH tunnel is a nested config - deep-merge it so partial updates preserve existing fields
        existing_ssh_tunnel = existing_job_inputs.get("ssh_tunnel")

        # Nested containers (e.g. Stripe `auth_method`, Snowflake `auth_type`, Billomat `registered_app`)
        # need a deep-merge that preserves sensitive fields not explicitly provided. The shallow merge
        # above would otherwise wipe redacted credentials nested inside these containers. Same container
        # list as the host-change gate above, so a merge here always has a matching preserved-credential check.
        for container_key in helpers._NESTED_AUTH_CONTAINERS:
            existing_container = existing_job_inputs.get(container_key)
            incoming_container = incoming_job_inputs.get(container_key)
            if incoming_container is not None and not isinstance(incoming_container, dict):
                raise ValidationError({"job_inputs": {container_key: "Must be an object."}})
            if not (isinstance(existing_container, dict) and isinstance(incoming_container, dict)):
                continue
            selection_changed = existing_container.get("selection") != incoming_container.get("selection")
            if selection_changed:
                # Selection switched (e.g. password→keypair) — use only incoming, don't carry over old secrets
                new_job_inputs[container_key] = incoming_container
            else:
                merged_container = {**existing_container, **incoming_container}
                for key in sensitive_fields:
                    if existing_container.get(key) and not incoming_container.get(key):
                        merged_container[key] = existing_container[key]
                new_job_inputs[container_key] = merged_container

        # Switch groups are nested containers too. The settings form submits only the fields the
        # user touched and skips a disabled group's children, so a payload that just flips
        # `enabled` would otherwise replace the whole stored group and drop a required nested
        # value that validation then rejects. Switching a group off keeps its stored value —
        # the user hasn't asked to forget it, and consumers gate on `enabled` before reading it.
        for group_key in declared_field_names.switch_groups:
            # A group declared with a hyphen can be stored under either spelling (see
            # `restore_declared_field_names`), so resolve both sides by declared name.
            incoming_key = helpers._stored_key(incoming_job_inputs, group_key)
            if incoming_key is None:
                continue
            incoming_group = incoming_job_inputs[incoming_key]
            if not isinstance(incoming_group, dict):
                raise ValidationError({"job_inputs": {group_key: "Must be an object."}})
            existing_group = helpers._stored_value(existing_job_inputs, group_key)
            if not isinstance(existing_group, dict):
                continue
            merged_group = {**existing_group, **incoming_group}
            # No switch group declares a secret today, but keep the carry-over so one could.
            for key in sensitive_fields:
                if existing_group.get(key) and not incoming_group.get(key):
                    merged_group[key] = existing_group[key]
            # Drop the other spelling so parsing can't see two competing groups.
            for key in helpers._name_variants(group_key):
                new_job_inputs.pop(key, None)
            new_job_inputs[incoming_key] = merged_group

        incoming_ssh_tunnel = incoming_job_inputs.get("ssh_tunnel")
        if existing_ssh_tunnel and incoming_ssh_tunnel is not None:
            ssh_tunnel_host_changed = "host" in incoming_ssh_tunnel and incoming_ssh_tunnel[
                "host"
            ] != existing_ssh_tunnel.get("host")

            # Deep-merge: start with existing, overlay incoming top-level keys
            merged_ssh_tunnel = {**existing_ssh_tunnel, **incoming_ssh_tunnel}

            # Check both 'auth' (new format) and 'auth_type' (legacy format from migration 0807)
            existing_auth = (
                (existing_ssh_tunnel or {}).get("auth") or (existing_ssh_tunnel or {}).get("auth_type") or {}
            )
            incoming_auth = (
                (incoming_ssh_tunnel or {}).get("auth") or (incoming_ssh_tunnel or {}).get("auth_type") or {}
            )

            if ssh_tunnel_host_changed and not incoming_auth:
                raise ValidationError("Changing the SSH tunnel host requires re-entering your SSH credentials.")

            if not incoming_auth:
                # No auth in incoming request - preserve entire existing auth
                merged_ssh_tunnel["auth"] = {**existing_auth}
            else:
                # Merge auth, preserving sensitive fields not explicitly provided
                merged_auth = {**incoming_auth}
                if not ssh_tunnel_host_changed:
                    for key in ("password", "passphrase", "private_key"):
                        if existing_auth.get(key) and not incoming_auth.get(key):
                            merged_auth[key] = existing_auth[key]
                merged_ssh_tunnel["auth"] = merged_auth

            new_job_inputs["ssh_tunnel"] = merged_ssh_tunnel

        is_valid, errors = source.validate_config(new_job_inputs)
        if not is_valid:
            raise ValidationError(f"Invalid source config: {', '.join(errors)}")

        # Clearing a multi-schema source's namespace migrates legacy rows to qualified naming.
        old_schema = detect_sql_schema_clear_transition(
            source_type=instance.source_type,
            existing_job_inputs=existing_job_inputs,
            incoming_job_inputs=incoming_job_inputs,
        )
        if old_schema is not None:
            apply_sql_warehouse_schema_clear_migration(instance, old_schema)

        source_config: Config = source.parse_config(new_job_inputs)
        validated_job_inputs = source_config.to_dict()

        # The settings form resubmits the whole connection config on every save, so changing an
        # unrelated setting (auto-syncing new tables, the prefix, the description) re-probed the
        # live connection too — and a momentarily unreachable database then failed the whole save,
        # leaving nothing to do but retry. Compare the parsed config against what's stored so the
        # probe below only runs when the connection actually changed. Direct query sources still
        # probe on every save: the same call refreshes their schemas and connection metadata.
        try:
            stored_job_inputs = source.parse_config(existing_job_inputs).to_dict()
        except Exception:
            # A stored config that no longer parses can't be compared, so treat it as changed and
            # let the probe run rather than skipping validation on a config we can't read.
            stored_job_inputs = None
        connection_config_changed = stored_job_inputs is None or stored_job_inputs != validated_job_inputs

        for key in helpers._CDC_EXPOSED_JOB_INPUT_KEYS:
            if key in existing_job_inputs:
                validated_job_inputs[key] = existing_job_inputs[key]
        validated_data["job_inputs"] = validated_job_inputs

        if job_inputs_were_submitted and (connection_config_changed or instance.is_direct_query):
            effective_api_version = source.resolve_api_version(instance.api_version)
            try:
                if isinstance(source, (PostgresSource, MySQLSource)):
                    credentials_valid, credentials_error = source.validate_credentials_for_access_method(
                        cast(Any, source_config),
                        instance.team_id,
                        instance.access_method,
                        api_version=effective_api_version,
                    )
                elif isinstance(source, CustomSource):
                    # Pass the source being updated so an integration-backed OAuth2 source can only validate
                    # with the integration bound to it — not another source's, whose token the probe would
                    # otherwise mint and send to the submitted manifest host. owner_user_id additionally gates
                    # an as-yet-unbound integration to its creator.
                    credentials_valid, credentials_error = source.validate_credentials(
                        source_config,
                        instance.team_id,
                        source_id=str(instance.pk),
                        owner_user_id=self.context["request"].user.id,
                        api_version=effective_api_version,
                    )
                else:
                    credentials_valid, credentials_error = source.validate_credentials(
                        source_config, instance.team_id, api_version=effective_api_version
                    )
            except Exception as e:
                credentials_valid, credentials_error = helpers._credentials_validation_failed(
                    source, instance.team_id, e
                )
            if not credentials_valid:
                raise ValidationError(credentials_error or helpers.INVALID_CREDENTIALS_FALLBACK_MESSAGE)
            if instance.is_direct_query:
                discovered_schemas = source.get_schemas(
                    source_config, instance.team_id, api_version=effective_api_version
                )
                validated_data["connection_metadata"] = helpers.get_direct_connection_metadata(
                    source_impl=source,
                    source_config=source_config,
                    team_id=instance.team_id,
                    source_model=instance,
                    fallback=instance.connection_metadata,
                )

        if job_inputs_were_submitted and isinstance(source, CustomSource):
            # Credential validation adopts re-entered OAuth2 secrets into the integration row and
            # rewrites the config (pointer set, static secrets cleared) — re-serialize so job_inputs
            # stores the pointer and never the raw secrets.
            validated_job_inputs = source_config.to_dict()
            for key in helpers._CDC_EXPOSED_JOB_INPUT_KEYS:
                if key in existing_job_inputs:
                    validated_job_inputs[key] = existing_job_inputs[key]
            validated_data["job_inputs"] = validated_job_inputs

        # Namespaced-resource sources (GitHub repos) track their schema rows against a resource
        # set in job_inputs; capture the old set before the write so we can reconcile after.
        namespaced_adapter = get_namespaced_resource_adapter(source_type_model)
        old_namespaced_resources: list[str] = []
        if namespaced_adapter is not None and job_inputs_were_submitted:
            old_namespaced_resources = namespaced_adapter.resources_for_job_inputs(existing_job_inputs)

        updated_source: ExternalDataSource = super().update(instance, validated_data)

        if namespaced_adapter is not None and job_inputs_were_submitted:
            # Adds schema rows for added resources, retires removed ones, and reconciles their
            # webhooks. No-op when the effective resource list didn't change.
            namespaced_adapter.reconcile_resources(
                source_model=updated_source,
                team=instance.team,
                old_resources=old_namespaced_resources,
                new_config=source_config,
            )

        if updated_source.is_direct_query and discovered_schemas is not None:
            schema_names = {schema.name: schema.label for schema in discovered_schemas}
            descriptions = {schema.name: schema.description for schema in discovered_schemas}

            with transaction.atomic():
                ExternalDataSource._base_manager.filter(pk=updated_source.pk).select_for_update().get()
                engine = get_direct_query_engine(updated_source.direct_engine)
                name_substitutions = helpers._refresh_name_substitutions(
                    engine, source=updated_source, source_schemas=discovered_schemas, team_id=instance.team_id
                )
                if name_substitutions:
                    schema_names = {name_substitutions.get(name, name): label for name, label in schema_names.items()}
                    descriptions = {
                        name_substitutions.get(name, name): description for name, description in descriptions.items()
                    }
                sync_old_schemas_with_new_schemas(
                    schema_names,
                    source_id=str(updated_source.id),
                    team_id=instance.team_id,
                    descriptions=descriptions,
                )
                # Direct call on the engine adapter (not the source hook) so tests mocking
                # `SourceRegistry.get_source` still exercise the real DataWarehouseTable rebuild.
                if engine is not None:
                    engine.reconcile_schemas(
                        source=updated_source, source_schemas=discovered_schemas, team_id=instance.team_id
                    )

            schemas = list(
                ExternalDataSchema.objects.filter(team_id=instance.team_id, source_id=updated_source.id)
                .exclude(deleted=True)
                # This is the update() response path, which serializes the full column shape
                # (include_columns=True) — building columns reads table.credential.access_key per schema,
                # so keep the credential joined here to avoid an N+1.
                .select_related("table__credential", "table__external_data_source")
                .order_by("name")
            )
            # `get_status`/`get_latest_error` derive the active/errored subset from this prefetch, so no
            # separate `active_schemas` query is needed.
            updated_source_any = cast(Any, updated_source)
            updated_source_any._prefetched_objects_cache = {"schemas": schemas}

        return updated_source


class ExternalDataSourceCreateSerializer(serializers.Serializer):
    source_type = serializers.ChoiceField(
        choices=ExternalDataSourceType.choices,
        help_text="The source type (e.g. 'Postgres', 'Stripe').",
    )
    payload = serializers.DictField(
        help_text=(
            "Connection credentials. Keys depend on source_type. Add a 'schemas' array to pick "
            "which tables sync; omit it and every discovered table syncs with default settings."
        ),
    )
    prefix = serializers.CharField(
        max_length=100,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Prefix added to the table names PostHog creates in HogQL. Does not filter which tables are imported.",
    )
    description = serializers.CharField(
        max_length=400, required=False, allow_null=True, allow_blank=True, help_text="Human-readable description."
    )
    access_method = serializers.ChoiceField(
        choices=ExternalDataSource.AccessMethod.choices,
        required=False,
        default=ExternalDataSource.AccessMethod.WAREHOUSE,
        help_text="Connection mode: 'warehouse' (import) or 'direct' (live query).",
    )
    created_via = serializers.ChoiceField(
        # `wizard` and `self_driving` are intentionally omitted: they are never accepted from a
        # caller (that would let any client self-label as wizard- or self-driving-created). They
        # are derived server-side by upgrading a machine-injected `mcp` value based on the request
        # transport (the wizard, PostHog Desktop, or the wizard's self-driving program).
        choices=[
            ExternalDataSource.CreatedVia.WEB,
            ExternalDataSource.CreatedVia.API,
            ExternalDataSource.CreatedVia.MCP,
        ],
        required=False,
        default=ExternalDataSource.CreatedVia.API,
        help_text=(
            "Where the request came from: `web` for the in-app UI, `api` for direct API callers, "
            "`mcp` for agent/MCP tool calls. `wizard` and `self_driving` cannot be set directly — "
            "they are derived server-side for wizard- and PostHog Desktop-driven MCP calls. Defaults to `api`."
        ),
    )
    direct_query_enabled = serializers.BooleanField(
        required=False,
        default=False,
        help_text=(
            "Whether a synced source should also be live-queryable via direct connection. "
            "Defaults to false; ignored for pure direct-query sources."
        ),
    )
    destination_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        help_text=(
            "Destinations every table on this source writes to. Set here rather than afterwards, "
            "so the opening sync already carries them. Omit to write to the PostHog warehouse only."
        ),
    )


class SourceSetupSerializer(serializers.Serializer):
    source_type = serializers.ChoiceField(
        choices=ExternalDataSourceType.choices,
        help_text="The source type to set up (e.g. 'Stripe', 'Postgres', 'Hubspot').",
    )
    payload = serializers.DictField(
        required=False,
        help_text=(
            "Connection details as flat keys for the source_type (discover required fields with the wizard "
            "tool). Prefer references over raw secrets: pass {'credential_id': <id>} referencing the connection "
            "details the user stored via the connect-link page (discover ids with the stored_credentials "
            "endpoint) — they are merged in server-side and deleted once consumed. An already-connected OAuth "
            "integration can be passed via its id key instead (e.g. {'hubspot_integration_id': 123}). "
            "For source_type 'Custom' (a user-defined REST API) the keys are 'manifest_json' (a stringified "
            "RESTAPIConfig describing client.base_url, auth, and resources) plus the credential for the auth "
            "type the manifest declares — 'auth_token' (bearer), 'auth_api_key' (api_key), or 'auth_password' "
            "(http_basic); keep secrets in these auth_* keys, never inline in the manifest. "
            "A 'schemas' array is NOT required — all discovered tables are enabled automatically with sensible "
            "sync defaults."
        ),
    )
    prefix = serializers.CharField(
        max_length=100,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text=(
            "Prefix added to the table names PostHog creates in HogQL, e.g. 'stripe' produces stripe_charges. "
            "Does not filter which tables are imported. Defaults to the source type."
        ),
    )
    description = serializers.CharField(
        max_length=400, required=False, allow_null=True, allow_blank=True, help_text="Human-readable description."
    )
    direct_query_enabled = serializers.BooleanField(
        required=False,
        default=False,
        help_text=(
            "Whether a synced source should also be live-queryable via direct connection. "
            "Defaults to false; ignored for pure direct-query sources."
        ),
    )


class SourceSetupWebhookSerializer(serializers.Serializer):
    success = serializers.BooleanField(
        help_text=(
            "Whether the webhook was registered with the external service. When true, webhook-capable tables "
            "(including webhook-only ones) sync via real-time webhooks; when false, tables fall back to the "
            "polling sync defaults and webhook-only tables stay disabled."
        )
    )
    webhook_url = serializers.CharField(
        allow_null=True, help_text="The PostHog endpoint the external service delivers events to."
    )
    error = serializers.CharField(
        allow_null=True, help_text="Why webhook registration failed (e.g. the credentials lack webhook permissions)."
    )
    pending_inputs = serializers.ListField(
        child=serializers.CharField(),
        help_text=(
            "Webhook input names the user still needs to provide (e.g. a signing secret the external API did not "
            "return on create). Submit them via the update_webhook_inputs endpoint."
        ),
    )


class SourceSetupResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="ID of the created external data source.")
    webhook = SourceSetupWebhookSerializer(
        required=False,
        help_text=(
            "Outcome of automatic webhook registration. Only present for sources that support webhooks "
            "(e.g. Stripe) and have webhook-capable tables."
        ),
    )


class ExternalDataSourceCreateResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="ID of the created external data source.")


class ExternalDataSourceErrorResponseSerializer(serializers.Serializer):
    message = serializers.CharField(help_text="Human-readable explanation of why the source could not be created.")


class SourceConnectLinkSerializer(serializers.Serializer):
    source_type = serializers.CharField(help_text="The source type the link is for.")
    auth_method = serializers.ChoiceField(
        choices=["oauth", "credentials"],
        help_text=(
            "What the user will do on the connect page: 'oauth' = authorize an account in their browser; "
            "'credentials' = enter connection details (or pick OAuth where the source offers both). Either "
            "way secrets never pass through the agent, and the result is always a stored credential id."
        ),
    )
    connect_url = serializers.CharField(
        help_text=(
            "Full URL to share with the user. It opens the source's connection form in PostHog — "
            "credentials never pass through the agent or the chat."
        )
    )
    instructions = serializers.CharField(help_text="Next steps for the agent to relay to the user.")


class SourceCredentialCreateSerializer(serializers.Serializer):
    source_type = serializers.ChoiceField(
        choices=ExternalDataSourceType.choices,
        help_text="The source type these credentials are for (e.g. 'Stripe', 'Postgres').",
    )
    payload = serializers.DictField(
        help_text=(
            "Connection details as flat keys for the source_type — the same fields the create flow accepts "
            "(host, port, password, API key, …). Checked against a live connection before being stored."
        ),
    )


class SourceCredentialSerializer(serializers.Serializer):
    credential_id = serializers.UUIDField(
        help_text="Stored credential id. Pass to the setup endpoint as {'credential_id': <id>} to create the source."
    )
    source_type = serializers.CharField(help_text="The source type the stored credentials are for.")
    created_at = serializers.DateTimeField(help_text="When the credentials were stored.")
    expires_at = serializers.DateTimeField(
        help_text="When the stored credentials expire. Unconsumed credentials are unusable past this time."
    )


def _find_unresolved_secret_refs(payload: Any) -> list[str]:
    """Return payload keys whose value is an unresolved secret reference.

    The wizard CLI's `wizard_ask` returns sensitive answers as `{"secretRef": "..."}` objects that the
    caller must resolve to real values before they reach PostHog. If one slips through, source creation
    fails downstream with a confusing "invalid credentials"/"invalid API key" error — detect it up front
    so the agent gets an actionable message instead.
    """
    if not isinstance(payload, dict):
        return []
    return [key for key, value in payload.items() if isinstance(value, dict) and "secretRef" in value]


def _unresolved_secret_ref_response(payload: Any) -> Response | None:
    offenders = _find_unresolved_secret_refs(payload)
    if not offenders:
        return None
    return Response(
        status=status.HTTP_400_BAD_REQUEST,
        data={
            "message": (
                f"Unresolved secret reference(s) for: {', '.join(sorted(offenders))}. These fields are still "
                "`{'secretRef': ...}` objects — PostHog cannot resolve them. Resolve the secret to its real "
                "value before calling (or collect credentials via data-warehouse-source-connect-link and pass "
                "the resulting credential_id instead)."
            )
        },
    )


def _find_top_level_oauth_field(config: dict) -> dict | None:
    """Find a top-level OAuth field ({type: 'oauth', kind, name, ...}) in a source config dump.

    Only a top-level OAuth field makes a source OAuth-only (e.g. Hubspot). An OAuth option
    nested inside a select (e.g. Stripe's auth_method) coexists with credential options, so
    those sources route to the credentials connect page — its form still offers the OAuth
    choice alongside API keys.
    """
    for field in config.get("fields") or []:
        if isinstance(field, dict) and field.get("type") == "oauth" and field.get("kind"):
            return field
    return None


class DatabaseSchemaRequestSerializer(serializers.Serializer):
    """Validate credentials and preview available tables from a remote database.

    The request body contains source_type plus flat source-specific credential fields
    (e.g. host, port, database, user, password, schema for Postgres). The credential
    fields vary per source_type and are validated dynamically by the source registry.

    For source_type "Custom" (a user-defined REST API) the body carries `manifest_json`
    (a stringified RESTAPIConfig describing client.base_url, auth, and resources) plus the
    credential for the manifest's declared auth type — `auth_token` (bearer), `auth_api_key`
    (api_key), or `auth_password` (http_basic); keep secrets in these auth_* keys, never
    inline in manifest_json. The returned tables mirror the manifest's resources, with
    detected primary keys and incremental cursors.
    """

    source_type = serializers.ChoiceField(
        choices=ExternalDataSourceType.choices,
        help_text="The source type to validate against.",
    )


class SourcePreviewRequestSerializer(serializers.Serializer):
    source_type = serializers.ChoiceField(
        choices=ExternalDataSourceType.choices,
        help_text="The source type to preview. Only 'Custom' (a user-defined REST API) is supported today.",
    )
    payload = serializers.DictField(
        required=False,
        help_text=(
            "Source config as flat keys. For source_type 'Custom': 'manifest_json' (a stringified RESTAPIConfig "
            "describing client.base_url, auth, and resources) plus the credential for the manifest's declared auth "
            "type — 'auth_token' (bearer), 'auth_api_key' (api_key), or 'auth_password' (http_basic). Secrets stay "
            "in these auth_* keys, never inline in the manifest."
        ),
    )
    resource_name = serializers.CharField(
        help_text="Which manifest resource (table) to read a sample from — one of the resource names in manifest_json.",
    )
    limit = serializers.IntegerField(
        required=False,
        default=PREVIEW_DEFAULT_ROWS,
        min_value=1,
        max_value=PREVIEW_MAX_ROWS,
        help_text=f"Maximum sample rows to return (1–{PREVIEW_MAX_ROWS}). Defaults to {PREVIEW_DEFAULT_ROWS}.",
    )


class SourcePreviewColumnSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Column name as it appears in the previewed rows.")
    type = serializers.CharField(
        help_text="JSON type inferred from the first non-null value: string, integer, number, boolean, object, array, or null."
    )


class SourcePreviewResponseSerializer(serializers.Serializer):
    rows = serializers.ListField(
        child=serializers.DictField(),
        help_text="Up to `limit` sample rows, after data_selector extraction — the raw records the sync would ingest.",
    )
    row_count = serializers.IntegerField(help_text="Number of sample rows returned (≤ limit).")
    columns = SourcePreviewColumnSerializer(
        many=True,
        help_text="Columns observed across the sample rows, each with an inferred JSON type.",
    )
    error = serializers.CharField(
        allow_null=True,
        help_text=(
            "Set when the live read failed (e.g. the host was unreachable or returned an auth error); rows is then "
            "empty. Manifest, validation, and SSRF problems return HTTP 400 instead of populating this field."
        ),
    )


class DraftCustomManifestRequestSerializer(serializers.Serializer):
    source_name = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Optional human name of the API being connected (e.g. 'Acme CRM'). Used only to orient the model.",
    )
    docs_url = serializers.URLField(
        required=False,
        allow_blank=True,
        help_text="URL of the API documentation to read. Provide this or docs_text; fetched server-side via the egress proxy.",
    )
    docs_text = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Raw API documentation or an OpenAPI/Swagger spec, pasted directly. Provide this or docs_url.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        # Strip first: a whitespace-only docs_text is truthy but useless (it'd fetch an empty URL).
        if not ((attrs.get("docs_url") or "").strip() or (attrs.get("docs_text") or "").strip()):
            raise serializers.ValidationError("Provide either docs_url or docs_text.")
        return attrs


class DraftCustomManifestResponseSerializer(serializers.Serializer):
    draft_status = serializers.ChoiceField(
        choices=["ok", "invalid", "model_error"],
        help_text=(
            "'ok' = a manifest validated; 'invalid' = a manifest was drafted but never validated within the budget "
            "(see error; manifest_json holds the last attempt to fix by hand); 'model_error' = the model returned no "
            "usable JSON."
        ),
    )
    manifest_json = serializers.CharField(
        allow_null=True,
        help_text="The drafted RESTAPIConfig manifest as a JSON string (non-secret), or null if none was produced.",
    )
    resource_names = serializers.ListField(
        child=serializers.CharField(),
        help_text="Names of the resources (tables) the validated manifest exposes. Empty unless draft_status is 'ok'.",
    )
    attempts = serializers.IntegerField(
        help_text="How many draft→validate→repair rounds were run.",
    )
    error = serializers.CharField(
        allow_null=True,
        help_text="The last validation error when draft_status is not 'ok'; null on success.",
    )


class SimpleExternalDataSourceSerializers(serializers.ModelSerializer):
    class Meta:
        model = ExternalDataSource
        fields = [
            "id",
            "created_at",
            "created_by",
            "status",
            "source_type",
        ]
        read_only_fields = ["id", "created_by", "created_at", "status", "source_type"]


class IntegrationAccountSerializer(serializers.Serializer):
    """A selectable account/resource exposed by an OAuth integration, in the shared shape every ad
    platform produces (see ``IntegrationAccount`` in the data-imports common module). One serializer
    and one frontend selector work across all platforms."""

    value = serializers.CharField(
        help_text="The identifier stored in the source config and used for API calls (numeric account id as a string, a site url, etc.)."
    )
    display_name = serializers.CharField(help_text="Primary human-readable label for the account.")
    is_primary = serializers.BooleanField(
        help_text="True when this account belongs to the connected user's own (primary) account context, rather than one they merely have access to. Sorted/marked first."
    )
    badges = serializers.ListField(
        child=serializers.CharField(),
        help_text="Short status chips for the account, e.g. ['Active'] or ['Pause'].",
    )
    group = serializers.CharField(
        allow_null=True,
        help_text="Optional grouping label for hierarchical platforms (e.g. the owning customer/manager name).",
    )
    secondary_text = serializers.CharField(
        allow_null=True,
        help_text="Extra identifier shown in parentheses and searchable, e.g. the alphanumeric account number.",
    )


class IntegrationAccountsResponseSerializer(serializers.Serializer):
    accounts = IntegrationAccountSerializer(
        many=True,
        help_text="All accounts the connected integration can access.",
    )


class AccountPickerManagementPermission(TeamMemberAdminManagementPermission):
    """Admin gate for the account picker, with a message the customer can act on.

    The base message names no next step. Free entry stays open on the account field, so a
    member who cannot list accounts can still finish the source by filling the account in.
    """

    message = (
        "You need admin access to this project to list the accounts this connection can reach. "
        "Ask an admin to finish the setup, or fill in the account yourself."
    )


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class ResolvedStoredCredential:
    payload: dict = dataclasses.field(repr=False)
    credential: PendingSourceCredential | None
    error_response: Response | None

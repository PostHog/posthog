"""Viewset for external data schemas."""

from typing import Any, cast

import structlog
import temporalio
from asgiref.sync import async_to_sync
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import filters, status, viewsets
from rest_framework.exceptions import MethodNotAllowed, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.hogql.database.database import Database

from posthog.api.log_entries import LogEntryRequestSerializer, LogEntrySerializer, fetch_log_entries
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.exceptions_capture import capture_exception
from posthog.models.user import User
from posthog.permissions import AccessControlPermission, is_service_auth
from posthog.utils import str_to_bool

from products.access_control.backend.facade.user_access_control import access_level_satisfied_for_resource
from products.data_warehouse.backend.facade.api import (
    cancel_external_data_workflow,
    get_direct_query_engine,
    get_postgres_source_location,
    is_any_external_data_schema_paused,
    is_cdc_enabled_for_team,
    update_external_job_status,
)
from products.warehouse_sources.backend.facade.models import (
    ExternalDataJob,
    ExternalDataSchema,
    ExternalDataSchemaDestination,
    ExternalDataSource,
    resolve_destinations,
    update_sync_type_config_keys,
)
from products.warehouse_sources.backend.facade.pipelines import finish_row_tracking
from products.warehouse_sources.backend.facade.source_management import (
    SourceRegistry,
    get_cdc_adapter,
    purge_buffer_prefix,
)
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType
from products.warehouse_sources.backend.presentation.views.destination_links import (
    DestinationLinkSerializer,
    SchemaDestinationsSerializer,
    set_schema_destinations,
)

from . import serializers, sync

logger = structlog.get_logger(__name__)


class WarehouseTableAccessPermission(AccessControlPermission):
    """Resolves a schema's access through the table it syncs.

    No access control rules are written against a schema, so the base class - which looks for rules
    keyed to the object's own id - finds none and lets everything through. Resolve through the table
    instead (whose access falls back to the source via RESOURCE_FALLBACK_MAP), or the source directly
    before the first sync. The required level still comes from the base class: viewer to read, editor
    to write."""

    def has_object_permission(self, request: Request, view, obj: ExternalDataSchema) -> bool:
        # Service credentials (PSAK/TST) are synthetic users UserAccessControl can't evaluate; they're
        # gated by API scope + project membership. Mirror AccessControlPermission.
        if is_service_auth(request):
            return True
        required_level = self._get_required_access_level(request, view)
        if not required_level:
            return True
        level = view.user_access_control.get_user_access_level(obj.table or obj.source)
        if level is None or not access_level_satisfied_for_resource("warehouse_table", level, required_level):
            self.message = f"You do not have {required_level} access to this table."
            return False
        return True


@extend_schema(extensions={"x-product": "warehouse_sources"})
class ExternalDataSchemaViewset(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "external_data_source"
    permission_classes = [WarehouseTableAccessPermission]
    scope_object_write_actions = [
        "update",
        "partial_update",
        "patch",
        "destroy",
        "reload",
        "resync",
        "cancel",
        "incremental_fields",
        "delete_data",
        "destinations",
    ]
    scope_object_read_actions = ["list", "retrieve", "logs"]
    queryset = ExternalDataSchema.objects.all()
    serializer_class = serializers.ExternalDataSchemaSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["name"]
    ordering = "-created_at"

    def check_object_permissions(self, request: Request, obj: Any) -> None:
        super().check_object_permissions(request, obj)
        if request.method not in ("GET", "HEAD", "OPTIONS") and isinstance(obj, ExternalDataSchema):
            if obj.source.is_system_managed:
                raise PermissionDenied("This schema is managed by PostHog and cannot be changed through this API.")

    @extend_schema(exclude=True)
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        # Schemas are created by source schema discovery, never via the API. ModelViewSet would
        # otherwise route POST here, whose serializer create path skips the api_version guards.
        raise MethodNotAllowed("POST")

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        context["database"] = Database.create_for(team_id=self.team_id, user=cast(User, self.request.user))
        # Only the single-schema retrieve embeds the parent-source summary (see ExternalDataSchemaSerializer.get_source).
        context["include_source"] = self.action == "retrieve"
        return context

    def safely_get_queryset(self, queryset):
        # `table__external_data_source` is read on every schema serialization (SimpleTableSerializer
        # derives the dotted HogQL name from it), and `source` by `get_api_version_deprecation` for
        # any schema carrying a version override — join both for all actions to avoid per-row queries.
        queryset = (
            queryset.exclude(deleted=True)
            .prefetch_related("created_by")
            .select_related("source", "table__external_data_source")
        )
        if self.action == "retrieve":
            # retrieve additionally embeds the table credential.
            queryset = queryset.select_related("table__credential")
        return queryset.order_by(self.ordering)

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        if self.action != "list" or is_service_auth(self.request):
            return queryset
        # A schema has no rules of its own, so the generic queryset filtering can't see its access.
        # Resolve each row the way retrieve does and drop the ones the user can't view - otherwise
        # the list serves names and sync metadata for tables and sources they're denied on.
        schemas = list(queryset)
        uac = self.user_access_control
        uac.preload_object_access_controls([schema.table or schema.source for schema in schemas])
        visible = [
            schema.id
            for schema in schemas
            if (level := uac.get_user_access_level(schema.table or schema.source)) is not None
            and access_level_satisfied_for_resource("warehouse_table", level, "viewer")
        ]
        if len(visible) == len(schemas):
            return queryset
        return queryset.filter(id__in=visible)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance: ExternalDataSchema = self.get_object()

        if instance.table:
            instance.table.soft_delete()
        instance.soft_delete()

        # CDC teardown, both best-effort: leaving the table in the publication makes the
        # customer's WAL carry its changes forever, and the buffer files are raw change data
        # nothing will consume — otherwise they sit until the 14-day lifecycle expiry.
        if instance.sync_type == ExternalDataSchema.SyncType.CDC:
            try:
                source = instance.source
                adapter = get_cdc_adapter(source)
                _, db_schema, source_table_name = get_postgres_source_location(
                    schema_name=instance.name,
                    schema_metadata=instance.schema_metadata,
                    default_schema=(source.job_inputs or {}).get("schema"),
                )
                adapter.remove_table(source, db_schema, source_table_name)
            except Exception:
                logger.exception("Failed to remove deleted CDC schema from publication", schema_id=str(instance.id))
            purge_buffer_prefix(self.team_id, str(instance.id), logger)

        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        request=DestinationLinkSerializer,
        responses={200: SchemaDestinationsSerializer},
    )
    @action(methods=["GET", "PATCH"], detail=True, filter_backends=[])
    def destinations(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Read or replace this table's destination override.

        Send `destination_ids: null` to clear the override so the table follows its source again.
        """
        schema = self.get_object()

        if request.method == "GET":
            links = list(
                ExternalDataSchemaDestination.objects.for_team(self.team_id)
                .filter(schema_id=schema.id, enabled=True)
                .exclude(destination__deleted=True)
            )
            overridden = (
                ExternalDataSchemaDestination.objects.for_team(self.team_id).filter(schema_id=schema.id).exists()
            )
            return Response(
                status=status.HTTP_200_OK,
                data=SchemaDestinationsSerializer(
                    {
                        "destination_ids": [str(link.destination_id) for link in links] if overridden else None,
                        "inherits_from_source": not overridden,
                        "effective_destination_ids": [str(d.id) for d in resolve_destinations(schema)],
                    }
                ).data,
            )

        serializer = DestinationLinkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        attached = set_schema_destinations(
            team_id=self.team_id,
            schema_id=schema.id,
            destination_ids=serializer.validated_data["destination_ids"],
        )
        return Response(
            status=status.HTTP_200_OK,
            data=SchemaDestinationsSerializer(
                {"destination_ids": attached, "inherits_from_source": attached is None}
            ).data,
        )

    @extend_schema(parameters=[LogEntryRequestSerializer])
    @action(methods=["GET"], detail=True, filter_backends=[])
    def logs(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance: ExternalDataSchema = self.get_object()
        param_serializer = LogEntryRequestSerializer(data=request.query_params)
        if not param_serializer.is_valid():
            raise ValidationError(param_serializer.errors)
        params = param_serializer.validated_data
        data = fetch_log_entries(
            team_id=self.team_id,
            log_source="external_data_jobs",
            log_source_id=str(instance.id),
            limit=params["limit"],
            instance_id=params.get("instance_id"),
            after=params.get("after"),
            before=params.get("before"),
            search=params.get("search"),
            level=params["level"].split(",") if params.get("level") else None,
        )
        page = self.paginate_queryset(data)
        if page is not None:
            return self.get_paginated_response(LogEntrySerializer(page, many=True).data)
        return Response(LogEntrySerializer(data, many=True).data)

    @extend_schema(
        request=None,
        description=(
            "Trigger a sync for the schema using its configured sync method. Most methods keep the "
            "existing warehouse table and add or merge new rows, but a full-refresh schema rebuilds "
            "the whole table on every run. To force a rebuild from the source, use resync."
        ),
        responses={
            200: OpenApiResponse(description="The sync was triggered."),
            400: OpenApiResponse(
                response={
                    "type": "object",
                    "properties": {"detail": {"type": "string"}},
                },
                description="The sync could not be started.",
            ),
        },
    )
    @action(methods=["POST"], detail=True)
    def reload(self, request: Request, *args: Any, **kwargs: Any):
        instance: ExternalDataSchema = self.get_object()

        if is_any_external_data_schema_paused(self.team_id):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Monthly sync limit reached. Please increase your billing limit to resume syncing."},
            )

        try:
            sync._trigger_schema_sync(instance)
        except temporalio.service.RPCError as e:
            # Only mark the schema Running once the trigger succeeded: a Running status with no
            # workflow behind it sticks forever (nothing finalizes it) and blocks cancel.
            logger.exception(f"Could not trigger external data job for schema {instance.id}", exc_info=e)
            return Response(
                data={"detail": "Couldn't start the sync. Try again in a few minutes."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            logger.exception(f"Could not trigger external data job for schema {instance.id}", exc_info=e)
            raise

        instance.status = ExternalDataSchema.Status.RUNNING
        instance.save()
        return Response(status=status.HTTP_200_OK)

    @extend_schema(
        request=None,
        description=(
            "Request a full resync of the schema. For sources that can backfill, this drops the "
            "warehouse table and re-imports every row from the source, so existing data is deleted "
            "first. A webhook-only schema cannot backfill, so it keeps its existing table and "
            "resumes ingestion instead. To sync without requesting a rebuild, use reload."
        ),
        responses={
            200: OpenApiResponse(description="The full resync was triggered."),
            400: OpenApiResponse(
                response={
                    "type": "object",
                    "properties": {"detail": {"type": "string"}},
                },
                description="The resync could not be started.",
            ),
        },
    )
    @action(methods=["POST"], detail=True)
    def resync(self, request: Request, *args: Any, **kwargs: Any):
        instance: ExternalDataSchema = self.get_object()

        if is_any_external_data_schema_paused(self.team_id):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Monthly sync limit reached. Please increase your billing limit to resume syncing."},
            )

        latest_running_job = (
            ExternalDataJob.objects.filter(schema_id=instance.pk, team_id=instance.team_id)
            .order_by("-created_at")
            .first()
        )

        if latest_running_job and latest_running_job.workflow_id and latest_running_job.status == "Running":
            cancel_external_data_workflow(latest_running_job.workflow_id)

        cdc_resync = instance.is_cdc
        updates: dict[str, Any] = {"reset_pipeline": True}
        removes: list[str] = []
        if cdc_resync:
            # Reset CDC state so the next run does a full re-snapshot
            updates["cdc_mode"] = "snapshot"
            removes = ["cdc_last_log_position", "cdc_deferred_runs"]

        # Merge under a row lock so this reset can't clobber a concurrent CDC extract activity's
        # sync_type_config writes. Persist BEFORE triggering the workflow so the Postgres source
        # sees cdc_mode="snapshot" when it reloads the schema from DB — otherwise a race: the
        # workflow starts, loads stale "streaming" mode, raises CDCHandledExternally, and the
        # full-refresh never runs.
        # initial_sync_complete is saved in the same transaction as cdc_mode via extra_model_fields
        # so no reader can observe cdc_mode="snapshot" with initial_sync_complete=True.
        extra: dict[str, Any] = {"initial_sync_complete": False} if cdc_resync else {}
        instance.sync_type_config = update_sync_type_config_keys(
            instance.id, instance.team_id, updates=updates, removes=removes, extra_model_fields=extra
        )
        if cdc_resync:
            instance.initial_sync_complete = False

        try:
            sync._trigger_schema_sync(instance)
        except temporalio.service.RPCError as e:
            # Only mark the schema Running once the trigger succeeded: a Running status with no
            # workflow behind it sticks forever (nothing finalizes it) and blocks cancel. The
            # sync_type_config reset above stays; the schema's intent is still "resync next run".
            logger.exception(f"Could not trigger external data job for schema {instance.id}", exc_info=e)
            return Response(
                data={"detail": "Couldn't start the sync. Try again in a few minutes."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        instance.status = ExternalDataSchema.Status.RUNNING
        instance.save(update_fields=["status", "updated_at"])

        return Response(status=status.HTTP_200_OK)

    @extend_schema(
        request=None,
        responses={
            200: OpenApiResponse(
                response={
                    "type": "object",
                    "properties": {"detail": {"type": "string"}},
                },
                description="The running sync was cancelled. v3 pipeline jobs are marked Failed immediately; "
                "for older pipeline versions the cancelled workflow records the final status. When no sync "
                "was actually running but the schema was stuck reporting Running, the schema status is "
                "corrected instead and the response says so.",
            ),
            400: OpenApiResponse(
                response={
                    "type": "object",
                    "properties": {"detail": {"type": "string"}},
                },
                description="No running sync to cancel, or the sync already finished.",
            ),
        },
    )
    @action(methods=["POST"], detail=True)
    def cancel(self, request: Request, *args: Any, **kwargs: Any):
        instance: ExternalDataSchema = self.get_object()

        latest_running_job = (
            ExternalDataJob.objects.filter(schema_id=instance.pk, team_id=instance.team_id)
            .order_by("-created_at")
            .first()
        )

        if not latest_running_job or latest_running_job.status != "Running" or not latest_running_job.workflow_id:
            job_is_running = latest_running_job is not None and latest_running_job.status == "Running"
            # A schema reporting Running with no running job is stale (e.g. a trigger that never
            # started a run): nothing will ever repaint it, so the stop button is the user's only
            # way out. Mirror the latest job's terminal status. CDC halted markers absorb status
            # updates (see update_external_job_status), so honor them here too.
            if instance.status == ExternalDataSchema.Status.RUNNING and not job_is_running and not instance.cdc_halted:
                if latest_running_job is not None:
                    instance.status = ExternalDataSchema.Status(latest_running_job.status)
                    instance.latest_error = latest_running_job.latest_error
                else:
                    instance.status = ExternalDataSchema.Status.FAILED
                instance.save(update_fields=["status", "latest_error", "updated_at"])
                return Response(
                    data={"detail": "No sync was running. The sync status has been updated."},
                    status=status.HTTP_200_OK,
                )
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"detail": "No running sync to cancel."},
            )

        if latest_running_job.pipeline_version != ExternalDataJob.PipelineVersion.V3:
            # v1/v2: normally the workflow handles the cancellation and writes the job's
            # terminal status itself, so the cancel RPC is the whole operation.
            try:
                cancel_external_data_workflow(latest_running_job.workflow_id)
            except temporalio.service.RPCError as e:
                if e.status != temporalio.service.RPCStatusCode.NOT_FOUND:
                    # Transient RPC failure against a possibly-live workflow. The workflow still
                    # owns the terminal status, so leave the job Running and surface the failure.
                    logger.exception(f"Could not cancel external data workflow for schema {instance.id}", exc_info=e)
                    return Response(
                        status=status.HTTP_400_BAD_REQUEST,
                        data={"detail": "Could not cancel the running sync. Please try again."},
                    )
                # The workflow is already gone (e.g. it was terminated rather than cancelled), so it
                # will never run the cleanup that writes the terminal status - the job and schema
                # would stay stuck on Running forever. Write the Failed status ourselves so the
                # schema unsticks and can be synced again.
                logger.info("cancel_sync_v2_workflow_already_gone", schema_id=str(instance.id))
                update_external_job_status(
                    job_id=str(latest_running_job.id),
                    team_id=instance.team_id,
                    status=ExternalDataJob.Status.FAILED,
                    logger=logger,
                    latest_error="Sync cancelled by user",
                )
            return Response(status=status.HTTP_200_OK)

        # v3: durable marker FIRST. Failed is terminal/absorbing, so the loader's later
        # Completed write and the workflow finally-block write become no-ops.
        model = update_external_job_status(
            job_id=str(latest_running_job.id),
            team_id=instance.team_id,
            status=ExternalDataJob.Status.FAILED,
            logger=logger,
            latest_error="Sync cancelled by user",
        )
        if model.status != ExternalDataJob.Status.FAILED:
            # The job reached a different terminal state concurrently (e.g. Completed).
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"detail": "The sync already finished."},
            )

        try:
            cancel_external_data_workflow(latest_running_job.workflow_id)
        except temporalio.service.RPCError as e:
            if e.status == temporalio.service.RPCStatusCode.NOT_FOUND:
                # v3 loading phase: the extraction workflow already completed while the loader
                # drains batches. The Failed marker above makes the loader skip and clean up.
                logger.info("cancel_sync_workflow_already_finished", schema_id=str(instance.id))
            else:
                # Transient RPC failure against a possibly-live workflow. The Failed marker is
                # already durable (terminal statuses absorb the workflow's later writes, and the
                # v3 loader cleans up off the marker), so the cancel stands - but the workflow
                # may keep running until it finishes on its own, so surface the failure.
                logger.exception("cancel_sync_workflow_cancel_rpc_failed", schema_id=str(instance.id))

        try:
            # Clear the schema's in-flight row counter; nothing will finish it once the job is Failed.
            async_to_sync(finish_row_tracking)(instance.team_id, str(instance.id))
        except Exception as e:
            # Best-effort: the counter is rebuilt from scratch by the next sync.
            logger.exception("cancel_sync_row_tracking_cleanup_failed", schema_id=str(instance.id))
            capture_exception(e)

        return Response(status=status.HTTP_200_OK)

    @action(methods=["DELETE"], detail=True)
    def delete_data(self, request: Request, *args: Any, **kwargs: Any):
        instance: ExternalDataSchema = self.get_object()

        if instance.source.is_direct_query:
            direct_engine_adapter = get_direct_query_engine(instance.source.direct_engine)
            if direct_engine_adapter is not None:
                direct_engine_adapter.hide_table(instance.table)
            instance.should_sync = False
            instance.save(update_fields=["should_sync", "updated_at"])
            return Response(status=status.HTTP_200_OK)

        instance.delete_table()

        return Response(status=status.HTTP_200_OK)

    @action(methods=["POST"], detail=True)
    def incremental_fields(self, request: Request, *args: Any, **kwargs: Any):
        instance: ExternalDataSchema = self.get_object()
        source: ExternalDataSource = instance.source

        if not source.job_inputs:
            return Response(status=status.HTTP_400_BAD_REQUEST, data={"message": "Missing job inputs"})

        if not source.source_type:
            return Response(status=status.HTTP_400_BAD_REQUEST, data={"message": "Missing source type"})

        source_type_enum = ExternalDataSourceType(source.source_type)

        new_source = SourceRegistry.get_source(source_type_enum)
        config = new_source.parse_config(source.job_inputs)

        effective_api_version = new_source.resolve_api_version(instance.api_version or source.api_version)
        credentials_valid, credentials_error = new_source.validate_credentials(
            config, self.team_id, instance.name, api_version=effective_api_version
        )
        if not credentials_valid:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": credentials_error or "Invalid credentials"},
            )

        try:
            schemas = new_source.get_schemas(
                config, self.team_id, names=[instance.name], api_version=effective_api_version
            )
        except Exception as e:
            # `validate_credentials` above just probed the same connection successfully, so a
            # failure here that the source itself classifies as non-retryable (e.g. a connect-time
            # timeout, which usually means an unreachable host or unconfigured firewall) is an
            # expected customer/upstream condition, not a bug — don't flood error tracking with it.
            # Mirrors `refresh_schemas`'s `_classify_refresh_schemas_error`.
            error_text = str(e)
            if not any(pattern and pattern in error_text for pattern in new_source.get_non_retryable_errors()):
                capture_exception(e)
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": str(e)},
            )

        if not schemas:
            return Response(
                data={
                    "message": f"Could not discover schema {instance.name}. The connection may be missing SELECT or "
                    "schema access privileges, or discovery may not support this relation type. Check that the "
                    "relation exists, restore read privileges, or expose it as a supported table or view, then try again."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Not every source honors the `names` filter (e.g. Slack returns all schemas regardless), so
        # `schemas` may contain unrelated tables in any order. Pick the one that matches this schema
        # instead of trusting `schemas[0]`, whose metadata could belong to a different table.
        schema = next((s for s in schemas if s.name == instance.name), None)
        if schema is None:
            return Response(
                status=status.HTTP_400_BAD_REQUEST, data={"message": f"Schema with name {instance.name} not found"}
            )

        # job_inputs is an EncryptedJSONField: booleans round-trip as "True"/"False"
        # strings, so bool(...) would treat "False" as truthy. str_to_bool decodes both.
        source_cdc_enabled = str_to_bool(source.job_inputs.get("cdc_enabled"))
        cdc_available = schema.supports_cdc if is_cdc_enabled_for_team(self.team) and source_cdc_enabled else None
        # xmin is source-capability-gated, mirroring the database_schema endpoint.
        xmin_available = (
            schema.supports_xmin
            if SourceRegistry.get_source(ExternalDataSourceType(source.source_type)).supports_xmin
            else None
        )

        data = {
            "incremental_fields": schema.incremental_fields,
            "incremental_available": schema.supports_incremental,
            "append_available": schema.supports_append,
            "cdc_available": cdc_available,
            "xmin_available": xmin_available,
            "full_refresh_available": not schema.webhook_only,
            "supports_webhooks": schema.supports_webhooks,
            "webhook_only": schema.webhook_only,
            "available_columns": [
                {"field": col_name, "label": col_name, "type": col_type, "nullable": nullable}
                for col_name, col_type, nullable in schema.columns
            ],
            "detected_primary_keys": schema.detected_primary_keys,
        }

        return Response(status=status.HTTP_200_OK, data=data)

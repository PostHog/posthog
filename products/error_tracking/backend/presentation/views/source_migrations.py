import asyncio
from typing import cast

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models.user import User
from posthog.temporal.common.client import async_connect

from products.error_tracking.backend.models import ErrorTrackingMigration
from products.error_tracking.backend.temporal.source_migration.base import get_adapter
from products.error_tracking.backend.temporal.source_migration.starter import start_migration_workflow
from products.warehouse_sources.backend.facade import api as warehouse_api

logger = structlog.get_logger(__name__)

ACTIVE_STATUSES = (
    ErrorTrackingMigration.Status.CREATED,
    ErrorTrackingMigration.Status.SYNCING,
    ErrorTrackingMigration.Status.IMPORTING,
    ErrorTrackingMigration.Status.FINALIZING,
)


class MigrationConfigSerializer(serializers.Serializer):
    org_slug = serializers.CharField(
        required=False,
        max_length=200,
        help_text="Source organization identifier. Required for Sentry migrations; namespaces imported "
        "issue fingerprints.",
    )
    date_from = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="Only import source events created at or after this time. Omit to import everything retained.",
    )
    date_to = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="Only import source events created before this time. Omit for no upper bound.",
    )
    issue_statuses = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Only import events belonging to source issues in these statuses (source-specific values, "
        "e.g. Sentry's unresolved/resolved/ignored). Omit to import all issues.",
    )
    sentry_project_slugs = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Sentry only: restrict the import to these project slugs. Omit to import every project.",
    )


class MigrationStateSerializer(serializers.Serializer):
    issues_total = serializers.IntegerField(
        required=False, help_text="Total source issues matched by the migration's filters."
    )
    events_total = serializers.IntegerField(
        required=False, help_text="Total source events matched by the migration's filters."
    )
    events_emitted = serializers.IntegerField(
        required=False, help_text="Events successfully submitted to ingestion so far."
    )
    events_dropped = serializers.IntegerField(
        required=False, help_text="Events dropped by ingestion (for example, exceptions quota exceeded)."
    )


class ErrorTrackingMigrationSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique id of the migration.")
    source_type = serializers.ChoiceField(
        read_only=True,
        choices=ErrorTrackingMigration.SourceType.choices,
        help_text="External error tracker the data is imported from.",
    )
    status = serializers.ChoiceField(
        read_only=True,
        choices=ErrorTrackingMigration.Status.choices,
        help_text="Current phase of the migration.",
    )
    external_data_source_id = serializers.UUIDField(
        read_only=True, help_text="Id of the data warehouse source feeding the migration."
    )
    config = MigrationConfigSerializer(read_only=True, help_text="Source-specific settings and import scope filters.")
    state = MigrationStateSerializer(read_only=True, help_text="Progress counters, updated as the import runs.")
    code_migration_task_id = serializers.UUIDField(
        read_only=True,
        allow_null=True,
        help_text="Id of the code migration agent task, when one was started from this migration.",
    )
    latest_error = serializers.CharField(
        read_only=True, allow_null=True, help_text="Human-readable error when the migration failed."
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When the migration was created.")
    updated_at = serializers.DateTimeField(read_only=True, help_text="When the migration last changed.")


class MigrationCreateRequestSerializer(serializers.Serializer):
    source_type = serializers.ChoiceField(
        choices=ErrorTrackingMigration.SourceType.choices,
        help_text="External error tracker to migrate from.",
    )
    external_data_source_id = serializers.UUIDField(
        help_text="Id of an existing data warehouse source of the matching type to import from. "
        "The schemas the migration reads must be enabled on it."
    )
    config = MigrationConfigSerializer(
        required=False,
        help_text="Source-specific settings and optional import scope filters. Sentry migrations require org_slug.",
    )


class MigrationAttachCodeMigrationSerializer(serializers.Serializer):
    task_id = serializers.UUIDField(help_text="Id of the wizard cloud-run task performing the SDK code migration.")


class ErrorTrackingMigrationViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "error_tracking"
    serializer_class = ErrorTrackingMigrationSerializer

    def _migrations(self):
        return ErrorTrackingMigration.objects.for_team(self.team.id)

    def _get_migration(self, pk: str) -> ErrorTrackingMigration:
        try:
            return self._migrations().get(id=pk)
        except (ErrorTrackingMigration.DoesNotExist, ValueError) as err:
            raise NotFound() from err

    @extend_schema(responses={200: ErrorTrackingMigrationSerializer(many=True)})
    def list(self, request: Request, *args, **kwargs) -> Response:
        migrations = self._migrations().order_by("-created_at")
        page = self.paginate_queryset(list(migrations))
        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return Response(self.get_serializer(migrations, many=True).data)

    @extend_schema(responses={200: ErrorTrackingMigrationSerializer})
    def retrieve(self, request: Request, *args, pk=None, **kwargs) -> Response:
        return Response(self.get_serializer(self._get_migration(pk)).data)

    @validated_request(
        request_serializer=MigrationCreateRequestSerializer,
        responses={201: OpenApiResponse(response=ErrorTrackingMigrationSerializer)},
        summary="Start an error tracking migration",
        description="Imports issues and events from a synced data warehouse source into error tracking.",
    )
    def create(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        data = request.validated_data
        source_id = data["external_data_source_id"]
        adapter = get_adapter(data["source_type"])

        config = {
            key: value.isoformat() if hasattr(value, "isoformat") else value
            for key, value in (data.get("config") or {}).items()
            if value is not None
        }
        config_error = adapter.validate_config(config)
        if config_error is not None:
            raise ValidationError({"config": config_error})

        try:
            source = warehouse_api.get_source(source_id, self.team.id)
        except Exception as err:
            raise ValidationError({"external_data_source_id": "Data warehouse source not found."}) from err
        if source.source_type != adapter.external_source_type:
            raise ValidationError(
                {"external_data_source_id": f"The source must be a {adapter.external_source_type} source."}
            )

        if self._migrations().filter(status__in=ACTIVE_STATUSES).exists():
            raise ValidationError("A migration is already running for this project.")

        migration = ErrorTrackingMigration.objects.create(
            team=self.team,
            created_by=cast(User, request.user),
            source_type=data["source_type"],
            external_data_source_id=source_id,
            config=config,
        )

        try:
            workflow_id, workflow_run_id = asyncio.run(
                start_migration_workflow(migration_id=str(migration.id), team_id=self.team.id)
            )
        except WorkflowAlreadyStartedError as err:
            migration.status = ErrorTrackingMigration.Status.FAILED
            migration.latest_error = "A workflow for this migration already exists."
            migration.save(update_fields=["status", "latest_error", "updated_at"])
            raise ValidationError("A workflow for this migration already exists.") from err

        migration.workflow_id = workflow_id
        migration.workflow_run_id = workflow_run_id
        migration.save(update_fields=["workflow_id", "workflow_run_id", "updated_at"])
        return Response(self.get_serializer(migration).data, status=status.HTTP_201_CREATED)

    @validated_request(
        responses={200: OpenApiResponse(response=ErrorTrackingMigrationSerializer)},
        summary="Cancel an error tracking migration",
    )
    @action(methods=["POST"], detail=True)
    def cancel(self, request: ValidatedRequest, *args, pk=None, **kwargs) -> Response:
        migration = self._get_migration(pk)
        if migration.status not in ACTIVE_STATUSES:
            raise ValidationError("Only a running migration can be cancelled.")
        if migration.workflow_id:
            asyncio.run(_cancel_workflow(migration.workflow_id))
        migration.status = ErrorTrackingMigration.Status.CANCELLED
        migration.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(migration).data)

    @validated_request(
        request_serializer=MigrationAttachCodeMigrationSerializer,
        responses={200: OpenApiResponse(response=ErrorTrackingMigrationSerializer)},
        summary="Attach a code migration task",
        description="Records the wizard cloud-run task that migrates the project's code off the source SDK.",
    )
    @action(methods=["POST"], detail=True)
    def attach_code_migration(self, request: ValidatedRequest, *args, pk=None, **kwargs) -> Response:
        migration = self._get_migration(pk)
        migration.code_migration_task_id = request.validated_data["task_id"]
        migration.save(update_fields=["code_migration_task_id", "updated_at"])
        return Response(self.get_serializer(migration).data)


async def _cancel_workflow(workflow_id: str) -> None:
    client = await async_connect()
    await client.get_workflow_handle(workflow_id).cancel()

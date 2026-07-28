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

from products.error_tracking.backend.models import ErrorTrackingSentryMigration
from products.error_tracking.backend.temporal.sentry_migration.starter import start_sentry_migration_workflow
from products.warehouse_sources.backend.facade import api as warehouse_api

logger = structlog.get_logger(__name__)

ACTIVE_STATUSES = (
    ErrorTrackingSentryMigration.Status.CREATED,
    ErrorTrackingSentryMigration.Status.SYNCING,
    ErrorTrackingSentryMigration.Status.IMPORTING,
    ErrorTrackingSentryMigration.Status.FINALIZING,
)


class SentryMigrationConfigSerializer(serializers.Serializer):
    date_from = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="Only import Sentry events created at or after this time. Omit to import everything retained.",
    )
    date_to = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="Only import Sentry events created before this time. Omit for no upper bound.",
    )
    issue_statuses = serializers.ListField(
        child=serializers.ChoiceField(choices=["unresolved", "resolved", "ignored"]),
        required=False,
        help_text="Only import events belonging to Sentry issues in these statuses. Omit to import all issues.",
    )
    sentry_project_slugs = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Only import events from these Sentry project slugs. Omit to import every project in the org.",
    )


class SentryMigrationStateSerializer(serializers.Serializer):
    issues_total = serializers.IntegerField(
        required=False, help_text="Total Sentry issues matched by the migration's filters."
    )
    events_total = serializers.IntegerField(
        required=False, help_text="Total Sentry events matched by the migration's filters."
    )
    events_emitted = serializers.IntegerField(
        required=False, help_text="Events successfully submitted to ingestion so far."
    )
    events_dropped = serializers.IntegerField(
        required=False, help_text="Events dropped by ingestion (for example, exceptions quota exceeded)."
    )


class ErrorTrackingSentryMigrationSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique id of the migration.")
    status = serializers.ChoiceField(
        read_only=True,
        choices=ErrorTrackingSentryMigration.Status.choices,
        help_text="Current phase of the migration.",
    )
    org_slug = serializers.CharField(read_only=True, help_text="Sentry organization slug the data is imported from.")
    external_data_source_id = serializers.UUIDField(
        read_only=True, help_text="Id of the Sentry data warehouse source feeding the migration."
    )
    config = SentryMigrationConfigSerializer(read_only=True, help_text="Import scope filters.")
    state = SentryMigrationStateSerializer(read_only=True, help_text="Progress counters, updated as the import runs.")
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


class SentryMigrationCreateRequestSerializer(serializers.Serializer):
    external_data_source_id = serializers.UUIDField(
        help_text="Id of an existing Sentry data warehouse source to import from. "
        "The source must have the issues and issue_events schemas enabled."
    )
    org_slug = serializers.CharField(
        max_length=200,
        help_text="Sentry organization slug of the source. Used to namespace imported issue fingerprints.",
    )
    config = SentryMigrationConfigSerializer(
        required=False, help_text="Optional import scope filters. Omit to import everything retained by Sentry."
    )


class SentryMigrationAttachCodeMigrationSerializer(serializers.Serializer):
    task_id = serializers.UUIDField(help_text="Id of the wizard cloud-run task performing the SDK code migration.")


class ErrorTrackingSentryMigrationViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "error_tracking"
    serializer_class = ErrorTrackingSentryMigrationSerializer

    def _migrations(self):
        return ErrorTrackingSentryMigration.objects.for_team(self.team.id)

    def _get_migration(self, pk: str) -> ErrorTrackingSentryMigration:
        try:
            return self._migrations().get(id=pk)
        except (ErrorTrackingSentryMigration.DoesNotExist, ValueError) as err:
            raise NotFound() from err

    @extend_schema(responses={200: ErrorTrackingSentryMigrationSerializer(many=True)})
    def list(self, request: Request, *args, **kwargs) -> Response:
        migrations = self._migrations().order_by("-created_at")
        page = self.paginate_queryset(list(migrations))
        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return Response(self.get_serializer(migrations, many=True).data)

    @extend_schema(responses={200: ErrorTrackingSentryMigrationSerializer})
    def retrieve(self, request: Request, *args, pk=None, **kwargs) -> Response:
        return Response(self.get_serializer(self._get_migration(pk)).data)

    @validated_request(
        request_serializer=SentryMigrationCreateRequestSerializer,
        responses={201: OpenApiResponse(response=ErrorTrackingSentryMigrationSerializer)},
        summary="Start a Sentry migration",
        description="Imports issues and events from a synced Sentry data warehouse source into error tracking.",
    )
    def create(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        data = request.validated_data
        source_id = data["external_data_source_id"]

        try:
            source = warehouse_api.get_source(source_id, self.team.id)
        except Exception as err:
            raise ValidationError({"external_data_source_id": "Data warehouse source not found."}) from err
        if source.source_type != "Sentry":
            raise ValidationError({"external_data_source_id": "The source must be a Sentry source."})

        if self._migrations().filter(status__in=ACTIVE_STATUSES).exists():
            raise ValidationError("A Sentry migration is already running for this project.")

        config = data.get("config") or {}
        migration = ErrorTrackingSentryMigration.objects.create(
            team=self.team,
            created_by=cast(User, request.user),
            external_data_source_id=source_id,
            org_slug=data["org_slug"],
            config={
                key: value.isoformat() if hasattr(value, "isoformat") else value
                for key, value in config.items()
                if value is not None
            },
        )

        try:
            workflow_id, workflow_run_id = asyncio.run(
                start_sentry_migration_workflow(migration_id=str(migration.id), team_id=self.team.id)
            )
        except WorkflowAlreadyStartedError as err:
            migration.status = ErrorTrackingSentryMigration.Status.FAILED
            migration.latest_error = "A workflow for this migration already exists."
            migration.save(update_fields=["status", "latest_error", "updated_at"])
            raise ValidationError("A workflow for this migration already exists.") from err

        migration.workflow_id = workflow_id
        migration.workflow_run_id = workflow_run_id
        migration.save(update_fields=["workflow_id", "workflow_run_id", "updated_at"])
        return Response(self.get_serializer(migration).data, status=status.HTTP_201_CREATED)

    @validated_request(
        responses={200: OpenApiResponse(response=ErrorTrackingSentryMigrationSerializer)},
        summary="Cancel a Sentry migration",
    )
    @action(methods=["POST"], detail=True)
    def cancel(self, request: ValidatedRequest, *args, pk=None, **kwargs) -> Response:
        migration = self._get_migration(pk)
        if migration.status not in ACTIVE_STATUSES:
            raise ValidationError("Only a running migration can be cancelled.")
        if migration.workflow_id:
            asyncio.run(_cancel_workflow(migration.workflow_id))
        migration.status = ErrorTrackingSentryMigration.Status.CANCELLED
        migration.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(migration).data)

    @validated_request(
        request_serializer=SentryMigrationAttachCodeMigrationSerializer,
        responses={200: OpenApiResponse(response=ErrorTrackingSentryMigrationSerializer)},
        summary="Attach a code migration task",
        description="Records the wizard cloud-run task that migrates the project's code off the Sentry SDK.",
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

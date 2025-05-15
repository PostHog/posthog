from rest_framework import serializers, viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.request import Request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.temporal.common.client import sync_connect
from .models import ManagedMigration
from posthog.constants import GENERAL_PURPOSE_TASK_QUEUE
import asyncio
from django.conf import settings


class ManagedMigrationSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = ManagedMigration
        fields = [
            "id",
            "source",
            "start_date",
            "end_date",
            "event_names_mode",
            "event_names",
            "status",
            "created_at",
            "finished_at",
            "last_updated_at",
            "error",
            "created_by",
        ]
        read_only_fields = ["id", "status", "created_at", "finished_at", "last_updated_at", "error", "created_by"]

    def create(self, validated_data):
        request = self.context["request"]
        validated_data["created_by"] = request.user
        validated_data["team_id"] = self.context["team_id"]
        validated_data["status"] = ManagedMigration.Status.STARTING
        validated_data["workflow_id"] = None
        return super().create(validated_data)


class ManagedMigrationViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = ManagedMigration.objects.all()
    serializer_class = ManagedMigrationSerializer
    ordering = "-created_at"

    def safely_get_queryset(self, queryset):
        order = self.request.GET.get("order", None)
        if order:
            queryset = queryset.order_by(order)
        else:
            queryset = queryset.order_by(self.ordering)
        return queryset

    def perform_create(self, serializer):
        migration = serializer.save()

        try:
            client = sync_connect()
            workflow_inputs = {
                "team_id": migration.team.id,
                "api_key": self.request.data["api_key"],
                "secret_key": self.request.data["secret_key"],
                "posthog_api_key": migration.team.api_token,
                "source": migration.source,
                "job_id": str(migration.id),
                "start_date": migration.start_date.isoformat(),
                "end_date": migration.end_date.isoformat(),
                "posthog_domain": settings.SITE_URL,
            }

            workflow_id = f"managed-migration-{migration.id}"
            asyncio.run(
                client.start_workflow(
                    "external-event-job",
                    workflow_inputs,
                    id=workflow_id,
                    task_queue=GENERAL_PURPOSE_TASK_QUEUE,
                )
            )

            migration.workflow_id = workflow_id
            migration.status = ManagedMigration.Status.RUNNING
            migration.save()

        except Exception:
            migration.status = ManagedMigration.Status.FAILED
            migration.error = "Something went wrong starting the migration"
            migration.save()
            raise

    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, *args, **kwargs):
        """Cancel a running migration."""
        migration = self.get_object()

        if migration.status not in [ManagedMigration.Status.RUNNING, ManagedMigration.Status.STARTING]:
            return Response(
                {"error": "Can only cancel running migrations"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Cancel the Temporal workflow if it exists
            if migration.workflow_id:
                client = sync_connect()
                handle = client.get_workflow_handle(workflow_id=migration.workflow_id)
                asyncio.run(handle.cancel())

            # Update migration status
            migration.status = ManagedMigration.Status.CANCELLED
            migration.save()

            return Response({"status": "success"})

        except Exception:
            return Response(
                {"error": "Something went wrong canelling the migration"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

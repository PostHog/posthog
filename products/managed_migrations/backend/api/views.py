from rest_framework import serializers, viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.request import Request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from .models import ManagedMigration


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
        return super().create(validated_data)


class ManagedMigrationViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "managed_migration"
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
        # TODO: Start Temporal workflow here
        migration.status = ManagedMigration.Status.FAILED
        migration.error = "Temporal workflow not yet implemented"
        migration.save()

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
            # TODO: Implement cancel logic
            return Response(
                {"error": "Cancel logic not implemented"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

import threading

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import MessageCategory

from products.workflows.backend.services.customerio_import_service import CustomerIOImportService


class MessageCategorySerializer(serializers.ModelSerializer):
    def validate(self, data):
        if self.instance is None:
            # Ensure key is unique per team for new instances
            if MessageCategory.objects.filter(team_id=self.context["team_id"], key=data["key"], deleted=False).exists():
                raise serializers.ValidationError({"key": "A message category with this key already exists."})
        else:
            if "key" in data and hasattr(self.instance, "key") and data["key"] != self.instance.key:
                raise serializers.ValidationError({"key": "The key field cannot be updated after creation."})
        return data

    class Meta:
        model = MessageCategory
        fields = (
            "id",
            "key",
            "name",
            "description",
            "public_description",
            "category_type",
            "created_at",
            "updated_at",
            "created_by",
            "deleted",
        )
        read_only_fields = (
            "id",
            "created_at",
            "updated_at",
            "created_by",
        )

    def create(self, validated_data):
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)


class CustomerIOImportSerializer(serializers.Serializer):
    """Serializer for Customer.io import request"""

    app_api_key = serializers.CharField(required=True, help_text="Customer.io App API Key")


class MessageCategoryViewSet(
    TeamAndOrgViewSetMixin,
    ForbidDestroyModel,
    viewsets.ModelViewSet,
):
    scope_object = "INTERNAL"

    serializer_class = MessageCategorySerializer
    queryset = MessageCategory.objects.all()

    def safely_get_queryset(self, queryset):
        return queryset.filter(
            deleted=False,
        )

    # Store import service instances for progress tracking
    _import_services = {}

    @action(detail=False, methods=["post"])
    def import_from_customerio(self, request, **kwargs):
        """
        Import subscription topics and preferences from Customer.io
        """
        serializer = CustomerIOImportSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        api_key = serializer.validated_data["app_api_key"]

        # Create import service
        import_service = CustomerIOImportService(team=self.team, api_key=api_key, user=request.user)

        # Store service for progress tracking (use team ID as key)
        import_id = f"{self.team.id}_{request.user.id}"
        self._import_services[import_id] = import_service

        # Start import in a thread for async processing
        def run_import():
            import_service.import_all()

        thread = threading.Thread(target=run_import)
        thread.start()

        # Return immediate response with import ID
        return Response(
            {
                "import_id": import_id,
                "status": "started",
                "message": "Import started. Poll /import_progress for updates.",
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=False, methods=["get"])
    def import_progress(self, request, **kwargs):
        """
        Get progress of Customer.io import
        """
        import_id = request.query_params.get("import_id", f"{self.team.id}_{request.user.id}")

        if import_id not in self._import_services:
            return Response({"error": "No import in progress"}, status=status.HTTP_404_NOT_FOUND)

        import_service = self._import_services[import_id]
        progress = import_service.get_progress()

        # Clean up completed imports
        if progress.get("status") in ["completed", "failed"]:
            # Keep for a bit to allow final status check
            pass

        return Response(progress, status=status.HTTP_200_OK)

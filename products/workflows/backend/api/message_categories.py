from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
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

    @action(detail=False, methods=["post"])
    def import_from_customerio(self, request, **kwargs):
        """
        Import subscription topics and globally unsubscribed users from Customer.io API
        """
        serializer = CustomerIOImportSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        api_key = serializer.validated_data["app_api_key"]

        # Create import service
        import_service = CustomerIOImportService(team=self.team, api_key=api_key, user=request.user)

        # Run import synchronously
        result = import_service.import_api_data()

        # Return the result directly
        return Response(result, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], parser_classes=[MultiPartParser, FormParser])
    def import_preferences_csv(self, request, **kwargs):
        """
        Import customer preferences from CSV file
        Expected CSV columns: id, email, cio_subscription_preferences
        """
        csv_file = request.FILES.get("csv_file")

        if not csv_file:
            return Response({"error": "No file provided"}, status=status.HTTP_400_BAD_REQUEST)

        # Validate file type
        if not csv_file.name.endswith(".csv"):
            return Response({"error": "File must be a CSV"}, status=status.HTTP_400_BAD_REQUEST)

        # Size limit (10MB)
        max_size = 10 * 1024 * 1024
        if csv_file.size > max_size:
            return Response(
                {"error": f"File too large. Maximum size is 10MB, your file is {csv_file.size / (1024*1024):.1f}MB"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        import_service = CustomerIOImportService(team=self.team, api_key=None, user=request.user)

        # Process CSV synchronously (should be fast enough for reasonable file sizes)
        result = import_service.process_preferences_csv(csv_file)

        # Return results including any failed imports
        return Response(result, status=status.HTTP_200_OK)

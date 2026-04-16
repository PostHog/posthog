from django.utils import timezone

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.integration import Integration

from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.optout_sync_config import OptOutSyncConfig
from products.messaging.backend.services.customerio_import_service import CustomerIOImportService


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
        Import subscription topics and globally unsubscribed users from Customer.io API.
        Persists the App API key in Integration(kind="customerio-app").
        If no app_api_key is provided, reuses the stored Integration key.
        """
        api_key = request.data.get("app_api_key")

        if not api_key:
            # Reuse stored key from Integration
            try:
                integration = Integration.objects.get(team_id=self.team_id, kind="customerio-app")
                api_key = integration.sensitive_config.get("app_api_key")
            except Integration.DoesNotExist:
                pass

        if not api_key:
            return Response(
                {"error": "No API key provided and no stored key found."}, status=status.HTTP_400_BAD_REQUEST
            )

        # Persist the API key in Integration before import starts
        integration, _ = Integration.objects.update_or_create(
            team_id=self.team_id,
            kind="customerio-app",
            defaults={
                "sensitive_config": {"app_api_key": api_key},
                "created_by": request.user,
                "errors": "",
            },
        )
        config, _ = OptOutSyncConfig.objects.get_or_create(team_id=self.team_id)
        config.app_integration = integration
        config.save(update_fields=["app_integration"])

        # Create import service
        import_service = CustomerIOImportService(team=self.team, api_key=api_key, user=request.user)

        # Run import synchronously
        result = import_service.import_api_data()

        # Persist import result (success or failure)
        if result.get("status") == "completed":
            config.app_import_result = {
                "status": "completed",
                "imported_at": timezone.now().isoformat(),
                "categories_created": result.get("categories_created", 0),
                "globally_unsubscribed_count": result.get("globally_unsubscribed_count", 0),
            }
        else:
            errors = result.get("errors", [])
            config.app_import_result = {
                "status": "failed",
                "imported_at": timezone.now().isoformat(),
                "error": ", ".join(errors) if errors else "Import failed",
            }
        config.save(update_fields=["app_import_result"])

        # Return the result directly
        return Response(result, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"])
    def optout_sync_config(self, request, **kwargs):
        """
        Get the Customer.io sync configuration state for this team.
        Used by the frontend to derive step completion.
        """
        try:
            config = OptOutSyncConfig.objects.select_related(
                "app_integration",
            ).get(team_id=self.team_id)
        except OptOutSyncConfig.DoesNotExist:
            return Response(
                {
                    "app_integration_id": None,
                    "app_import_result": None,
                    "csv_import_result": None,
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            {
                "app_integration_id": config.app_integration_id,
                "app_import_result": config.app_import_result,
                "csv_import_result": config.csv_import_result,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["delete"])
    def remove_customerio_app_config(self, request, **kwargs):
        """Remove the Customer.io App API integration and reset import state."""
        Integration.objects.filter(team_id=self.team_id, kind="customerio-app").delete()
        try:
            config = OptOutSyncConfig.objects.get(team_id=self.team_id)
            config.app_integration = None
            config.app_import_result = None
            config.save(update_fields=["app_integration", "app_import_result"])
        except OptOutSyncConfig.DoesNotExist:
            pass
        return Response(status=status.HTTP_204_NO_CONTENT)

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
                {"error": f"File too large. Maximum size is 10MB, your file is {csv_file.size / (1024 * 1024):.1f}MB"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        import_service = CustomerIOImportService(team=self.team, api_key=None, user=request.user)

        # Process CSV synchronously (should be fast enough for reasonable file sizes)
        result = import_service.process_preferences_csv(csv_file)

        config, _ = OptOutSyncConfig.objects.get_or_create(team_id=self.team_id)
        if result.get("status") == "completed":
            config.csv_import_result = {
                "status": "completed",
                "imported_at": timezone.now().isoformat(),
                "total_rows": result.get("total_rows", 0),
                "users_with_optouts": result.get("users_with_optouts", 0),
                "users_skipped": result.get("users_skipped", 0),
                "parse_errors": result.get("parse_errors", 0),
            }
        else:
            config.csv_import_result = {
                "status": "failed",
                "imported_at": timezone.now().isoformat(),
                "error": result.get("details", "CSV import failed"),
            }
        config.save(update_fields=["csv_import_result"])

        return Response(result, status=status.HTTP_200_OK)

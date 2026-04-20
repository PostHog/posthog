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
        integration = Integration.objects.filter(team_id=self.team_id, kind="customerio-app").first()
        api_key = request.data.get("app_api_key") or (
            integration.sensitive_config.get("app_api_key") if integration else None
        )

        if not api_key:
            return Response(
                {"error": "No API key provided and no stored key found."}, status=status.HTTP_400_BAD_REQUEST
            )

        if integration and request.data.get("app_api_key"):
            return Response(
                {"error": "Integration already exists. Delete it first to use a different key."},
                status=status.HTTP_409_CONFLICT,
            )

        if not integration:
            integration = Integration.objects.create(
                team_id=self.team_id,
                kind="customerio-app",
                sensitive_config={"app_api_key": api_key},
                created_by=request.user,
                errors="",
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
                "webhook_integration",
                "track_integration",
            ).get(team_id=self.team_id)
        except OptOutSyncConfig.DoesNotExist:
            return Response(
                {
                    "app_integration_id": None,
                    "app_import_result": None,
                    "csv_import_result": None,
                    "webhook_enabled": False,
                    "has_webhook_secret": False,
                    "track_enabled": False,
                    "has_track_credentials": False,
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            {
                "app_integration_id": config.app_integration.id if config.app_integration else None,
                "app_import_result": config.app_import_result,
                "csv_import_result": config.csv_import_result,
                "webhook_enabled": config.webhook_enabled,
                "has_webhook_secret": bool(
                    config.webhook_integration
                    and config.webhook_integration.sensitive_config.get("webhook_signing_secret")
                ),
                "track_enabled": config.track_enabled,
                "has_track_credentials": bool(
                    config.track_integration
                    and config.track_integration.sensitive_config.get("site_id")
                    and config.track_integration.sensitive_config.get("api_key")
                ),
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

    @action(detail=False, methods=["post"])
    def save_webhook_config(self, request, **kwargs):
        """
        Save webhook signing secret and/or toggle the Customer.io webhook sync.

        Accepts:
          - webhook_signing_secret (optional): set on first creation only
          - webhook_enabled (required): enable or disable the webhook
        """
        signing_secret = request.data.get("webhook_signing_secret")
        enabled = bool(request.data.get("webhook_enabled", False))

        integration = Integration.objects.filter(team_id=self.team_id, kind="customerio-webhook").first()

        if integration and signing_secret:
            return Response(
                {"error": "Integration already exists. Delete it first to use a different secret."},
                status=status.HTTP_409_CONFLICT,
            )

        if enabled and not integration and not signing_secret:
            return Response(
                {"error": "Webhook signing secret is required to enable sync."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not integration and signing_secret:
            integration = Integration.objects.create(
                team_id=self.team_id,
                kind="customerio-webhook",
                sensitive_config={"webhook_signing_secret": signing_secret},
                created_by=request.user,
                errors="",
            )

        config, _ = OptOutSyncConfig.objects.get_or_create(team_id=self.team_id)
        config.webhook_integration = integration
        config.webhook_enabled = enabled
        config.save(update_fields=["webhook_integration", "webhook_enabled"])

        has_webhook_secret = bool(integration and integration.sensitive_config.get("webhook_signing_secret"))
        return Response(
            {
                "webhook_enabled": enabled,
                "has_webhook_secret": has_webhook_secret,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["delete"])
    def remove_webhook_config(self, request, **kwargs):
        """Remove the Customer.io webhook integration and reset inbound sync state."""
        Integration.objects.filter(team_id=self.team_id, kind="customerio-webhook").delete()
        try:
            config = OptOutSyncConfig.objects.get(team_id=self.team_id)
            config.webhook_integration = None
            config.webhook_enabled = False
            config.save(update_fields=["webhook_integration", "webhook_enabled"])
        except OptOutSyncConfig.DoesNotExist:
            pass
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["post"])
    def save_track_config(self, request, **kwargs):
        """
        Save Customer.io Track API credentials and/or toggle outbound sync.

        Accepts:
          - site_id (optional): set on first creation only
          - api_key (optional): set on first creation only
          - region (optional): "us" or "eu", set on first creation only
          - track_enabled (required): enable or disable outbound sync
        """
        site_id = request.data.get("site_id")
        api_key = request.data.get("api_key")
        region = request.data.get("region", "us")
        enabled = bool(request.data.get("track_enabled", False))
        has_new_creds = bool(site_id and api_key)

        integration = Integration.objects.filter(team_id=self.team_id, kind="customerio-track").first()

        if integration and has_new_creds:
            return Response(
                {"error": "Integration already exists. Delete it first to use different credentials."},
                status=status.HTTP_409_CONFLICT,
            )

        if enabled and not integration and not has_new_creds:
            return Response(
                {"error": "Site ID and API key are required to enable outbound sync."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not integration and has_new_creds:
            integration = Integration.objects.create(
                team_id=self.team_id,
                kind="customerio-track",
                sensitive_config={"site_id": site_id, "api_key": api_key},
                config={"region": region},
                created_by=request.user,
                errors="",
            )

        config, _ = OptOutSyncConfig.objects.get_or_create(team_id=self.team_id)
        config.track_integration = integration
        config.track_enabled = enabled
        config.save(update_fields=["track_integration", "track_enabled"])

        has_track_credentials = bool(
            integration and integration.sensitive_config.get("site_id") and integration.sensitive_config.get("api_key")
        )
        return Response(
            {
                "track_enabled": enabled,
                "has_track_credentials": has_track_credentials,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["delete"])
    def remove_track_config(self, request, **kwargs):
        """Remove the Customer.io Track API integration and reset outbound sync state."""
        Integration.objects.filter(team_id=self.team_id, kind="customerio-track").delete()
        try:
            config = OptOutSyncConfig.objects.get(team_id=self.team_id)
            config.track_integration = None
            config.track_enabled = False
            config.save(update_fields=["track_integration", "track_enabled"])
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

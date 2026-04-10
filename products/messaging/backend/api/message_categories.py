from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.integration import Integration

from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.services.customerio_import_service import CustomerIOImportService
from products.messaging.backend.services.customerio_sync_service import CUSTOMERIO_INTEGRATION_KIND, get_sync_config


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


class CustomerIOSyncConfigSerializer(serializers.Serializer):
    """Serializer for configuring bi-directional Customer.io unsubscribe sync.

    All fields are optional on update — only provided fields are overwritten so the caller
    can e.g. rotate the webhook secret without re-submitting the Track API key.
    """

    site_id = serializers.CharField(
        required=False,
        allow_blank=False,
        help_text="Customer.io Site ID (Settings > API Credentials > Track API Keys)",
    )
    track_api_key = serializers.CharField(
        required=False,
        allow_blank=False,
        write_only=True,
        help_text="Customer.io Track API Key — used to push outbound unsubscribes",
    )
    webhook_signing_secret = serializers.CharField(
        required=False,
        allow_blank=False,
        write_only=True,
        help_text="Shared secret used to sign incoming Customer.io reporting webhooks",
    )
    region = serializers.ChoiceField(choices=["us", "eu"], required=False, default="us")


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

    @action(detail=False, methods=["get", "post"], url_path="customerio_sync")
    def customerio_sync(self, request, **kwargs):
        """Read or update the Customer.io sync configuration for the current team.

        GET returns the non-sensitive fields of the configuration (if any) and whether
        outbound/inbound sync are enabled. POST creates or updates the stored credentials.

        Credentials are stored on the shared ``Integration`` model with ``kind="customerio"``
        so they share the same encrypted-at-rest storage as other third-party integrations.
        """
        if request.method == "GET":
            config = get_sync_config(self.team.id)
            if config is None:
                return Response(
                    {"configured": False, "outbound_enabled": False, "webhook_configured": False},
                    status=status.HTTP_200_OK,
                )
            return Response(
                {
                    "configured": True,
                    "site_id": config.site_id,
                    "region": config.region,
                    "outbound_enabled": config.outbound_enabled,
                    "webhook_configured": bool(config.webhook_signing_secret),
                    "webhook_url": request.build_absolute_uri(f"/webhooks/customerio/{self.team.id}/"),
                },
                status=status.HTTP_200_OK,
            )

        serializer = CustomerIOSyncConfigSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        integration, _ = Integration.objects.get_or_create(
            team_id=self.team.id,
            kind=CUSTOMERIO_INTEGRATION_KIND,
            integration_id=None,
            defaults={
                "config": {},
                "sensitive_config": {},
                "created_by": request.user,
            },
        )
        # Only overwrite fields that were supplied in the request — this lets callers
        # rotate a single credential without re-sending the others.
        config_updates: dict = {}
        if "site_id" in data:
            config_updates["site_id"] = data["site_id"]
        if "region" in data:
            config_updates["region"] = data["region"]
        if config_updates:
            integration.config = {**(integration.config or {}), **config_updates}

        sensitive_updates: dict = {}
        if "track_api_key" in data:
            sensitive_updates["track_api_key"] = data["track_api_key"]
        if "webhook_signing_secret" in data:
            sensitive_updates["webhook_signing_secret"] = data["webhook_signing_secret"]
        if sensitive_updates:
            integration.sensitive_config = {**(integration.sensitive_config or {}), **sensitive_updates}

        integration.save()

        refreshed = get_sync_config(self.team.id)
        response_body = {
            "configured": True,
            "site_id": refreshed.site_id if refreshed else None,
            "region": refreshed.region if refreshed else "us",
            "outbound_enabled": refreshed.outbound_enabled if refreshed else False,
            "webhook_configured": bool(refreshed.webhook_signing_secret) if refreshed else False,
            "webhook_url": request.build_absolute_uri(f"/webhooks/customerio/{self.team.id}/"),
        }
        return Response(response_body, status=status.HTTP_200_OK)

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

        # Return results including any failed imports
        return Response(result, status=status.HTTP_200_OK)

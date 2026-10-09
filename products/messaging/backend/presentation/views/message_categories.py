from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.messaging.backend.facade.customerio import (
    CustomerIOConfigConflict,
    CustomerIOConfigIncomplete,
    get_sync_config_state,
    import_from_customerio,
    import_preferences_csv,
    remove_app_config,
    remove_track_config,
    remove_webhook_config,
    save_track_config,
    save_webhook_config,
)
from products.messaging.backend.models.message_category import MessageCategory


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
        try:
            result = import_from_customerio(self.team_id, request.data.get("app_api_key"), request.user.id)
        except CustomerIOConfigIncomplete as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except CustomerIOConfigConflict as e:
            return Response({"error": str(e)}, status=status.HTTP_409_CONFLICT)

        # Return the result directly
        return Response(result, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"])
    def optout_sync_config(self, request, **kwargs):
        """
        Get the Customer.io sync configuration state for this team.
        Used by the frontend to derive step completion.
        """
        state = get_sync_config_state(self.team_id)
        return Response(
            {
                "app_integration_id": state.app_integration_id,
                "app_import_result": state.app_import_result,
                "csv_import_result": state.csv_import_result,
                "webhook_enabled": state.webhook_enabled,
                "has_webhook_secret": state.has_webhook_secret,
                "track_enabled": state.track_enabled,
                "has_track_credentials": state.has_track_credentials,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["delete"])
    def remove_customerio_app_config(self, request, **kwargs):
        """Remove the Customer.io App API integration and reset import state."""
        remove_app_config(self.team_id)
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

        try:
            state = save_webhook_config(self.team_id, signing_secret, enabled, request.user.id)
        except CustomerIOConfigConflict as e:
            return Response({"error": str(e)}, status=status.HTTP_409_CONFLICT)
        except CustomerIOConfigIncomplete as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "webhook_enabled": state.webhook_enabled,
                "has_webhook_secret": state.has_webhook_secret,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["delete"])
    def remove_webhook_config(self, request, **kwargs):
        """Remove the Customer.io webhook integration and reset inbound sync state."""
        remove_webhook_config(self.team_id)
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

        try:
            state = save_track_config(self.team_id, site_id, api_key, region, enabled, request.user.id)
        except CustomerIOConfigConflict as e:
            return Response({"error": str(e)}, status=status.HTTP_409_CONFLICT)
        except CustomerIOConfigIncomplete as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "track_enabled": state.track_enabled,
                "has_track_credentials": state.has_track_credentials,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["delete"])
    def remove_track_config(self, request, **kwargs):
        """Remove the Customer.io Track API integration and reset outbound sync state."""
        remove_track_config(self.team_id)
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

        result = import_preferences_csv(self.team_id, csv_file, request.user.id)

        return Response(result, status=status.HTTP_200_OK)

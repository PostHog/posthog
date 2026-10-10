from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.messaging.backend.facade.categories import (
    MESSAGE_CATEGORY_TYPE_CHOICES,
    MessageCategoryMissing,
    MessageCategoryRow,
    category_key_in_use,
    create_category,
    get_category,
    list_categories,
    update_category,
)
from products.messaging.backend.facade.customerio import (
    CustomerIOConfigConflict,
    CustomerIOConfigIncomplete,
    SyncConfigState,
    TrackConfigState,
    WebhookConfigState,
    get_sync_config_state,
    import_from_customerio,
    import_preferences_csv,
    remove_app_config,
    remove_track_config,
    remove_webhook_config,
    save_track_config,
    save_webhook_config,
)


class MessageCategorySerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    key = serializers.CharField(max_length=64)
    name = serializers.CharField(max_length=128)
    description = serializers.CharField(allow_blank=True, required=False, style={"base_template": "textarea.html"})
    public_description = serializers.CharField(
        allow_blank=True, required=False, style={"base_template": "textarea.html"}
    )
    category_type = serializers.ChoiceField(choices=MESSAGE_CATEGORY_TYPE_CHOICES, required=False)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)
    created_by = serializers.IntegerField(source="created_by_id", read_only=True, allow_null=True)
    deleted = serializers.BooleanField(required=False)

    def validate(self, data):
        if self.instance is None:
            # Ensure key is unique per team for new instances
            if category_key_in_use(self.context["team_id"], data["key"]):
                raise serializers.ValidationError({"key": "A message category with this key already exists."})
        else:
            if "key" in data and hasattr(self.instance, "key") and data["key"] != self.instance.key:
                raise serializers.ValidationError({"key": "The key field cannot be updated after creation."})
        return data


class CustomerIOImportSerializer(serializers.Serializer):
    """Serializer for Customer.io import request"""

    app_api_key = serializers.CharField(required=True, help_text="Customer.io App API Key")


class SyncConfigStateSerializer(DataclassSerializer):
    class Meta:
        dataclass = SyncConfigState


class WebhookConfigStateSerializer(DataclassSerializer):
    class Meta:
        dataclass = WebhookConfigState


class TrackConfigStateSerializer(DataclassSerializer):
    class Meta:
        dataclass = TrackConfigState


CATEGORY_ID_PARAMETER = OpenApiParameter(
    name="id",
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.PATH,
    description="A UUID string identifying this message category.",
)


@extend_schema_view(
    retrieve=extend_schema(parameters=[CATEGORY_ID_PARAMETER]),
    update=extend_schema(parameters=[CATEGORY_ID_PARAMETER]),
    partial_update=extend_schema(parameters=[CATEGORY_ID_PARAMETER]),
    destroy=extend_schema(parameters=[CATEGORY_ID_PARAMETER]),
)
class MessageCategoryViewSet(
    TeamAndOrgViewSetMixin,
    ForbidDestroyModel,
    viewsets.ModelViewSet,
):
    scope_object = "INTERNAL"

    serializer_class = MessageCategorySerializer

    def _category(self) -> MessageCategoryRow:
        # INTERNAL scope has no object-level access rules, so a team-scoped lookup is the whole check.
        try:
            return get_category(self.team_id, self.kwargs["pk"])
        except MessageCategoryMissing:
            raise NotFound()

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        categories = list_categories(self.team_id)
        # The paginator only needs len() and slicing, which the facade's sequence provides.
        page = self.paginate_queryset(categories)
        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return Response(self.get_serializer(categories, many=True).data)

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(self.get_serializer(self._category()).data)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        category = create_category(self.team_id, request.user.id, serializer.validated_data)
        data = self.get_serializer(category).data
        return Response(data, status=status.HTTP_201_CREATED, headers=self.get_success_headers(data))

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        partial = kwargs.pop("partial", False)
        category = self._category()
        serializer = self.get_serializer(category, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        updated = update_category(self.team_id, category.id, serializer.validated_data)
        return Response(self.get_serializer(updated).data)

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
        return Response(SyncConfigStateSerializer(state).data, status=status.HTTP_200_OK)

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

        return Response(WebhookConfigStateSerializer(state).data, status=status.HTTP_200_OK)

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

        return Response(TrackConfigStateSerializer(state).data, status=status.HTTP_200_OK)

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

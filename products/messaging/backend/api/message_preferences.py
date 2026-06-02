from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.plugins import plugin_server_api

from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.message_preferences import (
    ALL_MESSAGE_PREFERENCE_CATEGORY_ID,
    MessageRecipientPreference,
    PreferenceStatus,
)


class OptOutsPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class MessagePreferencesSerializer(serializers.ModelSerializer):
    identifier = serializers.CharField(help_text="The recipient identifier (e.g. email address).")
    updated_at = serializers.DateTimeField(help_text="When the preference was last updated.")
    preferences = serializers.JSONField(help_text="Map of category ID to preference status.")

    class Meta:
        model = MessageRecipientPreference
        fields = [
            "id",
            "identifier",
            "updated_at",
            "preferences",
        ]
        read_only_fields = [
            "id",
            "identifier",
            "created_at",
            "updated_at",
            "created_by",
        ]


class AddOptOutRequestSerializer(serializers.Serializer):
    identifier = serializers.CharField(
        max_length=512,
        help_text="The recipient identifier to opt out (e.g. email address).",
    )
    category_key = serializers.CharField(
        required=False,
        help_text="Optional message category key. If omitted, the recipient is opted out of all marketing messages.",
    )


class MessagePreferencesViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"
    serializer_class = _FallbackSerializer

    @action(detail=False, methods=["get"])
    def opt_outs(self, request, **kwargs):
        """Get opt-outs filtered by category or overall opt-outs if no category specified"""
        category_key = request.query_params.get("category_key")

        if category_key:
            # Get opt-outs for a specific category
            try:
                category = MessageCategory.objects.get(key=category_key, team_id=self.team_id)
            except MessageCategory.DoesNotExist:
                return Response({"error": "Category not found"}, status=404)

        # Find recipients who have opted out of this specific category, or use the derived $all category if no specific category is provided
        category_id = category.id if category_key else ALL_MESSAGE_PREFERENCE_CATEGORY_ID
        query_filters = {}

        query_filters[f"preferences__{str(category_id)}"] = PreferenceStatus.OPTED_OUT.value

        opt_outs = MessageRecipientPreference.objects.filter(
            team_id=self.team_id,
            **query_filters,
        ).order_by("-updated_at")  # Order by most recently updated first

        # Apply pagination
        paginator = OptOutsPagination()
        page = paginator.paginate_queryset(opt_outs, request)
        if page is not None:
            serializer = MessagePreferencesSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

        # Fallback if pagination fails for some reason
        serializer = MessagePreferencesSerializer(opt_outs, many=True)
        return Response(serializer.data)

    @extend_schema(
        request=AddOptOutRequestSerializer,
        responses={201: MessagePreferencesSerializer},
        summary="Manually add a recipient to the opt-out list",
    )
    @action(detail=False, methods=["post"])
    def add_opt_out(self, request, **kwargs):
        """Manually add a recipient to the opt-out list for a specific category or all marketing messages."""
        serializer = AddOptOutRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        identifier = serializer.validated_data["identifier"]
        category_key = serializer.validated_data.get("category_key")

        if category_key:
            try:
                category = MessageCategory.objects.get(key=category_key, team_id=self.team_id)
            except MessageCategory.DoesNotExist:
                return Response({"error": "Category not found"}, status=status.HTTP_404_NOT_FOUND)
            category_id = str(category.id)
        else:
            category_id = ALL_MESSAGE_PREFERENCE_CATEGORY_ID

        preference, created = MessageRecipientPreference.objects.get_or_create(
            team_id=self.team_id,
            identifier=identifier,
            defaults={"created_by": request.user},
        )
        preference.set_preference(category_id, PreferenceStatus.OPTED_OUT)

        response_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(MessagePreferencesSerializer(preference).data, status=response_status)

    @action(detail=False, methods=["get"])
    def webhook_url(self, request, **kwargs):
        """Return the webhook URL for Customer.io integration setup."""
        base = request.build_absolute_uri("/")[:-1]
        return Response({"url": f"{base}/api/environments/{self.team_id}/messaging/customerio/webhook/"})

    @action(detail=False, methods=["post"])
    def generate_link(self, request, **kwargs):
        """Generate an unsubscribe link for the current user's email address"""
        user = request.user
        if not user or not user.email:
            return Response({"error": "User email not found"}, status=400)

        identifier = request.data.get("recipient", user.email)

        token = plugin_server_api.generate_messaging_preferences_token(self.team_id, identifier)

        # Build the full URL
        preferences_url = f"{request.build_absolute_uri('/')[:-1]}/messaging-preferences/{token}/"

        return Response(
            {
                "preferences_url": preferences_url,
            }
        )

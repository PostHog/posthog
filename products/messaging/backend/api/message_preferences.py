import re

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.streaming import streaming_response
from posthog.plugins import plugin_server_api

from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.message_preferences import (
    ALL_MESSAGE_PREFERENCE_CATEGORY_ID,
    MessageRecipientPreference,
    PreferenceStatus,
)
from products.messaging.backend.services.opt_out_service import BulkOptOutEntry, OptOutService, UnknownCategoryError

MAX_BULK_OPT_OUT_ENTRIES = 1000
UNSAFE_FILENAME_CHARACTERS = re.compile(r"[^A-Za-z0-9_-]+")


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


class MessagingErrorSerializer(serializers.Serializer):
    error = serializers.CharField(help_text="Human-readable description of what went wrong.")


class PaginatedOptOutsSerializer(serializers.Serializer):
    """OpenAPI shape for the paginated opt-outs response, so the generated clients get the
    {count, next, previous, results} envelope instead of an untyped object."""

    count = serializers.IntegerField(help_text="Total number of opted-out recipients for the category.")
    next = serializers.URLField(allow_null=True, help_text="URL for the next page, or null on the last page.")
    previous = serializers.URLField(allow_null=True, help_text="URL for the previous page, or null on the first page.")
    results = MessagePreferencesSerializer(many=True)


class BulkOptOutEntrySerializer(serializers.Serializer):
    identifier = serializers.CharField(
        max_length=512,
        help_text="The recipient identifier to opt out (e.g. email address).",
    )
    category_key = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Message category key for this recipient. Overrides the request-level category_key.",
    )


class BulkAddOptOutsRequestSerializer(serializers.Serializer):
    opt_outs = BulkOptOutEntrySerializer(
        many=True,
        allow_empty=False,
        help_text=f"Recipients to opt out, at most {MAX_BULK_OPT_OUT_ENTRIES} per request.",
    )
    category_key = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Message category key applied to entries without their own. If omitted, recipients are opted out of all marketing messages.",
    )

    def validate_opt_outs(self, value: list[dict]) -> list[dict]:
        if len(value) > MAX_BULK_OPT_OUT_ENTRIES:
            raise serializers.ValidationError(f"Send at most {MAX_BULK_OPT_OUT_ENTRIES} opt-outs per request.")
        return value


class BulkAddOptOutsResultSerializer(serializers.Serializer):
    total = serializers.IntegerField(help_text="Number of opt-out entries received.")
    opted_out = serializers.IntegerField(help_text="Number of recipient and category pairs recorded as opted out.")
    skipped = serializers.IntegerField(help_text="Number of entries skipped because their category_key doesn't exist.")
    # The metaclass pops declared fields off the class, so this doesn't actually shadow
    # Serializer.errors at runtime — mypy just can't see that.
    errors = serializers.ListField(  # type: ignore[assignment]
        child=serializers.CharField(),
        help_text="The first few entry-level problems, so the caller can fix their list.",
    )


class MessagePreferencesViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "hog_flow"
    # Only the opt-out list endpoints are reachable with API keys (and therefore MCP);
    # webhook_url and generate_link stay session-only by being listed in neither.
    scope_object_read_actions = ["opt_outs", "export_opt_outs_csv"]
    scope_object_write_actions = ["add_opt_out", "bulk_add_opt_outs"]
    serializer_class = _FallbackSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="category_key",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Message category key to list opt-outs for. If omitted, lists recipients opted out of all marketing messages.",
            ),
            OpenApiParameter(name="page", type=OpenApiTypes.INT, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="page_size", type=OpenApiTypes.INT, location=OpenApiParameter.QUERY, required=False),
        ],
        responses={
            200: PaginatedOptOutsSerializer,
            404: OpenApiResponse(response=MessagingErrorSerializer),
        },
        summary="List recipients opted out of a message category",
    )
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

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="category_key",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Message category key to export. If omitted, exports recipients opted out of all marketing messages.",
            )
        ],
        responses={
            (200, "text/csv"): OpenApiTypes.STR,
            404: OpenApiResponse(response=MessagingErrorSerializer),
        },
        summary="Download the opt-out list as a CSV file",
    )
    @action(detail=False, methods=["get"])
    def export_opt_outs_csv(self, request, **kwargs):
        """Stream the opt-out list for a category as a CSV file that can be re-imported as-is."""
        category_key = request.query_params.get("category_key")
        service = OptOutService(team_id=self.team_id, user=request.user)

        try:
            rows = service.export_rows(category_key)
        except UnknownCategoryError as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)

        filename_suffix = (
            UNSAFE_FILENAME_CHARACTERS.sub("-", category_key).strip("-") if category_key else "all-marketing"
        )
        return streaming_response(
            rows,
            content_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="opt-outs-{filename_suffix or "category"}.csv"'},
        )

    @extend_schema(
        request=BulkAddOptOutsRequestSerializer,
        responses={
            200: BulkAddOptOutsResultSerializer,
            404: OpenApiResponse(response=MessagingErrorSerializer),
        },
        summary="Add multiple recipients to the opt-out list",
    )
    @action(detail=False, methods=["post"])
    def bulk_add_opt_outs(self, request, **kwargs):
        """Opt every recipient in the list out of the category named on their entry, or a default category."""
        serializer = BulkAddOptOutsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        entries = [
            BulkOptOutEntry(identifier=entry["identifier"], category_key=entry.get("category_key") or None)
            for entry in serializer.validated_data["opt_outs"]
        ]

        service = OptOutService(team_id=self.team_id, user=request.user)
        try:
            result = service.opt_out_recipients(entries, serializer.validated_data.get("category_key") or None)
        except UnknownCategoryError as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)

        return Response(BulkAddOptOutsResultSerializer(result).data, status=status.HTTP_200_OK)

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

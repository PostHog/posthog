import csv
from datetime import UTC, datetime

from django.db.models import QuerySet
from django.http import HttpResponse

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request
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
    identifier = serializers.CharField(help_text="Recipient identifier (typically an email address).")
    updated_at = serializers.DateTimeField(help_text="When this recipient's preferences were last updated.")
    preferences = serializers.JSONField(
        help_text=(
            "Mapping of category id (or `$all` for the global marketing bucket) to one of "
            "`OPTED_IN`, `OPTED_OUT`, or `NO_PREFERENCE`."
        ),
    )

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


class MessagePreferencesViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"
    serializer_class = _FallbackSerializer

    def _get_opt_outs_queryset(
        self, request: Request
    ) -> tuple[QuerySet[MessageRecipientPreference] | None, Response | None, MessageCategory | None]:
        """Build the opt-out queryset shared by `opt_outs` and `export_opt_outs`.

        Returns ``(queryset, error_response, category)``. On error (e.g. unknown
        ``category_key``), the queryset is ``None`` and a ready-to-return DRF
        ``Response`` is provided instead.
        """
        category_key = request.query_params.get("category_key")
        category: MessageCategory | None = None

        if category_key:
            try:
                category = MessageCategory.objects.get(key=category_key, team_id=self.team_id)
            except MessageCategory.DoesNotExist:
                return None, Response({"error": "Category not found"}, status=404), None

        # Use the specific category id if provided, otherwise the derived $all bucket
        category_id = category.id if category else ALL_MESSAGE_PREFERENCE_CATEGORY_ID
        query_filters = {f"preferences__{str(category_id)}": PreferenceStatus.OPTED_OUT.value}

        queryset = MessageRecipientPreference.objects.filter(
            team_id=self.team_id,
            **query_filters,
        ).order_by("-updated_at")
        return queryset, None, category

    @action(detail=False, methods=["get"])
    def opt_outs(self, request, **kwargs):
        """Get opt-outs filtered by category or overall opt-outs if no category specified"""
        opt_outs, error, _category = self._get_opt_outs_queryset(request)
        if error is not None:
            return error
        assert opt_outs is not None

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
        parameters=[
            OpenApiParameter(
                name="category_key",
                description=(
                    "Optional category key. When omitted, exports recipients who opted out of all "
                    "marketing communications (the `$all` bucket)."
                ),
                required=False,
                type=str,
            ),
        ],
        responses={(200, "text/csv"): OpenApiTypes.STR},
        description=(
            "Export opt-out recipients as CSV. Returns a `text/csv` attachment with columns "
            "`Recipient` and `Opt-out date` (ISO-8601 UTC), filtered identically to the "
            "`opt_outs` endpoint."
        ),
    )
    @action(detail=False, methods=["get"])
    def export_opt_outs(self, request, **kwargs):
        """Export opt-outs as a CSV file, filtered by category if provided."""
        opt_outs, error, category = self._get_opt_outs_queryset(request)
        if error is not None:
            return error
        assert opt_outs is not None

        response = HttpResponse(content_type="text/csv")
        date_str = datetime.now(tz=UTC).strftime("%Y-%m-%d")
        slug = category.key if category else "marketing"
        response["Content-Disposition"] = f'attachment; filename="opt-outs-{slug}-{date_str}.csv"'

        writer = csv.writer(response)
        writer.writerow(["Recipient", "Opt-out date"])
        for opt_out in opt_outs.iterator():
            writer.writerow(
                [
                    opt_out.identifier,
                    opt_out.updated_at.isoformat() if opt_out.updated_at else "",
                ]
            )
        return response

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

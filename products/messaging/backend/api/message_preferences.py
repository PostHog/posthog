import re
from typing import Any, Literal

from django.db import transaction

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.streaming import streaming_response
from posthog.plugins import plugin_server_api

from products.messaging.backend.models.message_category import MessageCategory, MessageCategoryType
from products.messaging.backend.models.message_preferences import (
    ALL_MESSAGE_PREFERENCE_CATEGORY_ID,
    MessageRecipientPreference,
    PreferenceStatus,
)
from products.messaging.backend.services.opt_out_service import BulkOptOutEntry, OptOutService, UnknownCategoryError
from products.messaging.backend.tasks import sync_preferences_to_customerio_task

MAX_BULK_OPT_OUT_ENTRIES = 1000
UNSAFE_FILENAME_CHARACTERS = re.compile(r"[^A-Za-z0-9_-]+")


class OptOutsPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class MessagePreferencesSerializer(serializers.ModelSerializer):
    identifier = serializers.CharField(help_text="The recipient identifier (e.g. email address).")
    updated_at = serializers.DateTimeField(help_text="When the preference was last updated.")
    preferences = serializers.JSONField(
        help_text="Map of category ID to preference status (`OPTED_IN`, `OPTED_OUT` or `NO_PREFERENCE`). "
        "The reserved `$all` key covers every marketing message."
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
        extra_kwargs = {
            "id": {"help_text": "Server-assigned UUID for this recipient's preference record."},
        }


class AddOptOutRequestSerializer(serializers.Serializer):
    identifier = serializers.CharField(
        max_length=512,
        help_text="The recipient identifier to opt out (e.g. email address).",
    )
    category_key = serializers.CharField(
        required=False,
        help_text="Optional message category key. If omitted, the recipient is opted out of all marketing messages.",
    )


class RemoveOptOutRequestSerializer(serializers.Serializer):
    identifier = serializers.CharField(
        max_length=512,
        help_text="The recipient identifier to opt back in (e.g. email address).",
    )
    category_key = serializers.CharField(
        required=False,
        help_text="Optional message category key. If omitted, the recipient is opted back in to all marketing messages.",
    )


class GenerateLinkRequestSerializer(serializers.Serializer):
    recipient = serializers.CharField(
        required=False,
        max_length=512,
        help_text="Recipient to generate the link for. Defaults to the requesting user's own email address.",
    )


class PreferencesLinkSerializer(serializers.Serializer):
    preferences_url = serializers.URLField(
        help_text="Token-gated URL where the recipient can manage their preferences."
    )


class WebhookUrlSerializer(serializers.Serializer):
    url = serializers.URLField(help_text="URL to register in Customer.io so it posts subscription changes to PostHog.")


class MessagingErrorSerializer(serializers.Serializer):
    error = serializers.CharField(help_text="Human-readable description of what went wrong.")


class OptOutsListQuerySerializer(serializers.Serializer):
    # allow_blank preserves the pre-serializer behavior: an empty category_key reads as "no
    # category" (the global list) rather than a 400.
    category_key = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Message category key to list opt-outs for. If omitted, lists recipients opted out of all marketing messages.",
    )
    search = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=512,
        help_text="Case-insensitive substring match on the recipient identifier.",
    )


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
    """
    Per-team messaging preferences for recipients.

    Preferences are stored per message category, plus a reserved `$all` key covering every
    marketing message. A send is skipped when either the category or `$all` is opted out, so a
    two-way preference center needs both `add_opt_out` and `remove_opt_out`.
    """

    scope_object = "hog_flow"
    # Every action here is a custom @action, so none of them match the default read/write action
    # names — an action listed in neither gets no scope mapping and APIScopePermission rejects
    # personal API key requests for it. Only the opt-out list endpoints are reachable with API
    # keys (and therefore MCP); webhook_url and generate_link stay session-only by being listed
    # in neither.
    scope_object_read_actions = ["opt_outs", "export_opt_outs_csv"]
    scope_object_write_actions = ["add_opt_out", "bulk_add_opt_outs", "remove_opt_out"]
    serializer_class = _FallbackSerializer

    def _require_resource_access(self, required_level: Literal["viewer", "editor"], message: str) -> None:
        # Resource-level check: `AccessControlPermission` only guarantees the caller has some
        # hog_flow object access. These endpoints act on team-wide data with no per-workflow
        # object, so require project-wide hog_flow access — otherwise a member granted access to
        # a single workflow could read or rewrite the whole team's opt-out list.
        if not self.user_access_control.check_access_level_for_resource("hog_flow", required_level):
            raise PermissionDenied(message)

    @validated_request(
        query_serializer=OptOutsListQuerySerializer,
        parameters=[
            OpenApiParameter(name="page", type=OpenApiTypes.INT, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="page_size", type=OpenApiTypes.INT, location=OpenApiParameter.QUERY, required=False),
        ],
        responses={
            200: OpenApiResponse(response=PaginatedOptOutsSerializer),
            404: OpenApiResponse(response=MessagingErrorSerializer),
        },
        summary="List recipients opted out of a message category",
    )
    @action(detail=False, methods=["get"])
    def opt_outs(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """Get opt-outs filtered by category or overall opt-outs if no category specified"""
        self._require_resource_access("viewer", "You need hog_flow viewer access to view the opt-out list.")

        category_key = request.validated_query_data.get("category_key")

        # Find recipients who have opted out of this specific category, or use the derived $all category if no specific category is provided
        preference_key = ALL_MESSAGE_PREFERENCE_CATEGORY_ID
        if category_key:
            category = MessageCategory.objects.filter(key=category_key, team_id=self.team_id).first()
            if category is None:
                return Response({"error": "Category not found"}, status=404)
            preference_key = str(category.id)

        opt_outs = MessageRecipientPreference.objects.filter(
            team_id=self.team_id,
            **{f"preferences__{preference_key}": PreferenceStatus.OPTED_OUT.value},
        )

        search = request.validated_query_data.get("search")
        if search:
            opt_outs = opt_outs.filter(identifier__icontains=search)

        opt_outs = opt_outs.order_by("-updated_at")  # Order by most recently updated first

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
    def add_opt_out(self, request: Request, **kwargs: Any) -> Response:
        """Manually add a recipient to the opt-out list for a specific category or all marketing messages."""
        self._require_resource_access("editor", "You need hog_flow editor access to modify the opt-out list.")

        serializer = AddOptOutRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        identifier = serializer.validated_data["identifier"]
        category_key = serializer.validated_data.get("category_key")

        category = None
        if category_key:
            category = MessageCategory.objects.filter(key=category_key, team_id=self.team_id).first()
            if category is None:
                return Response({"error": "Category not found"}, status=status.HTTP_404_NOT_FOUND)

        category_id = str(category.id) if category else ALL_MESSAGE_PREFERENCE_CATEGORY_ID

        preference, created = MessageRecipientPreference.objects.get_or_create(
            team_id=self.team_id,
            identifier=identifier,
            defaults={"created_by": request.user},
        )
        preference.set_preference(category_id, PreferenceStatus.OPTED_OUT)

        # Customer.io round-trips can take tens of seconds, so sync off the request path
        # once the preference write has committed.
        transaction.on_commit(lambda: sync_preferences_to_customerio_task.delay(self.team_id, identifier))

        response_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(MessagePreferencesSerializer(preference).data, status=response_status)

    @extend_schema(
        request=RemoveOptOutRequestSerializer,
        responses={201: MessagePreferencesSerializer},
        summary="Remove a recipient from the opt-out list",
    )
    @action(detail=False, methods=["post"])
    def remove_opt_out(self, request: Request, **kwargs: Any) -> Response:
        """Opt a recipient back in to a specific category, or to all marketing messages."""
        self._require_resource_access("editor", "You need hog_flow editor access to modify the opt-out list.")

        serializer = RemoveOptOutRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        identifier = serializer.validated_data["identifier"]
        category_key = serializer.validated_data.get("category_key")

        category = None
        if category_key:
            category = MessageCategory.objects.filter(key=category_key, team_id=self.team_id).first()
            if category is None:
                return Response({"error": "Category not found"}, status=status.HTTP_404_NOT_FOUND)

        preference, created = MessageRecipientPreference.objects.get_or_create(
            team_id=self.team_id,
            identifier=identifier,
            defaults={"created_by": request.user},
        )
        preferences = dict(preference.preferences or {})

        if category is None:
            preferences[ALL_MESSAGE_PREFERENCE_CATEGORY_ID] = PreferenceStatus.OPTED_IN.value
        else:
            self._lift_global_opt_out(preferences, category)
            preferences[str(category.id)] = PreferenceStatus.OPTED_IN.value

        preference.preferences = preferences
        preference.save(update_fields=["preferences", "updated_at"])

        transaction.on_commit(lambda: sync_preferences_to_customerio_task.delay(self.team_id, identifier))

        response_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(MessagePreferencesSerializer(preference).data, status=response_status)

    def _lift_global_opt_out(self, preferences: dict[str, Any], category: MessageCategory) -> None:
        """Clear a `$all` opt-out that would otherwise swallow a per-category resubscribe.

        Sends check the category and `$all` together, so opting someone back in to one category
        does nothing while `$all` stays opted out. Pin the team's other marketing categories to
        opted out first, so lifting `$all` resubscribes only the category the caller named
        instead of silently widening consent to everything.

        The pinning overwrites even an explicit OPTED_IN on a sibling category (e.g. one a
        Customer.io webhook recorded): while `$all` was opted out that opt-in was inert, so
        preserving the recipient's effective state means opting the sibling out, not letting
        the stale opt-in spring back to life.
        """
        if category.category_type != MessageCategoryType.MARKETING:
            return
        if preferences.get(ALL_MESSAGE_PREFERENCE_CATEGORY_ID) != PreferenceStatus.OPTED_OUT.value:
            return

        other_category_ids = (
            MessageCategory.objects.filter(
                team_id=self.team_id, category_type=MessageCategoryType.MARKETING, deleted=False
            )
            .exclude(id=category.id)
            .values_list("id", flat=True)
        )
        for other_category_id in other_category_ids:
            preferences[str(other_category_id)] = PreferenceStatus.OPTED_OUT.value

        preferences[ALL_MESSAGE_PREFERENCE_CATEGORY_ID] = PreferenceStatus.OPTED_IN.value

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
        self._require_resource_access("viewer", "You need hog_flow viewer access to view the opt-out list.")

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
        self._require_resource_access("editor", "You need hog_flow editor access to modify the opt-out list.")

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

    @extend_schema(
        responses={200: WebhookUrlSerializer},
        summary="Get the Customer.io webhook URL for the team",
    )
    @action(detail=False, methods=["get"])
    def webhook_url(self, request: Request, **kwargs: Any) -> Response:
        """Return the webhook URL for Customer.io integration setup."""
        self._require_resource_access("viewer", "You need hog_flow viewer access to view the opt-out list.")

        base = request.build_absolute_uri("/")[:-1]
        return Response({"url": f"{base}/api/environments/{self.team_id}/messaging/customerio/webhook/"})

    @extend_schema(
        request=GenerateLinkRequestSerializer,
        responses={200: PreferencesLinkSerializer},
        summary="Generate a preferences page link for a recipient",
    )
    @action(detail=False, methods=["post"])
    def generate_link(self, request: Request, **kwargs: Any) -> Response:
        """Generate an unsubscribe link for the current user's email address"""
        # The minted token lets whoever holds it rewrite that recipient's preferences, so this
        # action is gated as a write despite being read-shaped.
        self._require_resource_access("editor", "You need hog_flow editor access to generate a preferences link.")

        user_email = getattr(request.user, "email", None)
        if not user_email:
            return Response({"error": "User email not found"}, status=400)

        serializer = GenerateLinkRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identifier = serializer.validated_data.get("recipient", user_email)

        token = plugin_server_api.generate_messaging_preferences_token(self.team_id, identifier)

        # Build the full URL
        preferences_url = f"{request.build_absolute_uri('/')[:-1]}/messaging-preferences/{token}/"

        return Response(
            {
                "preferences_url": preferences_url,
            }
        )

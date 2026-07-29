from typing import Any, Literal

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.plugins import plugin_server_api

from products.messaging.backend.models.message_category import MessageCategory, MessageCategoryType
from products.messaging.backend.models.message_preferences import (
    ALL_MESSAGE_PREFERENCE_CATEGORY_ID,
    MessageRecipientPreference,
    PreferenceStatus,
)
from products.messaging.backend.services.customerio_sync_service import sync_preferences_to_customerio


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


class PaginatedMessagePreferencesSerializer(serializers.Serializer):
    """OpenAPI shape for the paginated opt-outs response. Declared so drf-spectacular emits
    the {count, next, previous, results} envelope on the generated client, rather than a bare
    array — which the frontend actually receives at runtime."""

    count = serializers.IntegerField(help_text="Total number of opted-out recipients for the team.")
    next = serializers.URLField(allow_null=True, help_text="URL for the next page, or null on the last page.")
    previous = serializers.URLField(allow_null=True, help_text="URL for the previous page, or null on the first page.")
    results = MessagePreferencesSerializer(many=True)


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


class MessagePreferencesViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """
    Per-team messaging preferences for recipients.

    Preferences are stored per message category, plus a reserved `$all` key covering every
    marketing message. A send is skipped when either the category or `$all` is opted out, so a
    two-way preference center needs both `add_opt_out` and `remove_opt_out`.
    """

    scope_object = "hog_flow"
    # Every action here is a custom @action, so none of them match the default read/write action
    # names. Both lists have to be declared: without them no scope maps to the action at all and
    # APIScopePermission rejects the request as "does not support personal API key access".
    # `generate_link` counts as a write — the token it mints can rewrite a recipient's preferences.
    scope_object_read_actions = ["opt_outs", "webhook_url"]
    scope_object_write_actions = ["add_opt_out", "remove_opt_out", "generate_link"]
    serializer_class = _FallbackSerializer

    def _require_resource_access(self, required_level: Literal["viewer", "editor"], message: str) -> None:
        # Resource-level check: `AccessControlPermission` only guarantees the caller has some
        # hog_flow object access. These endpoints act on team-wide data with no per-workflow
        # object, so require project-wide hog_flow access — otherwise a member granted access to
        # a single workflow could read or rewrite the whole team's opt-out list.
        if not self.user_access_control.check_access_level_for_resource("hog_flow", required_level):
            raise PermissionDenied(message)

    @extend_schema(
        parameters=[
            OpenApiParameter(name="category_key", type=str, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="page", type=int, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="page_size", type=int, location=OpenApiParameter.QUERY, required=False),
        ],
        responses={200: PaginatedMessagePreferencesSerializer},
        summary="List opted-out recipients for the team",
    )
    @action(detail=False, methods=["get"])
    def opt_outs(self, request: Request, **kwargs: Any) -> Response:
        """Get opt-outs filtered by category or overall opt-outs if no category specified"""
        self._require_resource_access("viewer", "You need hog_flow viewer access to view the opt-out list.")

        category_key = request.query_params.get("category_key")

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

        sync_preferences_to_customerio(self.team_id, identifier, preference.preferences)

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

        sync_preferences_to_customerio(self.team_id, identifier, preferences)

        response_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(MessagePreferencesSerializer(preference).data, status=response_status)

    def _lift_global_opt_out(self, preferences: dict[str, Any], category: MessageCategory) -> None:
        """Clear a `$all` opt-out that would otherwise swallow a per-category resubscribe.

        Sends check the category and `$all` together, so opting someone back in to one category
        does nothing while `$all` stays opted out. Pin the team's other marketing categories to
        opted out first, so lifting `$all` resubscribes only the category the caller named
        instead of silently widening consent to everything.
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
            preferences.setdefault(str(other_category_id), PreferenceStatus.OPTED_OUT.value)

        preferences[ALL_MESSAGE_PREFERENCE_CATEGORY_ID] = PreferenceStatus.OPTED_IN.value

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
        # The minted token lets whoever holds it rewrite that recipient's preferences, so this is
        self._require_resource_access("editor", "You need hog_flow editor access to generate a preferences link.")

        user_email = getattr(request.user, "email", None)
        if not user_email:
            return Response({"error": "User email not found"}, status=400)

        identifier = request.data.get("recipient", user_email)

        token = plugin_server_api.generate_messaging_preferences_token(self.team_id, identifier)

        # Build the full URL
        preferences_url = f"{request.build_absolute_uri('/')[:-1]}/messaging-preferences/{token}/"

        return Response(
            {
                "preferences_url": preferences_url,
            }
        )

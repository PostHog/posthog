from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import MessageCategory, MessageRecipientPreference
from posthog.models.message_preferences import ALL_MESSAGE_PREFERENCE_CATEGORY_ID, PreferenceStatus
from posthog.plugins import plugin_server_api


class MessagePreferencesSerializer(serializers.ModelSerializer):
    identifier = serializers.CharField()
    updated_at = serializers.DateTimeField()
    preferences = serializers.JSONField()

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
        )

        serializer = MessagePreferencesSerializer(opt_outs, many=True)
        return Response(serializer.data)

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

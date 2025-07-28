from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import MessageRecipientPreference, MessageCategory
from posthog.models.message_preferences import PreferenceStatus


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

        # Find recipients who have opted out of this specific category, or all categories if no specific category is provided
        categories_to_check = (
            [category]
            if category_key
            else MessageCategory.objects.filter(team_id=self.team_id, category_type="marketing", deleted=False)
        )
        query_filters = {}
        for category in categories_to_check:
            category_preference_lookup = f"preferences__{str(category.id)}"
            query_filters[category_preference_lookup] = PreferenceStatus.OPTED_OUT

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

        # Get or create preferences for the user's email
        recipient = MessageRecipientPreference.get_or_create_for_identifier(team_id=self.team_id, identifier=identifier)

        # Generate the preferences token
        token = recipient.generate_preferences_token()

        # Build the full URL
        preferences_url = f"{request.build_absolute_uri('/')[:-1]}/messaging-preferences/{token}/"

        return Response(
            {
                "preferences_url": preferences_url,
            }
        )

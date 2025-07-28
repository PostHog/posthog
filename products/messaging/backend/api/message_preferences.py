from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import MessageRecipientPreference, MessageCategory
from posthog.models.message_preferences import PreferenceStatus


class MessageCategoryPreferenceSerializer(serializers.Serializer):
    email = serializers.ChoiceField(choices=PreferenceStatus.choices, default=PreferenceStatus.NO_PREFERENCE)
    sms = serializers.ChoiceField(choices=PreferenceStatus.choices, default=PreferenceStatus.NO_PREFERENCE)
    push = serializers.ChoiceField(choices=PreferenceStatus.choices, default=PreferenceStatus.NO_PREFERENCE)


class MessagePreferencesSerializer(serializers.ModelSerializer):
    identifier = serializers.CharField()
    updated_at = serializers.DateTimeField()
    category_id = serializers.UUIDField(required=False)
    category_key = serializers.CharField(required=False)
    category_name = serializers.CharField(required=False)

    class Meta:
        model = MessageRecipientPreference
        fields = [
            "id",
            "identifier",
            "updated_at",
            "category_id",
            "category_key",
            "category_name",
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

            # Find recipients who have opted out of this specific category
            opt_outs = []
            recipients = MessageRecipientPreference.objects.filter(team_id=self.team_id)

            for recipient in recipients:
                preference_status = recipient.get_preference(category.id)
                if preference_status == PreferenceStatus.OPTED_OUT:
                    opt_outs.append(
                        {
                            "id": str(recipient.id),
                            "identifier": recipient.identifier,
                            "updated_at": recipient.updated_at,
                            "category_id": str(category.id),
                            "category_key": category.key,
                            "category_name": category.name,
                        }
                    )

            serializer = MessagePreferencesSerializer(opt_outs, many=True)
            return Response(serializer.data)

        # Get users who have opted out of all marketing emails
        marketing_categories = MessageCategory.objects.filter(
            team_id=self.team_id, category_type="marketing", deleted=False
        )

        if not marketing_categories.exists():
            return Response([])

        overall_opt_outs = []
        recipients = MessageRecipientPreference.objects.filter(team_id=self.team_id)

        for recipient in recipients:
            # Check if user has at least one OPTED_OUT and no OPTED_IN values
            has_opted_out = False
            has_opted_in = False

            for category in marketing_categories:
                preference_status = recipient.get_preference(category.id)
                if preference_status == PreferenceStatus.OPTED_OUT:
                    has_opted_out = True
                elif preference_status == PreferenceStatus.OPTED_IN:
                    has_opted_in = True
                    break  # If we find any OPTED_IN, we can stop checking

            if has_opted_out and not has_opted_in:
                overall_opt_outs.append(
                    {
                        "id": str(recipient.id),
                        "identifier": recipient.identifier,
                        "updated_at": recipient.updated_at,
                    }
                )

        serializer = MessagePreferencesSerializer(overall_opt_outs, many=True)
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

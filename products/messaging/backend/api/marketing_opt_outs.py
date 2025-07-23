from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import MessageRecipientPreference, MessageCategory
from posthog.models.message_preferences import PreferenceStatus


class MarketingOptOutSerializer(serializers.Serializer):
    identifier = serializers.CharField()
    opt_out_date = serializers.DateTimeField(source="updated_at")
    category_id = serializers.UUIDField(required=False)
    category_name = serializers.CharField(required=False)
    source = serializers.CharField(default="manual")


class MarketingOptOutViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"

    @action(detail=False, methods=["get"])
    def by_category(self, request):
        """Get opt-outs filtered by category"""
        category_id = request.query_params.get("category_id")

        if not category_id:
            return Response({"error": "category_id parameter is required"}, status=400)

        try:
            category = MessageCategory.objects.get(id=category_id, team_id=self.team_id, category_type="marketing")
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
                        "opt_out_date": recipient.updated_at,
                        "category_id": str(category.id),
                        "category_name": category.name,
                        "source": "preference_page",
                    }
                )

        serializer = MarketingOptOutSerializer(opt_outs, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def overall(self, request):
        """Get users who have opted out of all marketing emails"""

        # For now, we'll consider users who have opted out of all existing marketing categories
        # as having opted out "overall"
        marketing_categories = MessageCategory.objects.filter(
            team_id=self.team_id, category_type="marketing", deleted=False
        )

        if not marketing_categories.exists():
            return Response([])

        overall_opt_outs = []
        recipients = MessageRecipientPreference.objects.filter(team_id=self.team_id)

        for recipient in recipients:
            # Check if user has opted out of all marketing categories
            all_opted_out = True
            for category in marketing_categories:
                preference_status = recipient.get_preference(category.id)
                if preference_status != PreferenceStatus.OPTED_OUT:
                    all_opted_out = False
                    break

            if all_opted_out and marketing_categories.count() > 0:
                overall_opt_outs.append(
                    {
                        "id": str(recipient.id),
                        "identifier": recipient.identifier,
                        "opt_out_date": recipient.updated_at,
                        "source": "preference_page",
                    }
                )

        serializer = MarketingOptOutSerializer(overall_opt_outs, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def categories(self, request):
        """Get available marketing categories for filtering"""
        categories = MessageCategory.objects.filter(
            team_id=self.team_id, category_type="marketing", deleted=False
        ).values("id", "name", "key")

        return Response(list(categories))

from django.db.models import QuerySet

from rest_framework import mixins, serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.utils import strict_fetch

from products.marketing_analytics.backend.models.recommendation_dismissal import (
    RecommendationDismissal,
    RecommendationRule,
)


class RecommendationDismissalSerializer(serializers.ModelSerializer):
    rule = serializers.ChoiceField(
        choices=RecommendationRule.choices, help_text="The rule that produced the dismissed recommendation."
    )
    # Campaign names can carry edge spaces, and a trimmed copy would no longer match the recommendation.
    subject = serializers.CharField(
        max_length=400,
        trim_whitespace=False,
        help_text="The campaign name or search term the dismissed recommendation is about.",
    )
    campaign = serializers.CharField(
        max_length=400,
        trim_whitespace=False,
        required=False,
        allow_blank=True,
        default="",
        help_text="The campaign a search term recommendation applies to. Empty for campaign recommendations.",
    )
    dismissed_by = UserBasicSerializer(read_only=True, help_text="The user who dismissed the recommendation.")

    class Meta:
        model = RecommendationDismissal
        fields = ["id", "rule", "subject", "campaign", "dismissed_by", "created_at"]
        read_only_fields = ["id", "dismissed_by", "created_at"]
        extra_kwargs = {
            "id": {"help_text": "The dismissal id. Delete it to show the recommendation again."},
            "created_at": {"help_text": "When the recommendation was dismissed."},
        }

    def create(self, validated_data: dict[str, str]) -> RecommendationDismissal:
        request = self.context["request"]
        # A second dismissal of the same recommendation, for example from another tab, returns the first one.
        dismissal, _ = RecommendationDismissal.objects.for_team(self.context["team_id"]).get_or_create(
            team_id=self.context["team_id"],
            rule=validated_data["rule"],
            subject=validated_data["subject"],
            campaign=validated_data["campaign"],
            defaults={"dismissed_by": request.user},
        )
        return dismissal


class RecommendationDismissalViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    Marketing analytics recommendations that the team dismissed. A dismissed recommendation stays hidden
    for everyone in the project until someone deletes the dismissal.
    """

    scope_object = "marketing_analytics"
    queryset = RecommendationDismissal.objects.unscoped()
    serializer_class = RecommendationDismissalSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def safely_get_queryset(self, queryset: QuerySet[RecommendationDismissal]) -> QuerySet[RecommendationDismissal]:
        queryset = queryset.filter(team_id=self.team_id)
        if self.action == "list":
            queryset = strict_fetch(queryset.select_related("dismissed_by").order_by("-created_at", "-id"))
        return queryset

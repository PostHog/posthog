from django.db.models import QuerySet

from rest_framework import mixins, serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer

from products.marketing_analytics.backend.models.recommendation_resolution import (
    RecommendationResolution,
    RecommendationResolutionState,
    RecommendationRule,
)


class RecommendationSnapshotSerializer(serializers.Serializer):
    action = serializers.CharField(max_length=1000, help_text="The recommendation's `action` when it was resolved.")
    impact = serializers.FloatField(
        allow_null=True, required=False, default=None, help_text="The recommendation's `impact` when it was resolved."
    )
    currency = serializers.CharField(
        max_length=8,
        allow_null=True,
        required=False,
        default=None,
        help_text="The recommendation's `currency` when it was resolved.",
    )


class RecommendationResolutionSerializer(serializers.ModelSerializer):
    rule = serializers.ChoiceField(
        choices=RecommendationRule.choices, help_text="The rule that produced the resolved recommendation."
    )
    source_type = serializers.ChoiceField(
        choices=RecommendationResolution.SourceType.choices,
        required=False,
        default=RecommendationResolution.SourceType.GOOGLE_ADS,
        help_text="The recommendation's `identity.source_type`.",
    )
    customer_id = serializers.CharField(
        max_length=64,
        required=False,
        allow_blank=True,
        default="",
        help_text="The recommendation's `identity.customer_id`.",
    )
    campaign_id = serializers.CharField(
        max_length=64,
        required=False,
        allow_blank=True,
        default="",
        help_text="The recommendation's `identity.campaign_id`.",
    )
    # The query matches resolutions on the exact identity it emitted, so a trimmed copy would never match.
    subject = serializers.CharField(
        max_length=1024,
        required=False,
        allow_blank=True,
        default="",
        trim_whitespace=False,
        help_text="The recommendation's `identity.subject`.",
    )
    resolution = serializers.ChoiceField(
        choices=RecommendationResolutionState.choices,
        help_text="Dismissed hides the recommendation. Applied marks that someone made the change it suggests.",
    )
    snapshot = RecommendationSnapshotSerializer(
        required=False,
        allow_null=True,
        default=None,
        help_text="What the recommendation suggested when it was resolved.",
    )
    resolved_by = UserBasicSerializer(read_only=True, help_text="The user who last resolved the recommendation.")

    class Meta:
        model = RecommendationResolution
        fields = [
            "id",
            "rule",
            "source_type",
            "customer_id",
            "campaign_id",
            "subject",
            "resolution",
            "snapshot",
            "resolved_by",
            "resolved_at",
            "created_at",
        ]
        read_only_fields = ["id", "resolved_by", "resolved_at", "created_at"]
        extra_kwargs = {
            "id": {"help_text": "The resolution id. Delete it to show the recommendation again."},
            "resolved_at": {"help_text": "When the recommendation was last resolved."},
            "created_at": {"help_text": "When the recommendation was first resolved."},
        }

    def create(self, validated_data: dict[str, object]) -> RecommendationResolution:
        request = self.context["request"]
        defaults: dict[str, object] = {
            "resolution": validated_data["resolution"],
            "snapshot": validated_data["snapshot"],
            "resolved_by": request.user,
        }
        # Resolving a recommendation again, for example from another tab, replaces the earlier resolution.
        resolution, _ = RecommendationResolution.objects.for_team(self.context["team_id"]).update_or_create(
            team_id=self.context["team_id"],
            rule=validated_data["rule"],
            source_type=validated_data["source_type"],
            customer_id=validated_data["customer_id"],
            campaign_id=validated_data["campaign_id"],
            subject=validated_data["subject"],
            defaults=defaults,
        )
        return resolution


class RecommendationResolutionViewSet(
    TeamAndOrgViewSetMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    Marketing analytics recommendations that someone in the project dismissed or marked as applied. The
    recommendations query leaves a resolved recommendation out for everyone in the project until someone deletes
    its resolution.
    """

    scope_object = "marketing_analytics"
    queryset = RecommendationResolution.objects.unscoped()
    serializer_class = RecommendationResolutionSerializer
    permission_classes = [IsAuthenticated]

    def safely_get_queryset(self, queryset: QuerySet[RecommendationResolution]) -> QuerySet[RecommendationResolution]:
        return RecommendationResolution.objects.for_team(self.team_id)

from rest_framework import serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.llm_analytics.backend.models.annotations import LLMAnalyticsAnnotation


class LLMAnalyticsAnnotationSerializer(serializers.ModelSerializer):
    class Meta:
        model = LLMAnalyticsAnnotation
        fields = [
            "id",
            "team_id",
            "organization_id",
            "target_type",
            "target_id",
            "content",
            "rating",
            "data",
            "created_at",
            "updated_at",
            "deleted",
        ]
        read_only_fields = [
            "id",
            "team_id",
            "organization_id",
            "created_at",
            "updated_at",
            "deleted",
        ]


class LLMAnalyticsAnnotationsViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "llm_analytics"  # type: ignore[assignment]

    serializer_class = LLMAnalyticsAnnotationSerializer
    queryset = LLMAnalyticsAnnotation.objects.all()
    ordering = ["-created_at"]

    def safely_get_queryset(self, queryset):
        # TeamAndOrgViewSetMixin sets self.team and self.organization
        return queryset.filter(team_id=self.team.id, organization_id=self.organization.id)

    def perform_create(self, serializer):
        serializer.save(team_id=self.team.id, organization_id=self.organization.id)

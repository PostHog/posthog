from rest_framework import serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer

from products.llm_analytics.backend.models.annotations import LLMAnalyticsAnnotation


class LLMAnalyticsAnnotationSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

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
            "created_by",
            "created_at",
            "updated_at",
            "deleted",
        ]
        read_only_fields = [
            "id",
            "team_id",
            "organization_id",
            "created_by",
            "created_at",
            "updated_at",
            "deleted",
        ]


class LLMAnalyticsAnnotationsViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    # Required by APIScopePermission (match the other llm_analytics endpoints)
    scope_object = "llm_analytics"

    queryset = LLMAnalyticsAnnotation.objects.all()
    serializer_class = LLMAnalyticsAnnotationSerializer

    def safely_get_queryset(self, queryset):
        # TeamAndOrgViewSetMixin sets self.team and self.organization
        return queryset.filter(team_id=self.team.id, organization_id=self.organization.id, deleted=False)

    def perform_create(self, serializer):
        serializer.save(team_id=self.team.id, organization_id=self.organization.id, created_by=self.request.user)

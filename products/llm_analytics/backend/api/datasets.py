from django.db.models import QuerySet
import structlog
from rest_framework import serializers
from rest_framework.viewsets import ModelViewSet

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from products.llm_analytics.backend.models import Dataset

logger = structlog.get_logger(__name__)


class DatasetSerializer(serializers.ModelSerializer):
    class Meta:
        model = Dataset
        fields = ["id", "name", "description", "metadata", "created_at", "updated_at", "deleted"]
        read_only_fields = ["id", "created_at", "updated_at", "team", "created_by"]

    def create(self, validated_data: dict, *args, **kwargs):
        request = self.context["request"]
        validated_data["team"] = self.context["get_team"]()
        validated_data["created_by"] = request.user
        return super().create(validated_data, *args, **kwargs)


class DatasetViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, ModelViewSet):
    scope_object = "dataset"
    serializer_class = DatasetSerializer
    queryset = Dataset.objects.all().exclude(deleted=True)
    param_derived_from_user_current_team = "team_id"

    def safely_get_queryset(self, queryset: QuerySet[Dataset]) -> QuerySet[Dataset]:
        if self.action == "list":
            filters = self.request.GET
            if "name" in filters:
                queryset = queryset.filter(name__icontains=filters["name"])

        return queryset

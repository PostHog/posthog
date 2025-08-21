import structlog
from rest_framework import serializers
from rest_framework.viewsets import ModelViewSet

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from products.llm_observability.models import Dataset

logger = structlog.get_logger(__name__)


class DatasetSerializer(serializers.ModelSerializer):
    class Meta:
        model = Dataset
        fields = ["id", "name", "description", "metadata", "created_at", "updated_at", "deleted"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def create(self, validated_data: dict, *args, **kwargs):
        request = self.context["request"]
        validated_data["created_by"] = request.user
        return super().create(request, *args, **kwargs)


class DatasetViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, ModelViewSet):
    scope_object = "dataset"
    serializer_class = DatasetSerializer
    queryset = Dataset.objects.all().exclude(deleted=True)

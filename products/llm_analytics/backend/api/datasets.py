from django.db.models import Q, QuerySet

import structlog
import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import serializers
from rest_framework.viewsets import ModelViewSet

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer

from products.llm_analytics.backend.models import Dataset
from products.llm_analytics.backend.models.datasets import DatasetItem

logger = structlog.get_logger(__name__)


class DatasetSerializer(serializers.ModelSerializer):
    class Meta:
        model = Dataset
        fields = [
            "id",
            "name",
            "description",
            "metadata",
            "created_at",
            "updated_at",
            "deleted",
            "created_by",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "team",
            "created_by",
        ]

    created_by = UserBasicSerializer(read_only=True)

    def create(self, validated_data: dict, *args, **kwargs):
        request = self.context["request"]
        validated_data["team"] = self.context["get_team"]()
        validated_data["created_by"] = request.user
        return super().create(validated_data, *args, **kwargs)


class DatasetFilter(django_filters.FilterSet):
    search = django_filters.CharFilter(method="filter_search", help_text="Search in name, description, or metadata")
    order_by = django_filters.OrderingFilter(
        fields=(
            ("created_at", "created_at"),
            ("updated_at", "updated_at"),
        ),
        field_labels={
            "created_at": "Created At",
            "updated_at": "Updated At",
        },
    )

    class Meta:
        model = Dataset
        fields = ["search", "order_by"]

    def filter_search(self, queryset, name, value):
        if value:
            return queryset.filter(
                Q(name__icontains=value) | Q(description__icontains=value) | Q(metadata__icontains=value)
            )
        return queryset


class DatasetViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, ModelViewSet):
    scope_object = "dataset"
    serializer_class = DatasetSerializer
    queryset = Dataset.objects.all()
    param_derived_from_user_current_team = "team_id"
    filter_backends = [DjangoFilterBackend]
    filterset_class = DatasetFilter

    def safely_get_queryset(self, queryset: QuerySet[Dataset, Dataset]) -> QuerySet[Dataset, Dataset]:
        if self.action in {"list", "retrieve"}:
            return queryset.exclude(deleted=True)
        return queryset


class DatasetItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = DatasetItem
        fields = [
            "id",
            "dataset",
            "input",
            "output",
            "metadata",
            "ref_trace_id",
            "ref_timestamp",
            "ref_source_id",
            "deleted",
            "created_at",
            "updated_at",
            "created_by",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "team",
            "created_by",
        ]

    created_by = UserBasicSerializer(read_only=True)

    def create(self, validated_data: dict, *args, **kwargs):
        request = self.context["request"]
        validated_data["team"] = self.context["get_team"]()
        validated_data["created_by"] = request.user
        return super().create(validated_data, *args, **kwargs)


class DatasetItemViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, ModelViewSet):
    scope_object = "dataset"
    serializer_class = DatasetItemSerializer
    queryset = DatasetItem.objects.all()
    param_derived_from_user_current_team = "team_id"
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["dataset"]

    def safely_get_queryset(self, queryset: QuerySet[DatasetItem, DatasetItem]) -> QuerySet[DatasetItem, DatasetItem]:
        if self.action in {"list", "retrieve"}:
            return queryset.exclude(deleted=True)
        return queryset

from django.db.models import Q, QuerySet

import structlog
import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter
from rest_framework import serializers
from rest_framework.viewsets import ModelViewSet

from posthog.api.documentation import extend_schema
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
            "team",
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
        fields = {
            "id": ["in"],
        }

    def filter_search(self, queryset, name, value):
        if value:
            return queryset.filter(
                Q(name__icontains=value) | Q(description__icontains=value) | Q(metadata__icontains=value)
            )
        return queryset

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "id__in",
                OpenApiTypes.STR,
                description="Filter by dataset IDs",
                examples=[
                    OpenApiExample(
                        "Single dataset ID",
                        value="695401fa-6f0e-4389-b186-c45a7f1273d3",
                    ),
                    OpenApiExample(
                        "Multiple dataset IDs",
                        description="Filter by multiple dataset IDs separated by a comma",
                        value="695401fa-6f0e-4389-b186-c45a7f1273d3,bffe0715-abe4-4902-837b-316be727445b",
                    ),
                ],
            ),
            OpenApiParameter(
                "search",
                OpenApiTypes.STR,
                description="Full-text search by name, description, or metadata",
                examples=[
                    OpenApiExample(
                        "Search by name",
                        value="My dataset",
                    ),
                ],
            ),
            OpenApiParameter(
                "order_by",
                OpenApiTypes.STR,
                description="Order by created_at or updated_at",
                examples=[
                    OpenApiExample(
                        "Order by created_at ascending",
                        value="created_at",
                    ),
                    OpenApiExample(
                        "Order by updated_at descending",
                        value="-updated_at",
                    ),
                ],
            ),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)


class DatasetViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, ModelViewSet):
    scope_object = "dataset"
    serializer_class = DatasetSerializer
    queryset = Dataset.objects.all()
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
            "team",
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
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["dataset"]

    def safely_get_queryset(self, queryset: QuerySet[DatasetItem, DatasetItem]) -> QuerySet[DatasetItem, DatasetItem]:
        if self.action in {"list", "retrieve"}:
            return queryset.exclude(deleted=True)
        return queryset

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "dataset",
                OpenApiTypes.STR,
                description="Filter by dataset ID",
                examples=[
                    OpenApiExample(
                        "Single dataset ID",
                        value="695401fa-6f0e-4389-b186-c45a7f1273d3",
                    ),
                ],
            ),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

from __future__ import annotations

from typing import Any, cast

from django.db import IntegrityError, transaction
from django.db.models import Count, Q, QuerySet

import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse
from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from posthog.schema import ProductKey

from posthog.api.documentation import extend_schema
from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.models import Team, User
from posthog.permissions import AccessControlPermission
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin

from products.llm_analytics.backend.api.metrics import llma_track_latency
from products.llm_analytics.backend.api.trace_reviews import TraceReviewFeatureFlagPermission
from products.llm_analytics.backend.models.review_queues import ReviewQueue, ReviewQueueItem
from products.llm_analytics.backend.models.trace_reviews import TraceReview


class ReviewQueueSerializer(serializers.ModelSerializer):
    name = serializers.CharField(
        read_only=True,
        help_text="Human-readable queue name.",
    )
    created_by = UserBasicSerializer(read_only=True, help_text="User who created this review queue.")
    pending_item_count = serializers.IntegerField(
        read_only=True,
        help_text="Number of pending traces currently assigned to this queue.",
    )

    class Meta:
        model = ReviewQueue
        fields = [
            "id",
            "name",
            "pending_item_count",
            "created_at",
            "updated_at",
            "created_by",
            "team",
        ]
        read_only_fields = fields


class BaseReviewQueueWriteSerializer(serializers.Serializer):
    name = serializers.CharField(
        max_length=255,
        required=False,
        help_text="Human-readable queue name.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        team = cast(Team, self.context["team"])
        instance = cast(ReviewQueue | None, self.instance)

        name = attrs.get("name", instance.name if instance else None)
        if not name:
            raise serializers.ValidationError({"name": "This field is required."})

        normalized_name = name.strip()
        if not normalized_name:
            raise serializers.ValidationError({"name": "This field is required."})

        duplicate_queryset = ReviewQueue.objects.filter(team=team, name=normalized_name, deleted=False)
        if instance:
            duplicate_queryset = duplicate_queryset.exclude(pk=instance.pk)

        if duplicate_queryset.exists():
            raise serializers.ValidationError({"name": "A queue with this name already exists."})

        attrs["name"] = normalized_name
        return attrs

    def create(self, validated_data: dict[str, Any]) -> ReviewQueue:
        request = cast(Request, self.context["request"])
        team = cast(Team, self.context["team"])
        queue_user = cast(User, request.user)

        try:
            return ReviewQueue.objects.create(
                team=team,
                name=validated_data["name"],
                created_by=queue_user,
            )
        except IntegrityError as err:
            raise serializers.ValidationError({"name": "A queue with this name already exists."}) from err

    def update(self, instance: ReviewQueue, validated_data: dict[str, Any]) -> ReviewQueue:
        instance.name = validated_data["name"]
        instance.save(update_fields=["name", "updated_at"])
        return instance


class ReviewQueueCreateSerializer(BaseReviewQueueWriteSerializer):
    name = serializers.CharField(
        max_length=255,
        help_text="Human-readable queue name.",
    )


class ReviewQueueUpdateSerializer(BaseReviewQueueWriteSerializer):
    pass


class TraceIdInFilter(django_filters.BaseInFilter, django_filters.CharFilter):
    pass


class ReviewQueueFilter(django_filters.FilterSet):
    search = django_filters.CharFilter(method="filter_search", help_text="Search review queue names.")
    order_by = django_filters.OrderingFilter(
        fields=(
            ("name", "name"),
            ("updated_at", "updated_at"),
            ("created_at", "created_at"),
        ),
        field_labels={
            "name": "Name",
            "updated_at": "Updated At",
            "created_at": "Created At",
        },
    )

    class Meta:
        model = ReviewQueue
        fields = {
            "name": ["exact"],
        }

    def filter_search(self, queryset: QuerySet, _name: str, value: str) -> QuerySet:
        if value:
            return queryset.filter(name__icontains=value)
        return queryset


class ReviewQueueItemSerializer(serializers.ModelSerializer):
    queue_id = serializers.UUIDField(
        read_only=True,
        help_text="Review queue ID that currently owns this pending trace.",
    )
    queue_name = serializers.CharField(
        source="queue.name",
        read_only=True,
        help_text="Human-readable name of the queue that currently owns this pending trace.",
    )
    trace_id = serializers.CharField(
        read_only=True,
        help_text="Trace ID currently pending review.",
    )
    created_by = UserBasicSerializer(read_only=True, help_text="User who queued this trace.")

    class Meta:
        model = ReviewQueueItem
        fields = [
            "id",
            "queue_id",
            "queue_name",
            "trace_id",
            "created_at",
            "updated_at",
            "created_by",
            "team",
        ]
        read_only_fields = fields


class BaseReviewQueueItemWriteSerializer(serializers.Serializer):
    queue_id = serializers.UUIDField(help_text="Review queue ID that should own this pending trace.")

    def _resolve_queue(self, queue_id: str) -> ReviewQueue:
        team = cast(Team, self.context["team"])
        queue = ReviewQueue.objects.filter(team=team, pk=queue_id, deleted=False).first()
        if not queue:
            raise serializers.ValidationError({"queue_id": "Review queue not found."})
        return queue

    def validate_queue_id(self, value: str) -> str:
        self.context["_resolved_queue"] = self._resolve_queue(value)
        return value

    def _get_resolved_queue(self) -> ReviewQueue:
        return cast(ReviewQueue, self.context["_resolved_queue"])


class ReviewQueueItemCreateSerializer(BaseReviewQueueItemWriteSerializer):
    trace_id = serializers.CharField(
        max_length=255,
        help_text="Trace ID to add to the selected review queue.",
    )

    def _validate_trace_id_constraints(self, *, team: Team, trace_id: str, resolved_queue: ReviewQueue) -> None:
        if TraceReview.objects.filter(team=team, trace_id=trace_id, deleted=False).exists():
            raise serializers.ValidationError(
                {"trace_id": "This trace is already reviewed and cannot be added to a queue."}
            )

        existing_item = ReviewQueueItem.objects.filter(team=team, trace_id=trace_id, deleted=False).first()
        if existing_item:
            if existing_item.queue_id == resolved_queue.id:
                raise serializers.ValidationError({"trace_id": "This trace is already pending in this queue."})
            raise serializers.ValidationError({"trace_id": "This trace is already pending in another queue."})

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        team = cast(Team, self.context["team"])
        resolved_queue = self._get_resolved_queue()

        normalized_trace_id = attrs["trace_id"].strip()
        if not normalized_trace_id:
            raise serializers.ValidationError({"trace_id": "This field is required."})

        self._validate_trace_id_constraints(team=team, trace_id=normalized_trace_id, resolved_queue=resolved_queue)

        attrs["trace_id"] = normalized_trace_id
        attrs["_resolved_queue"] = resolved_queue
        return attrs

    @transaction.atomic
    def create(self, validated_data: dict[str, Any]) -> ReviewQueueItem:
        request = cast(Request, self.context["request"])
        team = cast(Team, self.context["team"])
        queue_user = cast(User, request.user)
        resolved_queue = cast(ReviewQueue, validated_data.pop("_resolved_queue"))
        validated_data.pop("queue_id", None)
        trace_id = validated_data["trace_id"]

        Team.objects.select_for_update().get(id=team.id)
        self._validate_trace_id_constraints(team=team, trace_id=trace_id, resolved_queue=resolved_queue)

        try:
            return ReviewQueueItem.objects.create(
                team=team,
                queue=resolved_queue,
                trace_id=trace_id,
                created_by=queue_user,
            )
        except IntegrityError as err:
            raise serializers.ValidationError({"trace_id": "This trace is already pending in another queue."}) from err


class ReviewQueueItemUpdateSerializer(BaseReviewQueueItemWriteSerializer):
    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        team = cast(Team, self.context["team"])
        instance = cast(ReviewQueueItem, self.instance)
        resolved_queue = self._get_resolved_queue()

        if TraceReview.objects.filter(team=team, trace_id=instance.trace_id, deleted=False).exists():
            raise serializers.ValidationError({"trace_id": "This trace is already reviewed and cannot stay queued."})

        attrs["_resolved_queue"] = resolved_queue
        return attrs

    def update(self, instance: ReviewQueueItem, validated_data: dict[str, Any]) -> ReviewQueueItem:
        resolved_queue = cast(ReviewQueue, validated_data.pop("_resolved_queue"))
        validated_data.pop("queue_id", None)

        instance.queue = resolved_queue
        instance.save(update_fields=["queue", "updated_at"])
        return instance


class ReviewQueueItemFilter(django_filters.FilterSet):
    queue_id = django_filters.UUIDFilter(field_name="queue_id", help_text="Filter by a specific review queue ID.")
    trace_id = django_filters.CharFilter(field_name="trace_id", help_text="Filter by an exact trace ID.")
    trace_id__in = TraceIdInFilter(field_name="trace_id", lookup_expr="in", help_text="Filter by trace IDs.")
    search = django_filters.CharFilter(method="filter_search", help_text="Search pending trace IDs.")
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
        model = ReviewQueueItem
        fields = {
            "queue_id": ["exact"],
            "trace_id": ["exact", "in"],
        }

    def filter_search(self, queryset: QuerySet, _name: str, value: str) -> QuerySet:
        if value:
            return queryset.filter(trace_id__icontains=value)
        return queryset


@extend_schema(tags=[ProductKey.LLM_ANALYTICS])
class ReviewQueueViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, ModelViewSet):
    scope_object = "llm_analytics"
    permission_classes = [TraceReviewFeatureFlagPermission, AccessControlPermission]
    serializer_class = ReviewQueueSerializer
    queryset = ReviewQueue.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_class = ReviewQueueFilter
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def safely_get_queryset(self, queryset: QuerySet[ReviewQueue, ReviewQueue]) -> QuerySet[ReviewQueue, ReviewQueue]:
        return (
            queryset.filter(team_id=self.team_id, deleted=False)
            .select_related("created_by")
            .annotate(pending_item_count=Count("items", filter=Q(items__deleted=False)))
        )

    def _serialize_saved_queue(self, queue: ReviewQueue) -> dict[str, Any]:
        hydrated_queue = self.get_queryset().get(pk=queue.pk)
        return self.get_serializer(hydrated_queue).data

    @staticmethod
    def _event_properties(queue: ReviewQueue) -> dict[str, str]:
        return {
            "review_queue_id": str(queue.id),
            "review_queue_name": queue.name,
        }

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "search",
                OpenApiTypes.STR,
                description="Search review queue names.",
                examples=[OpenApiExample("Queue search", value="support")],
            ),
            OpenApiParameter(
                "order_by",
                OpenApiTypes.STR,
                description="Order by `name`, `updated_at`, or `created_at`.",
                examples=[OpenApiExample("Alphabetical", value="name")],
            ),
        ]
    )
    @llma_track_latency("llma_review_queues_list")
    @monitor(feature=None, endpoint="llma_review_queues_list", method="GET")
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @llma_track_latency("llma_review_queues_retrieve")
    @monitor(feature=None, endpoint="llma_review_queues_retrieve", method="GET")
    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        request=ReviewQueueCreateSerializer,
        responses={201: OpenApiResponse(response=ReviewQueueSerializer)},
    )
    @llma_track_latency("llma_review_queues_create")
    @monitor(feature=None, endpoint="llma_review_queues_create", method="POST")
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = ReviewQueueCreateSerializer(
            data=request.data,
            context={**self.get_serializer_context(), "team": self.team},
        )
        serializer.is_valid(raise_exception=True)
        queue = serializer.save()

        report_user_action(
            request.user,
            "llma review queue created",
            self._event_properties(queue),
            team=self.team,
            request=request,
        )

        return Response(self._serialize_saved_queue(queue), status=status.HTTP_201_CREATED)

    @extend_schema(
        request=ReviewQueueUpdateSerializer,
        responses={200: OpenApiResponse(response=ReviewQueueSerializer)},
    )
    @llma_track_latency("llma_review_queues_partial_update")
    @monitor(feature=None, endpoint="llma_review_queues_partial_update", method="PATCH")
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        queue = self.get_object()
        serializer = ReviewQueueUpdateSerializer(
            queue,
            data=request.data,
            partial=True,
            context={**self.get_serializer_context(), "team": self.team},
        )
        serializer.is_valid(raise_exception=True)
        queue = serializer.save()

        report_user_action(
            request.user,
            "llma review queue updated",
            self._event_properties(queue),
            team=self.team,
            request=request,
        )

        return Response(self._serialize_saved_queue(queue), status=status.HTTP_200_OK)

    @llma_track_latency("llma_review_queues_destroy")
    @monitor(feature=None, endpoint="llma_review_queues_destroy", method="DELETE")
    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        queue = self.get_object()

        queue.soft_delete()

        report_user_action(
            request.user,
            "llma review queue deleted",
            self._event_properties(queue),
            team=self.team,
            request=request,
        )

        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=[ProductKey.LLM_ANALYTICS])
class ReviewQueueItemViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, ModelViewSet):
    scope_object = "llm_analytics"
    permission_classes = [TraceReviewFeatureFlagPermission, AccessControlPermission]
    serializer_class = ReviewQueueItemSerializer
    queryset = ReviewQueueItem.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_class = ReviewQueueItemFilter
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def safely_get_queryset(
        self, queryset: QuerySet[ReviewQueueItem, ReviewQueueItem]
    ) -> QuerySet[ReviewQueueItem, ReviewQueueItem]:
        return (
            queryset.filter(team_id=self.team_id, deleted=False, queue__deleted=False)
            .select_related("queue", "created_by")
            .order_by("created_at", "id")
        )

    def _serialize_saved_item(self, item: ReviewQueueItem) -> dict[str, Any]:
        hydrated_item = self.get_queryset().get(pk=item.pk)
        return self.get_serializer(hydrated_item).data

    @staticmethod
    def _event_properties(item: ReviewQueueItem) -> dict[str, str]:
        return {
            "review_queue_item_id": str(item.id),
            "review_queue_id": str(item.queue_id),
            "trace_id": item.trace_id,
        }

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "queue_id",
                OpenApiTypes.UUID,
                description="Filter by a specific review queue ID.",
            ),
            OpenApiParameter(
                "trace_id",
                OpenApiTypes.STR,
                description="Filter by an exact trace ID.",
                examples=[OpenApiExample("Trace ID", value="trace_123")],
            ),
            OpenApiParameter(
                "trace_id__in",
                OpenApiTypes.STR,
                description="Filter by multiple trace IDs separated by commas.",
                examples=[OpenApiExample("Trace IDs", value="trace_123,trace_456")],
            ),
            OpenApiParameter(
                "search",
                OpenApiTypes.STR,
                description="Search pending trace IDs.",
                examples=[OpenApiExample("Search", value="trace_")],
            ),
            OpenApiParameter(
                "order_by",
                OpenApiTypes.STR,
                description="Order by `created_at` or `updated_at`.",
                examples=[OpenApiExample("Newest first", value="-created_at")],
            ),
        ]
    )
    @llma_track_latency("llma_review_queue_items_list")
    @monitor(feature=None, endpoint="llma_review_queue_items_list", method="GET")
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @llma_track_latency("llma_review_queue_items_retrieve")
    @monitor(feature=None, endpoint="llma_review_queue_items_retrieve", method="GET")
    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        request=ReviewQueueItemCreateSerializer,
        responses={201: OpenApiResponse(response=ReviewQueueItemSerializer)},
    )
    @llma_track_latency("llma_review_queue_items_create")
    @monitor(feature=None, endpoint="llma_review_queue_items_create", method="POST")
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = ReviewQueueItemCreateSerializer(
            data=request.data,
            context={**self.get_serializer_context(), "team": self.team},
        )
        serializer.is_valid(raise_exception=True)
        item = serializer.save()

        report_user_action(
            request.user,
            "llma review queue item created",
            self._event_properties(item),
            team=self.team,
            request=request,
        )

        return Response(self._serialize_saved_item(item), status=status.HTTP_201_CREATED)

    @extend_schema(
        request=ReviewQueueItemUpdateSerializer,
        responses={200: OpenApiResponse(response=ReviewQueueItemSerializer)},
    )
    @llma_track_latency("llma_review_queue_items_partial_update")
    @monitor(feature=None, endpoint="llma_review_queue_items_partial_update", method="PATCH")
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        item = self.get_object()
        serializer = ReviewQueueItemUpdateSerializer(
            item,
            data=request.data,
            context={**self.get_serializer_context(), "team": self.team},
        )
        serializer.is_valid(raise_exception=True)
        item = serializer.save()

        report_user_action(
            request.user,
            "llma review queue item moved",
            self._event_properties(item),
            team=self.team,
            request=request,
        )

        return Response(self._serialize_saved_item(item), status=status.HTTP_200_OK)

    @llma_track_latency("llma_review_queue_items_destroy")
    @monitor(feature=None, endpoint="llma_review_queue_items_destroy", method="DELETE")
    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        item = self.get_object()

        item.soft_delete()

        report_user_action(
            request.user,
            "llma review queue item deleted",
            self._event_properties(item),
            team=self.team,
            request=request,
        )

        return Response(status=status.HTTP_204_NO_CONTENT)

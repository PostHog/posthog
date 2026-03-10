from typing import cast

from django.db import IntegrityError
from django.db.models import Q, QuerySet
from django.utils import timezone

import django_filters
import posthoganalytics
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter
from rest_framework import serializers, status
from rest_framework.permissions import BasePermission
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
from products.llm_analytics.backend.models.trace_reviews import TraceReview
from products.llm_analytics.backend.trace_review_validation import normalize_and_validate_score_fields

TRACE_REVIEW_FEATURE_FLAG = "llma-trace-review"


def is_trace_review_feature_enabled(user: User, team: Team) -> bool:
    distinct_id = user.distinct_id or str(user.uuid)
    organization_id = str(team.organization_id)
    project_id = str(team.id)

    return posthoganalytics.feature_enabled(
        TRACE_REVIEW_FEATURE_FLAG,
        distinct_id,
        groups={"organization": organization_id, "project": project_id},
        group_properties={"organization": {"id": organization_id}, "project": {"id": project_id}},
        only_evaluate_locally=False,
        send_feature_flag_events=False,
    )


class TraceReviewFeatureFlagPermission(BasePermission):
    def has_permission(self, request, view) -> bool:
        return is_trace_review_feature_enabled(cast(User, request.user), view.team)


class TraceReviewSerializer(serializers.ModelSerializer):
    trace_id = serializers.CharField(
        max_length=255,
        help_text="Trace ID for the review. Only one active review can exist per trace and team.",
    )
    score_kind = serializers.ChoiceField(
        choices=TraceReview.ScoreKind.choices,
        required=False,
        allow_null=True,
        help_text="Optional score mode. Use `label` for good/bad reviews, `numeric` for a decimal score, or null for review-only.",
    )
    score_label = serializers.ChoiceField(
        choices=TraceReview.ScoreLabel.choices,
        required=False,
        allow_null=True,
        help_text="Optional label score. Only valid when `score_kind` is `label`.",
    )
    score_numeric = serializers.DecimalField(
        max_digits=8,
        decimal_places=3,
        required=False,
        allow_null=True,
        help_text="Optional numeric score. Only valid when `score_kind` is `numeric`.",
    )
    comment = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Optional human comment or reasoning for the review.",
    )
    created_by = UserBasicSerializer(read_only=True)
    reviewed_by = UserBasicSerializer(read_only=True, help_text="User who last saved this review.")

    class Meta:
        model = TraceReview
        fields = [
            "id",
            "trace_id",
            "score_kind",
            "score_label",
            "score_numeric",
            "comment",
            "created_at",
            "updated_at",
            "created_by",
            "reviewed_by",
            "team",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "created_by",
            "reviewed_by",
            "team",
        ]

    def validate(self, attrs: dict) -> dict:
        instance = self.instance
        team = self.context["get_team"]()

        trace_id = attrs.get("trace_id", instance.trace_id if instance else None)
        if not trace_id:
            raise serializers.ValidationError({"trace_id": "This field is required."})

        if instance and trace_id != instance.trace_id:
            raise serializers.ValidationError({"trace_id": "Trace ID cannot be changed once a review is created."})

        if not instance and TraceReview.objects.filter(team=team, trace_id=trace_id, deleted=False).exists():
            raise serializers.ValidationError({"trace_id": "An active review already exists for this trace."})

        return normalize_and_validate_score_fields(
            attrs,
            current_score_kind=instance.score_kind if instance else None,
            current_score_label=instance.score_label if instance else None,
            current_score_numeric=instance.score_numeric if instance else None,
        )

    def create(self, validated_data: dict, *args, **kwargs) -> TraceReview:
        request = self.context["request"]
        validated_data["team"] = self.context["get_team"]()
        validated_data["created_by"] = request.user
        validated_data["reviewed_by"] = request.user
        try:
            return super().create(validated_data, *args, **kwargs)
        except IntegrityError as err:
            raise serializers.ValidationError({"trace_id": "An active review already exists for this trace."}) from err

    def update(self, instance: TraceReview, validated_data: dict) -> TraceReview:
        validated_data["reviewed_by"] = self.context["request"].user
        return super().update(instance, validated_data)


class TraceIdInFilter(django_filters.BaseInFilter, django_filters.CharFilter):
    pass


class TraceReviewFilter(django_filters.FilterSet):
    trace_id = django_filters.CharFilter(field_name="trace_id", help_text="Filter by an exact trace ID.")
    trace_id__in = TraceIdInFilter(field_name="trace_id", lookup_expr="in", help_text="Filter by trace IDs.")
    search = django_filters.CharFilter(method="filter_search", help_text="Search in trace IDs or comments.")
    order_by = django_filters.OrderingFilter(
        fields=(
            ("updated_at", "updated_at"),
            ("created_at", "created_at"),
        ),
        field_labels={
            "updated_at": "Updated At",
            "created_at": "Created At",
        },
    )

    class Meta:
        model = TraceReview
        fields = {
            "trace_id": ["exact", "in"],
        }

    def filter_search(self, queryset: QuerySet, _name: str, value: str) -> QuerySet:
        if value:
            return queryset.filter(Q(trace_id__icontains=value) | Q(comment__icontains=value))
        return queryset


@extend_schema(tags=[ProductKey.LLM_ANALYTICS])
class TraceReviewViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, ModelViewSet):
    scope_object = "llm_analytics"
    permission_classes = [TraceReviewFeatureFlagPermission, AccessControlPermission]
    serializer_class = TraceReviewSerializer
    queryset = TraceReview.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_class = TraceReviewFilter

    def safely_get_queryset(self, queryset: QuerySet[TraceReview, TraceReview]) -> QuerySet[TraceReview, TraceReview]:
        return (
            queryset.filter(team_id=self.team_id)
            .exclude(deleted=True)
            .select_related("created_by", "reviewed_by")
            .order_by("-updated_at", "id")
        )

    def perform_create(self, serializer) -> None:
        instance = serializer.save()
        report_user_action(
            self.request.user,
            "llma trace review created",
            self._event_properties(instance),
            team=self.team,
            request=self.request,
        )

    def perform_update(self, serializer) -> None:
        instance = serializer.save()
        report_user_action(
            self.request.user,
            "llma trace review updated",
            self._event_properties(instance),
            team=self.team,
            request=self.request,
        )

    @llma_track_latency("llma_trace_reviews_destroy")
    @monitor(feature=None, endpoint="llma_trace_reviews_destroy", method="DELETE")
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if not instance.deleted:
            instance.deleted = True
            instance.deleted_at = timezone.now()
            instance.save(update_fields=["deleted", "deleted_at"])
            report_user_action(
                request.user,
                "llma trace review deleted",
                self._event_properties(instance),
                team=self.team,
                request=self.request,
            )

        return Response(status=status.HTTP_204_NO_CONTENT)

    @staticmethod
    def _event_properties(instance: TraceReview) -> dict[str, str | bool | None]:
        return {
            "trace_review_id": str(instance.id),
            "trace_id": instance.trace_id,
            "score_kind": instance.score_kind,
            "score_label": instance.score_label,
            "score_numeric": str(instance.score_numeric) if instance.score_numeric is not None else None,
            "has_comment": bool(instance.comment),
        }

    @extend_schema(
        parameters=[
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
                description="Search trace IDs and comments.",
                examples=[OpenApiExample("Comment search", value="hallucination")],
            ),
            OpenApiParameter(
                "order_by",
                OpenApiTypes.STR,
                description="Order by `updated_at` or `created_at`.",
                examples=[OpenApiExample("Newest first", value="-updated_at")],
            ),
        ]
    )
    @llma_track_latency("llma_trace_reviews_list")
    @monitor(feature=None, endpoint="llma_trace_reviews_list", method="GET")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @llma_track_latency("llma_trace_reviews_retrieve")
    @monitor(feature=None, endpoint="llma_trace_reviews_retrieve", method="GET")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @llma_track_latency("llma_trace_reviews_create")
    @monitor(feature=None, endpoint="llma_trace_reviews_create", method="POST")
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @llma_track_latency("llma_trace_reviews_update")
    @monitor(feature=None, endpoint="llma_trace_reviews_update", method="PUT")
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @llma_track_latency("llma_trace_reviews_partial_update")
    @monitor(feature=None, endpoint="llma_trace_reviews_partial_update", method="PATCH")
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, cast

from django.db import IntegrityError, transaction
from django.db.models import Prefetch, Q, QuerySet
from django.utils import timezone

import django_filters
import posthoganalytics
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse
from rest_framework import serializers, status
from rest_framework.permissions import BasePermission
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
from products.llm_analytics.backend.models.review_queues import ReviewQueueItem
from products.llm_analytics.backend.models.score_definitions import ScoreDefinition, ScoreDefinitionVersion
from products.llm_analytics.backend.models.trace_reviews import TraceReview, TraceReviewScore
from products.llm_analytics.backend.score_definition_configs import (
    ScoreDefinitionConfigField,
    normalize_score_definition_key,
)

TRACE_REVIEW_FEATURE_FLAG = "llma-trace-review"
TRACE_REVIEW_SCORE_VALUE_FIELDS = ("categorical_values", "numeric_value", "boolean_value")


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


class TraceReviewScoreSerializer(serializers.ModelSerializer):
    categorical_values = serializers.ListField(
        read_only=True,
        allow_null=True,
        child=serializers.CharField(),
        help_text="Categorical option keys selected for this score.",
    )
    definition_id = serializers.UUIDField(
        read_only=True,
        help_text="Stable scorer definition ID.",
    )
    definition_name = serializers.CharField(
        source="definition.name",
        read_only=True,
        help_text="Human-readable scorer name.",
    )
    definition_kind = serializers.CharField(
        source="definition.kind",
        read_only=True,
        help_text="Scorer kind for this saved score.",
    )
    definition_archived = serializers.BooleanField(
        source="definition.archived",
        read_only=True,
        help_text="Whether the scorer is currently archived.",
    )
    definition_version_id = serializers.UUIDField(
        source="definition_version",
        read_only=True,
        help_text="Immutable scorer version ID used to validate this score.",
    )
    definition_version = serializers.IntegerField(
        source="definition_version_number",
        read_only=True,
        help_text="Immutable scorer version number used to validate this score.",
    )
    definition_config = ScoreDefinitionConfigField(
        read_only=True,
        help_text="Immutable scorer configuration snapshot used to validate this score.",
    )

    class Meta:
        model = TraceReviewScore
        fields = [
            "id",
            "definition_id",
            "definition_name",
            "definition_kind",
            "definition_archived",
            "definition_version_id",
            "definition_version",
            "definition_config",
            "categorical_values",
            "numeric_value",
            "boolean_value",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class TraceReviewSerializer(serializers.ModelSerializer):
    trace_id = serializers.CharField(
        read_only=True,
        help_text="Trace ID for the review.",
    )
    comment = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Optional human comment or reasoning for the review.",
    )
    created_by = UserBasicSerializer(read_only=True)
    reviewed_by = UserBasicSerializer(read_only=True, help_text="User who last saved this review.")
    scores = TraceReviewScoreSerializer(
        many=True,
        read_only=True,
        help_text="Saved scorer values for this review.",
    )

    class Meta:
        model = TraceReview
        fields = [
            "id",
            "trace_id",
            "comment",
            "created_at",
            "updated_at",
            "created_by",
            "reviewed_by",
            "scores",
            "team",
        ]
        read_only_fields = fields


class TraceReviewScoreWriteSerializer(serializers.Serializer):
    definition_id = serializers.UUIDField(help_text="Stable scorer definition ID.")
    definition_version_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Optional immutable scorer version ID. Defaults to the scorer's current version.",
    )
    categorical_values = serializers.ListField(
        required=False,
        allow_null=True,
        min_length=1,
        child=serializers.CharField(allow_blank=False, max_length=128),
        help_text="Categorical option keys selected for this score.",
    )
    numeric_value = serializers.DecimalField(
        required=False,
        allow_null=True,
        max_digits=12,
        decimal_places=6,
        help_text="Numeric value selected for this score.",
    )
    boolean_value = serializers.BooleanField(
        required=False,
        allow_null=True,
        help_text="Boolean value selected for this score.",
    )

    def validate_categorical_values(self, value: list[str]) -> list[str]:
        normalized_values = [
            normalize_score_definition_key(option_key, field_name="categorical_values") for option_key in value
        ]

        if len(normalized_values) != len(set(normalized_values)):
            raise serializers.ValidationError("Provide unique categorical option keys.")

        return normalized_values

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        provided_fields = [
            field_name for field_name in TRACE_REVIEW_SCORE_VALUE_FIELDS if attrs.get(field_name) is not None
        ]

        if len(provided_fields) != 1:
            raise serializers.ValidationError("Provide exactly one score value field.")

        return attrs


class BaseTraceReviewWriteSerializer(serializers.Serializer):
    trace_id = serializers.CharField(
        max_length=255,
        required=False,
        help_text="Trace ID for the review. Only one active review can exist per trace and team.",
    )
    comment = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Optional human comment or reasoning for the review.",
    )
    scores = TraceReviewScoreWriteSerializer(
        many=True,
        required=False,
        help_text="Full desired score set for this review. Omit scorers you want to leave blank.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        team = cast(Team, self.context["team"])
        instance = cast(TraceReview | None, self.instance)

        trace_id = attrs.get("trace_id", instance.trace_id if instance else None)
        if not trace_id:
            raise serializers.ValidationError({"trace_id": "This field is required."})

        normalized_trace_id = trace_id.strip()
        if not normalized_trace_id:
            raise serializers.ValidationError({"trace_id": "This field is required."})

        if instance and normalized_trace_id != instance.trace_id:
            raise serializers.ValidationError({"trace_id": "Trace ID cannot be changed once a review is created."})

        if not instance and TraceReview.objects.filter(team=team, trace_id=normalized_trace_id, deleted=False).exists():
            raise serializers.ValidationError({"trace_id": "An active review already exists for this trace."})

        attrs["trace_id"] = normalized_trace_id

        if "comment" in attrs:
            attrs["comment"] = (attrs.get("comment") or "").strip() or None

        if not instance:
            attrs["scores"] = attrs.get("scores", [])

        if "scores" in attrs:
            attrs["_resolved_scores"] = self._resolve_scores(cast(list[dict[str, Any]], attrs["scores"]))

        return attrs

    @staticmethod
    def _decimal_from_config(value: Any) -> Decimal | None:
        if value is None:
            return None

        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return None

    @staticmethod
    def _int_from_config(value: Any) -> int | None:
        if value is None:
            return None

        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _resolve_scores(self, score_payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
        team = cast(Team, self.context["team"])
        score_errors: list[dict[str, str]] = [{} for _ in score_payloads]

        definition_positions: dict[str, list[int]] = {}
        for index, score_payload in enumerate(score_payloads):
            definition_key = str(score_payload["definition_id"])
            definition_positions.setdefault(definition_key, []).append(index)

        for positions in definition_positions.values():
            if len(positions) > 1:
                for position in positions:
                    score_errors[position]["definition_id"] = "Each scorer can only appear once per review."

        definition_ids = [score_payload["definition_id"] for score_payload in score_payloads]
        requested_version_ids = {
            score_payload["definition_version_id"]
            for score_payload in score_payloads
            if score_payload.get("definition_version_id") is not None
        }

        definition_lookup = {
            str(definition.id): definition
            for definition in ScoreDefinition.objects.filter(team=team)
            .filter(Q(id__in=definition_ids) | Q(versions__id__in=requested_version_ids))
            .select_related("current_version")
            .prefetch_related("versions")
            .distinct()
        }
        version_lookup = {
            str(version.id): version
            for definition in definition_lookup.values()
            for version in definition.versions.all()
            if version.id in requested_version_ids
        }

        resolved_scores: list[dict[str, Any]] = []

        for index, score_payload in enumerate(score_payloads):
            definition_key = str(score_payload["definition_id"])
            definition = definition_lookup.get(definition_key)

            if definition is None:
                score_errors[index]["definition_id"] = "Unknown scorer definition."
                continue

            definition_version_id = score_payload.get("definition_version_id")
            if definition_version_id is None:
                definition_version = definition.current_version
                if definition_version is None:
                    score_errors[index]["definition_version_id"] = "This scorer does not have a current version."
                    continue
            else:
                definition_version = version_lookup.get(str(definition_version_id))
                if definition_version is None:
                    score_errors[index]["definition_version_id"] = "Unknown scorer version."
                    continue

            if definition_version.definition_id != definition.id:
                score_errors[index]["definition_version_id"] = "This scorer version does not belong to the scorer."
                continue

            validation_error = self._validate_score_value(definition, definition_version, score_payload)
            if validation_error:
                score_errors[index].update(validation_error)
                continue

            resolved_scores.append(
                {
                    "definition": definition,
                    "definition_version": definition_version,
                    "categorical_values": score_payload.get("categorical_values"),
                    "numeric_value": score_payload.get("numeric_value"),
                    "boolean_value": score_payload.get("boolean_value"),
                }
            )

        if any(error for error in score_errors):
            raise serializers.ValidationError({"scores": score_errors})

        return resolved_scores

    def _validate_score_value(
        self,
        definition: ScoreDefinition,
        definition_version: ScoreDefinitionVersion,
        score_payload: dict[str, Any],
    ) -> dict[str, str]:
        if definition.kind == ScoreDefinition.Kind.CATEGORICAL:
            categorical_values = score_payload.get("categorical_values")
            if categorical_values is None:
                return {"categorical_values": "This scorer requires `categorical_values`."}

            option_keys = {
                option["key"]
                for option in definition_version.config.get("options", [])
                if isinstance(option, dict) and isinstance(option.get("key"), str)
            }

            invalid_values = [option_key for option_key in categorical_values if option_key not in option_keys]
            if invalid_values:
                return {"categorical_values": "Select valid categorical option keys."}

            selection_mode = definition_version.config.get("selection_mode") or "single"
            selection_count = len(categorical_values)

            if selection_mode == "single":
                if selection_count != 1:
                    return {"categorical_values": "This scorer allows exactly one categorical option."}
                return {}

            minimum = self._int_from_config(definition_version.config.get("min_selections"))
            maximum = self._int_from_config(definition_version.config.get("max_selections"))

            if minimum is not None and selection_count < minimum:
                return {"categorical_values": f"Select at least {minimum} categorical options."}

            if maximum is not None and selection_count > maximum:
                return {"categorical_values": f"Select no more than {maximum} categorical options."}

            return {}

        if definition.kind == ScoreDefinition.Kind.NUMERIC:
            numeric_value = score_payload.get("numeric_value")
            if numeric_value is None:
                return {"numeric_value": "This scorer requires `numeric_value`."}

            numeric_minimum = self._decimal_from_config(definition_version.config.get("min"))
            numeric_maximum = self._decimal_from_config(definition_version.config.get("max"))
            numeric_step = self._decimal_from_config(definition_version.config.get("step"))

            if numeric_minimum is not None and numeric_value < numeric_minimum:
                return {"numeric_value": f"Ensure this value is greater than or equal to {numeric_minimum}."}

            if numeric_maximum is not None and numeric_value > numeric_maximum:
                return {"numeric_value": f"Ensure this value is less than or equal to {numeric_maximum}."}

            if numeric_step is not None:
                base = numeric_minimum if numeric_minimum is not None else Decimal("0")
                if (numeric_value - base) % numeric_step != 0:
                    return {"numeric_value": f"Ensure this value increments by {numeric_step}."}

            return {}

        boolean_value = score_payload.get("boolean_value")
        if boolean_value is None:
            return {"boolean_value": "This scorer requires `boolean_value`."}

        return {}

    def _replace_scores(self, review: TraceReview, resolved_scores: list[dict[str, Any]]) -> None:
        TraceReviewScore.objects.filter(review=review).delete()

        if not resolved_scores:
            return

        TraceReviewScore.objects.bulk_create(
            [
                TraceReviewScore(
                    team=review.team,
                    review=review,
                    definition=score_payload["definition"],
                    definition_version=score_payload["definition_version"].id,
                    definition_version_number=score_payload["definition_version"].version,
                    definition_config=score_payload["definition_version"].config,
                    categorical_values=score_payload["categorical_values"],
                    numeric_value=score_payload["numeric_value"],
                    boolean_value=score_payload["boolean_value"],
                    created_by=cast(User, self.context["request"].user),
                )
                for score_payload in resolved_scores
            ]
        )

    def _clear_pending_queue_item(self, *, team: Team, trace_id: str) -> None:
        pending_item = (
            ReviewQueueItem.objects.select_for_update().filter(team=team, trace_id=trace_id, deleted=False).first()
        )
        if pending_item is not None:
            pending_item.soft_delete()

    @transaction.atomic
    def create(self, validated_data: dict[str, Any]) -> TraceReview:
        request = cast(Request, self.context["request"])
        team = cast(Team, self.context["team"])
        review_user = cast(User, request.user)
        resolved_scores = cast(list[dict[str, Any]], validated_data.pop("_resolved_scores", []))
        validated_data.pop("scores", None)
        trace_id = validated_data["trace_id"]

        Team.objects.select_for_update().get(id=team.id)

        try:
            review = TraceReview.objects.create(
                team=team,
                trace_id=trace_id,
                comment=validated_data.get("comment"),
                created_by=review_user,
                reviewed_by=review_user,
            )
        except IntegrityError as err:
            raise serializers.ValidationError({"trace_id": "An active review already exists for this trace."}) from err

        self._clear_pending_queue_item(team=team, trace_id=review.trace_id)
        self._replace_scores(review, resolved_scores)
        return review

    @transaction.atomic
    def update(self, instance: TraceReview, validated_data: dict[str, Any]) -> TraceReview:
        request = cast(Request, self.context["request"])
        team = cast(Team, self.context["team"])
        review_user = cast(User, request.user)
        resolved_scores = cast(list[dict[str, Any]] | None, validated_data.pop("_resolved_scores", None))
        validated_data.pop("scores", None)
        validated_data.pop("trace_id", None)

        if "comment" in validated_data:
            instance.comment = validated_data["comment"]

        instance.reviewed_by = review_user
        instance.save(update_fields=["comment", "reviewed_by", "updated_at"])

        self._clear_pending_queue_item(team=team, trace_id=instance.trace_id)

        if resolved_scores is not None:
            self._replace_scores(instance, resolved_scores)

        return instance


class TraceReviewCreateSerializer(BaseTraceReviewWriteSerializer):
    trace_id = serializers.CharField(
        max_length=255,
        help_text="Trace ID for the review. Only one active review can exist per trace and team.",
    )


class TraceReviewUpdateSerializer(BaseTraceReviewWriteSerializer):
    pass


class TraceIdInFilter(django_filters.BaseInFilter, django_filters.CharFilter):
    pass


class TraceReviewDefinitionInFilter(django_filters.BaseInFilter, django_filters.UUIDFilter):
    pass


class TraceReviewFilter(django_filters.FilterSet):
    trace_id = django_filters.CharFilter(field_name="trace_id", help_text="Filter by an exact trace ID.")
    trace_id__in = TraceIdInFilter(field_name="trace_id", lookup_expr="in", help_text="Filter by trace IDs.")
    definition_id = django_filters.UUIDFilter(
        method="filter_definition_id",
        help_text="Filter by a stable scorer definition ID.",
    )
    definition_id__in = TraceReviewDefinitionInFilter(
        method="filter_definition_id_in",
        help_text="Filter by multiple scorer definition IDs separated by commas.",
    )
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

    def filter_definition_id(self, queryset: QuerySet, _name: str, value: Any) -> QuerySet:
        if value:
            return queryset.filter(scores__definition_id=value).distinct()
        return queryset

    def filter_definition_id_in(self, queryset: QuerySet, _name: str, value: Any) -> QuerySet:
        if value:
            return queryset.filter(scores__definition_id__in=value).distinct()
        return queryset

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
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def safely_get_queryset(self, queryset: QuerySet[TraceReview, TraceReview]) -> QuerySet[TraceReview, TraceReview]:
        score_queryset = TraceReviewScore.objects.select_related("definition").order_by("definition__name", "id")

        return (
            queryset.filter(team_id=self.team_id)
            .exclude(deleted=True)
            .select_related("created_by", "reviewed_by")
            .prefetch_related(Prefetch("scores", queryset=score_queryset))
            .order_by("-updated_at", "id")
        )

    def _serialize_saved_review(self, review: TraceReview) -> dict[str, Any]:
        hydrated_review = self.get_queryset().get(pk=review.pk)
        return self.get_serializer(hydrated_review).data

    @staticmethod
    def _event_properties(review: TraceReview) -> dict[str, str | bool | int]:
        return {
            "trace_review_id": str(review.id),
            "trace_id": review.trace_id,
            "score_count": review.scores.count(),
            "has_comment": bool(review.comment),
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
                "definition_id",
                OpenApiTypes.UUID,
                description="Filter by a stable scorer definition ID.",
            ),
            OpenApiParameter(
                "definition_id__in",
                OpenApiTypes.STR,
                description="Filter by multiple scorer definition IDs separated by commas.",
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
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @llma_track_latency("llma_trace_reviews_retrieve")
    @monitor(feature=None, endpoint="llma_trace_reviews_retrieve", method="GET")
    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        request=TraceReviewCreateSerializer, responses={201: OpenApiResponse(response=TraceReviewSerializer)}
    )
    @llma_track_latency("llma_trace_reviews_create")
    @monitor(feature=None, endpoint="llma_trace_reviews_create", method="POST")
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = TraceReviewCreateSerializer(
            data=request.data,
            context={**self.get_serializer_context(), "team": self.team},
        )
        serializer.is_valid(raise_exception=True)
        review = serializer.save()

        report_user_action(
            request.user,
            "llma trace review created",
            self._event_properties(review),
            team=self.team,
            request=request,
        )

        return Response(self._serialize_saved_review(review), status=status.HTTP_201_CREATED)

    @extend_schema(
        request=TraceReviewUpdateSerializer, responses={200: OpenApiResponse(response=TraceReviewSerializer)}
    )
    @llma_track_latency("llma_trace_reviews_partial_update")
    @monitor(feature=None, endpoint="llma_trace_reviews_partial_update", method="PATCH")
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        review = self.get_object()
        serializer = TraceReviewUpdateSerializer(
            review,
            data=request.data,
            partial=True,
            context={**self.get_serializer_context(), "team": self.team},
        )
        serializer.is_valid(raise_exception=True)
        review = serializer.save()

        report_user_action(
            request.user,
            "llma trace review updated",
            self._event_properties(review),
            team=self.team,
            request=request,
        )

        return Response(self._serialize_saved_review(review), status=status.HTTP_200_OK)

    @llma_track_latency("llma_trace_reviews_destroy")
    @monitor(feature=None, endpoint="llma_trace_reviews_destroy", method="DELETE")
    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        review = self.get_object()
        if not review.deleted:
            review.deleted = True
            review.deleted_at = timezone.now()
            review.save(update_fields=["deleted", "deleted_at", "updated_at"])

            report_user_action(
                request.user,
                "llma trace review deleted",
                self._event_properties(review),
                team=self.team,
                request=request,
            )

        return Response(status=status.HTTP_204_NO_CONTENT)

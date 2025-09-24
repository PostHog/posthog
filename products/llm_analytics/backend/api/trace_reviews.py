from django.db import IntegrityError
from django.db.models import QuerySet

from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from posthog.api.documentation import extend_schema
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer

from products.llm_analytics.backend.models import TraceReview


class TraceReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = TraceReview
        fields = [
            "id",
            "trace_id",
            "reviewed_by",
            "reviewed_at",
            "created_at",
            "updated_at",
            "team",
        ]
        read_only_fields = [
            "id",
            "reviewed_by",
            "reviewed_at",
            "created_at",
            "updated_at",
            "team",
        ]

    reviewed_by = UserBasicSerializer(read_only=True)

    def create(self, validated_data: dict, *args, **kwargs):
        request = self.context["request"]
        validated_data["team"] = self.context["get_team"]()
        validated_data["reviewed_by"] = request.user
        return super().create(validated_data, *args, **kwargs)


class TraceReviewViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, ModelViewSet):
    scope_object = "trace_review"
    serializer_class = TraceReviewSerializer
    queryset = TraceReview.objects.all()

    def safely_get_queryset(self, queryset: QuerySet[TraceReview, TraceReview]) -> QuerySet[TraceReview, TraceReview]:
        return queryset

    @extend_schema(
        request=TraceReviewSerializer,
        responses={201: TraceReviewSerializer, 409: {"description": "Trace already reviewed"}},
        summary="Mark a trace as reviewed",
        description="Mark a trace as reviewed by the current user. Each trace can only be reviewed once per team.",
    )
    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            instance = serializer.save()
            return Response(self.get_serializer(instance).data, status=status.HTTP_201_CREATED)
        except IntegrityError:
            return Response(
                {"detail": "This trace has already been reviewed for this team."}, status=status.HTTP_409_CONFLICT
            )

    @extend_schema(
        methods=["GET"],
        responses={200: TraceReviewSerializer, 404: {"description": "Review not found"}},
        summary="Get review status for a trace",
        description="Get the review status for a specific trace.",
    )
    @extend_schema(
        methods=["DELETE"],
        responses={204: {"description": "Review removed successfully"}, 404: {"description": "Review not found"}},
        summary="Remove review from a trace",
        description="Remove the review status from a trace.",
    )
    @extend_schema(
        methods=["POST"],
        request=serializers.ListField(child=serializers.CharField(max_length=255)),
        responses={200: serializers.DictField()},
        summary="Get review status for multiple traces",
        description="Get review status for multiple traces in a single request.",
    )
    @action(detail=False, methods=["post"], url_path="batch-status")
    def batch_status(self, request: Request, parent_lookup_team_id: str) -> Response:
        trace_ids = request.data
        if not isinstance(trace_ids, list):
            return Response({"detail": "Expected a list of trace IDs."}, status=status.HTTP_400_BAD_REQUEST)

        team = self.team
        reviews = TraceReview.objects.filter(team=team, trace_id__in=trace_ids).select_related("reviewed_by")

        # Create a dictionary mapping trace_id to review data
        review_dict = {}
        for review in reviews:
            review_dict[review.trace_id] = {
                "id": review.id,
                "reviewed_by": {
                    "id": review.reviewed_by.id,
                    "email": review.reviewed_by.email,
                    "first_name": review.reviewed_by.first_name,
                },
                "reviewed_at": review.reviewed_at,
            }

        return Response(review_dict)

    @action(detail=False, methods=["get", "delete"], url_path="by-trace/(?P<trace_id>[^/.]+)")
    def trace_review_by_id(self, request: Request, parent_lookup_team_id: str, trace_id: str) -> Response:
        team = self.team
        try:
            review = TraceReview.objects.get(team=team, trace_id=trace_id)

            if request.method == "DELETE":
                review.delete()
                return Response(status=status.HTTP_204_NO_CONTENT)
            else:  # GET
                serializer = self.get_serializer(review)
                return Response(serializer.data)

        except TraceReview.DoesNotExist:
            return Response({"detail": "Review not found for this trace."}, status=status.HTTP_404_NOT_FOUND)

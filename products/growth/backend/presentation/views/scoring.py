from typing import Any, cast

from drf_spectacular.utils import OpenApiResponse
from rest_framework import request, response, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated

from posthog.api.mixins import validated_request
from posthog.api.utils import ErrorResponseSerializer
from posthog.exceptions import Conflict
from posthog.exceptions_capture import capture_exception
from posthog.models import User
from posthog.permissions import IsStaffUser

from products.growth.backend.facade.scoring import (
    DuplicateScoringVersion,
    ScoringConfigNotFound,
    ScoringPreviewUnavailable,
    activate_scoring_formula,
    default_scoring_source,
    list_scoring_configs,
    preview_formula,
    save_scoring_formula,
)
from products.growth.backend.presentation.scoring_serializers import (
    ScoringActivateRequestSerializer,
    ScoringConfigListResponseSerializer,
    ScoringConfigSerializer,
    ScoringOutcomeSerializer,
    ScoringPreviewRequestSerializer,
    ScoringPreviewResponseSerializer,
    ScoringSaveRequestSerializer,
)


class ScoringViewSet(viewsets.ViewSet):
    scope_object = "INTERNAL"
    permission_classes = [IsAuthenticated, IsStaffUser]

    def handle_exception(self, exc: Exception) -> response.Response:
        capture_exception(exc, {"path": "growth_enrichment_scoring", "action": self.action})
        if isinstance(exc, ScoringConfigNotFound):
            exc = NotFound(str(exc))
        elif isinstance(exc, ScoringPreviewUnavailable):
            exc = ValidationError(str(exc))
        elif isinstance(exc, DuplicateScoringVersion):
            exc = Conflict(str(exc))
        return super().handle_exception(exc)

    @validated_request(responses={200: OpenApiResponse(response=ScoringConfigListResponseSerializer)})
    @action(methods=["GET"], detail=False)
    def configs(self, request: request.Request, **kwargs: Any) -> response.Response:
        serializer = ScoringConfigListResponseSerializer(
            {"results": list_scoring_configs(), "default_source": default_scoring_source()}
        )
        return response.Response(serializer.data)

    @validated_request(
        request_serializer=ScoringPreviewRequestSerializer,
        responses={
            200: OpenApiResponse(response=ScoringPreviewResponseSerializer),
            400: OpenApiResponse(response=ErrorResponseSerializer),
        },
    )
    @action(methods=["POST"], detail=False)
    def preview(self, request: request.Request, **kwargs: Any) -> response.Response:
        data = request.validated_data
        rows = preview_formula(data["source"], data["base_config_id"], data["sample"])
        serializer = ScoringPreviewResponseSerializer(
            {
                "results": rows,
                "summary": {
                    "evaluated": len(rows),
                    "changed": sum(
                        row.error is None
                        and ScoringOutcomeSerializer(row.active).data != ScoringOutcomeSerializer(row.preview).data
                        for row in rows
                    ),
                    "errors": sum(row.error is not None for row in rows),
                },
            }
        )
        return response.Response(serializer.data)

    @validated_request(
        request_serializer=ScoringSaveRequestSerializer,
        responses={
            201: OpenApiResponse(response=ScoringConfigSerializer),
            404: OpenApiResponse(response=ErrorResponseSerializer),
            409: OpenApiResponse(response=ErrorResponseSerializer),
        },
    )
    @action(methods=["POST"], detail=False)
    def save(self, request: request.Request, **kwargs: Any) -> response.Response:
        data = request.validated_data
        config = save_scoring_formula(
            data["source"], data["version"], data["base_config_id"], cast(User, request.user).id
        )
        return response.Response(ScoringConfigSerializer(config).data, status=status.HTTP_201_CREATED)

    @validated_request(
        request_serializer=ScoringActivateRequestSerializer,
        responses={
            200: OpenApiResponse(response=ScoringConfigSerializer),
            404: OpenApiResponse(response=ErrorResponseSerializer),
        },
    )
    @action(methods=["POST"], detail=False)
    def activate(self, request: request.Request, **kwargs: Any) -> response.Response:
        config = activate_scoring_formula(request.validated_data["config_id"])
        return response.Response(ScoringConfigSerializer(config).data)

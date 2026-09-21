from typing import Any, cast

from django.db import IntegrityError
from django.shortcuts import get_object_or_404

from drf_spectacular.utils import OpenApiResponse
from rest_framework import request, response, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated

from posthog.api.mixins import validated_request
from posthog.api.utils import ErrorResponseSerializer
from posthog.exceptions import Conflict
from posthog.exceptions_capture import capture_exception
from posthog.models import User
from posthog.permissions import IsStaffUser

from products.growth.backend.api.scoring_serializers import (
    ScoringActivateRequestSerializer,
    ScoringConfigListResponseSerializer,
    ScoringConfigSerializer,
    ScoringOutcomeSerializer,
    ScoringPreviewRequestSerializer,
    ScoringPreviewResponseSerializer,
    ScoringSaveRequestSerializer,
)
from products.growth.backend.enrichment.scoring_lab import preview_scoring_formula
from products.growth.backend.enrichment.scoring_rules import parse_scoring_rules
from products.growth.backend.models import IcpScoringConfig


class ScoringViewSet(viewsets.ViewSet):
    scope_object = "INTERNAL"
    permission_classes = [IsAuthenticated, IsStaffUser]

    def handle_exception(self, exc: Exception) -> response.Response:
        capture_exception(exc, {"path": "growth_enrichment_scoring", "action": self.action})
        return super().handle_exception(exc)

    @validated_request(responses={200: OpenApiResponse(response=ScoringConfigListResponseSerializer)})
    @action(methods=["GET"], detail=False)
    def configs(self, request: request.Request, **kwargs: Any) -> response.Response:
        configs = IcpScoringConfig.objects.select_related("created_by").order_by("-created_at")[:100]
        serializer = ScoringConfigListResponseSerializer(
            {"results": configs, "default_source": parse_scoring_rules({}).source}
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
        active = IcpScoringConfig.objects.filter(is_active=True).first()
        if active is None:
            raise ValidationError("Import and activate the initial scoring lists before previewing a formula.")
        data = request.validated_data
        base = get_object_or_404(IcpScoringConfig, pk=data["base_config_id"])
        rows = preview_scoring_formula(active, base, data["source"], data["sample"])
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
        base = get_object_or_404(IcpScoringConfig, pk=data["base_config_id"])
        rules = parse_scoring_rules(base.scoring_rules)
        try:
            config = IcpScoringConfig.objects.create(
                version=data["version"],
                tags=base.tags,
                quality_investors=base.quality_investors,
                scoring_rules={"source": data["source"], "ai_labels": list(rules.ai_labels)},
                created_by=cast(User, request.user),
                is_active=False,
            )
        except IntegrityError as error:
            raise Conflict("A scoring version with this name already exists. Choose another name.") from error
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
        config = get_object_or_404(IcpScoringConfig, pk=request.validated_data["config_id"])
        config.activate()
        return response.Response(ScoringConfigSerializer(config).data)

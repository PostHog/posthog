import uuid
from typing import Any, cast

from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import validated_request
from posthog.auth import InternalAPIUser, ScopedServiceJWTAuthentication
from posthog.llm.gateway_client import GatewayNotConfiguredError

from products.ml_inference.backend.facade.contracts import (
    DecisionGatewayError,
    DecisionGatewayUnreachableError,
    DecisionsDisabledError,
)
from products.workflows.backend.facade.api import classify_workflow_text, workflow_exists
from products.workflows.backend.facade.service_jwt import WORKFLOW_CLASSIFICATION_PURPOSE


class WorkflowClassificationJWTAuthentication(ScopedServiceJWTAuthentication):
    purpose = WORKFLOW_CLASSIFICATION_PURPOSE

    # nosemgrep: tuple-return-prefer-dataclass -- DRF authentication contract
    def _authenticate_claims(self, request: Request, claims: dict[str, Any]) -> tuple[Any, Any]:
        user, _ = super()._authenticate_claims(request, claims)
        try:
            workflow_id = uuid.UUID(str(claims.get("hog_flow_id")))
        except ValueError as error:
            raise AuthenticationFailed("Service token is missing its workflow claim.") from error
        return user, workflow_id


class WorkflowClassificationRequestSerializer(serializers.Serializer):
    text = serializers.CharField(
        max_length=8192, trim_whitespace=False, help_text="Text to classify, up to 8 KiB encoded as UTF-8."
    )
    instructions = serializers.CharField(max_length=2000, help_text="How to choose a label for the text.")
    labels = serializers.DictField(
        child=serializers.CharField(max_length=1000, allow_blank=True),
        help_text="2 to 16 label names mapped to descriptions of when to use each label.",
    )

    def validate_text(self, value: str) -> str:
        if len(value.encode("utf-8")) > 8192:
            raise serializers.ValidationError("Text must be at most 8 KiB.")
        return value

    def validate_labels(self, value: dict[str, str]) -> dict[str, str]:
        if not 2 <= len(value) <= 16:
            raise serializers.ValidationError("Add between 2 and 16 labels.")
        if any(not label.strip() or len(label) > 100 for label in value):
            raise serializers.ValidationError("Labels must be non-empty and at most 100 characters.")
        return value


class WorkflowClassificationResponseSerializer(serializers.Serializer):
    label = serializers.CharField(help_text="The chosen label.")
    confidence = serializers.FloatField(help_text="Confidence in the chosen label, between 0 and 1.")
    probabilities = serializers.DictField(
        child=serializers.FloatField(), help_text="Probability of each configured label, between 0 and 1."
    )


class WorkflowClassificationErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Why the classification could not run.")


class WorkflowClassificationViewSet(viewsets.GenericViewSet):
    authentication_classes = [WorkflowClassificationJWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = WorkflowClassificationRequestSerializer

    @validated_request(
        request_serializer=WorkflowClassificationRequestSerializer,
        responses={
            200: WorkflowClassificationResponseSerializer,
            403: WorkflowClassificationErrorSerializer,
            422: WorkflowClassificationErrorSerializer,
            502: WorkflowClassificationErrorSerializer,
            503: WorkflowClassificationErrorSerializer,
        },
        summary="Classify text from a workflow with JEV",
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        team_id = cast(int, cast(InternalAPIUser, request.user).current_team_id)
        workflow_id = cast(uuid.UUID, request.auth)
        if not workflow_exists(team_id=team_id, workflow_id=workflow_id):
            return Response({"detail": "Workflow no longer exists."}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        data = request.validated_data
        try:
            result = classify_workflow_text(
                team_id=team_id,
                workflow_id=str(workflow_id),
                text=data["text"],
                instructions=data["instructions"],
                labels=data["labels"],
            )
        except DecisionsDisabledError:
            return Response(
                {
                    "detail": "JEV classification requires decisions to be enabled and AI data processing to be approved."
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        except (GatewayNotConfiguredError, DecisionGatewayUnreachableError):
            return Response(
                {"detail": "JEV is unavailable. Try again later."}, status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except DecisionGatewayError:
            return Response({"detail": "JEV could not classify this text."}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(WorkflowClassificationResponseSerializer(result).data)

from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from ..build import OrchestraBuildError
from ..facade import api
from .serializers import (
    DeploymentFilterSerializer,
    DeploymentRegisterSerializer,
    DeploymentSummarySerializer,
    ExecutionDetailSerializer,
    ExecutionFilterSerializer,
    ExecutionSummarySerializer,
    TriggeredExecutionResponseSerializer,
    TriggerExecutionSerializer,
)


class ExecutionViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "orchestra"

    @extend_schema(
        parameters=[ExecutionFilterSerializer],
        responses={200: ExecutionSummarySerializer(many=True)},
        description="List workflow executions with optional filters.",
    )
    def list(self, request: Request, **kwargs) -> Response:
        filters = ExecutionFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        items = api.list_executions(
            team_id=self.team_id,
            status=filters.validated_data.get("status"),
            execution_type=filters.validated_data.get("execution_type"),
            date_from=filters.validated_data.get("date_from") or None,
            date_to=filters.validated_data.get("date_to") or None,
            limit=filters.validated_data.get("limit", 50),
            offset=filters.validated_data.get("offset", 0),
        )
        return Response(ExecutionSummarySerializer(items, many=True).data)

    @extend_schema(
        responses={200: ExecutionDetailSerializer},
        description="Retrieve a workflow execution with its full event history.",
    )
    def retrieve(self, request: Request, pk: str = "", **kwargs) -> Response:
        detail = api.get_execution(pk, team_id=self.team_id)
        return Response(ExecutionDetailSerializer(detail).data, status=status.HTTP_200_OK)

    @extend_schema(
        request=TriggerExecutionSerializer,
        responses={201: TriggeredExecutionResponseSerializer},
        description="Trigger a workflow execution against the team's active deployment.",
    )
    def create(self, request: Request, **kwargs) -> Response:
        payload = TriggerExecutionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            execution_id = api.trigger_execution(
                team_id=self.team_id,
                execution_type=payload.validated_data["execution_type"],
                input=payload.validated_data.get("input"),
            )
        except LookupError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        return Response(
            TriggeredExecutionResponseSerializer({"execution_id": execution_id}).data,
            status=status.HTTP_201_CREATED,
        )


class DeploymentViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "orchestra"

    @extend_schema(
        parameters=[DeploymentFilterSerializer],
        responses={200: DeploymentSummarySerializer(many=True)},
        description="List recent deployments for the current team, newest first.",
    )
    def list(self, request: Request, **kwargs) -> Response:
        filters = DeploymentFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        items = api.list_deployments(
            team_id=self.team_id,
            date_from=filters.validated_data.get("date_from") or None,
            date_to=filters.validated_data.get("date_to") or None,
            limit=filters.validated_data.get("limit", 50),
        )
        return Response(DeploymentSummarySerializer(items, many=True).data)

    @extend_schema(
        request=DeploymentRegisterSerializer,
        responses={201: DeploymentSummarySerializer},
        description=(
            "Deploy a pre-built image. PostHog `docker run`s the image, registers the "
            "deployment as active, and starts draining the previous active deployment "
            "(if any) in a background thread."
        ),
    )
    def create(self, request: Request, **kwargs) -> Response:
        payload = DeploymentRegisterSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            summary = api.deploy_existing_image(
                team_id=self.team_id,
                code_version=payload.validated_data["code_version"],
                image_name=payload.validated_data["image_name"],
                registered_executions=payload.validated_data.get("registered_executions") or [],
            )
        except OrchestraBuildError as e:
            return Response({"detail": str(e)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(DeploymentSummarySerializer(summary).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        responses={200: DeploymentSummarySerializer},
        description="Return the currently-active deployment for the team, if any.",
    )
    @action(detail=False, methods=["get"], url_path="active", required_scopes=["orchestra:read"])
    def active(self, request: Request, **kwargs) -> Response:
        summary = api.get_active_deployment(team_id=self.team_id)
        if summary is None:
            return Response({"detail": "no active deployment"}, status=status.HTTP_404_NOT_FOUND)
        return Response(DeploymentSummarySerializer(summary).data)

    @extend_schema(
        responses={200: DeploymentSummarySerializer},
        description="Mark a deployment as stopped (called by the deploy script after `docker stop`).",
    )
    @action(detail=True, methods=["post"], url_path="mark_stopped", required_scopes=["orchestra:write"])
    def mark_stopped(self, request: Request, pk: str = "", **kwargs) -> Response:
        summary = api.mark_deployment_stopped(deployment_id=int(pk), team_id=self.team_id)
        if summary is None:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(DeploymentSummarySerializer(summary).data)

"""HTTP presentation for the subscription-owned Pulse history and feedback API."""

from typing import Literal, cast
from uuid import UUID

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.auth import OAuthAccessTokenAuthentication
from posthog.models import User
from posthog.permissions import APIScopePermission
from posthog.temporal.oauth import SANDBOX_OAUTH_APP_CLIENT_IDS

from products.subscriptions.backend.facade import api as pulse_api

from .serializers import (
    OutcomeDecisionResponseSerializer,
    OutcomeDecisionSerializer,
    ProactiveConfigurationOptionsSerializer,
    PulseExperimentDraftResponseSerializer,
    PulseExperimentDraftSerializer,
    PulseHistoryQuerySerializer,
    PulseOutcomeReplayResponseSerializer,
    PulsePublicResearchRequestSerializer,
    PulsePublicResearchResponseSerializer,
    PulseRunHistorySerializer,
)


class PulseExperimentDraftConflictResponse(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "The experiment draft request conflicts with its reservation."
    default_code = "pulse_experiment_draft_conflict"


class PulsePublicResearchUnavailableResponse(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Public research is temporarily unavailable."
    default_code = "pulse_public_research_unavailable"


class PulsePublicResearchConflictResponse(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Public research has reached its limit or an identical request is still running."
    default_code = "pulse_public_research_conflict"


class PulseHistoryViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "subscription"
    serializer_class = PulseRunHistorySerializer
    pagination_class = None

    @validated_request(
        query_serializer=PulseHistoryQuerySerializer,
        responses={200: OpenApiResponse(response=PulseRunHistorySerializer(many=True))},
        description="Return bounded proactive delivery history without raw evidence bodies.",
    )
    def list(self, request: ValidatedRequest, **kwargs) -> Response:
        subscription_id = request.validated_query_data["subscription_id"]
        try:
            history = pulse_api.list_pulse_history(
                team_id=self.team_id,
                team=self.team,
                user=cast(User, request.user),
                subscription_id=subscription_id,
            )
        except pulse_api.PulseSubscriptionNotFound as error:
            raise NotFound("Subscription not found.") from error
        return Response(PulseRunHistorySerializer(instance=history, many=True).data)


class PulseConfigurationOptionsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "subscription"
    serializer_class = ProactiveConfigurationOptionsSerializer
    pagination_class = None

    @validated_request(
        responses={200: OpenApiResponse(response=ProactiveConfigurationOptionsSerializer)},
        description=(
            "Return the current user's safe proactive subscription configuration options. "
            "Repository options are limited to repositories the user can currently authorize."
        ),
    )
    def list(self, request: ValidatedRequest, **kwargs) -> Response:
        options = pulse_api.get_proactive_configuration_options(
            team_id=self.team_id,
            user=cast(User, request.user),
        )
        return Response(ProactiveConfigurationOptionsSerializer(instance=options).data)


class PulseRunActionViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "subscription"
    serializer_class = OutcomeDecisionResponseSerializer

    @extend_schema(
        request=OutcomeDecisionSerializer,
        responses={
            200: OutcomeDecisionResponseSerializer,
            400: OpenApiResponse(description="The advice decision is invalid for this recommendation."),
            404: OpenApiResponse(description="Recommendation not found."),
        },
        description="Record an explicit adoption or dismissal for one advice-only proactive recommendation.",
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="decision",
        request=OutcomeDecisionSerializer,
        responses={
            200: OutcomeDecisionResponseSerializer,
            400: OpenApiResponse(description="The advice decision is invalid for this recommendation."),
            404: OpenApiResponse(description="Recommendation not found."),
        },
        description="Record an explicit adoption or dismissal for one advice-only proactive recommendation.",
    )
    @validated_request(
        request_serializer=OutcomeDecisionSerializer,
        responses={
            200: OpenApiResponse(response=OutcomeDecisionResponseSerializer),
            400: OpenApiResponse(description="The advice decision is invalid for this recommendation."),
            404: OpenApiResponse(description="Recommendation not found."),
        },
        description="Record an explicit adoption or dismissal for one advice-only proactive recommendation.",
    )
    def decision(self, request: ValidatedRequest, pk: str, **kwargs) -> Response:
        try:
            action_id = UUID(pk)
        except ValueError as error:
            raise ValidationError({"id": ["Must be a valid UUID."]}) from error
        try:
            result = pulse_api.decide_run_action_outcome(
                team_id=self.team_id,
                team=self.team,
                user=cast(User, request.user),
                action_id=action_id,
                decision=cast(Literal["adopted", "dismissed"], request.validated_data["decision"]),
            )
        except (pulse_api.PulseActionNotFound, pulse_api.PulseSubscriptionNotFound) as error:
            raise NotFound("Recommendation not found.") from error
        except pulse_api.PulseValidationError as error:
            raise ValidationError(error.errors) from error
        return Response(OutcomeDecisionResponseSerializer(instance=result).data, status=status.HTTP_200_OK)


class PulseExperimentDraftViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    authentication_classes = [OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "pulse_experiment_draft"
    serializer_class = PulseExperimentDraftResponseSerializer
    pagination_class = None

    @validated_request(
        request_serializer=PulseExperimentDraftSerializer,
        responses={
            200: OpenApiResponse(response=PulseExperimentDraftResponseSerializer),
            201: OpenApiResponse(response=PulseExperimentDraftResponseSerializer),
            400: OpenApiResponse(description="The bounded experiment draft input is invalid."),
            404: OpenApiResponse(description="The staged experiment reservation was not found."),
            409: OpenApiResponse(description="The request conflicts with its immutable reservation."),
        },
        description="Create the one inert experiment draft reserved for this staged Pulse task.",
    )
    def create(self, request: ValidatedRequest, **kwargs) -> Response:
        authenticator = request.successful_authenticator
        if not isinstance(authenticator, OAuthAccessTokenAuthentication):
            raise PermissionDenied("This operation requires a task-bound sandbox token.")
        access_token = authenticator.access_token
        application = access_token.application
        task_id = access_token.sandbox_task_id
        if (
            application is None
            or application.client_id not in SANDBOX_OAUTH_APP_CLIENT_IDS
            or task_id is None
            or not pulse_api.has_exact_pulse_experiment_draft_scopes(access_token.scope)
        ):
            raise PermissionDenied("This operation requires a task-bound sandbox token.")
        try:
            result = pulse_api.create_pulse_experiment_draft(
                team_id=self.team_id,
                task_id=task_id,
                actor_id=cast(User, request.user).id,
                input_dto=PulseExperimentDraftSerializer.to_dto(request.validated_data),
            )
        except pulse_api.PulseExperimentDraftNotFound as error:
            raise NotFound("Experiment draft reservation not found.") from error
        except pulse_api.PulseExperimentDraftConflict as error:
            raise PulseExperimentDraftConflictResponse(str(error)) from error
        response_status = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
        return Response(PulseExperimentDraftResponseSerializer(instance=result).data, status=response_status)


class PulsePublicResearchViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    authentication_classes = [OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "internal_run"
    scope_object_read_actions = ["create"]
    scope_object_write_actions: list[str] = []
    serializer_class = PulsePublicResearchResponseSerializer
    pagination_class = None

    @validated_request(
        request_serializer=PulsePublicResearchRequestSerializer,
        responses={
            200: OpenApiResponse(response=PulsePublicResearchResponseSerializer),
            400: OpenApiResponse(description="The public research topic is invalid."),
            409: OpenApiResponse(description="The research budget is exhausted or an identical request is running."),
            404: OpenApiResponse(description="Public research is unavailable for this active Pulse task."),
            503: OpenApiResponse(description="The public research provider is temporarily unavailable."),
        },
        description=(
            "Search and read one bounded public webpage for an active task-bound Pulse analysis. "
            "Returned content is untrusted reference material."
        ),
    )
    def create(self, request: ValidatedRequest, **kwargs) -> Response:
        authenticator = request.successful_authenticator
        if not isinstance(authenticator, OAuthAccessTokenAuthentication):
            raise PermissionDenied("This operation requires a task-bound sandbox token.")
        access_token = authenticator.access_token
        application = access_token.application
        task_id = access_token.sandbox_task_id
        if (
            application is None
            or application.client_id not in SANDBOX_OAUTH_APP_CLIENT_IDS
            or task_id is None
            or not pulse_api.has_exact_pulse_analysis_scopes(access_token.scope)
        ):
            raise PermissionDenied("This operation requires a task-bound sandbox token.")
        try:
            result = pulse_api.research_public_context_for_task(
                team_id=self.team_id,
                team=self.team,
                user=cast(User, request.user),
                task_id=task_id,
                topic=request.validated_data["topic"],
            )
        except pulse_api.PulsePublicResearchNotFound as error:
            raise NotFound("Public research is unavailable for this task.") from error
        except pulse_api.PulsePublicResearchInvalid as error:
            raise ValidationError({"topic": ["Choose one of the available public research topics."]}) from error
        except pulse_api.PulseEvidenceConflict as error:
            raise PulsePublicResearchConflictResponse() from error
        except pulse_api.PulsePublicResearchUnavailable as error:
            raise PulsePublicResearchUnavailableResponse() from error
        return Response(PulsePublicResearchResponseSerializer(instance=result).data, status=status.HTTP_200_OK)


class PulseOutcomeReplayViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    authentication_classes = [OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "internal_run"
    serializer_class = PulseOutcomeReplayResponseSerializer
    pagination_class = None

    @extend_schema(
        responses={
            200: PulseOutcomeReplayResponseSerializer,
            404: OpenApiResponse(description="The claimed outcome replay instruction was not found."),
        },
        description=(
            "Return the one server-derived comparison call for a claimed Pulse outcome. "
            "The instruction is available only to its active task-bound analysis sandbox."
        ),
    )
    def retrieve(self, request: Request, pk: str, **kwargs) -> Response:
        try:
            plan_id = UUID(pk)
        except ValueError as error:
            raise ValidationError({"id": ["Must be a valid UUID."]}) from error
        authenticator = request.successful_authenticator
        if not isinstance(authenticator, OAuthAccessTokenAuthentication):
            raise PermissionDenied("This operation requires a task-bound sandbox token.")
        access_token = authenticator.access_token
        application = access_token.application
        task_id = access_token.sandbox_task_id
        if (
            application is None
            or application.client_id not in SANDBOX_OAUTH_APP_CLIENT_IDS
            or task_id is None
            or not pulse_api.has_exact_pulse_analysis_scopes(access_token.scope)
        ):
            raise PermissionDenied("This operation requires a task-bound sandbox token.")
        try:
            result = pulse_api.get_pulse_outcome_replay_instruction(
                team_id=self.team_id,
                task_id=task_id,
                actor_id=cast(User, request.user).id,
                plan_id=plan_id,
            )
        except pulse_api.PulseOutcomeReplayNotFound as error:
            raise NotFound("Outcome replay instruction not found.") from error
        return Response(PulseOutcomeReplayResponseSerializer(instance=result).data)

import uuid
from typing import Any, cast

from drf_spectacular.utils import OpenApiResponse, extend_schema
from redis.exceptions import LockError
from rest_framework import serializers, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import InternalAPIUser
from posthog.redis import get_client

from products.cohorts.backend.facade.api import add_person_to_static_cohort, get_cohort_ref
from products.workflows.backend.facade.api import WorkflowNotFound, get_workflow_static_cohort_ids
from products.workflows.backend.facade.service_jwt import WORKFLOW_ADD_TO_STATIC_COHORT_PURPOSE
from products.workflows.backend.presentation.views.workflow_step_auth import WorkflowStepJWTAuthentication


class WorkflowStaticCohortMemberJWTAuthentication(WorkflowStepJWTAuthentication):
    purpose = WORKFLOW_ADD_TO_STATIC_COHORT_PURPOSE


class WorkflowStaticCohortMemberRequestSerializer(serializers.Serializer):
    cohort_id = serializers.IntegerField(min_value=1, help_text="ID of the static cohort to add the person to.")
    person_uuid = serializers.UUIDField(help_text="UUID of the person the workflow run is for.")


class WorkflowStaticCohortMemberResponseSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="A short result message for the workflow log.")


class WorkflowStaticCohortMemberViewSet(viewsets.GenericViewSet):
    """Add the workflow run's person to a static cohort, for the workflow's "Add to static cohort" step.

    Authenticated by a scoped service JWT the plugin server mints, never by a user credential. The write runs
    as a service, so the endpoint only accepts a cohort that the saved workflow names. The workflow serializer
    checks that the person who saves the step can edit that cohort. A test run or a draft sends its own copy of
    the step, which can name any cohort, so the cohort id in the request is not enough on its own."""

    authentication_classes = [WorkflowStaticCohortMemberJWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = WorkflowStaticCohortMemberRequestSerializer

    @extend_schema(
        request=WorkflowStaticCohortMemberRequestSerializer,
        responses={
            200: WorkflowStaticCohortMemberResponseSerializer,
            403: OpenApiResponse(
                response=WorkflowStaticCohortMemberResponseSerializer,
                description="The saved workflow doesn't add people to this cohort",
            ),
            404: OpenApiResponse(
                response=WorkflowStaticCohortMemberResponseSerializer,
                description="The person doesn't exist in this project",
            ),
            409: OpenApiResponse(
                response=WorkflowStaticCohortMemberResponseSerializer,
                description="The cohort was deleted or isn't static",
            ),
            422: OpenApiResponse(
                response=WorkflowStaticCohortMemberResponseSerializer, description="The workflow no longer exists"
            ),
            503: OpenApiResponse(
                response=WorkflowStaticCohortMemberResponseSerializer,
                description="Another run is adding the same person. The caller retries.",
            ),
        },
        summary="Add a workflow person to a static cohort",
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        # Both come from the verified token, not the URL or body.
        user = cast(InternalAPIUser, request.user)
        team_id = cast(int, user.current_team_id)
        hog_flow_id = cast(uuid.UUID, request.auth)

        serializer = WorkflowStaticCohortMemberRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cohort_id: int = serializer.validated_data["cohort_id"]
        person_uuid = str(serializer.validated_data["person_uuid"])

        try:
            allowed_cohort_ids = get_workflow_static_cohort_ids(team_id=team_id, workflow_id=hog_flow_id)
        except WorkflowNotFound:
            return _respond("Workflow no longer exists.", status.HTTP_422_UNPROCESSABLE_ENTITY)
        if cohort_id not in allowed_cohort_ids:
            return _respond(
                "The saved workflow doesn't add people to this cohort. Save or publish the workflow, then try again.",
                status.HTTP_403_FORBIDDEN,
            )

        cohort = get_cohort_ref(team_id=team_id, cohort_id=cohort_id)
        if cohort is None or cohort.deleted or not cohort.is_static:
            return _respond("The cohort was deleted or isn't static.", status.HTTP_409_CONFLICT)

        # The insert checks for an existing member and then writes, so two runs for the same person must not
        # overlap. Otherwise both see no member and the person is stored twice.
        lock = get_client().lock(
            f"workflow-static-cohort-member:{team_id}:{cohort_id}:{person_uuid}", timeout=30, blocking_timeout=5
        )
        try:
            with lock:
                added = add_person_to_static_cohort(team_id=team_id, cohort_id=cohort_id, person_uuid=person_uuid)
        except LockError:
            return _respond("Another run is adding this person. Trying again.", status.HTTP_503_SERVICE_UNAVAILABLE)
        if not added:
            return _respond("This person doesn't have a profile yet, so they weren't added.", status.HTTP_404_NOT_FOUND)
        return _respond("The person is in the static cohort.")


def _respond(detail: str, http_status: int = status.HTTP_200_OK) -> Response:
    return Response(WorkflowStaticCohortMemberResponseSerializer({"detail": detail}).data, status=http_status)

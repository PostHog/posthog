import uuid
from typing import Any, cast

from django.db.models import F, Value
from django.db.models.functions import Coalesce

from drf_spectacular.utils import OpenApiResponse, extend_schema
from redis.exceptions import LockError
from rest_framework import serializers, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import InternalAPIUser
from posthog.models.person.util import get_person_ids_and_uuids_by_uuids
from posthog.redis import get_client

from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.util import is_person_in_cohort
from products.workflows.backend.facade.api import workflow_exists
from products.workflows.backend.facade.service_jwt import WORKFLOW_ADD_STATIC_COHORT_MEMBER_PURPOSE
from products.workflows.backend.presentation.views.workflow_step_auth import WorkflowStepJWTAuthentication

MEMBERSHIP_LOCK_SECONDS = 30
MEMBERSHIP_LOCK_WAIT_SECONDS = 5


class WorkflowCohortMembershipJWTAuthentication(WorkflowStepJWTAuthentication):
    purpose = WORKFLOW_ADD_STATIC_COHORT_MEMBER_PURPOSE


class WorkflowCohortMembershipRequestSerializer(serializers.Serializer):
    cohort_id = serializers.IntegerField(min_value=1, help_text="ID of the static cohort to update.")
    person_uuid = serializers.UUIDField(help_text="UUID of the workflow person to add.")


class WorkflowCohortMembershipResponseSerializer(serializers.Serializer):
    result = serializers.ChoiceField(
        choices=[
            "added",
            "already_present",
            "missing_person",
            "cohort_not_found",
            "cohort_deleted",
            "cohort_not_static",
            "workflow_not_found",
            "busy",
        ],
        help_text="Machine-readable result of the cohort membership update.",
    )
    detail = serializers.CharField(help_text="A short result message for the workflow log.")


class WorkflowCohortMembershipViewSet(viewsets.GenericViewSet):
    authentication_classes = [WorkflowCohortMembershipJWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = WorkflowCohortMembershipRequestSerializer

    @extend_schema(
        request=WorkflowCohortMembershipRequestSerializer,
        responses={
            200: WorkflowCohortMembershipResponseSerializer,
            404: OpenApiResponse(response=WorkflowCohortMembershipResponseSerializer),
            409: OpenApiResponse(response=WorkflowCohortMembershipResponseSerializer),
            422: OpenApiResponse(response=WorkflowCohortMembershipResponseSerializer),
            503: OpenApiResponse(response=WorkflowCohortMembershipResponseSerializer),
        },
        summary="Add a workflow person to a static cohort",
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        user = cast(InternalAPIUser, request.user)
        team_id = cast(int, user.current_team_id)
        hog_flow_id = cast(uuid.UUID, request.auth)

        if not workflow_exists(team_id=team_id, workflow_id=hog_flow_id):
            return _result("workflow_not_found", "Workflow no longer exists.", status.HTTP_422_UNPROCESSABLE_ENTITY)

        serializer = WorkflowCohortMembershipRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cohort_id = serializer.validated_data["cohort_id"]
        person_uuid = str(serializer.validated_data["person_uuid"])

        cohort = Cohort.objects.filter(team_id=team_id, id=cohort_id).first()
        if cohort is None:
            return _result("cohort_not_found", "Static cohort was not found.", status.HTTP_404_NOT_FOUND)
        if cohort.deleted:
            return _result("cohort_deleted", "Static cohort was deleted.", status.HTTP_409_CONFLICT)
        if not cohort.is_static:
            return _result("cohort_not_static", "Selected cohort is not static.", status.HTTP_409_CONFLICT)

        people = get_person_ids_and_uuids_by_uuids(team_id, [person_uuid])
        if not people:
            return _result("missing_person", "Workflow person was not found.", status.HTTP_404_NOT_FOUND)

        person_id, resolved_uuid = people[0]
        lock = get_client().lock(
            f"workflow-static-cohort-member:{team_id}:{cohort_id}:{person_id}",
            timeout=MEMBERSHIP_LOCK_SECONDS,
            blocking_timeout=MEMBERSHIP_LOCK_WAIT_SECONDS,
        )
        try:
            with lock:
                if is_person_in_cohort(team_id, person_id, cohort_id):
                    return _result("already_present", "Person is already in the static cohort.")

                cohort.insert_users_list_by_id_uuid_pairs_skip_validation(
                    [(person_id, resolved_uuid)], team_id=team_id, raise_on_error=True, save_state=False
                )
                Cohort.objects.filter(team_id=team_id, id=cohort_id).update(count=Coalesce(F("count"), Value(0)) + 1)
        except LockError:
            return _result(
                "busy",
                "Static cohort is busy. The workflow will try again.",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return _result("added", "Person was added to the static cohort.")


def _result(result: str, detail: str, http_status: int = status.HTTP_200_OK) -> Response:
    return Response(
        WorkflowCohortMembershipResponseSerializer({"result": result, "detail": detail}).data, status=http_status
    )

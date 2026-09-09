from typing import Any, cast
from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import AuthenticationFailed, NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import InternalAPIUser, ScopedServiceJWTAuthentication
from posthog.jwt import PosthogJwtAudience
from posthog.models import Team
from posthog.models.team.team import DEPRECATED_ATTRS
from posthog.permissions import posthog_feature_flag_enabled
from posthog.scoped_service_jwt import ScopedServiceJwtPurpose

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.customer_analytics.backend.facade import contracts
from products.customer_analytics.backend.facade.constants import CUSTOMER_ANALYTICS_CUSTOMER_TASKS_FLAG
from products.customer_analytics.backend.facade.workflow_customer_tasks import create_workflow_customer_task
from products.workflows.backend.models import HogFlow


class WorkflowCustomerTasksJWTAuthentication(ScopedServiceJWTAuthentication):
    purpose = ScopedServiceJwtPurpose(
        audience=PosthogJwtAudience.CUSTOMER_TASKS_CREATE,
        settings_name="CUSTOMER_TASKS_CREATE_JWT_SECRETS",
    )


class WorkflowCustomerTaskCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=400, help_text="Task name.")
    description = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, help_text="Task description."
    )
    account_id = serializers.UUIDField(required=False, allow_null=True, help_text="UUID of the linked account.")
    assigned_to_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        max_value=2147483647,
        help_text="PostHog user ID of the assigned project member.",
    )
    due_at = serializers.DateTimeField(required=False, allow_null=True, help_text="ISO 8601 task deadline.")
    idempotency_key = serializers.CharField(
        max_length=128, help_text="Invocation and action key from the workflow worker."
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        unexpected = set(self.initial_data) - set(self.fields)
        if unexpected:
            raise serializers.ValidationError(dict.fromkeys(unexpected, "This field is not accepted."))
        return attrs


class WorkflowCustomerTaskResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="UUID of the created or previously created customer task.")


class WorkflowCustomerTaskViewSet(viewsets.GenericViewSet):
    authentication_classes = [WorkflowCustomerTasksJWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = WorkflowCustomerTaskCreateSerializer

    @extend_schema(
        request=WorkflowCustomerTaskCreateSerializer, responses={201: WorkflowCustomerTaskResponseSerializer}
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        serializer = WorkflowCustomerTaskCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        idempotency_key = data.pop("idempotency_key")
        claims = cast(dict[str, Any], request.auth)
        if claims.get("idempotency_key") != idempotency_key:
            raise AuthenticationFailed("Service token does not grant access to this invocation.")
        try:
            workflow_id = UUID(str(claims.get("hog_flow_id")))
        except ValueError:
            raise AuthenticationFailed("Service token is missing its workflow claim.") from None
        team_id = cast(int, cast(InternalAPIUser, request.user).current_team_id)
        task_id = _create_task(team_id, workflow_id, idempotency_key, contracts.CreateCustomerTaskInput(**data))
        return Response(WorkflowCustomerTaskResponseSerializer({"id": task_id}).data, status=status.HTTP_201_CREATED)


def _create_task(
    team_id: int, workflow_id: UUID, idempotency_key: str, input: contracts.CreateCustomerTaskInput
) -> UUID:
    workflow = HogFlow.objects.filter(team_id=team_id, id=workflow_id).select_related("created_by").first()
    if workflow is None:
        raise NotFound("Workflow not found.")
    owner = workflow.created_by
    if owner is None or not owner.is_active:
        raise PermissionDenied("Choose an active workflow owner before creating customer tasks.")
    # `select_related` builds its columns from the related model rather than through `TeamManager`,
    # so re-apply its defer to the joined parent. Without it every task creation in a child
    # environment re-reads the deprecated taxonomy columns, which TOAST out to megabytes per team.
    team = (
        Team.objects.select_related("parent_team")
        .defer(*(f"parent_team__{attr}" for attr in DEPRECATED_ATTRS))
        .get(id=team_id)
    )
    access = UserAccessControl(user=owner, team=team, organization_id=team.organization_id)
    if not access.has_project_access:
        raise PermissionDenied("The workflow owner no longer has access to this project.")
    if not posthog_feature_flag_enabled(
        CUSTOMER_ANALYTICS_CUSTOMER_TASKS_FLAG,
        str(owner.distinct_id),
        organization_id=team.organization_id,
        team_id=team.id,
    ):
        raise PermissionDenied("Enable customer tasks before using this workflow action.")
    canonical_team = team.parent_team or team
    canonical_access = UserAccessControl(user=owner, team=canonical_team, organization_id=team.organization_id)
    try:
        return create_workflow_customer_task(
            team=canonical_team,
            workflow_id=workflow_id,
            idempotency_key=idempotency_key,
            input=input,
            actor=owner,
            user_access_control=canonical_access,
        )
    except contracts.CustomerTaskAccessDenied:
        raise PermissionDenied(
            "The workflow owner needs editor access to customer tasks in the canonical project."
        ) from None
    except contracts.CustomerTaskAccountNotFound:
        raise NotFound("Account not found.") from None
    except (contracts.CustomerTaskAssigneeInvalid, contracts.CustomerTaskAssigneeCannotViewAccount):
        raise ValidationError(
            {"assigned_to_id": "Choose a project member who can access the linked account."}
        ) from None

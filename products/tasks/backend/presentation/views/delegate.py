from rest_framework import status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.access import code_access_required_response, usage_limit_response
from products.tasks.backend.facade.client_provenance import get_task_client_provenance, is_sandbox_origin_request
from products.tasks.backend.presentation.serializers import (
    TaskCreateResponseSerializer,
    TaskDelegateRequestSerializer,
    TaskRunErrorResponseSerializer,
)
from products.tasks.backend.presentation.views.api import internal_flag_enabled

TASKS_DELEGATE_FLAG = "tasks-delegate"


def _forbidden(message: str) -> Response:
    return Response(TaskRunErrorResponseSerializer({"error": message}).data, status=status.HTTP_403_FORBIDDEN)


class TaskDelegateViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """POST /tasks/delegate/ → create a task from a request and a run the server briefs."""

    scope_object = "task"
    serializer_class = TaskDelegateRequestSerializer

    @validated_request(
        request_serializer=TaskDelegateRequestSerializer,
        responses={
            201: TaskCreateResponseSerializer,
            403: TaskRunErrorResponseSerializer,
            429: TaskRunErrorResponseSerializer,
            503: TaskRunErrorResponseSerializer,
        },
        summary="Delegate a task",
        description=(
            "Create a task from a plain-language request and its first cloud run. The run starts in status "
            "`not_started` and stage `briefing` while the server writes the agent's instructions and picks the model, "
            "skills and PostHog tools, then it is queued and runs like any other cloud run. The response carries the "
            "task and its `latest_run`; `run_error` is set when the run could not be created."
        ),
    )
    def create(self, request: Request, *args, **kwargs) -> Response:
        user_id = getattr(request.user, "id", None)
        if (
            user_id is None
            or not internal_flag_enabled(request, self.team, TASKS_DELEGATE_FLAG)
            or is_sandbox_origin_request(request)
        ):
            return _forbidden("Delegated task runs are not available for this project")
        if access_response := code_access_required_response(request, self.organization):
            return access_response
        if limit_response := usage_limit_response(request.user, self.team_id):
            return limit_response

        result = tasks_facade.delegate_task(
            self.team_id,
            user_id,
            description=request.validated_data["description"],
            read_only=request.validated_data["read_only_tools"],
            client_provenance=get_task_client_provenance(request),
        )
        assert result.task is not None
        response_data = TaskCreateResponseSerializer(result.task).data
        if result.run_error:
            response_data["run_error"] = result.run_error
        return Response(response_data, status=status.HTTP_201_CREATED)

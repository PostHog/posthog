import json
from typing import Any, cast

from django.db import models

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import exceptions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.models import User

from products.cdp.backend.facade.api import is_hog_function_template_available
from products.mcp_store.backend.facade import api as mcp_store_facade
from products.mcp_store.backend.facade.contracts import ConnectorCallOutcome

T3_CODE_TEMPLATE_ID = "template-t3-code"
# The tools a T3 Code environment's MCP server exposes for listing projects and creating webhook tasks.
T3_CODE_TOOLS = ("t3_project_list", "schedule_task")
APPROVAL_CONTEXT = "workflow-t3-code-step"
PROJECT_LIST_LIMIT = 100

# T3 Code renders {{...}} placeholders from the request the step sends, and marks what it inserts as request data.
WEBHOOK_TASK_PROMPT = """A PostHog workflow started this run. Do what its step asks:

{{body.instructions}}

The workflow sent this data with it:

{{body}}"""

WEBHOOK_SCHEDULE = {
    "type": "webhook",
    # The step sends a new delivery id per run and repeats it on retries, so a retry starts no second run.
    "dedupe": {"replayKey": "{{headers.x-posthog-delivery-id}}"},
}


class T3CodeCallStatus(models.TextChoices):
    OK = "ok", "OK"
    NEEDS_APPROVAL = "needs_approval", "Needs approval"


class T3CodeMachineSerializer(serializers.Serializer):
    host = serializers.CharField(help_text="The host of the T3 Code environment's MCP URL. Pass it as `machine`.")
    name = serializers.CharField(help_text="The name the member gave the connection in MCP servers settings.")


class T3CodeMachinesSerializer(serializers.Serializer):
    machines = T3CodeMachineSerializer(
        many=True,
        help_text="The member's own T3 Code connections from MCP servers settings, and the team's shared ones.",
    )


class T3CodeCallSerializer(serializers.Serializer):
    machine = serializers.CharField(max_length=253, help_text="The host of one of the member's T3 Code machines.")
    approval_token = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="The token from a `needs_approval` answer. Send it once the member allowed the call.",
    )


class T3CodeWebhookTaskRequestSerializer(T3CodeCallSerializer):
    project_id = serializers.CharField(max_length=200, help_text="The T3 Code project the task starts threads in.")
    title = serializers.CharField(max_length=512, help_text="The task's name in T3 Code.")


class T3CodeApprovalSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=T3CodeCallStatus.choices,
        help_text="`needs_approval` when the member must allow this call first. Repeat it with `approval_token`.",
    )
    approval_token = serializers.CharField(
        allow_null=True, help_text="Set with `needs_approval`. Send it back to make the call once."
    )


class T3CodeProjectSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="The T3 Code project id.")
    title = serializers.CharField(help_text="The project's name in T3 Code.")
    has_default_model = serializers.BooleanField(
        help_text="Whether the project has a default model. T3 Code creates tasks only in projects that have one."
    )


class T3CodeProjectsSerializer(T3CodeApprovalSerializer):
    projects = T3CodeProjectSerializer(many=True, required=False, help_text="Set with `ok`: the machine's projects.")


class T3CodeWebhookTaskSerializer(T3CodeApprovalSerializer):
    webhook_url = serializers.CharField(
        required=False, help_text="Set with `ok`: the task's webhook URL. Use it as the step's webhook URL."
    )


class T3CodeErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="What went wrong and what to do about it.")


class WorkflowT3CodeViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Set up a workflow's T3 Code step with the member's own T3 Code connection from MCP servers settings."""

    scope_object = "hog_flow"
    scope_object_read_actions = ["machines", "projects"]
    scope_object_write_actions = ["webhook_tasks"]

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        if not is_hog_function_template_available(T3_CODE_TEMPLATE_ID, self.team):
            raise exceptions.NotFound()

    @extend_schema(responses={200: T3CodeMachinesSerializer})
    @action(detail=False, methods=["get"])
    def machines(self, request: Request, **kwargs: Any) -> Response:
        servers = mcp_store_facade.member_servers_with_tools(self.team.id, self._user.id, T3_CODE_TOOLS)
        return Response(T3CodeMachinesSerializer({"machines": servers}).data)

    @validated_request(
        T3CodeCallSerializer,
        responses={
            200: OpenApiResponse(response=T3CodeProjectsSerializer),
            400: OpenApiResponse(response=T3CodeErrorSerializer),
        },
        summary="List the projects on a T3 Code machine",
    )
    @action(detail=False, methods=["post"])
    def projects(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        outcome = self._call(request.validated_data, "t3_project_list", {"limit": PROJECT_LIST_LIMIT})
        if outcome.status != T3CodeCallStatus.OK:
            return Response(T3CodeProjectsSerializer(self._approval(outcome)).data)
        projects = [_project(project) for project in _structured(outcome).get("projects") or []]
        return Response(
            T3CodeProjectsSerializer({"status": T3CodeCallStatus.OK, "approval_token": None, "projects": projects}).data
        )

    @validated_request(
        T3CodeWebhookTaskRequestSerializer,
        responses={
            200: OpenApiResponse(response=T3CodeWebhookTaskSerializer),
            400: OpenApiResponse(response=T3CodeErrorSerializer),
        },
        summary="Create a T3 Code task that starts a new thread for each run of the step",
    )
    @action(detail=False, methods=["post"])
    def webhook_tasks(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        data = request.validated_data
        arguments = {
            "projectId": data["project_id"],
            "title": data["title"],
            "prompt": WEBHOOK_TASK_PROMPT,
            "schedule": WEBHOOK_SCHEDULE,
            "bindToCurrentThread": False,
        }
        outcome = self._call(data, "schedule_task", arguments)
        if outcome.status != T3CodeCallStatus.OK:
            return Response(T3CodeWebhookTaskSerializer(self._approval(outcome)).data)
        webhook_url = _structured(outcome).get("webhookUrl")
        if not webhook_url:
            raise exceptions.ValidationError(
                {
                    "detail": "T3 Code created the task, but PostHog can't reach it. Turn on T3 Connect remote "
                    "access for this machine in T3 Code, then copy the task's webhook URL here."
                }
            )
        report_user_action(self._user, "workflows t3 code task created", team=self.team, request=request)
        return Response(
            T3CodeWebhookTaskSerializer(
                {"status": T3CodeCallStatus.OK, "approval_token": None, "webhook_url": webhook_url}
            ).data
        )

    @property
    def _user(self) -> User:
        return cast(User, self.request.user)

    def _call(self, data: dict[str, Any], tool_name: str, arguments: dict[str, Any]) -> ConnectorCallOutcome:
        outcome = mcp_store_facade.call_member_server_tool(
            self.team.id,
            self._user.id,
            data["machine"],
            tool_name,
            arguments,
            actor_label="Workflows T3 Code step",
            approval_token=data.get("approval_token") or None,
            approval_context=APPROVAL_CONTEXT,
        )
        if outcome.status in (T3CodeCallStatus.OK, T3CodeCallStatus.NEEDS_APPROVAL) and not outcome.is_error:
            return outcome
        raise exceptions.ValidationError({"detail": _error_detail(outcome)})

    def _approval(self, outcome: ConnectorCallOutcome) -> dict[str, Any]:
        return {"status": T3CodeCallStatus.NEEDS_APPROVAL, "approval_token": outcome.approval_token}


def _structured(outcome: ConnectorCallOutcome) -> dict[str, Any]:
    return outcome.structured_content if isinstance(outcome.structured_content, dict) else {}


def _project(project: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": project.get("id"),
        "title": project.get("title"),
        "has_default_model": project.get("defaultModelSelection") is not None,
    }


def _error_detail(outcome: ConnectorCallOutcome) -> str:
    texts = [_failure_message(block["text"]) for block in outcome.content if isinstance(block.get("text"), str)]
    return " ".join(texts) or outcome.detail or "T3 Code could not run this request."


def _failure_message(text: str) -> str:
    # T3 Code reports a failed call as its serialized failure, whose message is the part a member can act on.
    try:
        failure = json.loads(text)
    except ValueError:
        return text
    message = failure.get("message") if isinstance(failure, dict) else None
    return message if isinstance(message, str) else text

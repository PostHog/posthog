from typing import Any, cast

from django.conf import settings
from django.db import models
from django.shortcuts import get_object_or_404

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle
from rest_framework.viewsets import GenericViewSet

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.exceptions import QuotaLimitExceeded
from posthog.models.user import User
from posthog.ph_client import feature_enabled_or_false
from posthog.rate_limit import AIBurstRateThrottle

from products.posthog_ai.backend.context_wrapper import MAX_TEXT_LENGTH
from products.posthog_ai.backend.models import AgentOperation
from products.posthog_ai.backend.services.agent_operations.service import (
    AgentOperationError,
    AgentOperationService,
    OperationView,
    StartRequest,
)

from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, is_team_limited

AGENT_MCP_FEATURE_FLAG = "posthog-agent-mcp"
REPOSITORY_PATTERN = r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"


class AgentOperationPlanStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    IN_PROGRESS = "in_progress", "In progress"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class AgentOperationResultStatus(models.TextChoices):
    COMPLETE = "complete", "Complete"
    NEEDS_INPUT = "needs_input", "Needs input"
    FAILED = "failed", "Failed"


class AgentOperationStartSerializer(serializers.Serializer):
    goal = serializers.CharField(
        max_length=MAX_TEXT_LENGTH,
        help_text="The product goal for PostHog AI, written as a complete request. For example: 'Why did signups drop last week?'",
    )
    client_request_id = serializers.CharField(
        max_length=128,
        help_text="A unique id that the client makes for this request. Send the same id again to recover a lost response. A new goal needs a new id.",
    )
    context = serializers.CharField(  # type: ignore[assignment]
        max_length=MAX_TEXT_LENGTH,
        required=False,
        allow_blank=True,
        help_text="Optional facts from the client, such as the feature under work or relevant file names. PostHog AI treats it as data, not as instructions.",
    )
    conversation_id = serializers.UUIDField(
        required=False,
        help_text="Continue the conversation of an earlier operation, so PostHog AI keeps its context.",
    )
    repository = serializers.RegexField(
        REPOSITORY_PATTERN,
        max_length=255,
        required=False,
        help_text="Optional GitHub repository in 'organization/repository' form, for PostHog AI to read. The repository is read-only.",
    )
    approvals = serializers.ChoiceField(
        choices=AgentOperation.Approvals.choices,
        required=False,
        default=AgentOperation.Approvals.NONE,
        help_text="'client' when the client can show approval prompts to its user, so PostHog AI asks before each sensitive tool call. 'none' (default) runs with no prompts; the key's scopes still limit the run.",
    )
    ref = serializers.CharField(
        max_length=255,
        required=False,
        help_text="Optional branch, tag, or commit in the repository. The default branch when not set. The server pins it to one commit.",
    )


class AgentOperationStatusQuerySerializer(serializers.Serializer):
    cursor = serializers.CharField(
        required=False,
        help_text="The cursor from the previous response. The response then has only the steps after it.",
    )


class AgentOperationReplySerializer(serializers.Serializer):
    message = serializers.CharField(
        max_length=MAX_TEXT_LENGTH,
        help_text="The answer to the operation's question, 'allow' or 'deny' for an approval, or a steering message while it runs.",
    )
    client_request_id = serializers.CharField(
        max_length=128,
        help_text="A unique id for this reply. Send the same id again to recover a lost response without a second delivery.",
    )


class AgentOperationProjectSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="Project id.")
    name = serializers.CharField(help_text="Project name.")


class AgentOperationPlanItemSerializer(serializers.Serializer):
    content = serializers.CharField(help_text="The plan item.")
    status = serializers.ChoiceField(choices=AgentOperationPlanStatus.choices, help_text="The state of the plan item.")


class AgentOperationLinkSerializer(serializers.Serializer):
    label = serializers.CharField(help_text="What the evidence is.")  # type: ignore[assignment]
    url = serializers.CharField(allow_null=True, help_text="A link to the evidence, when one exists.")


class AgentOperationArtifactSerializer(serializers.Serializer):
    type = serializers.CharField(help_text="The kind of PostHog object, such as insight, dashboard or feature_flag.")
    name = serializers.CharField(help_text="The object name.")
    url = serializers.CharField(allow_null=True, help_text="A link to the object, when one exists.")


class AgentOperationApprovalOptionSerializer(serializers.Serializer):
    option_id = serializers.CharField(help_text="Send this option's meaning as the reply: allow, allow all, or deny.")
    kind = serializers.CharField(help_text="Option kind, such as allow_once, allow_always or reject_once.")
    name = serializers.CharField(help_text="Option label.")


class AgentOperationApprovalSerializer(serializers.Serializer):
    request_id = serializers.CharField(help_text="The pending approval request.")
    title = serializers.CharField(
        help_text="A short label for the tool call that waits for approval, such as 'Execute SQL query'."
    )
    detail = serializers.CharField(
        allow_null=True,
        help_text="The PostHog command that waits for approval, such as 'call execute-sql {...}', cut to 600 characters. Null for other tools.",
    )
    options = AgentOperationApprovalOptionSerializer(many=True, help_text="The answers that the sandbox accepts.")


class AgentOperationResultSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=AgentOperationResultStatus.choices, help_text="What PostHog AI reported at the end of its turn."
    )
    answer = serializers.CharField(help_text="The answer or plan, in Markdown.")
    question = serializers.CharField(
        allow_null=True, help_text="The question for the requester, when status is needs_input."
    )
    assumptions = serializers.ListField(child=serializers.CharField(), help_text="Assumptions that PostHog AI made.")
    evidence = AgentOperationLinkSerializer(many=True, help_text="Queries, insights and replays used.")
    artifacts = AgentOperationArtifactSerializer(many=True, help_text="PostHog objects created or changed.")
    follow_ups = serializers.ListField(child=serializers.CharField(), help_text="Suggested next steps.")


class AgentOperationSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Operation id. Use it for status, reply and cancel.")
    state = serializers.ChoiceField(choices=AgentOperation.State.choices, help_text="Operation state.")
    state_reason = serializers.CharField(
        allow_null=True,
        help_text="Why the operation is in this state, for example question, approval_required, deadline, no_result or credential_revoked.",
    )
    goal = serializers.CharField(help_text="The goal that the client sent.")
    project = AgentOperationProjectSerializer(help_text="The project that the operation works in. It does not change.")
    conversation_id = serializers.UUIDField(
        help_text="The PostHog AI conversation. Send it with a new goal to continue."
    )
    task_id = serializers.UUIDField(allow_null=True, help_text="The backing task.")
    run_id = serializers.UUIDField(allow_null=True, help_text="The current run.")
    repository = serializers.CharField(allow_null=True, help_text="The repository that PostHog AI reads, if any.")
    resolved_commit = serializers.CharField(allow_null=True, help_text="The pinned commit of the repository.")
    posthog_url = serializers.CharField(help_text="Open the conversation in PostHog.")
    plan = AgentOperationPlanItemSerializer(many=True, help_text="PostHog AI's latest plan.")
    new_steps = serializers.ListField(
        child=serializers.CharField(), help_text="Steps since the cursor that the client sent."
    )
    steps_total = serializers.IntegerField(
        help_text="The number of steps that the operation recorded so far, across all its runs. new_steps shows at most 20 of them."
    )
    summary = serializers.CharField(allow_null=True, help_text="PostHog AI's running summary of the work.")
    approvals = serializers.ChoiceField(
        choices=AgentOperation.Approvals.choices, help_text="Whether the client answers approval prompts."
    )
    approval = AgentOperationApprovalSerializer(
        allow_null=True, help_text="The approval that the operation waits for. Reply 'allow', 'allow all' or 'deny'."
    )
    question = serializers.CharField(
        allow_null=True, help_text="The question or approval that the operation waits for."
    )
    result = AgentOperationResultSerializer(allow_null=True, help_text="The latest structured result.")
    cursor = serializers.CharField(help_text="Send this cursor with the next status request.")
    retry_after_seconds = serializers.IntegerField(help_text="Recommended delay before the next status request.")
    created_at = serializers.DateTimeField(help_text="When the operation started.")
    deadline_at = serializers.DateTimeField(help_text="When the operation stops if it has not finished.")
    finished_at = serializers.DateTimeField(allow_null=True, help_text="When the operation reached a terminal state.")


class AgentOperationErrorSerializer(serializers.Serializer):
    code = serializers.CharField(help_text="Machine-readable error code.")
    detail = serializers.CharField(help_text="What went wrong and what to do next.")


def _question(operation: AgentOperation) -> str | None:
    if operation.state != AgentOperation.State.NEEDS_INPUT:
        return None
    if operation.pending_permission_request:
        title = operation.pending_permission_request.get("title") or "a tool"
        return f"PostHog AI asks for approval: {title}. Reply 'allow', 'allow all' or 'deny'."
    return (operation.result or {}).get("question")


def _serialize(view: OperationView) -> dict[str, Any]:
    operation = view.operation
    return AgentOperationSerializer(
        {
            "id": operation.id,
            "state": operation.state,
            "state_reason": operation.state_reason,
            "goal": operation.goal,
            "project": {"id": operation.team.pk, "name": operation.team.name},
            "conversation_id": operation.conversation_id,
            "task_id": operation.task_id,
            "run_id": operation.run_id,
            "repository": operation.repository,
            "resolved_commit": operation.resolved_commit,
            "posthog_url": view.posthog_url,
            "plan": view.plan,
            "new_steps": view.new_steps,
            "steps_total": view.steps_total,
            "summary": view.summary,
            "approvals": operation.approvals,
            "approval": operation.pending_permission_request
            if operation.state == AgentOperation.State.NEEDS_INPUT
            else None,
            "question": _question(operation),
            "result": operation.result,
            "cursor": view.cursor,
            "retry_after_seconds": view.retry_after_seconds,
            "created_at": operation.created_at,
            "deadline_at": operation.deadline_at,
            "finished_at": operation.finished_at,
        }
    ).data


def _error(error: AgentOperationError) -> Response:
    return Response(
        AgentOperationErrorSerializer({"code": error.code, "detail": error.message}).data, status=error.status
    )


_ERRORS = {
    400: OpenApiResponse(response=AgentOperationErrorSerializer, description="The request is not valid."),
    409: OpenApiResponse(
        response=AgentOperationErrorSerializer, description="The request conflicts with the operation."
    ),
}

AI_DATA_PROCESSING_REQUIRED_MESSAGE = "Enable AI data processing for this organization to use the PostHog Agent MCP. An organization admin can turn it on in the organization settings."


class AgentOperationViewSet(TeamAndOrgViewSetMixin, GenericViewSet):
    """Goals that an external agent delegates to PostHog AI through the PostHog Agent MCP."""

    scope_object = "conversation"
    queryset = AgentOperation.objects.unscoped().none()

    def get_throttles(self) -> list[BaseThrottle]:
        # Only starting an operation starts new PostHog AI work, so only it has the AI burst limit, and no
        # daily limit. Local development skips it, like the conversation API. Replies answer a run that
        # exists, and clients read the status many times a minute, so the rest use the standard API limits.
        if self.action == "create":
            if settings.DEBUG and not settings.TEST:
                return []
            return [AIBurstRateThrottle()]
        return super().get_throttles()

    def _service(self) -> AgentOperationService:
        user = cast(User, self.request.user)
        if not self._agent_mcp_enabled(user):
            raise PermissionDenied(
                f"The PostHog Agent MCP is not available for this organization yet. It needs the '{AGENT_MCP_FEATURE_FLAG}' feature flag."
            )
        return AgentOperationService(self.team, user)

    def _require_ai_data_processing(self) -> None:
        # Only starting and steering a run send project data to the model. Status and cancel stay open.
        if self.team.organization.is_ai_data_processing_approved is not True:
            raise PermissionDenied(AI_DATA_PROCESSING_REQUIRED_MESSAGE)

    def _agent_mcp_enabled(self, user: User) -> bool:
        # Local dev reads flags from the local instance, which has no such flag until someone creates it.
        if settings.DEBUG and not settings.TEST:
            return True
        return feature_enabled_or_false(
            AGENT_MCP_FEATURE_FLAG,
            str(user.distinct_id),
            groups={"organization": str(self.team.organization_id)},
            group_properties={"organization": {"id": str(self.team.organization_id)}},
            send_feature_flag_events=False,
        )

    def _operation(self, pk: str) -> AgentOperation:
        return get_object_or_404(
            AgentOperation.objects.for_team(self.team_id).select_related("team"),
            id=pk,
            team_id=self.team_id,
            user_id=self.request.user.pk,
        )

    @validated_request(
        request_serializer=AgentOperationStartSerializer,
        responses={
            **_ERRORS,
            201: OpenApiResponse(response=AgentOperationSerializer, description="The operation started."),
            200: OpenApiResponse(response=AgentOperationSerializer, description="The same request was already sent."),
            409: OpenApiResponse(
                response=AgentOperationErrorSerializer,
                description="Too many runs are in progress, the conversation already has a run, or the request id is reused.",
            ),
            429: OpenApiResponse(
                response=AgentOperationErrorSerializer, description="Too many runs started in the last minute."
            ),
        },
        summary="Start an agent operation",
        description="Send a product goal to PostHog AI. Returns at once; read the status until the state is terminal.",
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        service = self._service()
        self._require_ai_data_processing()
        if is_team_limited(self.team.api_token, QuotaResource.AI_CREDITS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY):
            raise QuotaLimitExceeded(
                "Your organization reached its AI credit usage limit. Increase the limits in Billing settings, or ask an org admin to do so."
            )
        data = request.validated_data
        start = StartRequest(
            goal=data["goal"],
            client_request_id=data["client_request_id"],
            context=data.get("context") or None,
            conversation_id=str(data["conversation_id"]) if data.get("conversation_id") else None,
            repository=data.get("repository"),
            ref=data.get("ref"),
            approvals=data.get("approvals", AgentOperation.Approvals.NONE),
        )
        try:
            outcome = service.start(start, authenticator=getattr(request, "successful_authenticator", None))
            view = service.view(outcome.operation, None)
        except AgentOperationError as error:
            return _error(error)
        return Response(_serialize(view), status=status.HTTP_201_CREATED if outcome.created else status.HTTP_200_OK)

    @validated_request(
        query_serializer=AgentOperationStatusQuerySerializer,
        responses={200: OpenApiResponse(response=AgentOperationSerializer), **_ERRORS},
        summary="Get agent operation status",
        description="The operation state, the plan, the steps after the cursor, and the result when one exists.",
    )
    def retrieve(self, request: Request, pk: str, **kwargs: Any) -> Response:
        service = self._service()
        try:
            view = service.view(self._operation(pk), request.validated_query_data.get("cursor"))
        except AgentOperationError as error:
            return _error(error)
        return Response(_serialize(view))

    @validated_request(
        request_serializer=AgentOperationReplySerializer,
        responses={
            200: OpenApiResponse(response=AgentOperationSerializer),
            **_ERRORS,
            403: OpenApiResponse(
                response=AgentOperationErrorSerializer,
                description="The credential has fewer permissions than the one that started the operation.",
            ),
        },
        summary="Reply to an agent operation",
        description="Answer a question or an approval, or steer a running operation. 'allow', 'allow all' or 'deny' with no pending approval or question returns 409 with code no_pending_approval, because the approval was already answered.",
    )
    @action(detail=True, methods=["post"], url_path="reply", required_scopes=["conversation:write"])
    def reply(self, request: Request, pk: str, **kwargs: Any) -> Response:
        service = self._service()
        self._require_ai_data_processing()
        data = request.validated_data
        try:
            operation = service.reply(
                self._operation(pk),
                data["message"],
                data["client_request_id"],
                authenticator=getattr(request, "successful_authenticator", None),
            )
            view = service.view(operation, None)
        except AgentOperationError as error:
            return _error(error)
        return Response(_serialize(view))

    @validated_request(
        responses={200: OpenApiResponse(response=AgentOperationSerializer), **_ERRORS},
        summary="Cancel an agent operation",
        description="Request cancellation. The state is cancelling until the sandbox stops, then cancelled.",
    )
    @action(detail=True, methods=["post"], url_path="cancel", required_scopes=["conversation:write"])
    def cancel(self, request: Request, pk: str, **kwargs: Any) -> Response:
        service = self._service()
        try:
            operation = service.cancel(self._operation(pk))
            view = service.view(operation, None)
        except AgentOperationError as error:
            return _error(error)
        return Response(_serialize(view))

from typing import Any
from uuid import UUID

from drf_spectacular.openapi import AutoSchema
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.models.user import User
from posthog.permissions import APIScopePermission

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.access import compute_quota_limit_response
from products.tasks.backend.facade.compute_quota import ComputeBillingLimitExceeded
from products.tasks.backend.facade.onboarding import (
    onboarding_test_tools_enabled,
    start_onboarding_session,
    start_onboarding_test_session,
)
from products.tasks.backend.facade.onboarding_canvas import ensure_teaching_canvas
from products.tasks.backend.presentation.serializers import (
    ChannelContextGenerationSerializer,
    ChannelDeleteConflictSerializer,
    ChannelFeedMessageSerializer,
    ChannelFeedMessageWriteSerializer,
    ChannelInstructionsSerializer,
    ChannelInstructionsWriteSerializer,
    ChannelSerializer,
    ChannelStarWriteSerializer,
    ChannelUpdateSerializer,
    ChannelWriteSerializer,
    OnboardingSessionSerializer,
    OnboardingSessionTestResponseSerializer,
    OnboardingSessionTestSerializer,
    ProvisionedChannelsSerializer,
    TaskActivityMarkReadResponseSerializer,
    TaskActivityMarkReadSerializer,
    TaskActivityPageSerializer,
    TaskActivityQuerySerializer,
    TaskActivitySerializer,
    TaskMentionQuerySerializer,
    TaskMentionSerializer,
    TaskRunErrorResponseSerializer,
    TaskThreadMessageSerializer,
    TaskThreadMessageWriteSerializer,
    TeachingCanvasSerializer,
)

# Shared by the PUT and PATCH verbs on /instructions/ — same request/response contract,
# PATCH is an alias for clients that can't send PUT.
PUBLISH_INSTRUCTIONS_SCHEMA_KWARGS: dict[str, Any] = {
    "request": ChannelInstructionsWriteSerializer,
    "responses": {200: ChannelInstructionsSerializer},
    "summary": "Publish channel instructions",
    "description": (
        "Publish a new version of the channel's CONTEXT.md instructions. Pass base_version "
        "(the version you read) so a concurrent edit is rejected with 409 instead of overwritten."
    ),
}


class ChannelViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    API for task channels — the shared feeds tasks are kicked off in. The
    provision_defaults action get-or-creates the requester's personal "#me" channel and
    the team's shared "#general" channel; creation is resolve-or-create by normalized
    name so clients can map channel-like surfaces onto backend channels.
    """

    authentication_classes = [
        SessionAuthentication,
        PersonalAPIKeyAuthentication,
        OAuthAccessTokenAuthentication,
    ]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    serializer_class = ChannelSerializer
    # GET /instructions/ and /context_generation/ are reads; the PUT/PATCH/DELETE
    # method mappings resolve to their own action names, so they go in the write
    # bucket by name.
    scope_object_read_actions = ["list", "retrieve", "instructions", "instructions_versions", "context_generation"]
    scope_object_write_actions = [
        "create",
        "provision_defaults",
        "onboarding_session",
        "onboarding_session_test",
        "teaching_canvas_test",
        "partial_update",
        "destroy",
        "publish_instructions",
        "patch_instructions",
        "delete_instructions",
        "set_context_generation",
        "star",
    ]

    def _user_id(self) -> int | None:
        return getattr(self.request.user, "id", None)

    @staticmethod
    def _sandbox_task_id(request: Request) -> UUID | None:
        authenticator = request.successful_authenticator
        if not isinstance(authenticator, OAuthAccessTokenAuthentication):
            return None
        return authenticator.access_token.sandbox_task_id

    @extend_schema(
        responses={200: OpenApiResponse(response=ChannelSerializer(many=True), description="List of channels")},
        summary="List channels",
        description=(
            "All live public channels plus the requester's personal #me channel when it exists, "
            "sorted by name. Listing does not provision; call provision_defaults to create the "
            "default channels."
        ),
    )
    def list(self, request, *args, **kwargs):
        channels = tasks_facade.list_channels(self.team_id, self._user_id())
        return Response(ChannelSerializer(channels, many=True).data)

    @extend_schema(
        request=None,
        responses={
            200: OpenApiResponse(
                response=ProvisionedChannelsSerializer,
                description="The channel list plus which default channels this call created",
            )
        },
        summary="Provision default channels",
        description=(
            "Get-or-create the requester's personal #me channel and the team's shared #general "
            "channel, and report which of the two this call created. Idempotent."
        ),
    )
    @action(methods=["POST"], detail=False, url_path="provision_defaults")
    def provision_defaults(self, request: Request, **kwargs) -> Response:
        user_id = self._user_id()
        if user_id is None:
            raise PermissionDenied("Provisioning default channels requires a user.")
        provisioned = tasks_facade.provision_default_channels(self.team_id, user_id)
        return Response(ProvisionedChannelsSerializer(provisioned).data)

    @extend_schema(
        request=None,
        responses={
            200: OpenApiResponse(response=OnboardingSessionSerializer, description="The session that was started"),
            409: OpenApiResponse(description="This team has no #general space to open a session in"),
        },
        summary="Start a first-run onboarding session",
        description=(
            "Open the agent session a new user lands in, in the team's #general space. Reads the "
            "company's homepage, so it takes a few seconds and is deliberately not part of "
            "provisioning, which blocks the app opening. Callers fire it without awaiting it when "
            "provision_defaults reports personal_created."
        ),
    )
    @action(methods=["POST"], detail=False, url_path="onboarding_session")
    def onboarding_session(self, request: Request, **kwargs) -> Response:
        if not isinstance(request.user, User):
            raise PermissionDenied("Starting an onboarding session requires a user.")
        task_id = start_onboarding_session(self.team, request.user)
        if task_id is None:
            return Response({"detail": "No #general space to open a session in."}, status=409)
        return Response(OnboardingSessionSerializer({"task_id": task_id}).data)

    @extend_schema(
        request=OnboardingSessionTestSerializer,
        responses={200: OnboardingSessionTestResponseSerializer},
        summary="Start a test first-run onboarding session",
        description=(
            "Feature-flagged test path that creates a repeatable session from explicit prompt-building "
            "inputs, in the requester's personal space."
        ),
    )
    @action(methods=["POST"], detail=False, url_path="onboarding_session_test")
    def onboarding_session_test(self, request: Request, **kwargs) -> Response:
        if not isinstance(request.user, User) or not onboarding_test_tools_enabled(self.team, request.user):
            raise PermissionDenied("The onboarding test tools feature is not enabled.")
        serializer = OnboardingSessionTestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        task_id = start_onboarding_test_session(
            self.team,
            request.user,
            **values,
        )
        if task_id is None:
            return Response({"detail": "No personal space to open a session in."}, status=409)
        channel_id = tasks_facade.ensure_personal_channel_id(self.team_id, request.user.id)
        return Response(OnboardingSessionTestResponseSerializer({"task_id": task_id, "channel_id": channel_id}).data)

    @extend_schema(
        request=None,
        responses={200: TeachingCanvasSerializer},
        summary="Create the teaching canvas for testing",
        description="Feature-flagged test path that resolves or creates the teaching canvas in the requester's personal space.",
    )
    @action(methods=["POST"], detail=False, url_path="teaching_canvas_test")
    def teaching_canvas_test(self, request: Request, **kwargs) -> Response:
        if not isinstance(request.user, User) or not onboarding_test_tools_enabled(self.team, request.user):
            raise PermissionDenied("The onboarding test tools feature is not enabled.")
        channel_id = tasks_facade.ensure_personal_channel_id(self.team_id, request.user.id)
        teaching = ensure_teaching_canvas(self.team_id, channel_id, request.user, refresh=True)
        if teaching is None:
            return Response({"detail": "The teaching canvas was previously deleted."}, status=409)
        return Response(TeachingCanvasSerializer(teaching).data)

    @extend_schema(
        request=ChannelWriteSerializer,
        responses={200: ChannelSerializer},
        summary="Resolve or create a public channel",
        description=(
            "Returns the existing public channel with the (normalized) name, creating it if needed. "
            "A channel created here is starred for the requester unless star is false. "
            "The general name returns the team's general space; names that read as a private "
            'space ("me", "personal") are rejected.'
        ),
    )
    def create(self, request, **kwargs):
        serializer = ChannelWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        channel = tasks_facade.resolve_channel(
            self.team_id,
            self._user_id(),
            name=serializer.validated_data["name"],
            star=serializer.validated_data["star"],
        )
        if channel is None:
            return Response({"detail": "Invalid channel name"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ChannelSerializer(channel).data)

    @extend_schema(
        request=ChannelUpdateSerializer,
        responses={200: ChannelSerializer},
        summary="Rename a public channel",
    )
    def partial_update(self, request, pk=None, **kwargs):
        serializer = ChannelUpdateSerializer(data=request.data, context={"team_id": self.team_id}, partial=True)
        serializer.is_valid(raise_exception=True)
        result = tasks_facade.update_channel(pk, self.team_id, self._user_id(), **serializer.validated_data)
        if result == "not_found":
            raise NotFound()
        if result == "personal":
            raise PermissionDenied("Personal channels cannot be renamed")
        if result == "general":
            raise PermissionDenied("The general space can't be renamed")
        if result == "invalid_name":
            return Response({"detail": "Invalid channel name"}, status=status.HTTP_400_BAD_REQUEST)
        if result == "name_taken":
            return Response({"detail": "A channel with this name already exists"}, status=status.HTTP_400_BAD_REQUEST)
        channel = tasks_facade.get_channel(pk, self.team_id, self._user_id())
        if channel is None:
            raise NotFound()
        return Response(ChannelSerializer(channel).data)

    @extend_schema(
        responses={
            204: None,
            409: OpenApiResponse(
                response=ChannelDeleteConflictSerializer,
                description="The space still contains tasks or canvases.",
            ),
        },
        summary="Delete a public channel",
    )
    def destroy(self, request, pk=None, **kwargs):
        result = tasks_facade.delete_channel(pk, self.team_id, self._user_id())
        if result == "not_found":
            raise NotFound()
        if result == "personal":
            raise PermissionDenied("Your private space cannot be deleted")
        if result == "general":
            raise PermissionDenied("The general space can't be deleted")
        if result == "not_empty":
            return Response(
                {"detail": "Remove this space's tasks and canvases before deleting it."},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(responses={200: ChannelSerializer}, summary="Get a channel")
    def retrieve(self, request, pk=None, **kwargs):
        channel = tasks_facade.get_channel(pk, self.team_id, self._user_id())
        if channel is None:
            raise NotFound()
        return Response(ChannelSerializer(channel).data)

    @extend_schema(
        responses={200: ChannelInstructionsSerializer},
        summary="Get channel instructions",
        description=(
            "The channel's latest CONTEXT.md instructions. A channel with no published "
            "instructions reads as a blank version 0 — publish against base_version 0 to create version 1."
        ),
    )
    @action(methods=["GET"], detail=True)
    def instructions(self, request, pk=None, **kwargs):
        instructions = tasks_facade.get_channel_instructions(pk, self.team_id, self._user_id())
        if instructions is None:
            raise NotFound("Channel not found")
        return Response(ChannelInstructionsSerializer(instructions).data)

    @extend_schema(**PUBLISH_INSTRUCTIONS_SCHEMA_KWARGS)
    @instructions.mapping.put
    def publish_instructions(self, request, pk=None, **kwargs):
        sandbox_task_id = self._sandbox_task_id(request)
        if sandbox_task_id is not None and not tasks_facade.task_can_publish_channel_instructions(
            sandbox_task_id, self.team_id, pk
        ):
            raise PermissionDenied("This loop can update only the CONTEXT.md configured for this run.")

        serializer = ChannelInstructionsWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            published = tasks_facade.publish_channel_instructions(
                pk,
                self.team_id,
                self._user_id(),
                content=serializer.validated_data["content"],
                base_version=serializer.validated_data.get("base_version"),
            )
        except tasks_facade.ChannelInstructionsVersionConflictError as err:
            return Response(
                {
                    "detail": "The instructions changed since you read them. Reload the latest version and try again.",
                    "current_version": err.current_version,
                },
                status=status.HTTP_409_CONFLICT,
            )
        except tasks_facade.ChannelInstructionsVersionLimitError as err:
            return Response(
                {"detail": f"This channel has reached the maximum of {err.max_version} instruction versions."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except tasks_facade.ChannelInstructionsTooLargeError as err:
            return Response(
                {"detail": f"Instructions are limited to {err.max_bytes} bytes."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if published is None:
            raise NotFound("Channel not found")
        return Response(ChannelInstructionsSerializer(published).data)

    @extend_schema(**PUBLISH_INSTRUCTIONS_SCHEMA_KWARGS)
    @instructions.mapping.patch
    def patch_instructions(self, request, pk=None, **kwargs):
        return self.publish_instructions(request, pk, **kwargs)

    @extend_schema(request=None, responses={204: None}, summary="Delete channel instructions")
    @instructions.mapping.delete
    def delete_instructions(self, request, pk=None, **kwargs):
        deleted = tasks_facade.delete_channel_instructions(pk, self.team_id, self._user_id())
        if deleted is None:
            raise NotFound("Channel not found")
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        responses={200: OpenApiResponse(response=ChannelInstructionsSerializer(many=True))},
        summary="List channel instruction versions",
    )
    @action(methods=["GET"], detail=True, url_path="instructions/versions")
    def instructions_versions(self, request, pk=None, **kwargs):
        versions = tasks_facade.list_channel_instruction_versions(pk, self.team_id, self._user_id())
        if versions is None:
            raise NotFound("Channel not found")
        page = self.paginate_queryset(versions)
        if page is not None:
            return self.get_paginated_response(ChannelInstructionsSerializer(page, many=True).data)
        return Response(ChannelInstructionsSerializer(versions, many=True).data)

    @extend_schema(
        responses={200: ChannelContextGenerationSerializer},
        summary="Get the channel's CONTEXT.md generation task",
    )
    @action(methods=["GET"], detail=True, url_path="context_generation")
    def context_generation(self, request, pk=None, **kwargs):
        result = tasks_facade.get_channel_context_generation(pk, self.team_id, self._user_id())
        if result == "not_found":
            raise NotFound("Channel not found")
        return Response(ChannelContextGenerationSerializer({"task_id": result}).data)

    @extend_schema(
        request=ChannelContextGenerationSerializer,
        responses={200: ChannelContextGenerationSerializer},
        summary="Set or clear the channel's CONTEXT.md generation task",
    )
    @context_generation.mapping.put
    def set_context_generation(self, request, pk=None, **kwargs):
        serializer = ChannelContextGenerationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = tasks_facade.set_channel_context_generation(
            pk, self.team_id, self._user_id(), task_id=serializer.validated_data["task_id"]
        )
        if result == "not_found":
            raise NotFound("Channel not found")
        if result == "invalid_task":
            return Response({"detail": "Task not found in this team."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ChannelContextGenerationSerializer({"task_id": result}).data)

    @extend_schema(
        request=ChannelStarWriteSerializer,
        responses={204: None},
        summary="Star or unstar a channel for the requesting user",
    )
    @action(methods=["POST"], detail=True)
    def star(self, request, pk=None, **kwargs):
        serializer = ChannelStarWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user_id = self._user_id()
        if user_id is None:
            raise PermissionDenied("Stars are per-user")
        if not tasks_facade.star_channel(pk, self.team_id, user_id, starred=serializer.validated_data["starred"]):
            raise NotFound("Channel not found")
        return Response(status=status.HTTP_204_NO_CONTENT)


class ChannelFeedMessageViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    API for a channel's system-announcement feed — durable "PostHog agent" rows
    (context created, CONTEXT.md being built) rendered alongside the channel's task
    cards. Read by any team member for a public channel; personal channels are owner-only.
    """

    authentication_classes = [
        SessionAuthentication,
        PersonalAPIKeyAuthentication,
        OAuthAccessTokenAuthentication,
    ]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    http_method_names = ["get", "post", "head", "options"]
    serializer_class = ChannelFeedMessageSerializer

    def _channel_id(self) -> str:
        channel_id = self.kwargs.get("parent_lookup_channel_id")
        if not channel_id:
            raise NotFound("Channel ID is required")
        try:
            UUID(channel_id)
        except (ValueError, TypeError):
            raise NotFound("Channel not found")
        return channel_id

    def _user_id(self) -> int | None:
        return getattr(self.request.user, "id", None)

    @extend_schema(
        responses={
            200: OpenApiResponse(
                response=ChannelFeedMessageSerializer(many=True), description="Feed messages, chronological"
            )
        },
        summary="List channel feed messages",
        description="A channel's system announcements in chronological order.",
    )
    def list(self, request, *args, **kwargs):
        messages = tasks_facade.list_channel_feed_messages(self._channel_id(), self.team_id, self._user_id())
        if messages is None:
            raise NotFound("Channel not found")
        return Response(ChannelFeedMessageSerializer(messages, many=True).data)

    @extend_schema(
        request=ChannelFeedMessageWriteSerializer,
        responses={201: ChannelFeedMessageSerializer},
        summary="Post a channel feed message",
    )
    def create(self, request, **kwargs):
        serializer = ChannelFeedMessageWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = tasks_facade.create_channel_feed_message(
            self._channel_id(),
            self.team_id,
            self._user_id(),
            event=serializer.validated_data["event"],
            payload=serializer.validated_data.get("payload") or {},
            created_at=serializer.validated_data.get("created_at"),
        )
        if message is None:
            raise NotFound("Channel not found")
        if message == "full":
            raise ValidationError("This channel's feed is full.")
        return Response(ChannelFeedMessageSerializer(message).data, status=status.HTTP_201_CREATED)


class TaskMentionViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    API for the requester's mentions feed — thread messages across the team's tasks
    that @-mention them, indexed at write time.
    """

    authentication_classes = [
        SessionAuthentication,
        PersonalAPIKeyAuthentication,
        OAuthAccessTokenAuthentication,
    ]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    http_method_names = ["get", "head", "options"]
    serializer_class = TaskMentionSerializer

    def _user_id(self) -> int | None:
        return getattr(self.request.user, "id", None)

    @validated_request(
        query_serializer=TaskMentionQuerySerializer,
        responses={
            200: OpenApiResponse(response=TaskMentionSerializer(many=True), description="Mentions, newest first"),
        },
        summary="List mentions of the requester",
        description="Thread messages that @-mention the requester, newest first, restricted to tasks they can see.",
    )
    def list(self, request, *args, **kwargs):
        since = request.validated_query_data.get("since")
        limit = request.validated_query_data["limit"]
        mentions = tasks_facade.list_mentions(self.team_id, self._user_id(), since=since, limit=limit)
        return Response(TaskMentionSerializer(mentions, many=True).data)


class _ActivityPageEnvelopeSchema(AutoSchema):
    """Stops drf-spectacular's list-view heuristic from wrapping the `list` response in an array.

    `list` returns a single page envelope (`results` + `unread_count`), not a bare collection.
    Forcing the heuristic off renames the operation to `*_retrieve`, so pin the operationId back
    to keep the generated client's `*List` name.
    """

    def _is_list_view(self, serializer: Any = None) -> bool:
        return False

    def get_operation_id(self) -> str:
        operation_id = super().get_operation_id()
        if getattr(self.view, "action", None) == "list" and operation_id.endswith("_retrieve"):
            return operation_id.removesuffix("_retrieve") + "_list"
        return operation_id


class TaskActivityViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    API for the requester's task lifecycle and comment activity feed.
    """

    authentication_classes = [
        SessionAuthentication,
        PersonalAPIKeyAuthentication,
        OAuthAccessTokenAuthentication,
    ]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    http_method_names = ["get", "post", "head", "options"]
    serializer_class = TaskActivitySerializer
    # `list` hands back one envelope carrying its own unread total, so neither DRF's
    # pagination wrapper nor spectacular's array wrapper describes what it sends.
    pagination_class = None
    schema = _ActivityPageEnvelopeSchema()

    def _user_id(self) -> int | None:
        return getattr(self.request.user, "id", None)

    @validated_request(
        query_serializer=TaskActivityQuerySerializer,
        responses={
            200: OpenApiResponse(response=TaskActivityPageSerializer, description="Tasks, most-recent activity first"),
        },
        summary="List the requester's task activity",
        description=(
            "Task lifecycle rows collapse per task. Comment notifications remain separate. "
            "Results are most-recent first and restricted to tasks the requester can see."
        ),
    )
    def list(self, request, *args, **kwargs):
        activity = tasks_facade.list_task_activity(
            self.team_id,
            self._user_id(),
            limit=request.validated_query_data["limit"],
            before=request.validated_query_data.get("before"),
            before_id=request.validated_query_data.get("before_id"),
        )
        return Response(TaskActivityPageSerializer(activity).data)

    # @extend_schema must sit OUTSIDE @action: DRF's @action resets func.kwargs, wiping any schema
    # annotation applied earlier — including @validated_request's — from the generated OpenAPI.
    @extend_schema(
        request=TaskActivityMarkReadSerializer,
        responses={
            200: OpenApiResponse(response=TaskActivityMarkReadResponseSerializer, description="Remaining unread total"),
        },
        summary="Mark task activity read",
        description=(
            "Clear collapsed task activity through task timestamps and individual comment activity "
            "through activity IDs."
        ),
    )
    @action(detail=False, methods=["post"], url_path="mark_read", required_scopes=["task:write"])
    @validated_request(request_serializer=TaskActivityMarkReadSerializer)
    def mark_read(self, request, *args, **kwargs):
        activities = [
            (activity["task_id"], activity["seen_before"], activity.get("activity_id"))
            for activity in request.validated_data["activities"]
        ]
        marked_read = tasks_facade.mark_task_activity_read(self.team_id, self._user_id(), activities)
        return Response(
            {
                "marked_read": marked_read,
                "unread_count": tasks_facade.count_unread_task_activity(self.team_id, self._user_id()),
            }
        )


class TaskThreadMessageViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    API for a task's thread — the human-only side conversation around a task. Messages
    reach the agent only via the explicit send_to_agent action, gated to the task author.
    """

    authentication_classes = [
        SessionAuthentication,
        PersonalAPIKeyAuthentication,
        OAuthAccessTokenAuthentication,
    ]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    http_method_names = ["get", "post", "delete", "head", "options"]
    serializer_class = TaskThreadMessageSerializer

    def _task_id(self) -> str:
        task_id = self.kwargs.get("parent_lookup_task_id")
        if not task_id:
            raise NotFound("Task ID is required")
        try:
            UUID(task_id)
        except (ValueError, TypeError):
            raise NotFound("Task not found")
        return task_id

    def _user_id(self) -> int | None:
        return getattr(self.request.user, "id", None)

    @extend_schema(
        responses={
            200: OpenApiResponse(response=TaskThreadMessageSerializer(many=True), description="Thread messages")
        },
        summary="List thread messages",
        description="The task's thread in chronological order.",
    )
    def list(self, request, *args, **kwargs):
        messages = tasks_facade.list_thread_messages(self._task_id(), self.team_id, self._user_id())
        if messages is None:
            raise NotFound("Task not found")
        return Response(TaskThreadMessageSerializer(messages, many=True).data)

    @extend_schema(
        request=TaskThreadMessageWriteSerializer,
        responses={201: TaskThreadMessageSerializer},
        summary="Post a thread message",
    )
    def create(self, request, **kwargs):
        serializer = TaskThreadMessageWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = tasks_facade.create_thread_message(
            self._task_id(), self.team_id, self._user_id(), content=serializer.validated_data["content"]
        )
        if message is None:
            raise NotFound("Task not found")
        return Response(TaskThreadMessageSerializer(message).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={204: None}, summary="Delete own thread message")
    def destroy(self, request, pk=None, **kwargs):
        result = tasks_facade.delete_thread_message(pk, self._task_id(), self.team_id, self._user_id())
        if result == "not_found":
            raise NotFound()
        if result == "forbidden":
            raise PermissionDenied("Only the author can delete a thread message")
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        responses={
            200: TaskThreadMessageSerializer,
            400: OpenApiResponse(description="No signalable run, or message already forwarded"),
            429: OpenApiResponse(
                response=TaskRunErrorResponseSerializer,
                description="Organization reached its PostHog Desktop usage limit",
            ),
        },
        summary="Send a thread message to the agent",
        description="Task author only: forwards the message into the task's latest live run.",
    )
    @action(detail=True, methods=["post"], url_path="send_to_agent", required_scopes=["task:write"])
    def send_to_agent(self, request, pk=None, **kwargs):
        try:
            kind, message = tasks_facade.forward_thread_message(pk, self._task_id(), self.team_id, self._user_id())
        except ComputeBillingLimitExceeded as error:
            return compute_quota_limit_response(error.reason)
        if kind == "not_found":
            raise NotFound()
        if kind == "forbidden":
            raise PermissionDenied("Only the task author can send thread messages to the agent")
        if kind == "already_forwarded":
            return Response({"detail": "Message was already sent to the agent"}, status=status.HTTP_400_BAD_REQUEST)
        if kind == "no_run":
            return Response(
                {"detail": "Task has no active run to receive the message"}, status=status.HTTP_400_BAD_REQUEST
            )
        if kind == "signal_failed":
            return Response({"detail": "Failed to queue message for the agent"}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(TaskThreadMessageSerializer(message).data)

from uuid import UUID

from django.utils.dateparse import parse_datetime

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.permissions import APIScopePermission

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.presentation.serializers import (
    ChannelSerializer,
    ChannelWriteSerializer,
    TaskMentionSerializer,
    TaskThreadMessageSerializer,
    TaskThreadMessageWriteSerializer,
)


class ChannelViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    API for task channels — the shared feeds tasks are kicked off in. Listing lazily
    provisions the requester's personal "#me" channel; creation is resolve-or-create
    by normalized name so clients can map channel-like surfaces onto backend channels.
    """

    authentication_classes = [
        SessionAuthentication,
        PersonalAPIKeyAuthentication,
        OAuthAccessTokenAuthentication,
    ]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    serializer_class = ChannelSerializer

    def _user_id(self) -> int | None:
        return getattr(self.request.user, "id", None)

    @extend_schema(
        responses={200: OpenApiResponse(response=ChannelSerializer(many=True), description="List of channels")},
        summary="List channels",
        description="All live public channels plus the requester's personal #me channel (created on first list).",
    )
    def list(self, request, *args, **kwargs):
        channels = tasks_facade.list_channels(self.team_id, self._user_id())
        return Response(ChannelSerializer(channels, many=True).data)

    @extend_schema(
        request=ChannelWriteSerializer,
        responses={200: ChannelSerializer},
        summary="Resolve or create a public channel",
        description="Returns the existing public channel with the (normalized) name, creating it if needed.",
    )
    def create(self, request, **kwargs):
        serializer = ChannelWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        channel = tasks_facade.resolve_channel(self.team_id, self._user_id(), name=serializer.validated_data["name"])
        if channel is None:
            return Response({"detail": "Invalid channel name"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ChannelSerializer(channel).data)

    @extend_schema(
        request=ChannelWriteSerializer,
        responses={200: ChannelSerializer},
        summary="Rename a public channel",
    )
    def partial_update(self, request, pk=None, **kwargs):
        serializer = ChannelWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = tasks_facade.rename_channel(pk, self.team_id, name=serializer.validated_data["name"])
        if result == "not_found":
            raise NotFound()
        if result == "personal":
            raise PermissionDenied("Personal channels cannot be renamed")
        if result == "invalid_name":
            return Response({"detail": "Invalid channel name"}, status=status.HTTP_400_BAD_REQUEST)
        if result == "name_taken":
            return Response({"detail": "A channel with this name already exists"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ChannelSerializer(result).data)

    @extend_schema(responses={204: None}, summary="Delete a public channel")
    def destroy(self, request, pk=None, **kwargs):
        result = tasks_facade.delete_channel(pk, self.team_id)
        if result == "not_found":
            raise NotFound()
        if result == "personal":
            raise PermissionDenied("Personal channels cannot be deleted")
        return Response(status=status.HTTP_204_NO_CONTENT)


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

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "since",
                OpenApiTypes.DATETIME,
                description="Only return mentions created after this ISO 8601 timestamp.",
            )
        ],
        responses={
            200: OpenApiResponse(response=TaskMentionSerializer(many=True), description="Mentions, newest first"),
            400: OpenApiResponse(description="Unparseable since timestamp"),
        },
        summary="List mentions of the requester",
        description="Thread messages that @-mention the requester, newest first, restricted to tasks they can see.",
    )
    def list(self, request, *args, **kwargs):
        since = None
        since_param = request.query_params.get("since")
        if since_param:
            since = parse_datetime(since_param)
            if since is None:
                return Response({"detail": "Invalid since timestamp"}, status=status.HTTP_400_BAD_REQUEST)
        mentions = tasks_facade.list_mentions(self.team_id, self._user_id(), since=since)
        return Response(TaskMentionSerializer(mentions, many=True).data)


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
        },
        summary="Send a thread message to the agent",
        description="Task author only: forwards the message into the task's latest live run.",
    )
    @action(detail=True, methods=["post"], url_path="send_to_agent", required_scopes=["task:write"])
    def send_to_agent(self, request, pk=None, **kwargs):
        kind, message = tasks_facade.forward_thread_message(pk, self._task_id(), self.team_id, self._user_id())
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

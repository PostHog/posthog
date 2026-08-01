from typing import Any
from uuid import UUID

from drf_spectacular.openapi import AutoSchema
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.permissions import APIScopePermission

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.presentation.serializers import (
    ChannelDocumentAppendSerializer,
    ChannelDocumentCreateSerializer,
    ChannelDocumentSerializer,
    ChannelDocumentUpdateSerializer,
    ChannelFeedMessageSerializer,
    ChannelFeedMessageWriteSerializer,
    ChannelSerializer,
    ChannelWriteSerializer,
    TaskActivityMarkReadResponseSerializer,
    TaskActivityMarkReadSerializer,
    TaskActivityPageSerializer,
    TaskActivityQuerySerializer,
    TaskActivitySerializer,
    TaskMentionQuerySerializer,
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


class ChannelDocumentViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    API for a channel's documents — shared markdown docs (todo lists, plans) captured
    from agent conversations and edited collaboratively. Public channels are
    team-writable; personal (#me) channels stay creator-only.
    """

    authentication_classes = [
        SessionAuthentication,
        PersonalAPIKeyAuthentication,
        OAuthAccessTokenAuthentication,
    ]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    serializer_class = ChannelDocumentSerializer

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
                response=ChannelDocumentSerializer(many=True), description="Documents, most recently updated first"
            )
        },
        summary="List channel documents",
        description="A channel's shared markdown documents, most recently updated first.",
    )
    def list(self, request, *args, **kwargs):
        documents = tasks_facade.list_channel_documents(self._channel_id(), self.team_id, self._user_id())
        if documents is None:
            raise NotFound("Channel not found")
        return Response(ChannelDocumentSerializer(documents, many=True).data)

    @extend_schema(
        responses={200: ChannelDocumentSerializer},
        summary="Get a channel document",
    )
    def retrieve(self, request, pk=None, **kwargs):
        document = tasks_facade.get_channel_document(self._channel_id(), self.team_id, self._user_id(), document_id=pk)
        if document is None:
            raise NotFound("Document not found")
        return Response(ChannelDocumentSerializer(document).data)

    @extend_schema(
        request=ChannelDocumentCreateSerializer,
        responses={201: ChannelDocumentSerializer},
        summary="Resolve or create a channel document",
        description="Returns the channel's existing document with the same name and kind, creating it if needed.",
    )
    def create(self, request, **kwargs):
        serializer = ChannelDocumentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        document = tasks_facade.create_channel_document(
            self._channel_id(),
            self.team_id,
            self._user_id(),
            name=serializer.validated_data["name"],
            doc_kind=serializer.validated_data["doc_kind"],
            content=serializer.validated_data["content"],
        )
        if document is None:
            raise NotFound("Channel not found")
        if document == "full":
            raise ValidationError("This channel is at its document limit. Delete a document to add another.")
        if document == "too_large":
            raise ValidationError("Document content can be at most 256 KB.")
        return Response(ChannelDocumentSerializer(document).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=ChannelDocumentUpdateSerializer,
        responses={
            200: ChannelDocumentSerializer,
            409: OpenApiResponse(description="expected_version is stale; refetch the document and retry"),
        },
        summary="Replace a channel document's content",
    )
    def partial_update(self, request, pk=None, **kwargs):
        serializer = ChannelDocumentUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        document = tasks_facade.update_channel_document(
            self._channel_id(),
            self.team_id,
            self._user_id(),
            document_id=pk,
            content=serializer.validated_data["content"],
            expected_version=serializer.validated_data["expected_version"],
            name=serializer.validated_data.get("name"),
        )
        if document is None or document == "not_found":
            raise NotFound("Document not found")
        if document == "conflict":
            return Response(
                {"detail": "The document changed since you loaded it. Refetch it and retry the edit."},
                status=status.HTTP_409_CONFLICT,
            )
        if document == "too_large":
            raise ValidationError("Document content can be at most 256 KB.")
        return Response(ChannelDocumentSerializer(document).data)

    @extend_schema(responses={204: None}, summary="Delete a channel document")
    def destroy(self, request, pk=None, **kwargs):
        result = tasks_facade.delete_channel_document(self._channel_id(), self.team_id, self._user_id(), document_id=pk)
        if result == "not_found":
            raise NotFound("Document not found")
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        request=ChannelDocumentAppendSerializer,
        responses={200: ChannelDocumentSerializer},
        summary="Append to a channel document",
        description="Appends markdown lines to the document. Appends serialize server-side, so concurrent captures from different clients all land.",
    )
    @action(detail=True, methods=["post"], url_path="append", required_scopes=["task:write"])
    def append(self, request, pk=None, **kwargs):
        serializer = ChannelDocumentAppendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        document = tasks_facade.append_channel_document(
            self._channel_id(),
            self.team_id,
            self._user_id(),
            document_id=pk,
            text=serializer.validated_data["text"],
        )
        if document is None or document == "not_found":
            raise NotFound("Document not found")
        if document == "too_large":
            raise ValidationError("This append would push the document over its 256 KB limit.")
        return Response(ChannelDocumentSerializer(document).data)


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
    API for the requester's activity feed — one row per task they are involved in (created,
    @-mentioned in, or authored a thread message on), most-recent activity first.
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
            "Tasks the requester is involved in (created, mentioned, or messaged), one row per task, "
            "most-recent activity first, restricted to tasks they can see."
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
            "Clear the unread flag on the requester's feed rows for the given tasks. Read state is per "
            "task, so opening a task through any surface clears the same row."
        ),
    )
    @action(detail=False, methods=["post"], url_path="mark_read", required_scopes=["task:write"])
    @validated_request(request_serializer=TaskActivityMarkReadSerializer)
    def mark_read(self, request, *args, **kwargs):
        activities = [
            (activity["task_id"], activity["seen_before"]) for activity in request.validated_data["activities"]
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

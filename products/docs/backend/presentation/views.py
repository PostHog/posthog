"""
DRF views for docs.

Validate JSON via serializers, call the facade, return serialized responses.
No business logic here.
"""

from typing import cast
from uuid import UUID

from django.http.response import HttpResponseBase

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.streaming import sse_streaming_response
from posthog.models.user import User
from posthog.renderers import ServerSentEventRenderer
from posthog.settings import SERVER_GATEWAY_INTERFACE

from ee.hogai.utils.aio import async_to_sync

from ..facade import api, contracts
from .serializers import (
    DiscussionCreateSerializer,
    DiscussionReplySerializer,
    DiscussionResolveSerializer,
    DiscussionThreadSerializer,
    DocCollabConflictSerializer,
    DocCollabSaveSerializer,
    DocCreateSerializer,
    DocPresenceSerializer,
    DocReorderSerializer,
    DocSerializer,
    DocSummarySerializer,
    DocUpdateSerializer,
    SpaceHomeSerializer,
)

_CHANNEL_PARAM = OpenApiParameter(
    "channel",
    OpenApiTypes.UUID,
    description="Only return rows in this space (channel).",
    required=False,
)

_DOC_NOT_FOUND = "No doc with this id in this space."


def _display_name(user: User) -> str:
    return user.get_full_name() or "Wandering Hog"


class DocViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Docs: collaborative rich-text documents filed in a space.

    Live editing runs over prosemirror-collab steps on a Redis stream. This API stores the
    durable copy and fans steps, carets, and discussion pings out over one SSE stream.
    """

    scope_object = "INTERNAL"
    serializer_class = DocSerializer
    # A space holds a handful of docs and the tab row shows all of them at once.
    pagination_class = None

    def _actor(self) -> User:
        return cast(User, self.request.user)

    @extend_schema(parameters=[_CHANNEL_PARAM], responses={200: DocSummarySerializer(many=True)})
    def list(self, request: Request, **kwargs) -> Response:
        docs = api.list_docs(self.team_id, self._actor().pk, request.GET.get("channel"))
        return Response(DocSummarySerializer(docs, many=True).data)

    @extend_schema(responses={200: DocSerializer})
    def retrieve(self, request: Request, pk: str, **kwargs) -> Response:
        doc = api.get_doc(self.team_id, self._actor().pk, pk)
        if doc is None:
            raise NotFound(_DOC_NOT_FOUND)
        return Response(DocSerializer(doc).data)

    @extend_schema(request=DocCreateSerializer, responses={201: DocSerializer})
    def create(self, request: Request, **kwargs) -> Response:
        serializer = DocCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            doc = api.create_doc(
                contracts.CreateDocInput(
                    team_id=self.team_id,
                    user_id=self._actor().pk,
                    channel_id=data["channel"],
                    title=data.get("title", ""),
                    template=data["template"],
                )
            )
        except api.ChannelNotVisibleError as err:
            raise ValidationError({"channel": str(err)})

        return Response(DocSerializer(doc).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=DocUpdateSerializer, responses={200: DocSerializer})
    def partial_update(self, request: Request, pk: str, **kwargs) -> Response:
        serializer = DocUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        doc = api.update_doc(self.team_id, self._actor().pk, pk, title=data.get("title"), status=data.get("status"))
        if doc is None:
            raise NotFound(_DOC_NOT_FOUND)
        return Response(DocSerializer(doc).data)

    @extend_schema(responses={204: None})
    def destroy(self, request: Request, pk: str, **kwargs) -> Response:
        if not api.delete_doc(self.team_id, self._actor().pk, pk):
            raise NotFound(_DOC_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=DocReorderSerializer, responses={204: None})
    @action(methods=["POST"], detail=False, url_path="reorder")
    def reorder(self, request: Request, **kwargs) -> Response:
        serializer = DocReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        api.reorder_docs(self.team_id, self._actor().pk, data["channel"], data["doc_ids"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(parameters=[_CHANNEL_PARAM], responses={200: SpaceHomeSerializer})
    @action(methods=["GET"], detail=False, url_path="home", pagination_class=None)
    def home(self, request: Request, **kwargs) -> Response:
        channel_id = request.GET.get("channel")
        if not channel_id:
            raise ValidationError({"channel": "A channel id is required."})
        home = api.space_home(self.team_id, self._actor().pk, channel_id)
        return Response(SpaceHomeSerializer(home).data)

    @extend_schema(
        request=DocCollabSaveSerializer,
        responses={
            200: DocSerializer,
            409: OpenApiResponse(response=DocCollabConflictSerializer, description="Other steps landed first."),
            410: OpenApiResponse(response=DocCollabConflictSerializer, description="The client must reload the doc."),
        },
    )
    @action(methods=["POST"], detail=True, url_path="collab/save")
    def collab_save(self, request: Request, pk: str, **kwargs) -> Response:
        serializer = DocCollabSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = self._actor()

        result = api.save_steps(
            contracts.SaveStepsInput(
                team_id=self.team_id,
                user_id=user.pk,
                user_name=_display_name(user),
                doc_id=UUID(pk),
                client_id=data["client_id"],
                steps=data["steps"],
                version=data["version"],
                content=data["content"],
                text_content=data.get("text_content"),
                title=data.get("title"),
                cursor_head=data.get("cursor_head"),
            )
        )
        if result is None:
            raise NotFound(_DOC_NOT_FOUND)

        if result.status == "accepted":
            return Response(DocSerializer(result.doc).data)
        if result.status == "stale":
            return Response({"code": "stale", "version": result.version}, status=status.HTTP_410_GONE)
        return Response(
            {
                "code": "conflict",
                "steps": result.steps or [],
                "client_ids": result.client_ids or [],
                "version": result.version,
            },
            status=status.HTTP_409_CONFLICT,
        )

    @extend_schema(request=DocPresenceSerializer, responses={204: None})
    @action(methods=["POST"], detail=True, url_path="collab/presence")
    def collab_presence(self, request: Request, pk: str, **kwargs) -> Response:
        serializer = DocPresenceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = self._actor()

        published = api.publish_caret(
            contracts.PresenceInput(
                team_id=self.team_id,
                user_id=user.pk,
                user_name=_display_name(user),
                doc_id=UUID(pk),
                client_id=data["client_id"],
                version=data["version"],
                cursor=data["cursor"],
            )
        )
        if not published:
            raise NotFound(_DOC_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(responses={(200, "text/event-stream"): OpenApiTypes.STR})
    @action(methods=["GET"], detail=True, url_path="collab/stream", renderer_classes=[ServerSentEventRenderer])
    def collab_stream(self, request: Request, pk: str, **kwargs) -> HttpResponseBase:
        """SSE stream of accepted steps, carets, and discussion pings for this doc."""
        last_event_id = request.headers.get("Last-Event-ID")

        # Resolve the doc here, on the request thread: the stream body runs in an async
        # context that has no database connection.
        stream = api.stream_doc(self.team_id, self._actor().pk, pk, last_event_id=last_event_id)
        if stream is None:
            raise NotFound(_DOC_NOT_FOUND)

        # On ASGI (Granian in prod) the async generator runs as one cheap task per connection.
        # On WSGI (tests, fallback) async_to_sync bridges it via a worker thread + queue.
        return sse_streaming_response(
            stream if SERVER_GATEWAY_INTERFACE == "ASGI" else async_to_sync(lambda: stream),
            endpoint="doc_collab",
        )

    @extend_schema(methods=["GET"], request=None, responses={200: DiscussionThreadSerializer(many=True)})
    @extend_schema(methods=["POST"], request=DiscussionCreateSerializer, responses={201: DiscussionThreadSerializer})
    @action(methods=["GET", "POST"], detail=True, url_path="discussions", pagination_class=None)
    def discussions(self, request: Request, pk: str, **kwargs) -> Response:
        user = self._actor()

        if request.method == "GET":
            threads = api.list_threads(self.team_id, user.pk, pk)
            if threads is None:
                raise NotFound(_DOC_NOT_FOUND)
            return Response(DiscussionThreadSerializer(threads, many=True).data)

        serializer = DiscussionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        thread = api.create_thread(
            self.team_id,
            user.pk,
            pk,
            content=data["content"],
            anchor_key=data["anchor_key"],
            anchor_text=data["anchor_text"],
        )
        if thread is None:
            raise NotFound(_DOC_NOT_FOUND)
        return Response(DiscussionThreadSerializer(thread).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=DiscussionReplySerializer, responses={201: DiscussionThreadSerializer})
    @action(methods=["POST"], detail=True, url_path=r"discussions/(?P<thread_id>[^/.]+)/reply")
    def discussion_reply(self, request: Request, pk: str, thread_id: str, **kwargs) -> Response:
        serializer = DiscussionReplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            thread = api.reply_to_thread(
                self.team_id,
                self._actor().pk,
                pk,
                thread_id=thread_id,
                content=serializer.validated_data["content"],
            )
        except api.ThreadNotFoundError as err:
            raise NotFound(str(err))
        if thread is None:
            raise NotFound(_DOC_NOT_FOUND)
        return Response(DiscussionThreadSerializer(thread).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=DiscussionResolveSerializer, responses={200: DiscussionThreadSerializer})
    @action(methods=["POST"], detail=True, url_path=r"discussions/(?P<thread_id>[^/.]+)/resolve")
    def discussion_resolve(self, request: Request, pk: str, thread_id: str, **kwargs) -> Response:
        serializer = DiscussionResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            thread = api.set_thread_resolved(
                self.team_id,
                self._actor().pk,
                pk,
                thread_id=thread_id,
                resolved=serializer.validated_data["resolved"],
            )
        except api.ThreadNotFoundError as err:
            raise NotFound(str(err))
        if thread is None:
            raise NotFound(_DOC_NOT_FOUND)
        return Response(DiscussionThreadSerializer(thread).data)

import dataclasses
from typing import Any
from uuid import UUID, uuid4

from django.http import HttpResponse

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import BaseParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.oauth_provenance import is_sandbox_oauth_request

from products.meep.backend.facade import api
from products.meep.backend.presentation.scout_access import show_scouts


class FileParser(BaseParser):
    media_type = "application/octet-stream"

    def parse(self, stream: Any, media_type: str | None = None, parser_context: dict | None = None) -> dict:
        limit = 16 * 1024 * 1024
        contents = stream.read(limit + 1)
        if len(contents) > limit:
            raise serializers.ValidationError("Files must be at most 16 MiB.")
        return {"contents": contents}


class EnvelopeSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    topic = serializers.UUIDField()
    command = serializers.DictField()


class TaskMessageSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=32000)
    model = serializers.CharField(max_length=255, required=False, allow_null=True)


@extend_schema(exclude=True)
class ReplicaViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "meep"
    scope_object_read_actions = ["file_contents", "topic_models"]
    scope_object_write_actions = ["upload_file", "choose_model"]
    permission_classes = [IsAuthenticated]
    path_parameters = {"topic_id": UUID, "view_id": UUID, "item_id": UUID}
    records_have_object_access_rules = False

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        if is_sandbox_oauth_request(request):
            raise PermissionDenied("Use the topic tools for this task.")

    @action(detail=False, methods=["get"], required_scopes=["meep:read"])
    def health(self, request: Request, **kwargs: Any) -> Response:
        return Response(
            {
                "owner_id": request.user.uuid,
                "version": "1",
                "cursor": api.cursor(self.team_id, request.user.pk),
                "posthog": True,
            }
        )

    @action(detail=False, methods=["post"], required_scopes=["meep:write", "task:write"])
    def commands(self, request: Request, **kwargs: Any) -> Response:
        envelopes = EnvelopeSerializer(data=request.data.get("commands"), many=True, max_length=64)
        envelopes.is_valid(raise_exception=True)
        results = []
        for envelope in envelopes.validated_data:
            try:
                result = api.command(
                    self.team_id, request.user.pk, envelope["id"], envelope["topic"], envelope["command"]
                )
            except serializers.ValidationError as error:
                result = {"status": "rejected", "id": envelope["id"], "reason": str(error.detail)}
            results.append(result)
        return Response({"results": results})

    @action(detail=False, methods=["get"], required_scopes=["meep:read"])
    def changes(self, request: Request, **kwargs: Any) -> Response:
        cursor = serializers.IntegerField(min_value=0, max_value=2**63 - 1).run_validation(
            request.query_params.get("cursor", 0)
        )
        return Response(api.changes(self.team_id, request.user.pk, cursor, include_scouts=show_scouts(self)))

    @action(
        detail=False, methods=["get"], url_path=r"topics/(?P<topic_id>[0-9a-fA-F-]{36})", required_scopes=["meep:read"]
    )
    def topic_snapshot(self, request: Request, topic_id: UUID, **kwargs: Any) -> Response:
        return Response(api.topic_snapshot(self.team_id, request.user.pk, topic_id, include_scouts=show_scouts(self)))

    @action(
        detail=False,
        methods=["get"],
        url_path=r"topics/(?P<topic_id>[0-9a-fA-F-]{36})/tasks/(?P<item_id>[0-9a-fA-F-]{36})/conversation",
        required_scopes=["meep:read", "task:read"],
    )
    def task_conversation(self, request: Request, topic_id: UUID, item_id: UUID, **kwargs: Any) -> Response:
        return Response(api.task_conversation(self.team_id, request.user.pk, topic_id, item_id))

    @action(
        detail=False,
        methods=["post"],
        url_path=r"topics/(?P<topic_id>[0-9a-fA-F-]{36})/tasks/(?P<item_id>[0-9a-fA-F-]{36})/messages",
        required_scopes=["meep:write", "task:write"],
    )
    def task_messages(self, request: Request, topic_id: UUID, item_id: UUID, **kwargs: Any) -> HttpResponse:
        message = TaskMessageSerializer(data=request.data)
        message.is_valid(raise_exception=True)
        api.send_task_message(
            self.team_id,
            request.user.pk,
            topic_id,
            item_id,
            message.validated_data["text"],
            message.validated_data.get("model"),
        )
        return HttpResponse("null", content_type="application/json")

    @action(detail=False, methods=["get"], required_scopes=["meep:read"])
    def connections(self, request: Request, **kwargs: Any) -> Response:
        return Response({"connections": [self._connection()]})

    def _connection(self) -> dict[str, Any]:
        return {
            "id": "posthog",
            "kind": "posthog",
            "label": "PostHog",
            "account": self.team.name,
            "health": "ok",
            "summary": "Signed in to PostHog",
            "grants": api.grants(self.team_id, self.request.user.pk),
        }

    @action(
        detail=False,
        methods=["put"],
        url_path=r"connections/posthog/topics/(?P<topic_id>[0-9a-fA-F-]{36})",
        required_scopes=["meep:write"],
    )
    def grant(self, request: Request, topic_id: UUID, **kwargs: Any) -> Response:
        api.topic_snapshot(self.team_id, request.user.pk, topic_id)
        return Response(self._connection())

    @action(detail=False, methods=["get"], required_scopes=["meep:read"])
    def views(self, request: Request, **kwargs: Any) -> Response:
        return Response(api.views(self.team_id, request.user.pk))

    @action(detail=False, methods=["post"], url_path="views/commands", required_scopes=["meep:write", "task:write"])
    def view_commands(self, request: Request, **kwargs: Any) -> Response:
        view_id = serializers.UUIDField().run_validation(request.data.get("view"))
        cmd_id = serializers.UUIDField().run_validation(request.data.get("id"))
        return Response(api.edit_view(self.team_id, request.user.pk, view_id, cmd_id, request.data))

    @action(detail=False, methods=["post"], url_path="deletions/ack", required_scopes=["meep:write"])
    def ack(self, request: Request, **kwargs: Any) -> HttpResponse:
        replica = serializers.UUIDField().run_validation(request.data.get("replica"))
        topics = serializers.DictField(child=serializers.IntegerField(min_value=1)).run_validation(
            request.data.get("topics")
        )
        api.acknowledge(
            self.team_id,
            request.user.pk,
            replica,
            {serializers.UUIDField().run_validation(k): v for k, v in topics.items()},
        )
        return HttpResponse("null", content_type="application/json")

    @action(
        detail=False,
        methods=["get"],
        url_path=r"topics/(?P<topic_id>[0-9a-fA-F-]{36})/files",
        required_scopes=["meep:read"],
    )
    def file_list(self, request: Request, topic_id: UUID, **kwargs: Any) -> Response:
        return Response(api.files(self.team_id, request.user.pk, topic_id))

    @action(
        detail=False,
        methods=["get"],
        parser_classes=[FileParser],
        url_path=r"topics/(?P<topic_id>[0-9a-fA-F-]{36})/files/(?P<path>.+?)",
    )
    def file_contents(self, request: Request, topic_id: UUID, path: str, **kwargs: Any) -> HttpResponse:
        revision = (
            serializers.IntegerField(min_value=1).run_validation(request.query_params["revision"])
            if "revision" in request.query_params
            else None
        )
        file = api.read_file(self.team_id, request.user.pk, topic_id, path, revision)
        return HttpResponse(
            bytes(file.contents),
            content_type="application/octet-stream",
            headers={"x-meep-revision": str(file.revision)},
        )

    @file_contents.mapping.put
    def upload_file(self, request: Request, topic_id: UUID, path: str, **kwargs: Any) -> HttpResponse:
        if not path or len(path.encode()) > 1024 or any(part in ("", ".", "..") for part in path.split("/")):
            raise serializers.ValidationError("Invalid file path.")
        key = serializers.UUIDField().run_validation(request.headers.get("Idempotency-Key", uuid4()))
        base = request.headers.get("x-meep-base-revision")
        base = serializers.IntegerField(min_value=0).run_validation(base) if base is not None else None
        file = api.upload(self.team_id, request.user.pk, topic_id, path, request.data["contents"], key, base)
        response = HttpResponse(
            bytes(file.contents),
            content_type="application/octet-stream",
            headers={"x-meep-revision": str(file.revision)},
        )
        if file.competing_with is not None:
            response["x-meep-conflict-head"] = str(file.competing_with)
        return response

    @action(detail=False, methods=["get"], url_path="views/models", required_scopes=["meep:read", "task:read"])
    def view_models(self, request: Request, **kwargs: Any) -> Response:
        return Response(api.chat_models(self.team_id, request.user.pk, None, False, None, None))

    @action(detail=False, methods=["get"], url_path=r"topics/(?P<topic_id>[0-9a-fA-F-]{36})/models")
    def topic_models(self, request: Request, topic_id: UUID, **kwargs: Any) -> Response:
        return Response(api.chat_models(self.team_id, request.user.pk, topic_id, False, None, None))

    @topic_models.mapping.put
    def choose_model(self, request: Request, topic_id: UUID, **kwargs: Any) -> Response:
        field = serializers.CharField(max_length=255, allow_null=True)
        model = field.run_validation(request.data.get("model"))
        billing = field.run_validation(request.data.get("billing"))
        return Response(api.chat_models(self.team_id, request.user.pk, topic_id, True, model, billing))

    @action(
        detail=False,
        methods=["post"],
        url_path=r"views/(?P<view_id>[0-9a-fA-F-]{36})/sources",
        required_scopes=["meep:read"],
    )
    def view_source(self, request: Request, view_id: UUID, **kwargs: Any) -> Response:
        if request.data.get("source") != "topics":
            raise serializers.ValidationError("Expected a topic source.")
        args = serializers.DictField().run_validation(request.data.get("arguments"))
        topic_id = serializers.UUIDField().run_validation(args.get("topic"))
        tool = serializers.CharField().run_validation(request.data.get("tool"))
        return Response(api.view_source(self.team_id, request.user.pk, view_id, topic_id, tool, args.get("path")))

    @action(
        detail=False,
        methods=["get"],
        url_path=r"routines/(?P<topic_id>[0-9a-fA-F-]{36})/(?P<routine>[^/]+)",
        required_scopes=["meep:read"],
    )
    def routine_details(self, request: Request, topic_id: UUID, routine: str, **kwargs: Any) -> Response:
        details = api.routine_details(
            team_id=self.team_id, owner_id=request.user.pk, topic_id=topic_id, routine=routine
        )
        return Response({**dataclasses.asdict(details), "runs": []})

    @routine_details.mapping.put
    def routine_enable(self, request: Request, topic_id: UUID, routine: str, **kwargs: Any) -> Response:
        raise serializers.ValidationError(
            "Ask the topic chat to turn this routine on. It checks the delivery setup first."
        )

    @action(
        detail=False,
        methods=["get"],
        url_path=r"topics/(?P<topic_id>[0-9a-fA-F-]{36})/artifacts",
        required_scopes=["meep:read"],
    )
    def topic_artifacts(self, request: Request, topic_id: UUID, **kwargs: Any) -> Response:
        return Response(api.topic_artifacts(self.team_id, request.user.pk, topic_id))

    @action(
        detail=False,
        methods=["get"],
        url_path=(
            r"topics/(?P<topic_id>[0-9a-fA-F-]{36})/artifacts/(?P<item_id>[0-9a-fA-F-]{36})"
            r"/(?P<run_id>[0-9a-fA-F-]{36})/(?P<artifact_id>[0-9a-fA-F]+)"
        ),
        required_scopes=["meep:read"],
    )
    def topic_artifact(
        self, request: Request, topic_id: UUID, item_id: UUID, run_id: UUID, artifact_id: str, **kwargs: Any
    ) -> HttpResponse:
        limit = 5 * 1024 * 1024
        found = api.read_topic_artifact(self.team_id, request.user.pk, topic_id, item_id, run_id, artifact_id, limit)
        if found is None:
            return HttpResponse(status=413)
        data, content_type = found
        return HttpResponse(data, content_type=content_type)

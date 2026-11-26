from typing import Any
from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.oauth_provenance import get_oauth_access_token, is_sandbox_oauth_request

from products.meep.backend.facade import api
from products.meep.backend.presentation.scout_access import canonical_scout_access, show_scouts
from products.signals.backend.facade.source_scouts import cron_schedule_error
from products.tasks.backend.facade import agent_run_starts, contracts


class MeepScoutCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    instructions = serializers.CharField(max_length=16000)
    cron = serializers.CharField(
        required=False,
        max_length=100,
        help_text="Optional five-field schedule in the project's timezone. Defaults to the native scout cadence.",
    )

    def validate_cron(self, value: str) -> str:
        if error := cron_schedule_error(value):
            raise serializers.ValidationError(error)
        return value


class MeepScoutStatusSerializer(serializers.Serializer):
    scout_id = serializers.UUIDField()
    enabled = serializers.BooleanField()


class MeepScoutSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    skill_name = serializers.CharField()
    enabled = serializers.BooleanField()


class MeepRoutineBindSerializer(serializers.Serializer):
    workflow_id = serializers.UUIDField(help_text="The ID of the PostHog workflow this topic should show as a routine.")
    name = serializers.CharField(
        max_length=100, help_text="A short name for the routine, shown in the topic's Routines."
    )
    trigger = serializers.CharField(
        max_length=200, help_text="When the routine runs, in plain words, for example 'Every day at 09:00 UTC'."
    )


class MeepRoutineSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="The topic-local routine key.")
    name = serializers.CharField()
    trigger = serializers.CharField()
    workflow_id = serializers.UUIDField()


class MeepConversationBindingSerializer(serializers.Serializer):
    task_id = serializers.UUIDField()


class MeepTaskStartSerializer(serializers.Serializer):
    request_id = serializers.UUIDField(help_text="A stable ID for this request, reused when retrying.")
    title = serializers.CharField(max_length=255, help_text="A short title for the board task.")
    brief = serializers.CharField(max_length=16000, help_text="The independent work and expected result.")


class MeepTaskStartResultSerializer(serializers.Serializer):
    item_id = serializers.UUIDField(help_text="The created board item ID.")
    task_id = serializers.UUIDField(help_text="The child task ID.")
    run_id = serializers.UUIDField(help_text="The child run ID.")


class MeepTaskWaitSerializer(serializers.Serializer):
    request_id = serializers.UUIDField(help_text="A stable ID for this wait, reused when retrying.")
    item_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
        max_length=20,
        help_text="Up to 20 board item IDs to wait for.",
    )


class MeepTaskAnswerSerializer(serializers.Serializer):
    request_id = serializers.UUIDField(help_text="A stable ID for this answer, reused when retrying.")
    item_id = serializers.UUIDField(help_text="The board item asking for input.")
    question_run_id = serializers.UUIDField(help_text="The run ID that asked the question.")
    answer = serializers.CharField(max_length=16000, help_text="The person's answer to the child task.")


class MeepTaskWaitResultSerializer(serializers.Serializer):
    status = serializers.CharField(help_text="The wait status.")
    item_ids = serializers.ListField(child=serializers.UUIDField(), help_text="The selected board item IDs.")


class MeepTopicSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    title = serializers.CharField(max_length=255)
    mission = serializers.CharField()
    conversation_id = serializers.UUIDField(read_only=True, allow_null=True)
    created_at = serializers.DateTimeField(read_only=True)


class MeepTopicDetailsSerializer(MeepTopicSerializer):
    context = serializers.DictField(read_only=True)


class TopicViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "meep"
    permission_classes = [IsAuthenticated]
    serializer_class = MeepTopicSerializer
    path_parameters = {"pk": UUID}
    records_have_object_access_rules = False

    def _conversation(self, request: Request) -> UUID | None:
        if is_sandbox_oauth_request(request):
            key = getattr(get_oauth_access_token(request), "sandbox_task_id", None)
            if key is None:
                raise PermissionDenied("The task credential must identify its task.")
            return key
        return None

    def _delegating_run(self, request: Request) -> contracts.SandboxRunStarter:
        task_id = self._conversation(request)
        token = get_oauth_access_token(request)
        starter = agent_run_starts.resolve_sandbox_run_starter(
            self.team_id,
            sandbox_task_id=task_id,
            token_id=getattr(token, "id", None),
            user_id=request.user.pk,
        )
        if isinstance(starter, contracts.SandboxRunStartDenial):
            raise PermissionDenied("This task credential cannot delegate work.")
        return starter

    def list(self, request: Request, **kwargs: Any) -> Response:
        topics = api.list_topics(self.team_id, request.user.pk, self._conversation(request))
        page = self.paginate_queryset(topics)
        if page is not None:
            return self.get_paginated_response(MeepTopicSerializer(page, many=True).data)
        return Response(MeepTopicSerializer(topics, many=True).data)

    @extend_schema(responses=MeepTopicDetailsSerializer)
    def retrieve(self, request: Request, pk: UUID, **kwargs: Any) -> Response:
        topic = api.read_topic(self.team_id, request.user.pk, pk, self._conversation(request))
        detail = dict(MeepTopicSerializer(topic).data)
        detail["context"] = api.topic_context(
            self.team_id, request.user.pk, pk, self._conversation(request), include_scouts=show_scouts(self)
        )
        return Response(detail)

    def create(self, request: Request, **kwargs: Any) -> Response:
        if is_sandbox_oauth_request(request):
            raise PermissionDenied("Only a person can create a topic.")
        data = MeepTopicSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        topic = api.create_topic(self.team_id, request.user.pk, **data.validated_data)
        return Response(MeepTopicSerializer(topic).data, status=201)

    @extend_schema(request=MeepConversationBindingSerializer, responses=MeepTopicSerializer)
    @action(methods=["post"], detail=True, required_scopes=["meep:write", "task:read"])
    def conversation(self, request: Request, pk: UUID, **kwargs: Any) -> Response:
        if is_sandbox_oauth_request(request):
            raise PermissionDenied("Only a person can bind a task.")
        data = MeepConversationBindingSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        topic = api.bind_conversation(self.team_id, request.user.pk, pk, data.validated_data["task_id"])
        return Response(MeepTopicSerializer(topic).data)

    @extend_schema(
        operation_id="meep_topics_start_task", request=MeepTaskStartSerializer, responses=MeepTaskStartResultSerializer
    )
    @action(methods=["post"], detail=True, url_path="tasks/start", required_scopes=["meep_task:write"])
    def start_task(self, request: Request, pk: UUID, **kwargs: Any) -> Response:
        starter = self._delegating_run(request)
        payload = MeepTaskStartSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        result = api.spawn_child(
            team=self.team,
            user=request.user,
            parent_task_id=starter.parent_task_id,
            parent_run_id=starter.parent_run_id,
            topic_id=pk,
            request_id=payload.validated_data["request_id"],
            title=payload.validated_data["title"],
            instructions=payload.validated_data["brief"],
        )
        return Response(MeepTaskStartResultSerializer(result).data)

    @extend_schema(
        operation_id="meep_topics_wait_tasks", request=MeepTaskWaitSerializer, responses=MeepTaskWaitResultSerializer
    )
    @action(methods=["post"], detail=True, url_path="tasks/wait", required_scopes=["meep_task:write"])
    def wait_tasks(self, request: Request, pk: UUID, **kwargs: Any) -> Response:
        starter = self._delegating_run(request)
        payload = MeepTaskWaitSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        result = api.wait_for_children(
            team=self.team,
            user=request.user,
            parent_task_id=starter.parent_task_id,
            parent_run_id=starter.parent_run_id,
            topic_id=pk,
            request_id=payload.validated_data["request_id"],
            item_ids=payload.validated_data["item_ids"],
        )
        return Response(MeepTaskWaitResultSerializer(result).data)

    @extend_schema(
        operation_id="meep_topics_answer_task",
        request=MeepTaskAnswerSerializer,
        responses=MeepTaskStartResultSerializer,
    )
    @action(methods=["post"], detail=True, url_path="tasks/answer", required_scopes=["meep_task:write"])
    def answer_task(self, request: Request, pk: UUID, **kwargs: Any) -> Response:
        starter = self._delegating_run(request)
        payload = MeepTaskAnswerSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        result = api.answer_child(
            team=self.team,
            user=request.user,
            parent_task_id=starter.parent_task_id,
            parent_run_id=starter.parent_run_id,
            topic_id=pk,
            request_id=payload.validated_data["request_id"],
            item_id=payload.validated_data["item_id"],
            question_run_id=payload.validated_data["question_run_id"],
            answer=payload.validated_data["answer"],
        )
        return Response(MeepTaskStartResultSerializer(result).data)

    @extend_schema(
        operation_id="meep_topics_create_scout",
        request=MeepScoutCreateSerializer,
        responses={200: MeepScoutSerializer, 201: MeepScoutSerializer},
    )
    @action(methods=["post"], detail=True, url_path="scouts", required_scopes=["meep_scout:write"])
    def create_scout(self, request: Request, pk: UUID, **kwargs: Any) -> Response:
        task_id = self._conversation(request)
        if task_id is None or not canonical_scout_access(self):
            raise PermissionDenied("Create this scout from its Meep topic in a project you can access.")
        payload = MeepScoutCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        scout, created = api.create_topic_scout(
            team=self.team,
            user=request.user,
            task_id=task_id,
            topic_id=pk,
            name=payload.validated_data["name"],
            instructions=payload.validated_data["instructions"],
            cron=payload.validated_data.get("cron"),
            request=request,
        )
        return Response(MeepScoutSerializer(scout).data, status=201 if created else 200)

    @extend_schema(
        operation_id="meep_topics_set_scout_enabled", request=MeepScoutStatusSerializer, responses=MeepScoutSerializer
    )
    @action(methods=["post"], detail=True, url_path="scout-status", required_scopes=["meep_scout:write"])
    def scout_status(self, request: Request, pk: UUID, **kwargs: Any) -> Response:
        task_id = self._conversation(request)
        if task_id is None or not canonical_scout_access(self):
            raise PermissionDenied("Manage this scout from its Meep topic in a project you can access.")
        payload = MeepScoutStatusSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        scout = api.set_topic_scout_enabled(
            team=self.team,
            user=request.user,
            task_id=task_id,
            topic_id=pk,
            scout_id=payload.validated_data["scout_id"],
            enabled=payload.validated_data["enabled"],
            request=request,
        )
        return Response(MeepScoutSerializer(scout).data)

    @extend_schema(
        operation_id="meep_topics_bind_routine", request=MeepRoutineBindSerializer, responses=MeepRoutineSerializer
    )
    @action(methods=["post"], detail=True, url_path="routines", required_scopes=["meep_scout:write"])
    def bind_routine(self, request: Request, pk: UUID, **kwargs: Any) -> Response:
        task_id = self._conversation(request)
        if task_id is None or not canonical_scout_access(self):
            raise PermissionDenied("Link this routine from its Meep topic in a project you can access.")
        payload = MeepRoutineBindSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        routine = api.bind_topic_routine(
            team=self.team,
            user=request.user,
            task_id=task_id,
            topic_id=pk,
            workflow_id=payload.validated_data["workflow_id"],
            name=payload.validated_data["name"],
            trigger=payload.validated_data["trigger"],
        )
        return Response(MeepRoutineSerializer(routine).data)

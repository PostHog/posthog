import uuid
from typing import Any

from django.utils import timezone

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.posthog_ai.backend.api.serializers import TrackedQuestionRunSerializer, TrackedQuestionSerializer
from products.posthog_ai.backend.models import TrackedQuestion

logger = structlog.get_logger(__name__)


class TrackedQuestionViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    CRUD + lifecycle actions for watched Max AI answers.

    Each TrackedQuestion is a re-runnable Max conversation; a Temporal cron forks it on cadence
    and emits a Signal when the drift judge marks the change as material.
    """

    scope_object = "INTERNAL"  # gated by feature flag + AI data processing consent
    queryset = TrackedQuestion.objects.all().order_by("-created_at")
    serializer_class = TrackedQuestionSerializer

    def safely_get_queryset(self, queryset: Any) -> Any:
        # Exclude archived by default; an `?include_archived=true` query param flips this.
        include_archived = (self.request.query_params.get("include_archived") or "").lower() == "true"
        if not include_archived:
            queryset = queryset.exclude(status=TrackedQuestion.Status.ARCHIVED)
        return queryset

    @extend_schema(
        request=TrackedQuestionSerializer,
        responses={201: TrackedQuestionSerializer},
        description=(
            "Start watching a Max AI answer. Captures the underlying query as a baseline and schedules "
            "the first drift check based on the chosen cadence."
        ),
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().create(request, *args, **kwargs)

    @extend_schema(
        request=TrackedQuestionSerializer,
        responses={200: TrackedQuestionSerializer},
        description="Partially update a watched question (e.g. cadence, title, repository).",
    )
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().partial_update(request, *args, **kwargs)

    @extend_schema(
        responses={204: OpenApiResponse(description="Watched question archived (soft-delete).")},
        description="Archive a watched question. Sets status=archived; the row is preserved for audit.",
    )
    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        instance.status = TrackedQuestion.Status.ARCHIVED
        instance.save(update_fields=["status", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        request=None,
        responses={200: TrackedQuestionSerializer},
        description="Pause a watched question. It stops being evaluated by the scheduler until resumed.",
    )
    @action(methods=["POST"], detail=True)
    def pause(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        instance.status = TrackedQuestion.Status.PAUSED
        instance.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(instance).data)

    @extend_schema(
        request=None,
        responses={200: TrackedQuestionSerializer},
        description=(
            "Resume a paused watched question. Sets next_run_at to now so the next scheduler tick picks it up promptly."
        ),
    )
    @action(methods=["POST"], detail=True)
    def resume(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        instance.status = TrackedQuestion.Status.ACTIVE
        instance.next_run_at = timezone.now()
        instance.save(update_fields=["status", "next_run_at", "updated_at"])
        return Response(self.get_serializer(instance).data)

    @extend_schema(
        request=None,
        responses={
            202: OpenApiResponse(description="Manual drift-check workflow enqueued."),
            503: OpenApiResponse(description="Temporal client unavailable."),
        },
        description=(
            "Enqueue an out-of-band drift check that runs immediately rather than waiting for "
            "the next scheduled tick. Does not advance next_run_at."
        ),
    )
    @action(methods=["POST"], detail=True, url_path="run_now")
    def run_now(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        from django.conf import settings

        from asgiref.sync import async_to_sync

        from posthog.temporal.common.client import async_connect
        from posthog.temporal.watched_questions.workflows import (
            CheckWatchedQuestionInputs,
            CheckWatchedQuestionWorkflow,
        )

        instance = self.get_object()
        try:

            async def _start() -> None:
                client = await async_connect()
                await client.start_workflow(
                    CheckWatchedQuestionWorkflow.run,
                    CheckWatchedQuestionInputs(
                        tracked_question_id=str(instance.id),
                        team_id=instance.team_id,
                    ),
                    id=f"check-watched-question-{instance.id}-manual-{uuid.uuid4()}",
                    task_queue=settings.MAX_AI_TASK_QUEUE,
                )

            async_to_sync(_start)()
        except Exception:
            logger.exception("Failed to enqueue manual watched-question drift check", question_id=str(instance.id))
            return Response(status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        responses={200: TrackedQuestionRunSerializer(many=True)},
        description="List the run history for a watched question (newest first, up to 100 most-recent rows).",
    )
    @action(methods=["GET"], detail=True)
    def runs(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        runs = instance.runs.order_by("-created_at")[:100]
        return Response(TrackedQuestionRunSerializer(runs, many=True).data)
